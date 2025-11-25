from typing import Annotated

from bson import ObjectId
from fastapi import Depends

from app.core.config import settings
from app.db.mongo_client import get_db
from app.models.mongo import AsyncDB
from app.schemas.v1.advent import AdventRef, ImageActor
from app.schemas.v1.base import MongoId


class AdventRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.advent_collection_name]

    async def list_advent_refs(self) -> list[AdventRef]:
        cursor = self._collection.find().sort("advent_day", 1)
        docs = await cursor.to_list(length=None)
        return [AdventRef.model_validate(doc) for doc in docs]

    async def get_advent_ref_by_id(self, advent_ref_id: MongoId) -> AdventRef | None:
        doc = await self._collection.find_one({"_id": ObjectId(advent_ref_id)})
        return AdventRef.model_validate(doc) if doc else None

    async def get_advent_ref_by_key(self, key: str) -> AdventRef | None:
        doc = await self._collection.find_one({"key": key})
        return AdventRef.model_validate(doc) if doc else None

    async def get_advent_ref_by_day_and_actor(
        self, advent_day: int, actor: ImageActor
    ) -> list[AdventRef]:
        cursor = self._collection.find({"advent_day": advent_day, "actor": actor.value})
        docs = await cursor.to_list(length=None)
        return [AdventRef.model_validate(doc) for doc in docs] if docs else []

    async def get_advent_ref_by_day(self, advent_day: int) -> list[AdventRef]:
        cursor = self._collection.find({"advent_day": advent_day})
        docs = await cursor.to_list(length=None)
        return [AdventRef.model_validate(doc) for doc in docs] if docs else []

    async def create_advent_ref(self, advent_image_ref: AdventRef) -> AdventRef:
        result = await self._collection.insert_one(
            advent_image_ref.model_dump(by_alias=True, exclude_none=True)
        )
        doc = await self._collection.find_one({"_id": result.inserted_id})
        return AdventRef.model_validate(doc)
