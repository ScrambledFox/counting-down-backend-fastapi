from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from pymongo import ReturnDocument

from app.core.config import get_settings
from app.models.mongo import AsyncDB
from app.util.time import utc_now

settings = get_settings()

IMAGE_JOB_LEASE_SECONDS = 300


def completed_advent_cutoff(now: datetime) -> datetime:
    now = now.astimezone(UTC)
    year = now.year + ((now.month, now.day) >= (12, 26))
    return datetime(year, 1, 1, tzinfo=UTC)


class ImageJobRepository:
    """Durable per-image work, claimed atomically across web processes."""

    def __init__(self, db: AsyncDB) -> None:
        self.advents = db[settings.advent_collection_name]
        self.images = db[settings.image_metadata_collection_name]

    async def ensure_indexes(self) -> None:
        await self.advents.create_index([("archive.state", 1), ("uploaded_at", 1)])
        await self.images.create_index([("deleted_at", 1), ("thumbnail_job.retry_at", 1)])

    @staticmethod
    def _available(field: str, now: datetime) -> dict[str, Any]:
        return {
            "$and": [
                {
                    "$or": [
                        {f"{field}.lease_until": {"$exists": False}},
                        {f"{field}.lease_until": {"$lte": now}},
                    ]
                },
                {
                    "$or": [
                        {f"{field}.retry_at": {"$exists": False}},
                        {f"{field}.retry_at": {"$lte": now}},
                    ]
                },
            ]
        }

    async def _claim(self, collection: Any, field: str, query: dict) -> dict | None:
        now = utc_now()
        return await collection.find_one_and_update(
            {"$and": [query, self._available(field, now)]},
            {
                "$set": {
                    f"{field}.state": "processing",
                    f"{field}.token": uuid4().hex,
                    f"{field}.lease_until": now + timedelta(seconds=IMAGE_JOB_LEASE_SECONDS),
                },
                "$inc": {f"{field}.attempts": 1},
            },
            sort=[("uploaded_at", 1), ("_id", 1)],
            return_document=ReturnDocument.AFTER,
        )

    async def claim_advent(self) -> dict | None:
        return await self._claim(
            self.advents,
            "archive",
            {
                "uploaded_at": {"$lt": completed_advent_cutoff(utc_now())},
                "archive.state": {"$ne": "completed"},
            },
        )

    async def claim_thumbnail(self, sizes: list[int]) -> dict | None:
        return await self._claim(
            self.images,
            "thumbnail_job",
            {
                "deleted_at": None,
                "$expr": {
                    "$eq": [
                        {
                            "$setIsSubset": [
                                {
                                    "$setUnion": [
                                        sizes,
                                        {"$ifNull": ["$thumbnail_requested_sizes", []]},
                                    ]
                                },
                                {"$ifNull": ["$thumbnail_sizes_ready", []]},
                            ]
                        },
                        False,
                    ]
                },
            },
        )

    async def existing_image(self, source: dict) -> dict | None:
        # Include soft deletions so reconciliation never resurrects a deleted picture.
        return await self.images.find_one(
            {
                "$or": [
                    {"_id": source["_id"]},
                    {"image_key": source["image_key"]},
                ]
            }
        )

    async def publish_advent(self, source: dict, sizes: list[int]) -> None:
        existing = await self.existing_image(source)
        image_id = existing["_id"] if existing else source["_id"]
        year = source["uploaded_at"].year
        tags = ["advent", str(year), f"advent-{year}-day:{source['day']}", source["type"]]
        if source["type"] in ("spicy", "hot"):
            tags.append("sensitive")
        await self.images.update_one(
            {"_id": image_id},
            {
                "$setOnInsert": {
                    "image_key": source["image_key"],
                    "uploaded_by": source["uploaded_by"],
                    "uploaded_at": source["uploaded_at"],
                    "title": source.get("title", "Advent gift"),
                    "description": source.get("description", ""),
                    "media_type": source.get("content_type"),
                    "image_tags": tags,
                },
                "$set": {"source_advent_id": source["_id"]},
                "$addToSet": {"thumbnail_sizes_ready": {"$each": sizes}},
            },
            upsert=True,
        )
        await self.finish(self.advents, "archive", source, {"archive.gallery_image_id": image_id})

    async def finish(
        self, collection: Any, field: str, job: dict, extra: dict | None = None
    ) -> None:
        await collection.update_one(
            {"_id": job["_id"], f"{field}.token": job[field]["token"]},
            {
                "$set": {
                    f"{field}.state": "completed",
                    f"{field}.completed_at": utc_now(),
                    **(extra or {}),
                },
                "$unset": {
                    f"{field}.lease_until": "",
                    f"{field}.retry_at": "",
                    f"{field}.last_error": "",
                },
            },
        )

    async def finish_thumbnail(self, job: dict, sizes: list[int]) -> None:
        # Only the current lease holder may acknowledge work.
        await self.images.update_one(
            {"_id": job["_id"], "thumbnail_job.token": job["thumbnail_job"]["token"]},
            {"$addToSet": {"thumbnail_sizes_ready": {"$each": sizes}}},
        )
        await self.finish(self.images, "thumbnail_job", job)

    async def fail(self, collection: Any, field: str, job: dict, error: Exception) -> None:
        delay = min(3600, 30 * 2 ** min(job[field].get("attempts", 1) - 1, 7))
        await collection.update_one(
            {"_id": job["_id"], f"{field}.token": job[field]["token"]},
            {
                "$set": {
                    f"{field}.state": "failed",
                    f"{field}.last_error": str(error)[:500],
                    f"{field}.retry_at": utc_now() + timedelta(seconds=delay),
                },
                "$unset": {f"{field}.lease_until": ""},
            },
        )
