from typing import Annotated

from fastapi import Depends, Query

from app.api.routing import make_router
from app.core.auth import require_session
from app.schemas.v1.airport import (
    Airport,
    AirportCode,
    AirportCreate,
    AirportSearchRequest,
    AirportSearchResponse,
    IataCode,
)
from app.schemas.v1.base import MongoId
from app.schemas.v1.exceptions import NotFoundException
from app.schemas.v1.flight import Flight
from app.schemas.v1.response import DeletedResponse
from app.services.airport import AirportService
from app.services.flight import FlightService

router = make_router()

AirportServiceDep = Annotated[AirportService, Depends()]
FlightServiceDep = Annotated[FlightService, Depends()]


@router.get("/", summary="List all airports", dependencies=[Depends(require_session)])
async def list_airports(airport_service: AirportServiceDep) -> list[Airport]:
    return await airport_service.list_airports()


@router.get(
    "/search", summary="Search airports by name or city", dependencies=[Depends(require_session)]
)
async def search_airports(
    request: Annotated[AirportSearchRequest, Query()], airport_service: AirportServiceDep
) -> AirportSearchResponse:
    return await airport_service.search_airports(request)


@router.get(
    "/{airport_id}",
    summary="Get airport information by ID",
    dependencies=[Depends(require_session)],
)
async def get_airport_info_by_id(
    airport_id: MongoId, airport_service: AirportServiceDep
) -> Airport | None:
    airport = await airport_service.get_airport_by_id(airport_id)
    if not airport:
        raise NotFoundException("Airport", airport_id)
    return airport


@router.get(
    "/code/{airport_code}",
    summary="Get airport information by icao or iata code",
    dependencies=[Depends(require_session)],
)
async def get_airport_info(
    airport_code: AirportCode, airport_service: AirportServiceDep
) -> Airport | None:
    airport = await airport_service.get_airport_by_code(airport_code)
    if not airport:
        raise NotFoundException("Airport", airport_code)
    return airport


@router.get(
    "/iata/{airport_code}",
    summary="Get airport information by iata code",
    dependencies=[Depends(require_session)],
)
async def get_airport_info_iata(
    airport_code: IataCode, airport_service: AirportServiceDep
) -> Airport | None:
    airport = await airport_service.get_airport_by_code(airport_code)
    if not airport:
        raise NotFoundException("Airport", airport_code)
    return airport


@router.get(
    "/icao/{airport_code}",
    summary="Get airport information by icao code",
    dependencies=[Depends(require_session)],
)
async def get_airport_info_icao(
    airport_code: AirportCode, airport_service: AirportServiceDep
) -> Airport | None:
    airport = await airport_service.get_airport_by_code(airport_code)
    if not airport:
        raise NotFoundException("Airport", airport_code)
    return airport


@router.post("/", summary="Add a new airport", dependencies=[Depends(require_session)])
async def add_airport(airport_data: AirportCreate, airport_service: AirportServiceDep) -> Airport:
    return await airport_service.add_airport(airport_data)


@router.delete(
    "/code/{airport_code}",
    summary="Delete an airport by icao or iata code",
    dependencies=[Depends(require_session)],
)
async def delete_airport(airport_code: AirportCode, airport_service: AirportServiceDep):
    success = await airport_service.delete_airport_by_code(airport_code)
    if not success:
        raise NotFoundException("Airport", airport_code)
    return DeletedResponse()


@router.delete(
    "/{airport_id}", summary="Delete an airport by ID", dependencies=[Depends(require_session)]
)
async def delete_airport_by_id(airport_id: MongoId, airport_service: AirportServiceDep):
    success = await airport_service.delete_airport_by_id(airport_id)
    if not success:
        raise NotFoundException("Airport", airport_id)
    return DeletedResponse()


@router.get(
    "/{airport_code}/arrivals",
    summary="Get arrivals for an airport by icao or iata code",
    dependencies=[Depends(require_session)],
)
async def get_airport_arrivals(
    airport_code: AirportCode,
    airport_service: AirportServiceDep,
    flight_service: FlightServiceDep,
) -> list[Flight] | None:
    airport = await airport_service.get_airport_by_code(airport_code)
    if not airport:
        raise NotFoundException("Airport", airport_code)

    return await flight_service.get_flights_by_arrival_airport(airport)


@router.get(
    "/{airport_code}/departures",
    summary="Get departures for an airport by icao code",
    dependencies=[Depends(require_session)],
)
async def get_airport_departures(
    airport_code: AirportCode,
    airport_service: AirportServiceDep,
    flight_service: FlightServiceDep,
) -> list[Flight] | None:
    airport = await airport_service.get_airport_by_code(airport_code)
    if not airport:
        raise NotFoundException("Airport", airport_code)

    return await flight_service.get_flights_by_departure_airport(airport)
