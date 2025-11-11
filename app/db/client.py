import asyncio
from typing import Any, Final

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings

type AsyncDB = AsyncIOMotorDatabase[dict[str, Any]]
type AsyncClient = AsyncIOMotorClient[dict[str, Any]]


_client: AsyncClient | None = None
_client_lock: Final = asyncio.Lock()


async def get_db_client() -> AsyncClient:
    global _client
    if _client is not None:
        return _client

    async with _client_lock:
        if _client is not None:
            return _client

        client = AsyncIOMotorClient[dict[str, Any]](
            settings.mongo_url,
            serverSelectionTimeoutMS=5_000,
            uuidRepresentation="standard",
        )

        await client.admin.command("ping")

        _client = client
        return _client


async def get_db() -> AsyncDB:
    client = await get_db_client()
    db: AsyncDB = client[settings.mongo_app_name]
    return db


async def close_db_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
