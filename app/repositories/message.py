from collections.abc import Mapping
from typing import Any

from bson import ObjectId
from fastapi import Depends

from app.core.config import get_settings
from app.db.mongo_client import get_db
from app.models.mongo import AsyncDB
from app.schemas.v1.base import MongoId
from app.schemas.v1.message import Message

settings = get_settings()


class MessageRepository:
    def __init__(self, db: AsyncDB = Depends(get_db)) -> None:
        self._collection = db[settings.messages_collection_name]

    async def list_all(self) -> list[Message]:
        cursor = self._collection.find().sort("created_at", -1)
        docs = await cursor.to_list(length=None)
        return [Message.model_validate(doc) for doc in docs]

    async def list_not_deleted(self) -> list[Message]:
        cursor = self._collection.find({"deleted_at": None})
        docs = await cursor.to_list(length=None)
        return [Message.model_validate(doc) for doc in docs]

    async def get(self, message_id: MongoId) -> Message | None:
        doc = await self._collection.find_one({"_id": ObjectId(message_id)})
        return Message.model_validate(doc) if doc else None

    async def create(self, message: Message) -> Message:
        result = await self._collection.insert_one(
            message.model_dump(by_alias=True, exclude_none=True)
        )
        doc = await self._collection.find_one({"_id": result.inserted_id})
        return Message.model_validate(doc)

    async def update(self, message_id: MongoId, data: Mapping[str, Any]) -> Message | None:
        result = await self._collection.update_one({"_id": ObjectId(message_id)}, {"$set": data})
        if result.modified_count > 0:
            return await self.get(message_id)
        return None

    async def delete(self, message_id: MongoId) -> bool:
        result = await self._collection.delete_one({"_id": ObjectId(message_id)})
        return result.deleted_count > 0
