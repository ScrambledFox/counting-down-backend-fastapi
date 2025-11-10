from fastapi import Depends

from app.repositories.dependencies import get_todo_repo
from app.repositories.todos import TodoRepository
from app.services.todo import TodoService


async def get_todo_service(
    repo: TodoRepository = Depends(get_todo_repo),
) -> TodoService:
    return TodoService(repo)
