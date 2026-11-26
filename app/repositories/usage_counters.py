"""Fixed-window counters in MongoDB for login attempts and AI usage.

Each counter document is ``{_id: "<scope>:<window start>", count, expires_at}``. A TTL index
removes it after two windows, so the collection stays tiny. Increments are a single atomic
``find_one_and_update`` with upsert, so concurrent API instances share one count.
"""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.db.mongo_client import get_db
from app.models.mongo import AsyncDB
from app.util.time import utc_now

settings = get_settings()


def _window(scope: str, window_seconds: int, now: datetime) -> tuple[str, datetime]:
    timestamp = int(now.timestamp())
    start = timestamp - timestamp % window_seconds
    return f"{scope}:{start}", datetime.fromtimestamp(start, tz=now.tzinfo)


class UsageCounterRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.usage_counters_collection_name]

    async def increment(self, scope: str, window_seconds: int, now: datetime | None = None) -> int:
        """Add one to the counter of the current window and return the new count."""
        now = now or utc_now()
        counter_id, window_start = _window(scope, window_seconds, now)
        update = {
            "$inc": {"count": 1},
            "$setOnInsert": {"expires_at": window_start + timedelta(seconds=window_seconds * 2)},
        }
        try:
            doc = await self._collection.find_one_and_update(
                {"_id": counter_id}, update, upsert=True, return_document=ReturnDocument.AFTER
            )
        except DuplicateKeyError:
            # Two first increments raced on the upsert; the document exists now.
            doc = await self._collection.find_one_and_update(
                {"_id": counter_id}, update, return_document=ReturnDocument.AFTER
            )
        return int(doc["count"]) if doc else 1

    async def current(self, scope: str, window_seconds: int, now: datetime | None = None) -> int:
        counter_id, _ = _window(scope, window_seconds, now or utc_now())
        doc = await self._collection.find_one({"_id": counter_id}, {"count": 1})
        return int(doc["count"]) if doc else 0


async def ensure_usage_counter_indexes(db: AsyncDB) -> None:
    await db[settings.usage_counters_collection_name].create_index(
        "expires_at", expireAfterSeconds=0
    )
