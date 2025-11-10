from collections.abc import AsyncIterator

from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.repositories.together_list import TogetherListRepository

from .client import get_database


async def get_db() -> AsyncIterator[AsyncIOMotorDatabase]:
    yield get_database()


async def get_together_list_repo(
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> TogetherListRepository:
    return TogetherListRepository(db)
