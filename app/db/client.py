import asyncio
from typing import Final

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings
from app.models.db import Document

type AsyncDB = AsyncIOMotorDatabase[Document]
type AsyncClient = AsyncIOMotorClient[Document]


_client: AsyncClient | None = None
_client_lock: Final = asyncio.Lock()


async def get_db_client() -> AsyncClient:
    global _client
    if _client is not None:
        return _client

    async with _client_lock:
        if _client is not None:
            return _client

        client = AsyncIOMotorClient[Document](
            settings.mongo_url,
            serverSelectionTimeoutMS=5_000,
            uuidRepresentation="standard",
        )

        try:
            await client.admin.command("ping")
        except Exception as e:
            raise ConnectionError("Could not connect to MongoDB") from e

        _client = client
        return _client


async def get_db() -> AsyncDB:
    client = await get_db_client()
    return client[settings.mongo_app_name]

async def get_test_db() -> AsyncDB:
    client = await get_db_client()
    return client["test"]

async def get_test_db() -> AsyncDB:
    client = await get_db_client()
    return client["test"]


async def close_db_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
