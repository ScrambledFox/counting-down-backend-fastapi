from collections.abc import AsyncGenerator

import pytest_asyncio

from app.db.mongo_client import MotorMongoDBClient, get_mongo_client
from app.models.mongo import AsyncClient


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _mongo_client() -> AsyncGenerator[AsyncClient]:
    """Bind one Motor client to the session event loop.

    Why: get_mongo_client is lru_cached for production, so without this fixture
    the first integration test would bind the client's executor to its
    (function-scoped) loop, and every subsequent test would hit
    "Event loop is closed" when reusing the cached client.
    """
    get_mongo_client.cache_clear()
    client = get_mongo_client()
    yield client.client
    if isinstance(client, MotorMongoDBClient):
        client.client.close()
    get_mongo_client.cache_clear()
