from typing import Annotated

from fastapi import Depends

from app.repositories.airport import AirportRepository
from app.repositories.flight import FlightRepository
from app.schemas.v1.airport import (
    Airport,
    AirportCode,
    AirportCreate,
    AirportSearchRequest,
    AirportSearchResponse,
)
from app.schemas.v1.base import MongoId
from app.schemas.v1.exceptions import ConflictException
from app.util.time import utc_now


class AirportService:
    def __init__(
        self,
        repo: Annotated[AirportRepository, Depends()],
        flight_repo: Annotated[FlightRepository, Depends()],
    ):
        self._repo = repo
        self._flight_repo = flight_repo

    async def list_airports(self) -> list[Airport]:
        return await self._repo.list_airports()

    async def search_airports(self, request: AirportSearchRequest) -> AirportSearchResponse:
        results = await self._repo.search_airports(request.query, request.k)
        return AirportSearchResponse(results=results, count=len(results))

    async def get_airport_by_id(self, airport_id: MongoId) -> Airport | None:
        return await self._repo.get_airport_by_id(airport_id)

    async def get_airport_by_code(self, airport_code: AirportCode) -> Airport | None:
        normalized = airport_code.upper()
        return await self._repo.get_airport_by_code(normalized)

    async def add_airport(self, airport_data: AirportCreate) -> Airport:
        new_airport: Airport = Airport(**airport_data.model_dump(), created_at=utc_now())
        return await self._repo.create_airport(new_airport)

    async def delete_airport_by_code(self, airport_code: AirportCode) -> bool:
        normalized = airport_code.upper()
        airport = await self._repo.get_airport_by_code(normalized)
        if airport is None or airport.id is None:
            return False
        await self._ensure_not_referenced(airport.id)
        return await self._repo.delete_airport_by_id(airport.id)

    async def delete_airport_by_id(self, airport_id: MongoId) -> bool:
        airport = await self._repo.get_airport_by_id(airport_id)
        if airport is None:
            return False
        await self._ensure_not_referenced(airport_id)
        return await self._repo.delete_airport_by_id(airport_id)

    async def _ensure_not_referenced(self, airport_id: MongoId) -> None:
        if await self._flight_repo.count_referencing_airport(airport_id):
            raise ConflictException("Airport is referenced by an existing flight")
