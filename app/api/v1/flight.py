from typing import Annotated

from fastapi import Depends

from app.api.routing import make_router
from app.schemas.v1.base import MongoId
from app.schemas.v1.exceptions import NotFoundException
from app.schemas.v1.flight import Flight, FlightCreate, FlightNumber
from app.schemas.v1.response import DeletedResponse
from app.services.flight import FlightService

router = make_router()

FlightServiceDep = Annotated[FlightService, Depends()]


@router.get("/", summary="Get Active Flight Items", response_model=list[Flight])
async def get_active_flight_items(
    service: FlightServiceDep,
) -> list[Flight]:
    return await service.get_active_flights()


@router.get("/all", summary="Get Flight Items", response_model=list[Flight])
async def get_flight_items(
    service: FlightServiceDep,
) -> list[Flight]:
    flights = await service.get_all_flights()
    return sorted(flights, key=lambda x: x.departure_at, reverse=True)


@router.get(
    "/flight_number/{flight_code}",
    summary="Get Flight Item by Flight Number",
    response_model=Flight,
)
async def get_flight_item_by_code(
    flight_number: FlightNumber,
    service: FlightServiceDep,
) -> Flight | None:
    flight = await service.get_flight_by_flight_number(flight_number)
    if flight is None:
        raise NotFoundException("Flight", flight_number)
    return flight


@router.get("/{flight_id}", summary="Get Flight Item", response_model=Flight)
async def get_flight_item(
    flight_id: MongoId,
    service: FlightServiceDep,
) -> Flight | None:
    flight = await service.get_flight_by_id(flight_id)
    if flight is None:
        raise NotFoundException("Flight", flight_id)
    return flight


@router.get("/next", summary="Get Next Most Recent and Active Flight Item", response_model=Flight)
async def get_next_flight_item(
    service: FlightServiceDep,
) -> Flight | None:
    flight = await service.get_next_flight()
    if flight is None:
        raise NotFoundException("Next Flight", "N/A")
    return flight


@router.post("/", summary="Create Flight", response_model=Flight)
async def create_flight(
    flight: FlightCreate,
    service: FlightServiceDep,
) -> Flight:
    return await service.create_flight(flight)


@router.put("/{flight_id}", summary="Update Flight", response_model=Flight)
async def update_flight(
    flight_id: MongoId,
    flight: Flight,
    service: FlightServiceDep,
) -> Flight:
    updated_flight = await service.update_flight(flight_id, flight)
    if not updated_flight:
        raise NotFoundException("Flight", flight_id)
    return updated_flight


@router.delete("/{flight_id}", summary="Delete Flight")
async def delete_flight(
    flight_id: MongoId,
    service: FlightServiceDep,
):
    success = await service.delete_flight_by_id(flight_id)
    if not success:
        raise NotFoundException("Flight", flight_id)
    return DeletedResponse()


@router.delete("/code/{flight_code}", summary="Delete Flight by Code")
async def delete_flight_by_code(
    flight_code: str,
    service: FlightServiceDep,
):
    success = await service.delete_flight_by_code(flight_code)
    if not success:
        raise NotFoundException("Flight", flight_code)
    return DeletedResponse()
