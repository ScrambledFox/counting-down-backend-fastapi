from typing import Annotated

from bson import ObjectId
from fastapi import Depends

from app.core.config import settings
from app.db.client import AsyncDB, get_db
from app.schemas.v1.airport import Airport
from app.schemas.v1.base import MongoId


class AirportRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.airports_collection_name]

    async def list_airports(self) -> list[Airport]:
        cursor = self._collection.find().sort("icao", 1)
        docs = await cursor.to_list(length=None)
        return [Airport.model_validate(doc) for doc in docs]

    async def search_airports(self, query: str) -> list[Airport]:
        cursor = self._collection.find(
            {
                "$or": [
                    {"icao": {"$regex": query, "$options": "i"}},
                    {"iata": {"$regex": query, "$options": "i"}},
                    {"name": {"$regex": query, "$options": "i"}},
                    {"city": {"$regex": query, "$options": "i"}},
                    {"country": {"$regex": query, "$options": "i"}},
                ]
            }
        ).sort(Airport.icao, 1)
        docs = await cursor.to_list(length=None)
        return [Airport.model_validate(doc) for doc in docs]

    async def get_airport_by_id(self, airport_id: MongoId) -> Airport | None:
        doc = await self._collection.find_one({"_id": ObjectId(airport_id)})
        print(f"Doc {doc}")
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

    async def delete_airport_by_id(self, airport_id: str) -> bool:
        result = await self._collection.delete_one({"_id": airport_id})
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
