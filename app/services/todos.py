from __future__ import annotations

from typing import Any

from app.repositories.todos import TodoRepository


class TodoService:
    def __init__(self, repo: TodoRepository):
        self._repo = repo

    async def get_all_items(self) -> list[dict[str, Any]]:
        return await self._repo.list()

    async def get_item_by_id(self, item_id: str) -> dict[str, Any] | None:
        return await self._repo.get(item_id)

    async def create_item(self, data: dict[str, Any]) -> dict[str, Any]:
        title = data.get("title", "").strip()
        if not title:
            raise ValueError("Title cannot be empty")
        
        category = data.get("category", "").strip()
        if not category:
            raise ValueError("Category cannot be empty")
        
        cleaned_data = {
            "title": title,
            "category": category,
            "completed": data.get("completed", False),
        }
        
        return await self._repo.create(cleaned_data)

    async def update_item(
        self, item_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        existing_item = await self._repo.get(item_id)
        if not existing_item:
            return None
        
        update_data = {}
        
        if "title" in data:
            title = data["title"].strip()
            if not title:
                raise ValueError("Title cannot be empty")
            update_data["title"] = title
        
        if "category" in data:
            category = data["category"].strip()
            if not category:
                raise ValueError("Category cannot be empty")
            update_data["category"] = category
        
        if "completed" in data:
            update_data["completed"] = data["completed"]
        
        return await self._repo.update(item_id, update_data)

    async def delete_item(self, item_id: str) -> bool:
        return await self._repo.delete(item_id)

    async def toggle_item_completion(self, item_id: str) -> dict[str, Any] | None:
        item = await self._repo.get(item_id)
        if not item:
            return None
        if item.get("completed", False):
            return await self._repo.mark_incomplete(item_id)
        else:
            return await self._repo.mark_completed(item_id)
