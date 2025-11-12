from datetime import datetime
from enum import Enum

from app.schemas.v1.base import CustomModel


class FlightStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class Flight(CustomModel):
    flight_number: str
    departure_airport_icao: str
    arrival_airport_icao: str
    departure_at: datetime
    arrival_at: datetime
    status: FlightStatus
