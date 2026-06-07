import asyncio

from app.core import logging
from app.core.config import get_settings
from app.db.mongo_client import get_db
from app.integrations.openai_client import OpenAIClient
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


async def run_mediation_worker(stop_event: asyncio.Event | None = None) -> None:
    db = get_db()
    openai_client = OpenAIClient()
    safety = MediationSafetyService(openai_client)
    jobs = MediationJobRepository(db)
    service = MediationAIService(
        session_repo=MediationSessionRepository(db),
        perspective_repo=MediationPerspectiveRepository(db),
        ai_repo=MediationAIRepository(db),
        comment_repo=MediationCommentRepository(db),
        moderation_repo=MediationModerationRepository(db),
        job_repo=jobs,
        safety_service=safety,
        openai_client=openai_client,
    )

    while stop_event is None or not stop_event.is_set():
        stale_after = settings.mediation_job_processing_timeout_seconds
        await jobs.fail_exhausted_stale_processing_jobs(stale_after)
        job = await jobs.claim_next_pending_job(stale_after)
        if not job:
            await asyncio.sleep(settings.mediation_worker_poll_interval_seconds)
            continue
        try:
            await service.process_job(job)
            if job.id:
                await jobs.mark_completed(str(job.id))
        except Exception as exc:
            logger.exception("Mediation AI job failed")
            if job.id:
                await jobs.mark_failed_or_retry(str(job.id), str(exc))
