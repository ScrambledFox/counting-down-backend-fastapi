from datetime import UTC, datetime
from typing import Annotated

from bson import ObjectId
from fastapi import Depends
from pymongo import ASCENDING

from app.core.config import get_settings
from app.db.mongo_client import get_db
from app.models.mongo import AsyncDB
from app.schemas.v1.advent import Advent
from app.schemas.v1.base import MongoId
from app.schemas.v1.user import UserType
from app.util.time import utc_now

settings = get_settings()


def current_year_filter(user_type: UserType) -> dict:
    # Existing gifts already have an upload timestamp, so no data migration is needed.
    year = utc_now().year
    return {
        "uploaded_by": user_type,
        "uploaded_at": {
            "$gte": datetime(year, 1, 1, tzinfo=UTC),
            "$lt": datetime(year + 1, 1, 1, tzinfo=UTC),
        },
    }


class AdventRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.advent_collection_name]

    async def get_advents_uploaded_by(self, user_type: UserType) -> list[Advent]:
        cursor = self._collection.find(current_year_filter(user_type)).sort(
            [("day", ASCENDING), ("uploaded_at", ASCENDING)]
        )
        docs = await cursor.to_list(length=None)
        return [Advent.model_validate(doc) for doc in docs]

    async def get_advent_by_id(self, advent_ref_id: MongoId) -> Advent | None:
        doc = await self._collection.find_one({"_id": ObjectId(advent_ref_id)})
        return Advent.model_validate(doc) if doc else None

    async def get_advents_day_uploaded_by(self, day: int, user_type: UserType) -> list[Advent]:
        cursor = self._collection.find({**current_year_filter(user_type), "day": day}).sort(
            [("day", ASCENDING), ("uploaded_at", ASCENDING)]
        )
        docs = await cursor.to_list(length=None)
        return [Advent.model_validate(doc) for doc in docs]

    async def create_advent(self, advent_image_ref: Advent) -> Advent:
        result = await self._collection.insert_one(
            advent_image_ref.model_dump(by_alias=True, exclude_none=True)
        )
        doc = await self._collection.find_one({"_id": result.inserted_id})
        return Advent.model_validate(doc)

    async def delete_advent_by_id(self, advent_id: MongoId) -> bool:
        result = await self._collection.delete_one({"_id": ObjectId(advent_id)})
        return result.deleted_count > 0

    async def count_advents_uploaded_by(self, user_type: UserType) -> int:
        return await self._collection.count_documents(current_year_filter(user_type))
