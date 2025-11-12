from fastapi import APIRouter, Depends

from app.schemas.v1.flight import Flight
from app.services.flight import FlightService


router = APIRouter(tags=["flights"], prefix="/flights")


@router.get("/", summary="Get Flight Items")
async def get_flight_items(
    service: FlightService = Depends(get_flight_service),
) -> list[Flight]:
    return 