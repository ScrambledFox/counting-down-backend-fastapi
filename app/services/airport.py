from typing import Annotated

from fastapi import Depends

from app.repositories.airport import AirportRepository
from app.schemas.v1.airport import Airport, AirportCode, AirportCreate
from app.schemas.v1.base import MongoId
from app.util.time import utc_now


class AirportService:
    def __init__(self, repo: Annotated[AirportRepository, Depends()]):
        self._repo = repo

    async def list_airports(self) -> list[Airport]:
        return await self._repo.list_airports()

    async def search_airports(self, query: str) -> list[Airport]:
        return await self._repo.search_airports(query)

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
        return await self._repo.delete_airport_by_code(normalized)

    async def delete_airport_by_id(self, airport_id: MongoId) -> bool:
        return await self._repo.delete_airport_by_id(airport_id)
