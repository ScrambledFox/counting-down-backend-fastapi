from fastapi import Depends, Query

from app.api.routing import make_router
from app.core.auth import require_session
from app.schemas.v1.flight_lookup import FlightLookupResponse
from app.schemas.v1.session import SessionResponse
from app.services.flight_lookup import lookup_flight

router = make_router()


@router.get("/lookup", summary="Lookup flight metadata by flight number", response_model=FlightLookupResponse)
async def lookup_flight_route(
    flightNumber: str = Query(..., min_length=1),  # noqa: N803
    _session: SessionResponse = Depends(require_session),
) -> FlightLookupResponse:
    return await lookup_flight(flightNumber)
