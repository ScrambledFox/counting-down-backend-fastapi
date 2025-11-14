from datetime import datetime
from enum import Enum

from pydantic import Field

from app.schemas.v1.base import CustomModel, DefaultMongoIdField

type FlightNumber = str


class FlightStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class FlightBase(CustomModel):
    flight_number: FlightNumber
    departure_airport_icao: str
    arrival_airport_icao: str
    departure_at: datetime
    arrival_at: datetime
    status: FlightStatus


class Flight(FlightBase):
    id: DefaultMongoIdField = None
    created_at: datetime
    updated_at: datetime | None = None


class FlightCreate(FlightBase):
    status: FlightStatus = Field(default=FlightStatus.DRAFT)
