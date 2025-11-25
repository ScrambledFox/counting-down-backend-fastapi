from functools import lru_cache

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.db.interfaces.mongo import MongoDBClient
from app.models.mongo import AsyncClient, AsyncDB


class MotorMongoDBClient:
    def __init__(self, uri: str) -> None:
        self._client: AsyncClient = AsyncIOMotorClient(uri, uuidRepresentation="standard")

    @property
    def client(self) -> AsyncClient:
        return self._client

    def get_db(self, db_name: str) -> AsyncDB:
        return self._client[db_name]


@lru_cache
def get_mongo_client() -> MongoDBClient:
    """
    Get a cached singleton MongoDB client instance.

    :return: A cached singleton MongoDB client instance.
    :rtype: MongoDBClient
    """
    return MotorMongoDBClient(settings.mongo_url)


def get_db() -> AsyncDB:
    """
    Get the MongoDB database instance.

    :return: The MongoDB database instance.
    :rtype: AsyncDB
    """
    mongo_client = get_mongo_client()
    return mongo_client.get_db(settings.mongo_app_name)


def get_test_db() -> AsyncDB:
    """
    Get the MongoDB test database instance.

    :return: The MongoDB test database instance.
    :rtype: AsyncDB
    """
    mongo_client = get_mongo_client()
    return mongo_client.get_db("test")
