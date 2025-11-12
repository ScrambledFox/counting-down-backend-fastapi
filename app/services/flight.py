from app.repositories.flight import FlightRepository
from app.schemas.v1.flight import Flight


class FlightService:
    def __init__(self, repo: FlightRepository):
        self._repo = repo

    async def get_all_flights(self) -> list[Flight]:
        return await self._repo.list_flights()

    async def create_flight(self, flight: Flight) -> Flight:
        created_id = await self._repo.create_flight(flight)
        created_flight = await self._repo.get_flight(created_id)
        if created_flight is None:
            raise RuntimeError(f"Failed to fetch newly created flight with id {created_id}")
        return created_flight

    async def get_flight_by_id(self, flight_id: str) -> Flight | None:
        return await self._repo.get_flight(flight_id)

    async def update_flight(self, flight_id: str, flight: Flight) -> bool:
        return await self._repo.update_flight(flight_id, flight)

    async def delete_flight(self, flight_id: str) -> bool:
        return await self._repo.delete_flight(flight_id)

    async def get_active_flights(self) -> list[Flight]:
        return await self._repo.list_active_flights()

    async def get_most_recent_active_flight(self) -> Flight | None:
        return await self._repo.get_most_recent_active_flight()
