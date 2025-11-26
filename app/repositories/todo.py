from collections.abc import Mapping
from typing import Annotated, Any

from bson import ObjectId
from fastapi import Depends

from app.core.config import settings
from app.core.time import utc_now
from app.db.mongo_client import AsyncDB, get_db
from app.schemas.v1.base import MongoId
from app.schemas.v1.todo import Todo


class TodoRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.todos_collection_name]

    async def list_todos(self) -> list[Todo]:
        cursor = self._collection.find().sort("created_at", -1)
        docs = await cursor.to_list(length=None)
        return [Todo.model_validate(doc) for doc in docs]

    async def get_todo(self, todo_id: MongoId) -> Todo | None:
        doc = await self._collection.find_one({"_id": ObjectId(todo_id)})
        return Todo.model_validate(doc) if doc else None

    async def create_todo(self, todo: Todo) -> Todo:
        result = await self._collection.insert_one(
            todo.model_dump(by_alias=True, exclude_none=True)
        )
        doc = await self._collection.find_one({"_id": result.inserted_id})
        return Todo.model_validate(doc)

    async def update_todo(self, todo_id: MongoId, data: Mapping[str, Any]) -> Todo | None:
        result = await self._collection.update_one({"_id": ObjectId(todo_id)}, {"$set": data})
        if result.modified_count > 0:
            return await self.get_todo(todo_id)
        return None

    async def delete_todo(self, todo_id: MongoId) -> bool:
        result = await self._collection.update_one(
            {"_id": ObjectId(todo_id)}, {"$set": {"deleted_at": utc_now()}}
        )
        return result.modified_count > 0

    async def toggle_todo(self, todo_id: MongoId) -> Todo | None:
        updated_doc = await self._collection.find_one_and_update(
            {"_id": ObjectId(todo_id)},
            [{"$set": {"completed": {"$not": "$completed"}}}],
            return_document=True,
        )
        return Todo.model_validate(updated_doc) if updated_doc else None
