from typing import Annotated

from fastapi import Depends

from app.core.config import settings
from app.db.client import AsyncDB, get_db
from app.models.db import Query
from app.schemas.v1.airport import Airport
from app.schemas.v1.flight import Flight, FlightStatus


class FlightRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.flights_collection_name]

    async def list_flights(self) -> list[Flight]:
        cursor = self._collection.find().sort("departure_at", -1)
        docs = await cursor.to_list(length=None)
        return [Flight.model_validate(doc) for doc in docs]

    async def list_active_flights(self) -> list[Flight]:
        cursor = self._collection.find({"status": FlightStatus.ACTIVE})
        docs = await cursor.to_list(length=None)
        return [Flight.model_validate(doc) for doc in docs]

    async def get_most_recent_active_flight(self) -> Flight | None:
        doc = await self._collection.find_one(
            {"status": FlightStatus.ACTIVE}, sort=[("departure_at", -1)]
        )
        if doc:
            return Flight.model_validate(doc)
        return None

    async def create_flight(self, flight: Flight) -> Flight:
        result = await self._collection.insert_one(
            flight.model_dump(by_alias=True, exclude_none=True)
        )
        doc = await self._collection.find_one({"_id": result.inserted_id})
        return Flight.model_validate(doc)

    async def get_flight(self, flight_id: str) -> Flight | None:
        doc = await self._collection.find_one({"_id": flight_id})
        if doc:
            return Flight.model_validate(doc)
        return None

    async def update_flight(self, flight_id: str, flight: Flight) -> Flight | None:
        result = await self._collection.update_one({"_id": flight_id}, {"$set": dict(flight)})
        if result.modified_count > 0:
            return await self.get_flight(flight_id)
        return None

    async def delete_flight(self, flight_id: str) -> bool:
        result = await self._collection.delete_one({"_id": flight_id})
        return result.deleted_count > 0

    async def delete_flight_by_code(self, flight_code: str) -> bool:
        result = await self._collection.delete_one({"code": flight_code})
        return result.deleted_count > 0

    async def get_flights_by_departure_airport(
        self, airport: Airport, status: FlightStatus | None = None
    ) -> list[Flight]:
        query: Query = {"departure_airport_icao": airport.icao}
        if status is not None:
            query["status"] = status

        cursor = self._collection.find(query).sort("departure_at", -1)
        docs = await cursor.to_list(length=None)
        return [Flight.model_validate(doc) for doc in docs]

    async def get_flights_by_arrival_airport(
        self, airport: Airport, status: FlightStatus | None = None
    ) -> list[Flight]:
        query: Query = {"arrival_airport_icao": airport.icao}
        if status is not None:
            query["status"] = status

        cursor = self._collection.find(query).sort("arrival_at", -1)
        docs = await cursor.to_list(length=None)
        return [Flight.model_validate(doc) for doc in docs]
