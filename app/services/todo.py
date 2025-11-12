from __future__ import annotations

from app.core.time import utc_now
from app.repositories.todo import TodoRepository
from app.schemas.v1.todo import Todo, TodoCreate, TodoUpdate


class TodoService:
    def __init__(self, repo: TodoRepository):
        self._repo = repo

    async def get_all(self) -> list[Todo]:
        return await self._repo.list_todos()

    async def get_by_id(self, item_id: str) -> Todo | None:
        return await self._repo.get_todo(item_id)

    async def create(self, data: TodoCreate) -> Todo:
        now = utc_now()
        new_todo = Todo(
            title=data.title.strip(),
            category=data.category.strip(),
            completed=data.completed,
            created_at=now,
            updated_at=None,
        )

        created_id = await self._repo.create_todo(new_todo)

        created = await self._repo.get_todo(created_id)
        if created is None:
            raise RuntimeError(f"Failed to fetch newly created todo with id {created_id}")
        return created

    async def update(self, item_id: str, data: TodoUpdate) -> Todo | None:
        update_data = data.model_dump(exclude_unset=True)
        for key in ("title", "category"):
            if key in update_data and isinstance(update_data[key], str):
                update_data[key] = update_data[key].strip()
        update_data["updated_at"] = utc_now()
        return await self._repo.update_todo(item_id, update_data)

    async def delete(self, item_id: str) -> bool:
        return await self._repo.delete_todo(item_id)

    async def toggle_completion(self, item_id: str) -> Todo | None:
        return await self._repo.toggle_todo(item_id)
