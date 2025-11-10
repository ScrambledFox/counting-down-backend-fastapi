from collections.abc import AsyncIterator

from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.repositories.todos import TodoRepository

from .client import get_database


async def get_db() -> AsyncIterator[AsyncIOMotorDatabase]:
    yield get_database()


async def get_todo_repo(
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> TodoRepository:
    return TodoRepository(db)
