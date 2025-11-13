from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.exceptions import NotFoundException
from app.schemas.v1.airport import Airport, AirportCodeParam, AirportCreate, IataCodeParam
from app.schemas.v1.flight import Flight
from app.services.airport import AirportService
from app.services.flight import FlightService

router = APIRouter(tags=["airport"], prefix="/airport")

AirportServiceDep = Annotated[AirportService, Depends()]
FlightServiceDep = Annotated[FlightService, Depends()]


@router.get("/", summary="List all airports")
async def list_airports(airport_service: AirportServiceDep) -> list[Airport]:
    return await airport_service.list_airports()


@router.get("/search", summary="Search airports by name or city")
async def search_airports(query: str, airport_service: AirportServiceDep) -> list[Airport]:
    return await airport_service.search_airports(query)


@router.get("/{airport_id}", summary="Get airport information by ID")
async def get_airport_info_by_id(
    airport_id: str, airport_service: AirportServiceDep
) -> Airport | None:
    airport = await airport_service.get_airport_by_id(airport_id)
    if not airport:
        raise NotFoundException("Airport", airport_id)
    return airport


@router.get("/code/{airport_code}", summary="Get airport information by icao or iata code")
async def get_airport_info(
    airport_code: AirportCodeParam, airport_service: AirportServiceDep
) -> Airport | None:
    airport = await airport_service.get_airport_by_code(airport_code)
    if not airport:
        raise NotFoundException("Airport", airport_code)
    return airport


@router.get("/iata/{airport_code}", summary="Get airport information by iata code")
async def get_airport_info_iata(
    airport_code: IataCodeParam, airport_service: AirportServiceDep
) -> Airport | None:
    airport = await airport_service.get_airport_by_code(airport_code)
    if not airport:
        raise NotFoundException("Airport", airport_code)
    return airport


@router.get("/icao/{airport_code}", summary="Get airport information by icao code")
async def get_airport_info_icao(
    airport_code: AirportCodeParam, airport_service: AirportServiceDep
) -> Airport | None:
    airport = await airport_service.get_airport_by_code(airport_code)
    if not airport:
        raise NotFoundException("Airport", airport_code)
    return airport


@router.post("/", summary="Add a new airport")
async def add_airport(airport_data: AirportCreate, airport_service: AirportServiceDep) -> Airport:
    return await airport_service.add_airport(airport_data)


@router.delete("/code/{airport_code}", summary="Delete an airport by icao or iata code")
async def delete_airport(
    airport_code: AirportCodeParam, airport_service: AirportServiceDep
) -> bool:
    return await airport_service.delete_airport_by_code(airport_code)


@router.delete("/{airport_id}", summary="Delete an airport by ID")
async def delete_airport_by_id(airport_id: str, airport_service: AirportServiceDep) -> bool:
    return await airport_service.delete_airport_by_id(airport_id)


@router.get("/{airport_code}/arrivals", summary="Get arrivals for an airport by icao or iata code")
async def get_airport_arrivals(
    airport_code: AirportCodeParam,
    airport_service: AirportServiceDep,
    flight_service: FlightServiceDep,
) -> list[Flight] | None:
    airport = await airport_service.get_airport_by_code(airport_code)
    if not airport:
        raise NotFoundException("Airport", airport_code)

    return await flight_service.get_flights_by_arrival_airport(airport)


@router.get("/{airport_code}/departures", summary="Get departures for an airport by icao code")
async def get_airport_departures(
    airport_code: AirportCodeParam,
    airport_service: AirportServiceDep,
    flight_service: FlightServiceDep,
) -> list[Flight] | None:
    airport = await airport_service.get_airport_by_code(airport_code)
    if not airport:
        raise NotFoundException("Airport", airport_code)

    return await flight_service.get_flights_by_departure_airport(airport)
