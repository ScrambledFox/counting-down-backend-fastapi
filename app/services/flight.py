import asyncio
from typing import Annotated

from fastapi import Depends

from app.core.time import utc_now
from app.models.flight import Flight as FlightModel
from app.repositories.airport import AirportRepository
from app.repositories.flight import FlightRepository
from app.schemas.v1.airport import Airport
from app.schemas.v1.base import MongoId
from app.schemas.v1.flight import Flight as FlightSchema
from app.schemas.v1.flight import FlightCreate, FlightStatus, FlightUpdate


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
        departure_airport, arrival_airport = await asyncio.gather(
            self._airports.get_airport_by_code(flight.departure_airport_icao),
            self._airports.get_airport_by_code(flight.arrival_airport_icao),
        )
        if departure_airport is None:
            raise ValueError(
                f"Departure airport with ICAO {flight.departure_airport_icao} not found"
            )
        if arrival_airport is None:
            raise ValueError(f"Arrival airport with ICAO {flight.arrival_airport_icao} not found")

        now = utc_now()
        payload = flight.model_dump()
        payload.pop("departure_airport_icao")
        payload.pop("arrival_airport_icao")
        payload.update(
            departure_airport_id=departure_airport.id,
            arrival_airport_id=arrival_airport.id,
            created_at=now,
            updated_at=None,
            status=payload.get("status", FlightStatus.DRAFT),
        )

        new_flight = FlightModel(**payload)
        created_flight = await self._flights.create_flight(new_flight)
        return await self._to_schema(created_flight)

    async def get_flight_by_id(self, flight_id: MongoId) -> FlightSchema | None:
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

    async def update_flight(self, flight_id: MongoId, flight: FlightUpdate) -> FlightSchema | None:
        print(f"Updating flight with ID: {flight_id} using data: {flight}")
        print(f"Type of flight_id: {type(flight_id)}")
        existing = await self._flights.get_flight(flight_id)

        print(f"Existing flight: {existing}")

        if existing is None:
            return None

        updates = flight.model_dump(exclude_unset=True)
        if "departure_airport_icao" in updates:
            departure_airport = await self._airports.get_airport_by_code(
                updates.pop("departure_airport_icao")
            )
            if departure_airport is None:
                raise ValueError(
                    f"Departure airport with ICAO {flight.departure_airport_icao} not found"
                )
            updates["departure_airport_id"] = departure_airport.id

        print(f"Updates after departure airport check: {updates}")

        updates["updated_at"] = utc_now()

        print(f"Final updates to apply: {updates}")

        updated_flight = await self._flights.update_flight(
            flight_id, existing.model_copy(update=updates)
        )

        print(f"Updated flight: {updated_flight}")

        if updated_flight is None:
            return None
        return await self._to_schema(updated_flight)

    async def delete_flight_by_id(self, flight_id: MongoId) -> bool:
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
