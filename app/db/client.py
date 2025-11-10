from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    """Return a cached Motor client instance, creating it if needed."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongo_url)
    return _client


def get_database() -> AsyncIOMotorDatabase:
    """Return the primary application database."""
    return get_client()[settings.mongo_db_name]


def close_client():
    """Close the Motor client if it exists."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
