from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from app.core.time import utc_now
from app.models.todo import TodoModel
from app.repositories.todo import TodoRepository
from app.schemas.v1.todo import Todo, TodoCreate, TodoUpdate


class TodoService:
    def __init__(self, repo: TodoRepository):
        self._repo = repo
        self._todos_adapter = TypeAdapter(list[Todo])
        self._todo_adapter = TypeAdapter(Todo)

    def _to_todo(self, doc: dict[str, Any]) -> Todo:
        return self._todo_adapter.validate_python(doc)

    async def get_all(self) -> list[Todo]:
        docs = await self._repo.list()
        return [self._to_todo(doc) for doc in docs]

    async def get_by_id(self, item_id: str) -> Todo | None:
        doc = await self._repo.get(item_id)
        if doc:
            return self._to_todo(doc)
        return None

    async def create(self, data: TodoCreate) -> Todo:
        todo = TodoModel.from_dict(data)
        new_id = await self._repo.create(todo)
        return self._to_todo({**todo.model_dump(), "id": new_id})

    async def update(self, item_id: str, data: TodoUpdate) -> Todo | None:
        update_data = data.model_dump(exclude_unset=True)
        for key in ("title", "category"):
            if key in update_data and isinstance(update_data[key], str):
                update_data[key] = update_data[key].strip()
        update_data["updated_at"] = utc_now()
        updated_doc = await self._repo.update(item_id, update_data)
        if updated_doc:
            return self._to_todo(updated_doc)
        return None

    async def delete(self, item_id: str) -> bool:
        return await self._repo.delete(item_id)

    async def toggle_completion(self, item_id: str) -> Todo | None:
        item = await self._repo.toggle(item_id)
        if item:
            return self._to_todo(item)
        return None
