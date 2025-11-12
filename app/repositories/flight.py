from fastapi import Depends

from app.core.config import settings
from app.db.client import AsyncDB, get_db
from app.schemas.v1.flight import Flight, FlightStatus


class FlightRepository:
    def __init__(self, db: AsyncDB = Depends(get_db)) -> None:
        self._collection = db[settings.flights_collection_name]

    async def list_flights(self) -> list[Flight]:
        cursor = self._collection.find()
        docs = await cursor.to_list(length=None)
        return [Flight(**doc) for doc in docs]

    async def create_flight(self, flight: Flight) -> str:
        doc = await self._collection.insert_one(dict(flight))
        return str(doc.inserted_id)

    async def get_flight(self, flight_id: str) -> Flight | None:
        doc = await self._collection.find_one({"_id": flight_id})
        if doc:
            return Flight(**doc)
        return None

    async def update_flight(self, flight_id: str, flight: Flight) -> bool:
        result = await self._collection.update_one({"_id": flight_id}, {"$set": dict(flight)})
        return result.modified_count > 0

    async def delete_flight(self, flight_id: str) -> bool:
        result = await self._collection.delete_one({"_id": flight_id})
        return result.deleted_count > 0

    async def list_active_flights(self) -> list[Flight]:
        cursor = self._collection.find({"status": FlightStatus.ACTIVE})
        docs = await cursor.to_list(length=None)
        return [Flight(**doc) for doc in docs]

    async def get_most_recent_active_flight(self) -> Flight | None:
        doc = await self._collection.find_one(
            {"status": FlightStatus.ACTIVE}, sort=[("departure_at", -1)]
        )
        if doc:
            return Flight(**doc)
        return None
