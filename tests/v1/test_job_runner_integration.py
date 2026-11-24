"""Crash recovery, expired leases and concurrent runners against real MongoDB claims.

Uses the shared ``test`` database with synthetic records only.
"""

import asyncio
import time
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from app.core.config import get_settings
from app.db.mongo_client import get_test_db
from app.models.mongo import AsyncDB
from app.repositories.mediation import MediationJobRepository
from app.repositories.xiaobao_push import (
    XiaoBaoPushDeliveryRepository,
    ensure_xiaobao_push_indexes,
)
from app.schemas.v1.mediation import AIJobStatus, MediationAIJob, MediationAIJobType
from app.schemas.v1.user import UserType
from app.schemas.v1.xiaobao_push import XiaoBaoPushDeliveryStatus
from app.util.time import utc_now
from app.workers.job_runner import JobHandler, JobKind, run_jobs

settings = get_settings()
SUBSCRIPTION_ID = "64b64c000000000000000102"
SESSION_ID = "64b64c000000000000000103"
MESSAGE_ID = "64b64c000000000000000104"


@pytest_asyncio.fixture
async def job_db() -> AsyncGenerator[AsyncDB]:
    db = get_test_db()
    collections = (
        settings.xiaobao_push_deliveries_collection_name,
        settings.mediation_ai_jobs_collection_name,
    )
    for name in collections:
        await db[name].delete_many({})
    await ensure_xiaobao_push_indexes(db)
    await MediationJobRepository(db).ensure_indexes()
    yield db
    for name in collections:
        await db[name].delete_many({})


async def enqueue_tests(deliveries: XiaoBaoPushDeliveryRepository, count: int) -> None:
    for i in range(count):
        await deliveries.enqueue_test(
            owner=UserType.JORIS, subscription_id=SUBSCRIPTION_ID, client_test_id=f"synthetic-{i}"
        )


@pytest.mark.asyncio
async def test_expired_push_lease_is_reclaimed_after_a_crash(job_db: AsyncDB) -> None:
    deliveries = XiaoBaoPushDeliveryRepository(job_db)
    await enqueue_tests(deliveries, 1)

    crashed = await deliveries.claim_next(lease_seconds=0.3)
    assert crashed is not None
    # While the crashed runner's lease is alive, nobody else may claim the item.
    assert await deliveries.claim_next(lease_seconds=30) is None

    await asyncio.sleep(0.4)
    recovered = await deliveries.claim_next(lease_seconds=30)

    assert recovered is not None and recovered.id == crashed.id
    assert recovered.attempt_count == 2
    # The crashed runner can no longer acknowledge work it no longer owns.
    assert not await deliveries.mark_delivered(crashed)
    assert await deliveries.mark_delivered(recovered)


@pytest.mark.asyncio
async def test_concurrent_wakeups_deliver_each_push_once(job_db: AsyncDB) -> None:
    deliveries = XiaoBaoPushDeliveryRepository(job_db)
    await enqueue_tests(deliveries, 12)
    sent: list[str] = []

    async def process_one() -> bool:
        item = await deliveries.claim_next(lease_seconds=30)
        if item is None:
            return False
        sent.append(str(item.id))
        await asyncio.sleep(0.01)
        assert await deliveries.mark_delivered(item)
        return True

    def handler() -> JobHandler:
        return JobHandler(JobKind.PUSH, process_one, timeout_seconds=10, idle_interval_seconds=0.05)

    deadline = time.monotonic() + 60
    await asyncio.gather(*(run_jobs([handler()], deadline=deadline) for _ in range(3)))

    assert len(sent) == 12 and len(set(sent)) == 12
    remaining = await job_db[settings.xiaobao_push_deliveries_collection_name].count_documents(
        {"status": {"$ne": XiaoBaoPushDeliveryStatus.DELIVERED}}
    )
    assert remaining == 0


@pytest.mark.asyncio
async def test_concurrent_duplicate_enqueues_create_one_delivery(job_db: AsyncDB) -> None:
    deliveries = XiaoBaoPushDeliveryRepository(job_db)

    tests = await asyncio.gather(
        *(
            deliveries.enqueue_test(
                owner=UserType.JORIS, subscription_id=SUBSCRIPTION_ID, client_test_id="same"
            )
            for _ in range(8)
        )
    )
    messages = await asyncio.gather(
        *(
            deliveries.enqueue_message(
                message_id=MESSAGE_ID, owner=UserType.JORIS, subscription_id=SUBSCRIPTION_ID
            )
            for _ in range(8)
        )
    )

    assert len({item.id for item in tests}) == 1
    assert len({item.id for item in messages}) == 1
    assert await job_db[settings.xiaobao_push_deliveries_collection_name].count_documents({}) == 2


@pytest.mark.asyncio
async def test_stale_mediation_job_is_recovered_and_not_duplicated(job_db: AsyncDB) -> None:
    jobs = MediationJobRepository(job_db)
    now = utc_now()
    job = MediationAIJob(
        job_type=MediationAIJobType.SHARED_MEDIATION_ADVICE,
        status=AIJobStatus.PENDING,
        session_id=SESSION_ID,
        idempotency_key=f"shared_advice:{SESSION_ID}",
        created_at=now,
        updated_at=now,
    )
    created, duplicate = await asyncio.gather(
        jobs.create_job_if_not_exists(job), jobs.create_job_if_not_exists(job)
    )
    assert created.id == duplicate.id

    crashed = await jobs.claim_next_pending_job(stale_after_seconds=0.3)
    assert crashed is not None
    assert await jobs.claim_next_pending_job(stale_after_seconds=0.3) is None

    await asyncio.sleep(0.4)
    recovered = await jobs.claim_next_pending_job(stale_after_seconds=0.3)

    assert recovered is not None and recovered.id == crashed.id
    assert recovered.attempts == 2
