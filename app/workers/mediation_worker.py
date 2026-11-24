from app.core import logging
from app.core.config import get_settings
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
from app.services.mediation_ai import MediationAIService
from app.services.mediation_safety import MediationSafetyService

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
) -> bool:
    """Claim and process at most one mediation AI job; failures are retried by the queue."""
    stale_after = settings.mediation_job_processing_timeout_seconds
    await jobs.fail_exhausted_stale_processing_jobs(stale_after)
    job = await jobs.claim_next_pending_job(stale_after)
    if not job:
        return False
    try:
        await service.process_job(job)
        if job.id:
            await jobs.mark_completed(str(job.id))
    except Exception as exc:
        logger.exception("Mediation AI job failed", extra={"error_type": type(exc).__name__})
        if job.id:
            await jobs.mark_failed_or_retry(str(job.id), str(exc))
    return True
