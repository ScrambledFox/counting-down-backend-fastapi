from fastapi import Depends

from app.db.client import AsyncDB, get_db
from app.repositories.todo import TodoRepository
from app.services.todo import TodoService


async def get_db_dep() -> AsyncDB:
    return await get_db()


def get_todo_repository(
    db: AsyncDB = Depends(get_db_dep),
) -> TodoRepository:
    return TodoRepository(db)


def get_todo_service(repo: TodoRepository = Depends(get_todo_repository)) -> TodoService:
    return TodoService(repo)
