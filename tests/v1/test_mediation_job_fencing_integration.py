"""Mediation job ownership: claim tokens fence state changes and outputs are written once per job.

Uses the shared ``test`` database with synthetic records only.
"""

import asyncio
from collections.abc import AsyncGenerator
from datetime import timedelta

import pytest
import pytest_asyncio
from bson import ObjectId

from app.core.config import get_settings
from app.db.mongo_client import get_test_db
from app.models.mongo import AsyncDB
from app.repositories.mediation import (
    MediationAIRepository,
    MediationCommentRepository,
    MediationJobRepository,
)
from app.schemas.v1.mediation import (
    AIJobStatus,
    MediationAIJob,
    MediationAIJobType,
    MediationAIReflection,
)
from app.schemas.v1.user import UserType
from app.util.time import utc_now

settings = get_settings()
SESSION_ID = "64b64c000000000000000401"
PERSPECTIVE_ID = "64b64c000000000000000402"
STALE_AFTER = 0.3


@pytest_asyncio.fixture
async def mediation_db() -> AsyncGenerator[AsyncDB]:
    db = get_test_db()
    collections = (
        settings.mediation_ai_jobs_collection_name,
        settings.mediation_ai_reflections_collection_name,
        settings.mediation_comments_collection_name,
    )
    for name in collections:
        await db[name].delete_many({})
    await MediationJobRepository(db).ensure_indexes()
    await MediationAIRepository(db).ensure_indexes()
    await MediationCommentRepository(db).ensure_indexes()
    yield db
    for name in collections:
        await db[name].delete_many({})


async def create_job(jobs: MediationJobRepository, *, max_attempts: int = 3) -> MediationAIJob:
    now = utc_now()
    return await jobs.create_job_if_not_exists(
        MediationAIJob(
            job_type=MediationAIJobType.PRIVATE_REFLECTION,
            status=AIJobStatus.PENDING,
            session_id=SESSION_ID,
            source_entity_id=PERSPECTIVE_ID,
            idempotency_key=f"private_reflection:{SESSION_ID}:{PERSPECTIVE_ID}",
            max_attempts=max_attempts,
            created_at=now,
            updated_at=now,
        )
    )


async def stored(db: AsyncDB, job: MediationAIJob) -> dict:
    doc = await db[settings.mediation_ai_jobs_collection_name].find_one({"_id": ObjectId(job.id)})
    assert doc is not None
    return doc


@pytest.mark.asyncio
async def test_superseded_worker_cannot_change_the_new_owners_job(mediation_db: AsyncDB) -> None:
    jobs = MediationJobRepository(mediation_db)
    await create_job(jobs)

    stale = await jobs.claim_next_pending_job(STALE_AFTER)
    assert stale is not None and stale.lease_token
    await asyncio.sleep(STALE_AFTER + 0.1)
    current = await jobs.claim_next_pending_job(STALE_AFTER)
    assert current is not None and current.id == stale.id
    assert current.lease_token and current.lease_token != stale.lease_token

    # The superseded worker finishes late: none of its writes may land.
    assert await jobs.mark_completed(stale) is None
    assert await jobs.mark_failed_or_retry(stale, "TimeoutError") is None
    assert not await jobs.is_owner(stale)
    doc = await stored(mediation_db, current)
    assert doc["status"] == AIJobStatus.PROCESSING
    assert doc["lease_token"] == current.lease_token
    assert doc["attempts"] == 2

    # The current owner completes normally; the stale worker still cannot touch the result.
    assert await jobs.is_owner(current)
    completed = await jobs.mark_completed(current)
    assert completed is not None and completed.status == AIJobStatus.COMPLETED
    assert await jobs.mark_failed_or_retry(stale, "TimeoutError") is None
    doc = await stored(mediation_db, current)
    assert doc["status"] == AIJobStatus.COMPLETED and "lease_token" not in doc


@pytest.mark.asyncio
async def test_retry_then_failure_are_fenced_and_bounded(mediation_db: AsyncDB) -> None:
    jobs = MediationJobRepository(mediation_db)
    await create_job(jobs, max_attempts=2)

    first = await jobs.claim_next_pending_job(STALE_AFTER)
    assert first is not None
    retried = await jobs.mark_failed_or_retry(first, "APITimeoutError")
    assert retried is not None and retried.status == AIJobStatus.PENDING
    assert retried.lease_token is None and retried.error_message == "APITimeoutError"

    second = await jobs.claim_next_pending_job(STALE_AFTER)
    assert second is not None and second.lease_token != first.lease_token
    failed = await jobs.mark_failed_or_retry(second, "APITimeoutError")
    assert failed is not None and failed.status == AIJobStatus.FAILED
    assert await jobs.claim_next_pending_job(STALE_AFTER) is None


@pytest.mark.asyncio
async def test_job_claimed_before_this_change_is_recovered(mediation_db: AsyncDB) -> None:
    jobs = MediationJobRepository(mediation_db)
    job = await create_job(jobs)
    # A legacy worker claimed the job without a token and then disappeared.
    await mediation_db[settings.mediation_ai_jobs_collection_name].update_one(
        {"_id": ObjectId(job.id)},
        {
            "$set": {
                "status": AIJobStatus.PROCESSING,
                "attempts": 1,
                "started_at": utc_now() - timedelta(minutes=10),
            }
        },
    )
    legacy = MediationAIJob.model_validate(await stored(mediation_db, job))
    assert legacy.lease_token is None
    assert await jobs.mark_completed(legacy) is None

    recovered = await jobs.claim_next_pending_job(STALE_AFTER)

    assert recovered is not None and recovered.id == job.id and recovered.lease_token
    completed = await jobs.mark_completed(recovered)
    assert completed is not None and completed.status == AIJobStatus.COMPLETED


@pytest.mark.asyncio
async def test_ai_outputs_are_written_once_per_job(mediation_db: AsyncDB) -> None:
    ai = MediationAIRepository(mediation_db)
    comments = MediationCommentRepository(mediation_db)
    job_id = "64b64c000000000000000403"

    def reflection(response_id: str) -> MediationAIReflection:
        return MediationAIReflection.model_validate(
            {
                "session_id": SESSION_ID,
                "perspective_id": PERSPECTIVE_ID,
                "recipient_user_type": UserType.JORIS,
                "content": {
                    "emotional_reflection": "synthetic",
                    "calming_exercise": "synthetic",
                    "possible_underlying_needs": [],
                    "things_to_avoid_right_now": [],
                    "next_best_action": "synthetic",
                    "neutral_reminder": "synthetic",
                },
                "model": "synthetic-model",
                "prompt_version": "test",
                "openai_response_id": response_id,
                "created_at": utc_now(),
                "ai_job_id": job_id,
            }
        )

    # The current owner persists first; the superseded worker reaches persistence later.
    first = await ai.insert_reflection(reflection("current-owner"))
    late = await ai.insert_reflection(reflection("superseded-worker"))
    again = await ai.insert_reflection(reflection("superseded-worker"))

    assert first.id == late.id == again.id
    assert (
        await mediation_db[settings.mediation_ai_reflections_collection_name].count_documents({})
        == 1
    )
    # The stored output is never replaced by a later writer.
    assert again.openai_response_id == first.openai_response_id

    comment_a = await comments.create_ai_comment(SESSION_ID, None, "synthetic reply", job_id)
    comment_b = await comments.create_ai_comment(SESSION_ID, None, "late duplicate", job_id)
    assert comment_a.id == comment_b.id and comment_b.content == "synthetic reply"
