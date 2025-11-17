from datetime import datetime

from pydantic import Field

from app.models.flight import FlightNumber, FlightStatus
from app.schemas.v1.airport import Airport
from app.schemas.v1.base import CustomModel, DefaultMongoIdField


class FlightBase(CustomModel):
    flight_number: FlightNumber
    departure_airport: Airport
    arrival_airport: Airport
    departure_at: datetime
    arrival_at: datetime
    status: FlightStatus


class Flight(FlightBase):
    id: DefaultMongoIdField = None
    created_at: datetime
    updated_at: datetime | None = None


class FlightCreate(FlightBase):
    status: FlightStatus = Field(default=FlightStatus.DRAFT)
