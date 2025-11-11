from collections.abc import Mapping
from typing import Any

from bson import ObjectId
from fastapi import Depends
from pydantic import TypeAdapter

from app.core.config import settings
from app.db.client import AsyncDB, get_db
from app.models.db import Document
from app.schemas.v1.todo import Todo
from app.util.mongo import from_mongo


class TodoRepository:
    def __init__(self, db: AsyncDB = Depends(get_db)):
        self._collection = db[settings.todos_collection_name]

    @classmethod
    def _to_todo(cls, doc: Document) -> Todo:
        raw_doc = from_mongo(doc)
        return TypeAdapter(Todo).validate_python(raw_doc)

    async def list(self) -> list[Todo]:
        cursor = self._collection.find()
        docs = await cursor.to_list(length=None)
        return [self._to_todo(doc) for doc in docs]

    async def get(self, todo_id: str) -> Todo | None:
        doc = await self._collection.find_one({"_id": ObjectId(todo_id)})
        return self._to_todo(doc) if doc else None

    async def create(self, payload: Todo) -> str:
        doc = await self._collection.insert_one(dict(payload))
        return str(doc.inserted_id)

    async def update(self, todo_id: str, data: Mapping[str, Any]) -> Todo | None:
        result = await self._collection.update_one({"_id": ObjectId(todo_id)}, {"$set": data})
        if result.modified_count > 0:
            return await self.get(todo_id)
        return None

    async def delete(self, todo_id: str) -> bool:
        result = await self._collection.delete_one({"_id": ObjectId(todo_id)})
        return result.deleted_count > 0

    async def toggle(self, todo_id: str) -> Todo | None:
        updated_doc = await self._collection.find_one_and_update(
            {"_id": ObjectId(todo_id)},
            [{"$set": {"completed": {"$not": "$completed"}}}],
            return_document=True,
        )
        return self._to_todo(updated_doc) if updated_doc else None
