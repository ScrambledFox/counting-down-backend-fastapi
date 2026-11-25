import asyncio
from functools import partial

from app.core.config import get_settings
from app.core.logging import error_fields, get_logger
from app.db.s3_client import get_s3_storage
from app.models.mongo import AsyncDB
from app.repositories.image import ImageRepository
from app.repositories.image_jobs import ImageJobRepository
from app.repositories.image_metadata import ImageMetadataRepository
from app.services.image import ImageService
from app.workers.job_runner import JobResult

logger = get_logger(__name__)
settings = get_settings()

IMAGE_JOB_TIMEOUT_SECONDS = 120


async def process_advent(jobs: ImageJobRepository, service: ImageService, job: dict) -> None:
    existing = await jobs.existing_image(job)
    if existing and existing.get("deleted_at"):
        await jobs.finish(
            jobs.advents, "archive", job, {"archive.gallery_image_id": existing["_id"]}
        )
        return
    sizes = service._get_configured_thumbnail_sizes()
    await service.prepare_thumbnails(job["image_key"], sizes)
    await jobs.publish_advent(job, sizes)


async def process_thumbnail(jobs: ImageJobRepository, service: ImageService, job: dict) -> None:
    sizes = sorted(
        set(service._get_configured_thumbnail_sizes() + job.get("thumbnail_requested_sizes", []))
    )
    await service.prepare_thumbnails(job["image_key"], sizes)
    await jobs.finish_thumbnail(job, sizes)


async def process_one_image_job(jobs: ImageJobRepository, service: ImageService) -> JobResult:
    """Claim and process at most one advent archive or thumbnail job.

    Sequential work bounds CPU and storage load; durable leases survive restarts.
    """
    for field, collection, claim, process in (
        ("archive", jobs.advents, jobs.claim_advent, process_advent),
        (
            "thumbnail_job",
            jobs.images,
            partial(jobs.claim_thumbnail, service._get_configured_thumbnail_sizes()),
            process_thumbnail,
        ),
    ):
        job = await claim()
        if job is None:
            continue
        try:
            # Finish or release well before the five-minute lease expires.
            await asyncio.wait_for(process(jobs, service, job), timeout=IMAGE_JOB_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.error(
                "Image background job failed",
                extra={"event": "job_item_failed", "job_kind": "image", **error_fields(exc)},
            )
            await jobs.fail(collection, field, job, exc)
            return JobResult.FAILED
        return JobResult.PROCESSED
    return JobResult.IDLE


def build_image_job_services(db: AsyncDB) -> tuple[ImageJobRepository, ImageService]:
    jobs = ImageJobRepository(db)
    service = ImageService(ImageRepository(get_s3_storage()), ImageMetadataRepository(db))
    return jobs, service
