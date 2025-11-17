from typing import Annotated

from fastapi import Depends

from app.core.time import utc_now
from app.models.flight import Flight as FlightModel
from app.repositories.airport import AirportRepository
from app.repositories.flight import FlightRepository
from app.schemas.v1.airport import Airport
from app.schemas.v1.base import MongoId
from app.schemas.v1.flight import Flight as FlightSchema
from app.schemas.v1.flight import FlightCreate, FlightStatus


class FlightService:
    def __init__(
        self,
        flights: Annotated[FlightRepository, Depends()],
        airports: Annotated[AirportRepository, Depends()],
    ) -> None:
        self._flights = flights
        self._airports = airports

    async def _to_schema(self, flight: FlightModel) -> FlightSchema:
        departure_airport = await self._airports.get_airport_by_id(flight.departure_airport_id)
        arrival_airport = await self._airports.get_airport_by_id(flight.arrival_airport_id)

        # Debug some values to help trace issues
        print(f"Mapping flight ID {flight.id} to schema.")
        print(
            f"Departure airport ID: {flight.departure_airport_id}, "
            f"Arrival airport ID: {flight.arrival_airport_id}"
        )
        print(
            f"Fetched departure airport: {departure_airport}, "
            f"Fetched arrival airport: {arrival_airport}"
        )

        if departure_airport is None or arrival_airport is None:
            raise ValueError("Airport not found")

        return FlightSchema(
            **flight.model_dump(),
            departure_airport=departure_airport,
            arrival_airport=arrival_airport,
        )

    async def _map_list_to_schema(self, flights: list[FlightModel]) -> list[FlightSchema]:
        return [await self._to_schema(f) for f in flights]

    async def get_all_flights(self) -> list[FlightSchema]:
        flights = await self._flights.list_flights()
        return await self._map_list_to_schema(flights)

    async def create_flight(self, flight: FlightCreate) -> FlightSchema:
        new_flight = FlightModel(**flight.model_dump(), created_at=utc_now())
        created_flight = await self._flights.create_flight(new_flight)
        return await self._to_schema(created_flight)

    async def get_flight_by_id(self, flight_id: str) -> FlightSchema | None:
        flight = await self._flights.get_flight(flight_id)
        if flight is None:
            return None
        return await self._to_schema(flight)

    async def get_flight_by_flight_number(self, flight_number: str) -> FlightSchema | None:
        flights = await self._flights.list_flights()
        for flight in flights:
            if flight.flight_number == flight_number:
                return await self._to_schema(flight)
        return None

    async def get_next_flight(self) -> FlightSchema | None:
        flight = await self._flights.get_most_recent_active_flight()
        if flight is None:
            return None
        return await self._to_schema(flight)

    async def update_flight(self, flight_id: MongoId, flight: FlightSchema) -> FlightSchema | None:
        flight_model = FlightModel(**flight.model_dump())
        updated_flight = await self._flights.update_flight(flight_id, flight_model)
        if updated_flight is None:
            return None
        return await self._to_schema(updated_flight)

    async def delete_flight_by_id(self, flight_id: str) -> bool:
        return await self._flights.delete_flight(flight_id)

    async def delete_flight_by_code(self, flight_code: str) -> bool:
        return await self._flights.delete_flight_by_code(flight_code)

    async def get_active_flights(self) -> list[FlightSchema]:
        flights = await self._flights.list_active_flights()
        return await self._map_list_to_schema(flights)

    async def get_most_recent_active_flight(self) -> FlightSchema | None:
        flight = await self._flights.get_most_recent_active_flight()
        if flight is None:
            return None
        return await self._to_schema(flight)

    async def get_flights_by_arrival_airport(self, airport: Airport) -> list[FlightSchema]:
        flights = await self._flights.get_flights_by_arrival_airport(
            airport, status=FlightStatus.ACTIVE
        )
        return await self._map_list_to_schema(flights)

    async def get_flights_by_departure_airport(self, airport: Airport) -> list[FlightSchema]:
        flights = await self._flights.get_flights_by_departure_airport(
            airport, status=FlightStatus.ACTIVE
        )
        return await self._map_list_to_schema(flights)
