from collections.abc import Awaitable, Callable
from typing import cast

from fastapi import Depends

from app.db.client import AsyncDB
from app.db.dependencies import get_db_dep
from app.repositories.message import MessageRepository
from app.repositories.todo import TodoRepository


def get_todo_repository(
    db: AsyncDB = Depends(cast(Callable[[], Awaitable[AsyncDB]], get_db_dep)),
) -> TodoRepository:
    return TodoRepository(db)


def get_message_repository(
    db: AsyncDB = Depends(cast(Callable[[], Awaitable[AsyncDB]], get_db_dep)),
) -> MessageRepository:
    return MessageRepository(db)
