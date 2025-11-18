from datetime import datetime

from pydantic import Field

from app.models.flight import FlightNumber, FlightStatus
from app.schemas.v1.airport import Airport, IcaoCode
from app.schemas.v1.base import CustomModel, DefaultMongoIdField


class FlightBase(CustomModel):
    flight_number: FlightNumber
    departure_at: datetime
    arrival_at: datetime
    status: FlightStatus


class Flight(FlightBase):
    id: DefaultMongoIdField = None
    departure_airport: Airport
    arrival_airport: Airport
    created_at: datetime
    updated_at: datetime | None = None


class FlightCreate(FlightBase):
    status: FlightStatus = Field(default=FlightStatus.DRAFT)
    departure_airport_icao: IcaoCode
    arrival_airport_icao: IcaoCode


class FlightUpdate(CustomModel):
    flight_number: FlightNumber | None = None
    departure_at: datetime | None = None
    arrival_at: datetime | None = None
    status: FlightStatus | None = None
    departure_airport_icao: IcaoCode | None = None
    arrival_airport_icao: IcaoCode | None = None
