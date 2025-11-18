from typing import Annotated

from fastapi import Depends

from app.core.time import utc_now
from app.repositories.todo import TodoRepository
from app.schemas.v1.base import MongoId
from app.schemas.v1.todo import Todo, TodoCreate, TodoUpdate


class TodoService:
    _repo: TodoRepository

    def __init__(self, repo: Annotated[TodoRepository, Depends()]) -> None:
        self._repo = repo

    async def get_all(self) -> list[Todo]:
        return await self._repo.list_todos()

    async def get_by_id(self, item_id: MongoId) -> Todo | None:
        return await self._repo.get_todo(item_id)

    async def create(self, data: TodoCreate) -> Todo:
        now = utc_now()
        new_todo = Todo(
            title=data.title.strip(),
            category=data.category.strip(),
            completed=data.completed,
            created_at=now,
        )
        return await self._repo.create_todo(new_todo)

    async def update(self, item_id: MongoId, data: TodoUpdate) -> Todo | None:
        update_data = data.model_dump(exclude_unset=True)
        for key in ("title", "category"):
            if key in update_data and isinstance(update_data[key], str):
                update_data[key] = update_data[key].strip()
        update_data["updated_at"] = utc_now()
        return await self._repo.update_todo(item_id, update_data)

    async def delete(self, item_id: MongoId) -> bool:
        return await self._repo.delete_todo(item_id)

    async def toggle_completion(self, item_id: MongoId) -> Todo | None:
        return await self._repo.toggle_todo(item_id)
