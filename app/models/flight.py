from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.schemas.v1.base import DefaultMongoIdField, MongoId

type FlightNumber = str


class FlightStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class Flight(BaseModel):
    id: DefaultMongoIdField = None
    flight_number: FlightNumber
    departure_airport_id: MongoId
    arrival_airport_id: MongoId
    departure_at: datetime
    arrival_at: datetime
    status: FlightStatus
    created_at: datetime
    updated_at: datetime | None = None
