from __future__ import annotations

import datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import settings

COLLECTION_NAME = settings.together_list_collection_name

class TogetherListRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self._db = db
        self._collection = db[COLLECTION_NAME]

    @staticmethod
    def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
        if not doc:
            return {}
        doc["id"] = str(doc["_id"])
        return doc

    async def list(self) -> list[dict[str, Any]]:
        cursor = self._collection.find({}, sort=[("created_at", 1)])
        return [self._serialize(d) async for d in cursor]

    async def get(self, item_id: str) -> dict[str, Any] | None:
        if not ObjectId.is_valid(item_id):
            return None
        doc = await self._collection.find_one({"_id": ObjectId(item_id)})
        return self._serialize(doc) if doc else None

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        now = datetime.datetime.now(datetime.UTC)
        payload = {
            **data,
            "completed": data.get("completed", False),
            "created_at": now,
            "updated_at": now,
        }
        result = await self._collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._serialize(payload)

    async def update(self, item_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        if not ObjectId.is_valid(item_id):
            return None
        data["updated_at"] = datetime.datetime.now(datetime.UTC)
        result = await self._collection.find_one_and_update(
            {"_id": ObjectId(item_id)},
            {"$set": data},
            return_document=True,
        )
        return self._serialize(result) if result else None

    async def delete(self, item_id: str) -> bool:
        if not ObjectId.is_valid(item_id):
            return False
        res = await self._collection.delete_one({"_id": ObjectId(item_id)})
        return res.deleted_count == 1

    async def mark_completed(self, item_id: str) -> dict[str, Any] | None:
        return await self.update(item_id, {"completed": True})
    
    async def mark_incomplete(self, item_id: str) -> dict[str, Any] | None:
        return await self.update(item_id, {"completed": False})
