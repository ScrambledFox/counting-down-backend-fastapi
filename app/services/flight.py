from typing import Annotated

from fastapi import Depends

from app.core.time import utc_now
from app.repositories.flight import FlightRepository
from app.schemas.v1.airport import Airport
from app.schemas.v1.flight import Flight, FlightCreate, FlightStatus


class FlightService:
    def __init__(self, repo: Annotated[FlightRepository, Depends()]) -> None:
        self._repo = repo

    async def get_all_flights(self) -> list[Flight]:
        return await self._repo.list_flights()

    async def create_flight(self, flight: FlightCreate) -> Flight:
        new_flight = Flight(**flight.model_dump(), created_at=utc_now())
        return await self._repo.create_flight(new_flight)

    async def get_flight_by_id(self, flight_id: str) -> Flight | None:
        return await self._repo.get_flight(flight_id)

    async def get_flight_by_flight_number(self, flight_number: str) -> Flight | None:
        flights = await self._repo.list_flights()
        for flight in flights:
            if flight.flight_number == flight_number:
                return flight
        return None

    async def get_next_flight(self) -> Flight | None:
        return await self._repo.get_most_recent_active_flight()

    async def update_flight(self, flight_id: str, flight: Flight) -> Flight | None:
        return await self._repo.update_flight(flight_id, flight)

    async def delete_flight_by_id(self, flight_id: str) -> bool:
        return await self._repo.delete_flight(flight_id)

    async def delete_flight_by_code(self, flight_code: str) -> bool:
        return await self._repo.delete_flight_by_code(flight_code)

    async def get_active_flights(self) -> list[Flight]:
        return await self._repo.list_active_flights()

    async def get_most_recent_active_flight(self) -> Flight | None:
        return await self._repo.get_most_recent_active_flight()

    async def get_flights_by_arrival_airport(self, airport: Airport) -> list[Flight]:
        return await self._repo.get_flights_by_arrival_airport(airport, status=FlightStatus.ACTIVE)

    async def get_flights_by_departure_airport(self, airport: Airport) -> list[Flight]:
        return await self._repo.get_flights_by_departure_airport(
            airport, status=FlightStatus.ACTIVE
        )
