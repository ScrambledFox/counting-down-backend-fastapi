from typing import Annotated

from fastapi import Depends

from app.core.config import get_settings
from app.db.mongo_client import AsyncDB, get_db
from app.models.flight import Flight
from app.models.mongo import Query
from app.schemas.v1.airport import Airport
from app.schemas.v1.base import MongoId
from app.schemas.v1.flight import FlightStatus

settings = get_settings()


class FlightRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._flights = db[settings.flights_collection_name]

    async def _get_flights_by_airport(
        self,
        field: str,
        airport_id: MongoId | None,
        status: FlightStatus | None,
        sort_field: str,
    ) -> list[Flight]:
        if airport_id is None:
            return []

        query: Query = {field: airport_id}
        if status is not None:
            query["status"] = status

        cursor = self._flights.find(query).sort(sort_field, -1)
        docs = await cursor.to_list(length=None)
        return [Flight.model_validate(doc) for doc in docs]

    async def list_flights(self) -> list[Flight]:
        cursor = self._flights.find().sort("departure_at", -1)
        docs = await cursor.to_list(length=None)
        return [Flight.model_validate(doc) for doc in docs]

    async def list_active_flights(self) -> list[Flight]:
        cursor = self._flights.find({"status": FlightStatus.ACTIVE})
        docs = await cursor.to_list(length=None)
        return [Flight.model_validate(doc) for doc in docs]

    async def get_most_recent_active_flight(self) -> Flight | None:
        doc = await self._flights.find_one(
            {"status": FlightStatus.ACTIVE}, sort=[("departure_at", 1)]
        )
        if doc is None:
            return None
        return Flight.model_validate(doc)

    async def create_flight(self, flight: Flight) -> Flight:
        result = await self._flights.insert_one(flight.model_dump(by_alias=True, exclude_none=True))
        doc = await self._flights.find_one({"_id": result.inserted_id})
        return Flight.model_validate(doc)

    async def get_flight(self, flight_id: MongoId) -> Flight | None:
        doc = await self._flights.find_one({"_id": flight_id})
        if doc:
            return Flight.model_validate(doc)
        return None

    async def update_flight(self, flight_id: MongoId, flight: Flight) -> Flight | None:
        await self._flights.update_one({"_id": flight_id}, {"$set": dict(flight)})
        return await self.get_flight(flight_id)

    async def delete_flight(self, flight_id: MongoId) -> bool:
        result = await self._flights.delete_one({"_id": flight_id})
        return result.deleted_count > 0

    async def delete_flight_by_code(self, flight_code: str) -> bool:
        result = await self._flights.delete_one({"code": flight_code})
        return result.deleted_count > 0

    async def get_flights_by_departure_airport(
        self, airport: Airport, status: FlightStatus | None = None
    ) -> list[Flight]:
        return await self._get_flights_by_airport(
            field="departure_airport_id",
            airport_id=airport.id,
            status=status,
            sort_field="departure_at",
        )

    async def get_flights_by_arrival_airport(
        self, airport: Airport, status: FlightStatus | None = None
    ) -> list[Flight]:
        return await self._get_flights_by_airport(
            field="arrival_airport_id",
            airport_id=airport.id,
            status=status,
            sort_field="arrival_at",
        )
