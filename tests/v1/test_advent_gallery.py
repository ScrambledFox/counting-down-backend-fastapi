from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
from bson import ObjectId

from app.repositories.image_metadata import ImageMetadataRepository


class AdventCollection:
    def __init__(self, documents):
        self.documents = documents

    def find(self, query):
        async def iterate():
            for document in self.documents:
                if document["uploaded_at"] < query["uploaded_at"]["$lt"]:
                    yield document

        return iterate()


def gift(year, kind="cute"):
    return {
        "_id": ObjectId(),
        "image_key": f"gift-{year}",
        "day": 22,
        "uploaded_at": datetime(year, 11, 20, tzinfo=UTC),
        "uploaded_by": "Joris",
        "title": "Christmas surprise",
        "description": "For you",
        "type": kind,
        "content_type": "image/png",
    }


def repository(advents, photos):
    collection = Mock()

    async def update(query, operation, upsert):
        assert upsert is True
        photos.setdefault(query["_id"], {"_id": query["_id"], **operation["$setOnInsert"]})

    collection.update_one = AsyncMock(side_effect=update)
    repo = ImageMetadataRepository.__new__(ImageMetadataRepository)
    repo._collection = collection
    repo._advents = AdventCollection(advents)
    return repo


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("now", "expected_years"),
    [
        (datetime(2026, 11, 22, tzinfo=UTC), [2025]),
        (datetime(2026, 12, 25, 23, 59, 59, tzinfo=UTC), [2025]),
        (datetime(2026, 12, 26, tzinfo=UTC), [2025, 2026]),
        (datetime(2027, 1, 1, tzinfo=UTC), [2025, 2026]),
    ],
)
async def test_only_finished_calendars_are_published(now, expected_years):
    photos = {}
    repo = repository([gift(2025), gift(2026), gift(2027)], photos)
    with patch("app.repositories.image_metadata.utc_now", return_value=now):
        await repo.import_completed_advents()
    assert sorted(photo["uploaded_at"].year for photo in photos.values()) == expected_years


@pytest.mark.asyncio
async def test_import_reuses_images_and_preserves_edits_and_deletions():
    source = gift(2025, "spicy")
    photos = {}
    repo = repository([source], photos)
    with patch(
        "app.repositories.image_metadata.utc_now",
        return_value=datetime(2026, 11, 22, tzinfo=UTC),
    ):
        await repo.import_completed_advents()
        imported = photos[source["_id"]]
        assert imported["image_key"] == source["image_key"]
        assert imported["title"] == source["title"]
        assert imported["description"] == source["description"]
        assert imported["uploaded_by"] == source["uploaded_by"]
        assert imported["uploaded_at"] == source["uploaded_at"]
        assert imported["image_tags"] == [
            "advent",
            "2025",
            "advent-2025-day:22",
            "spicy",
            "sensitive",
        ]

        imported["title"] = "Edited in gallery"
        imported["deleted_at"] = datetime(2026, 1, 1, tzinfo=UTC)
        await repo.import_completed_advents()
        assert len(photos) == 1
        assert photos[source["_id"]]["title"] == "Edited in gallery"
        assert photos[source["_id"]]["deleted_at"] is not None
