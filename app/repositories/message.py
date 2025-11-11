from collections.abc import Mapping
from typing import Any

from bson import ObjectId
from fastapi import Depends
from pydantic import TypeAdapter

from app.core.config import settings
from app.db.client import AsyncDB, get_db
from app.models.db import Document
from app.schemas.v1.message import Message
from app.util.mongo import from_mongo


class MessageRepository:
    def __init__(self, db: AsyncDB = Depends(get_db)) -> None:
        self._collection = db[settings.messages_collection_name]

    @classmethod
    def _to_message(cls, doc: Document) -> Message:
        raw_doc = from_mongo(doc)
        return TypeAdapter(Message).validate_python(raw_doc)
    
    async def list(self) -> list[Message]:
        cursor = self._collection.find()
        docs = await cursor.to_list(length=None)
        return [self._to_message(doc) for doc in docs]
    
    async def get(self, message_id: str) -> Message | None:
        doc = await self._collection.find_one({"_id": ObjectId(message_id)})
        return self._to_message(doc) if doc else None
    
    async def create(self, payload: Message) -> str:
        doc = await self._collection.insert_one(dict(payload))
        return str(doc.inserted_id)
    
    async def update(self, message_id: str, data: Mapping[str, Any]) -> Message | None:
        result = await self._collection.update_one({"_id": ObjectId(message_id)}, {"$set": data})
        if result.modified_count > 0:
            return await self.get(message_id)
        return None
    
    async def delete(self, message_id: str) -> bool:
        result = await self._collection.delete_one({"_id": ObjectId(message_id)})
        return result.deleted_count > 0