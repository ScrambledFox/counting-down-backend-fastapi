"""Bind each durable queue's existing single-item function to the job runner."""

from collections.abc import Awaitable, Callable, Iterable

from app.core.config import get_settings
from app.models.mongo import AsyncDB
from app.repositories.image_jobs import IMAGE_JOB_LEASE_SECONDS
from app.workers.image_worker import build_image_job_services, process_one_image_job
from app.workers.job_runner import JobHandler, JobKind, JobResult
from app.workers.mediation_worker import build_mediation_job_services, process_one_mediation_job
from app.workers.xiaobao_push_worker import build_push_services, process_one_xiaobao_push_work_item
from app.workers.xiaobao_routine_clock import (
    build_routine_clock_repositories,
    process_xiaobao_routine_clock_iteration,
)
from app.workers.xiaobao_routine_worker import (
    build_routine_execution_service,
    process_one_xiaobao_routine_work_item,
)

settings = get_settings()

CLOCK_TIMEOUT_SECONDS = 60.0


def within_lease(lease_seconds: float) -> float:
    """Return a timeout that leaves the lease alive after cancellation.

    A cancelled item keeps its lease until it expires, so no other runner can claim it while
    the cancelled work might still be unwinding.
    """
    return lease_seconds - min(60.0, lease_seconds / 4)


def _lazy_queue[Services](
    kind: JobKind,
    build: Callable[[], Services],
    process: Callable[[Services], Awaitable[JobResult]],
    *,
    timeout_seconds: float,
    idle_interval_seconds: float,
) -> JobHandler:
    """Build a queue's dependencies on first use, independently of every other queue.

    A queue whose dependencies cannot be built (for example a missing API key) fails only its own
    turns: the runner records the failure, backs off for the idle interval and tries again, while
    healthy queues keep running.
    """
    services: Services | None = None

    async def process_one() -> JobResult:
        nonlocal services
        if services is None:
            services = build()
        return await process(services)

    return JobHandler(
        kind=kind,
        process_one=process_one,
        timeout_seconds=timeout_seconds,
        idle_interval_seconds=idle_interval_seconds,
    )


def _clock_handler(db: AsyncDB) -> JobHandler:
    async def process(repositories: tuple) -> JobResult:
        materialized = await process_xiaobao_routine_clock_iteration(*repositories)
        return JobResult.PROCESSED if materialized else JobResult.IDLE

    return _lazy_queue(
        JobKind.CLOCK,
        lambda: build_routine_clock_repositories(db),
        process,
        timeout_seconds=CLOCK_TIMEOUT_SECONDS,
        idle_interval_seconds=settings.xiaobao_routine_clock_poll_interval_seconds,
    )


def _push_handler(db: AsyncDB) -> JobHandler:
    return _lazy_queue(
        JobKind.PUSH,
        lambda: build_push_services(db),
        lambda services: process_one_xiaobao_push_work_item(*services),
        timeout_seconds=within_lease(settings.xiaobao_web_push_lease_seconds),
        idle_interval_seconds=settings.xiaobao_web_push_worker_poll_interval_seconds,
    )


def _routine_handler(db: AsyncDB) -> JobHandler:
    return _lazy_queue(
        JobKind.ROUTINE,
        lambda: build_routine_execution_service(db),
        lambda services: process_one_xiaobao_routine_work_item(*services),
        timeout_seconds=within_lease(settings.xiaobao_routine_lease_seconds),
        idle_interval_seconds=settings.xiaobao_routine_worker_poll_interval_seconds,
    )


def _mediation_handler(db: AsyncDB) -> JobHandler:
    return _lazy_queue(
        JobKind.MEDIATION,
        lambda: build_mediation_job_services(db),
        lambda services: process_one_mediation_job(*services),
        timeout_seconds=within_lease(settings.mediation_job_processing_timeout_seconds),
        idle_interval_seconds=settings.mediation_worker_poll_interval_seconds,
    )


def _image_handler(db: AsyncDB) -> JobHandler:
    return _lazy_queue(
        JobKind.IMAGE,
        lambda: build_image_job_services(db),
        lambda services: process_one_image_job(*services),
        timeout_seconds=within_lease(IMAGE_JOB_LEASE_SECONDS),
        idle_interval_seconds=settings.image_worker_poll_seconds,
    )


_BUILDERS = {
    JobKind.CLOCK: _clock_handler,
    JobKind.PUSH: _push_handler,
    JobKind.ROUTINE: _routine_handler,
    JobKind.MEDIATION: _mediation_handler,
    JobKind.IMAGE: _image_handler,
}


def build_job_handlers(db: AsyncDB, kinds: Iterable[JobKind]) -> list[JobHandler]:
    """Build handlers for the requested queues, in a stable order and without duplicates."""
    wanted = set(kinds)
    return [build(db) for kind, build in _BUILDERS.items() if kind in wanted]


def in_process_job_kinds() -> list[JobKind]:
    """Queues the web process should work on itself, from the existing feature flags."""
    kinds: list[JobKind] = []
    if settings.xiaobao_in_process_jobs_enabled:
        kinds += [JobKind.CLOCK, JobKind.PUSH, JobKind.ROUTINE]
    if settings.mediation_worker_enabled:
        kinds.append(JobKind.MEDIATION)
    if settings.image_worker_enabled:
        kinds.append(JobKind.IMAGE)
    return kinds
