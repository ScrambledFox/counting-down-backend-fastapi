"""Worker implementations report internally handled outcomes truthfully.

Each test drives a real worker function (only storage and transport are replaced) through the
runner, and checks both the persisted queue state and the reported ``job_run_summary`` counts.
"""

import json
import logging
import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.logging import LOG_NAME, StructuredFormatter
from app.repositories.image_jobs import ImageJobRepository
from app.schemas.v1.mediation import AIJobStatus, MediationAIJob, MediationAIJobType
from app.schemas.v1.user import UserType
from app.schemas.v1.xiaobao_push import (
    XiaoBaoPushDelivery,
    XiaoBaoPushDeliveryKind,
    XiaoBaoPushDeliveryStatus,
    XiaoBaoPushSubscription,
)
from app.services import xiaobao_push
from app.services.mediation_ai import MediationJobSupersededError
from app.services.xiaobao_push import PushTransportError, XiaoBaoPushDeliveryService
from app.util.time import utc_now
from app.workers.image_worker import process_one_image_job
from app.workers.job_runner import JobHandler, JobKind, JobResult, JobRunSummary, run_jobs
from app.workers.mediation_worker import process_one_mediation_job
from app.workers.xiaobao_push_worker import process_one_xiaobao_push_work_item

SECRET = "provider body quoting the private perspective"
OID_DELIVERY = "64b64c000000000000000501"
OID_SUBSCRIPTION = "64b64c000000000000000502"
OID_JOB = "64b64c000000000000000503"


@pytest.fixture
def app_logs(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    app_logger = logging.getLogger(LOG_NAME)
    app_logger.addHandler(caplog.handler)
    previous_level = app_logger.level
    app_logger.setLevel(logging.DEBUG)
    yield caplog
    app_logger.removeHandler(caplog.handler)
    app_logger.setLevel(previous_level)


def rendered(caplog: pytest.LogCaptureFixture) -> str:
    formatter = StructuredFormatter(json_output=True)
    return "\n".join(formatter.format(record) for record in caplog.records)


async def run_once(kind: JobKind, process_one: Any) -> JobRunSummary:
    """Run a single real worker call through the runner and return the summary."""
    calls = 0

    async def once() -> JobResult:
        nonlocal calls
        calls += 1
        return await process_one() if calls == 1 else JobResult.IDLE

    handler = JobHandler(kind, once, timeout_seconds=5, idle_interval_seconds=0.01)
    return await run_jobs([handler], deadline=time.monotonic() + 30)


# --- Push -------------------------------------------------------------------------------------


def push_fixtures(
    monkeypatch: pytest.MonkeyPatch, transport_error: Exception | None
) -> tuple[Any, Any, Any, XiaoBaoPushDelivery]:
    now = utc_now()
    delivery = XiaoBaoPushDelivery(
        id=OID_DELIVERY,
        kind=XiaoBaoPushDeliveryKind.TEST,
        owner_user_type=UserType.JORIS,
        subscription_id=OID_SUBSCRIPTION,
        status=XiaoBaoPushDeliveryStatus.PROCESSING,
        attempt_count=1,
        lease_token="lease",
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    subscription = XiaoBaoPushSubscription(
        id=OID_SUBSCRIPTION,
        owner_user_type=UserType.JORIS,
        device_id="device",
        endpoint_ciphertext="synthetic",
        p256dh_ciphertext="synthetic",
        auth_ciphertext="synthetic",
        endpoint_hash="hash",
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )
    monkeypatch.setattr(
        xiaobao_push.XiaoBaoPushCipher, "__init__", lambda _self: None, raising=False
    )
    monkeypatch.setattr(
        xiaobao_push.XiaoBaoPushCipher, "decrypt", lambda _self, _value: "synthetic"
    )
    subscriptions = SimpleNamespace(
        get_by_id=AsyncMock(return_value=subscription),
        record_failure=AsyncMock(),
        record_success=AsyncMock(),
        delete_owned=AsyncMock(),
    )
    deliveries = SimpleNamespace(
        fail_exhausted_stale=AsyncMock(),
        claim_next=AsyncMock(return_value=delivery),
        mark_delivered=AsyncMock(return_value=True),
        mark_terminal=AsyncMock(return_value=True),
        retry=AsyncMock(return_value=True),
        cancel_for_subscription=AsyncMock(),
    )
    transport = SimpleNamespace(send=AsyncMock(side_effect=transport_error))
    service = XiaoBaoPushDeliveryService(subscriptions, deliveries, SimpleNamespace(), transport)
    dispatch = SimpleNamespace(dispatch_pending=AsyncMock(return_value=0))
    return dispatch, service, deliveries, delivery


@pytest.mark.asyncio
async def test_retryable_push_failure_is_counted_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch, service, deliveries, delivery = push_fixtures(
        monkeypatch, PushTransportError("rate_limited", retryable=True)
    )

    summary = await run_once(
        JobKind.PUSH, lambda: process_one_xiaobao_push_work_item(dispatch, service, deliveries)
    )

    deliveries.retry.assert_awaited_once_with(delivery, "rate_limited")
    assert summary.failed == {"push": 1} and not summary.processed
    assert summary.unsuccessful


@pytest.mark.asyncio
async def test_unexpected_push_rejection_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch, service, deliveries, delivery = push_fixtures(
        monkeypatch, PushTransportError("rejected")
    )

    summary = await run_once(
        JobKind.PUSH, lambda: process_one_xiaobao_push_work_item(dispatch, service, deliveries)
    )

    deliveries.mark_terminal.assert_awaited_once_with(delivery, "rejected")
    assert summary.failed == {"push": 1}


@pytest.mark.asyncio
async def test_expired_push_subscription_is_an_expected_terminal_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch, service, deliveries, delivery = push_fixtures(
        monkeypatch, PushTransportError("expired")
    )

    summary = await run_once(
        JobKind.PUSH, lambda: process_one_xiaobao_push_work_item(dispatch, service, deliveries)
    )

    deliveries.mark_terminal.assert_awaited_once_with(delivery, "expired")
    assert summary.terminal == {"push": 1}
    assert not summary.failed and not summary.unsuccessful


@pytest.mark.asyncio
async def test_revoked_push_subscription_is_terminal_and_delivered_push_is_processed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch, service, deliveries, delivery = push_fixtures(monkeypatch, None)
    assert await service.process(delivery) == JobResult.PROCESSED
    deliveries.mark_delivered.assert_awaited_once_with(delivery)

    service._subscriptions.get_by_id = AsyncMock(return_value=None)
    assert await service.process(delivery) == JobResult.TERMINAL
    deliveries.mark_terminal.assert_awaited_with(delivery, "subscription_revoked")


# --- Mediation --------------------------------------------------------------------------------


def claimed_mediation_job() -> MediationAIJob:
    now = utc_now()
    return MediationAIJob(
        id=OID_JOB,
        job_type=MediationAIJobType.PRIVATE_REFLECTION,
        status=AIJobStatus.PROCESSING,
        session_id="64b64c000000000000000504",
        idempotency_key="private_reflection:synthetic",
        lease_token="token",
        attempts=1,
        created_at=now,
        updated_at=now,
    )


def mediation_jobs() -> SimpleNamespace:
    return SimpleNamespace(
        fail_exhausted_stale_processing_jobs=AsyncMock(return_value=0),
        claim_next_pending_job=AsyncMock(return_value=claimed_mediation_job()),
        mark_failed_or_retry=AsyncMock(),
        mark_completed=AsyncMock(return_value=claimed_mediation_job()),
    )


@pytest.mark.asyncio
async def test_internally_handled_mediation_failure_is_counted_and_sanitized(
    app_logs: pytest.LogCaptureFixture,
) -> None:
    jobs = mediation_jobs()
    service = SimpleNamespace(process_job=AsyncMock(side_effect=RuntimeError(SECRET)))

    summary = await run_once(JobKind.MEDIATION, lambda: process_one_mediation_job(jobs, service))

    stored_error = jobs.mark_failed_or_retry.await_args.args[1]
    assert stored_error == "RuntimeError"
    assert summary.failed == {"mediation": 1} and summary.unsuccessful
    jobs.mark_completed.assert_not_awaited()
    assert SECRET not in rendered(app_logs)
    summary_payload = json.loads(
        StructuredFormatter(json_output=True).format(
            logging.makeLogRecord({"msg": "x", **summary.as_log_fields()})
        )
    )
    assert summary_payload["failed_total"] == 1


@pytest.mark.asyncio
async def test_superseded_mediation_worker_is_terminal_not_failed() -> None:
    jobs = mediation_jobs()
    service = SimpleNamespace(process_job=AsyncMock(side_effect=MediationJobSupersededError()))

    summary = await run_once(JobKind.MEDIATION, lambda: process_one_mediation_job(jobs, service))

    assert summary.terminal == {"mediation": 1} and not summary.failed
    jobs.mark_failed_or_retry.assert_not_awaited()


# --- Image ------------------------------------------------------------------------------------


class RecordingCollection:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    async def update_one(self, _query: dict[str, Any], update: dict[str, Any]) -> None:
        self.updates.append(update)


@pytest.mark.asyncio
async def test_internally_handled_image_failure_is_counted_and_stores_type_only(
    monkeypatch: pytest.MonkeyPatch, app_logs: pytest.LogCaptureFixture
) -> None:
    advents = RecordingCollection()
    jobs = ImageJobRepository.__new__(ImageJobRepository)
    jobs.advents = advents  # type: ignore[assignment]
    jobs.images = RecordingCollection()  # type: ignore[assignment]
    job = {"_id": "advent-1", "archive": {"token": "t", "attempts": 1}, "image_key": "k"}
    jobs.claim_advent = AsyncMock(return_value=job)  # type: ignore[method-assign]

    async def failing_archive(*_args: object) -> None:
        raise RuntimeError(SECRET)

    monkeypatch.setattr("app.workers.image_worker.process_advent", failing_archive)
    service = SimpleNamespace(_get_configured_thumbnail_sizes=lambda: [128])

    summary = await run_once(JobKind.IMAGE, lambda: process_one_image_job(jobs, service))

    (update,) = advents.updates
    assert update["$set"]["archive.last_error"] == "RuntimeError"
    assert summary.failed == {"image": 1} and summary.unsuccessful
    assert SECRET not in rendered(app_logs)


# --- Back-off ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_that_keeps_failing_backs_off_instead_of_busy_looping() -> None:
    import asyncio

    calls = 0

    async def always_failed() -> JobResult:
        nonlocal calls
        calls += 1
        return JobResult.FAILED

    stop = asyncio.Event()
    runner = asyncio.create_task(
        run_jobs(
            [JobHandler(JobKind.MEDIATION, always_failed, 1, idle_interval_seconds=0.1)],
            continuous=True,
            stop_event=stop,
        )
    )
    await asyncio.sleep(0.35)
    stop.set()
    summary = await runner

    assert 2 <= calls <= 5
    assert summary.failed["mediation"] == calls
