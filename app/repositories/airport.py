import re
from typing import Annotated

from bson import ObjectId
from fastapi import Depends
from pymongo import ASCENDING, TEXT

from app.core.config import get_settings
from app.db.mongo_client import AsyncDB, get_db
from app.schemas.v1.airport import Airport
from app.schemas.v1.base import MongoId

settings = get_settings()


class AirportRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.airports_collection_name]

    async def ensure_indexes(self) -> None:
        # Unique ICAO keeps the seed idempotent and speeds up code lookups.
        await self._collection.create_index([("icao", ASCENDING)], unique=True)
        await self._collection.create_index([("iata", ASCENDING)])
        # Text index keeps typeahead search fast over the ~8k seeded airports.
        await self._collection.create_index([("name", TEXT), ("city", TEXT), ("country", TEXT)])

    async def list_airports(self) -> list[Airport]:
        cursor = self._collection.find().sort("icao", 1)
        docs = await cursor.to_list(length=None)
        return [Airport.model_validate(doc) for doc in docs]

    async def search_airports(self, query: str, limit: int = 10) -> list[Airport]:
        # Escape the query so codes / punctuation are matched literally.
        pattern = re.escape(query)
        cursor = (
            self._collection.find(
                {
                    "$or": [
                        {"icao": {"$regex": pattern, "$options": "i"}},
                        {"iata": {"$regex": pattern, "$options": "i"}},
                        {"name": {"$regex": pattern, "$options": "i"}},
                        {"city": {"$regex": pattern, "$options": "i"}},
                        {"country": {"$regex": pattern, "$options": "i"}},
                    ]
                }
            )
            .sort("icao", 1)
            .limit(limit)
        )
        docs = await cursor.to_list(length=limit)
        return [Airport.model_validate(doc) for doc in docs]

    async def get_airport_by_id(self, airport_id: MongoId) -> Airport | None:
        doc = await self._collection.find_one({"_id": ObjectId(airport_id)})
        return Airport.model_validate(doc) if doc else None

    async def get_airport_by_code(self, airport_code: str) -> Airport | None:
        doc = await self._collection.find_one(
            {
                "$or": [
                    {"icao": airport_code},
                    {"iata": airport_code},
                ]
            }
        )
        return Airport.model_validate(doc) if doc else None

    async def create_airport(self, airport: Airport) -> Airport:
        result = await self._collection.insert_one(
            airport.model_dump(by_alias=True, exclude_none=True)
        )
        doc = await self._collection.find_one({"_id": result.inserted_id})
        return Airport.model_validate(doc)

    async def delete_airport_by_id(self, airport_id: MongoId) -> bool:
        result = await self._collection.delete_one({"_id": ObjectId(airport_id)})
        return result.deleted_count > 0

    async def delete_airport_by_code(self, airport_code: str) -> bool:
        result = await self._collection.delete_one(
            {
                "$or": [
                    {"icao": airport_code},
                    {"iata": airport_code},
                ]
            }
        )
        return result.deleted_count > 0


async def ensure_airport_indexes(db: AsyncDB) -> None:
    await AirportRepository(db).ensure_indexes()
