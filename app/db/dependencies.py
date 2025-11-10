from collections.abc import AsyncIterator

from motor.motor_asyncio import AsyncIOMotorDatabase

from .client import get_database


async def get_db() -> AsyncIterator[AsyncIOMotorDatabase]:
    yield get_database()
