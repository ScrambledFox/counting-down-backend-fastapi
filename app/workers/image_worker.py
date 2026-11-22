import asyncio
from functools import partial

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.mongo_client import get_db
from app.db.s3_client import get_s3_storage
from app.repositories.image import ImageRepository
from app.repositories.image_jobs import ImageJobRepository
from app.repositories.image_metadata import ImageMetadataRepository
from app.services.image import ImageService

logger = get_logger(__name__)
settings = get_settings()


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


async def run_image_worker(stop_event: asyncio.Event) -> None:
    """Sequential work bounds CPU/storage load; durable leases survive restarts."""
    while not stop_event.is_set():
        try:
            db = get_db()
            jobs = ImageJobRepository(db)
            service = ImageService(ImageRepository(get_s3_storage()), ImageMetadataRepository(db))
            await jobs.ensure_indexes()
            while not stop_event.is_set():
                worked = False
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
                    worked = True
                    try:
                        # Finish or release well before the five-minute lease expires.
                        await asyncio.wait_for(process(jobs, service, job), timeout=120)
                    except Exception as exc:
                        logger.exception("Image background job failed: %s", field)
                        await jobs.fail(collection, field, job, exc)
                if not worked:
                    try:
                        await asyncio.wait_for(
                            stop_event.wait(), settings.image_worker_poll_seconds
                        )
                    except TimeoutError:
                        pass
        except Exception:
            logger.exception("Image worker disconnected; retrying")
            try:
                await asyncio.wait_for(stop_event.wait(), settings.image_worker_poll_seconds)
            except TimeoutError:
                pass
