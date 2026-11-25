from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
import pytest_asyncio
from bson import ObjectId

from app.api.v1.image import list_images
from app.db.mongo_client import get_test_db
from app.repositories.image import ImageRepository
from app.repositories.image_jobs import ImageJobRepository, completed_advent_cutoff
from app.repositories.image_metadata import ImageMetadataRepository
from app.schemas.v1.image import ImageMetadata
from app.services.image import ImageService
from app.workers.image_worker import process_advent, process_thumbnail

NOW = datetime(2026, 11, 22, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "year"),
    [
        (NOW, 2026),
        (datetime(2026, 12, 25, 23, 59, 59, tzinfo=UTC), 2026),
        (datetime(2026, 12, 26, tzinfo=UTC), 2027),
        (datetime(2027, 1, 1, tzinfo=UTC), 2027),
    ],
)
def test_archive_release_boundary(now, year):
    assert completed_advent_cutoff(now) == datetime(year, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_gallery_read_does_not_import_or_generate_thumbnails():
    images = AsyncMock(spec=ImageRepository)
    metadata = AsyncMock(spec=ImageMetadataRepository)
    metadata.list_image_metadata_page.return_value = []
    service = ImageService(images, metadata)
    assert await service.list_image_metadata_page(12, None) == ([], None)
    assert metadata.mock_calls == [
        # A single paginated database read, regardless of the size of the advent archive.
        call.list_image_metadata_page(13, None, None, sensitive_only=False, exclude_sensitive=False)
    ]
    assert images.mock_calls == []
    assert await service.get_thumbnail_presigned_url("key", ready_sizes=[]) is None
    images.generate_thumbnail_presigned_url.assert_not_awaited()
    metadata.get_image_metadata_by_key.assert_not_awaited()
    images.generate_thumbnail_presigned_url.return_value = "signed-preview"
    assert (
        await service.get_thumbnail_presigned_url("key", 128, ready_sizes=[128]) == "signed-preview"
    )
    images.get_thumbnail_exists.assert_not_awaited()
    images.get_image.assert_not_awaited()
    images.upload_thumbnail_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_thumbnails_are_reused_without_downloading_original():
    images = AsyncMock(spec=ImageRepository)
    images.get_thumbnail_exists.return_value = True
    service = ImageService(images, AsyncMock(spec=ImageMetadataRepository))
    await service.prepare_thumbnails("key", [128, 1200])
    assert images.get_thumbnail_exists.await_count == 2
    images.get_image.assert_not_awaited()
    images.upload_thumbnail_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_gallery_page_has_no_storage_checks_or_writes():
    images = AsyncMock(spec=ImageRepository)
    images.generate_image_presigned_url.return_value = "https://example.com/original"
    images.generate_thumbnail_presigned_url.return_value = "https://example.com/preview"
    metadata = AsyncMock(spec=ImageMetadataRepository)
    metadata.list_image_metadata_page.return_value = [
        ImageMetadata(
            id=str(ObjectId()),
            image_key=str(i),
            uploaded_by="Joris",
            media_type="image/png",
            thumbnail_sizes_ready=[128, 1200],
        )
        for i in range(12)
    ]
    page = await list_images(ImageService(images, metadata), limit=12, cursor=None)
    assert len(page.items) == 12
    assert metadata.mock_calls == [
        call.list_image_metadata_page(13, None, None, sensitive_only=False, exclude_sensitive=False)
    ]
    assert images.generate_thumbnail_presigned_url.await_count == 24
    images.get_thumbnail_exists.assert_not_awaited()
    images.get_image.assert_not_awaited()
    images.upload_thumbnail_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_preparation_never_publishes_a_new_advent():
    jobs = Mock(spec=ImageJobRepository)
    jobs.existing_image = AsyncMock(return_value=None)
    jobs.publish_advent = AsyncMock()
    service = Mock(spec=ImageService)
    service._get_configured_thumbnail_sizes.return_value = [128, 1200]
    service.prepare_thumbnails = AsyncMock(side_effect=RuntimeError("storage unavailable"))
    with pytest.raises(RuntimeError, match="storage unavailable"):
        await process_advent(jobs, service, gift())
    jobs.publish_advent.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_thumbnail_request_is_durable_not_an_untracked_task():
    images = AsyncMock(spec=ImageRepository)
    images.get_image_exists.return_value = True
    metadata = AsyncMock(spec=ImageMetadataRepository)
    service = ImageService(images, metadata)
    await service.request_thumbnail_generation("key", [128, 1200])
    metadata.request_thumbnails.assert_awaited_once_with("key", [128, 1200])
    images.get_image.assert_not_awaited()


@pytest_asyncio.fixture
async def jobs():
    # CI supplies a dedicated test database; these collections are isolated from production.
    repo = ImageJobRepository(get_test_db())
    await repo.advents.delete_many({})
    await repo.images.delete_many({})
    await repo.ensure_indexes()
    yield repo
    await repo.advents.delete_many({})
    await repo.images.delete_many({})


def gift(year=2025):
    return {
        "_id": ObjectId(),
        "uploaded_at": datetime(year, 11, 20, tzinfo=UTC),
        "uploaded_by": "Joris",
        "day": 22,
        "title": "Surprise",
        "description": "For you",
        "image_key": str(ObjectId()),
        "type": "spicy",
        "content_type": "image/png",
    }


@pytest.mark.asyncio
async def test_atomic_claims_retries_and_expired_lease(jobs):
    source = gift()
    await jobs.advents.insert_one(source)
    with patch("app.repositories.image_jobs.utc_now", return_value=NOW):
        first = await jobs.claim_advent()
        assert first is not None
        assert await jobs.claim_advent() is None  # Another process cannot claim an active lease.
        await jobs.fail(jobs.advents, "archive", first, RuntimeError("temporary"))
        assert await jobs.claim_advent() is None
    with patch("app.repositories.image_jobs.utc_now", return_value=NOW + timedelta(seconds=31)):
        retry = await jobs.claim_advent()
        assert retry["archive"]["attempts"] == 2
    with patch("app.repositories.image_jobs.utc_now", return_value=NOW + timedelta(minutes=6)):
        recovered = await jobs.claim_advent()
        assert recovered["archive"]["token"] != retry["archive"]["token"]
        await jobs.finish(jobs.advents, "archive", retry)  # Stale owner cannot complete it.
        stored = await jobs.advents.find_one({"_id": source["_id"]})
        assert stored["archive"]["state"] == "processing"
        await jobs.finish(jobs.advents, "archive", recovered)
        assert await jobs.claim_advent() is None


@pytest.mark.asyncio
async def test_backfill_keeps_edits_and_deleted_pictures_and_handles_late_gifts(jobs):
    old, current = gift(), gift(2026)
    await jobs.advents.insert_many([old, current])
    service = Mock(spec=ImageService)
    service._get_configured_thumbnail_sizes.return_value = [128, 1200]
    service.prepare_thumbnails = AsyncMock()
    with patch("app.repositories.image_jobs.utc_now", return_value=NOW):
        claimed = await jobs.claim_advent()
        await process_advent(jobs, service, claimed)
        photo = await jobs.images.find_one({"_id": old["_id"]})
        assert photo["image_key"] == old["image_key"]
        assert photo["image_tags"] == ["advent", "2025", "advent-2025-day:22", "spicy", "sensitive"]
        assert photo["thumbnail_sizes_ready"] == [128, 1200]
        assert await jobs.claim_advent() is None  # Current year stays hidden.
        # Retry after publishing but before acknowledging completion preserves gallery edits.
        await jobs.images.update_one(
            {"_id": old["_id"]}, {"$set": {"title": "Edited", "deleted_at": NOW}}
        )
        await jobs.publish_advent(claimed, [128, 1200])
        assert await jobs.images.count_documents({}) == 1
        photo = await jobs.images.find_one({"_id": old["_id"]})
        assert photo["title"] == "Edited" and photo["deleted_at"] is not None
        # Reconcile an existing import with the same key but another metadata ID.
        late = gift()
        await jobs.advents.insert_one(late)
        metadata_id = ObjectId()
        await jobs.images.insert_one(
            {"_id": metadata_id, "image_key": late["image_key"], "deleted_at": NOW}
        )
        claimed_late = await jobs.claim_advent()
        service.prepare_thumbnails.reset_mock()
        await process_advent(jobs, service, claimed_late)
        service.prepare_thumbnails.assert_not_awaited()
        assert await jobs.images.count_documents({}) == 2
        assert await jobs.claim_advent() is None


@pytest.mark.asyncio
async def test_thumbnail_reconciliation_and_custom_request_race(jobs):
    metadata = ImageMetadata(image_key="legacy", uploaded_by="Joris", media_type="image/png")
    await jobs.images.insert_one(metadata.model_dump(exclude_none=True))
    service = Mock(spec=ImageService)
    service._get_configured_thumbnail_sizes.return_value = [128, 1200]
    service.prepare_thumbnails = AsyncMock()
    with patch("app.repositories.image_jobs.utc_now", return_value=NOW):
        job = await jobs.claim_thumbnail([128, 1200])
        assert await jobs.claim_thumbnail([128, 1200]) is None
        # A custom request arriving during generation must still be processed afterward.
        await jobs.images.update_one(
            {"_id": job["_id"]}, {"$addToSet": {"thumbnail_requested_sizes": 256}}
        )
        await process_thumbnail(jobs, service, job)
        next_job = await jobs.claim_thumbnail([128, 1200])
        assert next_job is not None
        await process_thumbnail(jobs, service, next_job)
        service.prepare_thumbnails.assert_awaited_with("legacy", [128, 256, 1200])
        assert await jobs.claim_thumbnail([128, 1200]) is None
