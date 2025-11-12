from collections.abc import Awaitable, Callable
from typing import cast

from fastapi import Depends

from app.db.client import AsyncDB, get_db
from app.repositories.message import MessageRepository
from app.repositories.todo import TodoRepository
from app.services.message import MessageService
from app.services.todo import TodoService


async def get_db_dep() -> AsyncDB:
    return await get_db()


def get_todo_repository(
    db: AsyncDB = Depends(cast(Callable[[], Awaitable[AsyncDB]], get_db_dep)),
) -> TodoRepository:
    return TodoRepository(db)


def get_todo_service(
    repo: TodoRepository = Depends(get_todo_repository),
) -> TodoService:
    return TodoService(repo)


def get_message_repository(
    db: AsyncDB = Depends(cast(Callable[[], Awaitable[AsyncDB]], get_db_dep)),
) -> MessageRepository:
    return MessageRepository(db)


def get_message_service(
    repo: MessageRepository = Depends(get_message_repository),
) -> MessageService:
    return MessageService(repo)
