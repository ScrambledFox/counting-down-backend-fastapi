from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.exceptions import NotFoundException
from app.schemas.v1.flight import Flight, FlightCreate
from app.services.flight import FlightService

router = APIRouter(tags=["flights"], prefix="/flights")

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


@router.get("/{flight_id}", summary="Get Flight Item", response_model=Flight)
async def get_flight_item(
    flight_id: str,
    service: FlightServiceDep,
) -> Flight | None:
    return await service.get_flight_by_id(flight_id)


@router.get(
    "/flight_number/{flight_code}",
    summary="Get Flight Item by Flight Number",
    response_model=Flight,
)
async def get_flight_item_by_code(
    flight_number: str,
    service: FlightServiceDep,
) -> Flight | None:
    return await service.get_flight_by_flight_number(flight_number)


@router.post("/", summary="Create Flight", response_model=Flight)
async def create_flight(
    flight: FlightCreate,
    service: FlightServiceDep,
) -> Flight:
    return await service.create_flight(flight)


@router.put("/{flight_id}", summary="Update Flight", response_model=Flight)
async def update_flight(
    flight_id: str,
    flight: Flight,
    service: FlightServiceDep,
) -> Flight:
    updated_flight = await service.update_flight(flight_id, flight)
    if not updated_flight:
        raise NotFoundException("Flight", flight_id)
    return updated_flight


@router.delete("/{flight_id}", summary="Delete Flight", response_model=dict[str, str])
async def delete_flight(
    flight_id: str,
    service: FlightServiceDep,
) -> dict[str, str]:
    success = await service.delete_flight(flight_id)
    if not success:
        raise NotFoundException("Flight", flight_id)
    return {"detail": "Flight deleted"}


@router.delete(
    "/code/{flight_code}", summary="Delete Flight by Code", response_model=dict[str, str]
)
async def delete_flight_by_code(
    flight_code: str,
    service: FlightServiceDep,
) -> dict[str, str]:
    success = await service.delete_flight_by_code(flight_code)
    if not success:
        raise NotFoundException("Flight", flight_code)
    return {"detail": "Flight deleted"}
