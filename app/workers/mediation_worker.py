from app.core import logging
from app.core.config import get_settings
from app.core.logging import error_fields
from app.integrations.openai_client import OpenAIClient
from app.models.mongo import AsyncDB
from app.repositories.mediation import (
    MediationAIRepository,
    MediationCommentRepository,
    MediationJobRepository,
    MediationModerationRepository,
    MediationPerspectiveRepository,
    MediationSessionRepository,
)
from app.services.mediation_ai import MediationAIService, MediationJobSupersededError
from app.services.mediation_safety import MediationSafetyService
from app.workers.job_runner import JobResult

settings = get_settings()
logger = logging.get_logger(__name__)


def build_mediation_job_services(db: AsyncDB) -> tuple[MediationJobRepository, MediationAIService]:
    openai_client = OpenAIClient()
    jobs = MediationJobRepository(db)
    service = MediationAIService(
        session_repo=MediationSessionRepository(db),
        perspective_repo=MediationPerspectiveRepository(db),
        ai_repo=MediationAIRepository(db),
        comment_repo=MediationCommentRepository(db),
        moderation_repo=MediationModerationRepository(db),
        job_repo=jobs,
        safety_service=MediationSafetyService(openai_client),
        openai_client=openai_client,
    )
    return jobs, service


async def process_one_mediation_job(
    jobs: MediationJobRepository, service: MediationAIService
) -> JobResult:
    """Claim and process at most one mediation AI job; failures are retried by the queue.

    Every state change is fenced by the claim's lease token, so a worker whose lease went stale
    can neither persist outputs (checked before each write phase) nor change the job's state.
    """
    stale_after = settings.mediation_job_processing_timeout_seconds
    await jobs.fail_exhausted_stale_processing_jobs(stale_after)
    job = await jobs.claim_next_pending_job(stale_after)
    if not job:
        return JobResult.IDLE
    try:
        await service.process_job(job)
    except MediationJobSupersededError:
        logger.warning(
            "Mediation AI job was claimed by another worker",
            extra={"event": "job_superseded", "job_kind": "mediation"},
        )
        return JobResult.TERMINAL
    except Exception as exc:
        fields = error_fields(exc)
        logger.error(
            "Mediation AI job failed",
            extra={"event": "job_item_failed", "job_kind": "mediation", **fields},
        )
        # Store the error type only; messages may contain provider response bodies.
        await jobs.mark_failed_or_retry(job, fields["error_type"])
        return JobResult.FAILED
    if await jobs.mark_completed(job) is None:
        logger.warning(
            "Mediation AI job was claimed by another worker before completion",
            extra={"event": "job_superseded", "job_kind": "mediation"},
        )
        return JobResult.TERMINAL
    return JobResult.PROCESSED
