from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints, field_validator

from app.schemas.v1.base import CustomModel, MongoId

type Coordinates = tuple[float, float]

AirportCodeParam = Annotated[
    str,
    StringConstraints(min_length=3, max_length=4, pattern=r"^[A-Za-z]{3,4}$"),
    AfterValidator(lambda v: v.upper()),
]

IcaoCodeParam = Annotated[
    str,
    StringConstraints(min_length=4, max_length=4, pattern=r"^[A-Za-z]{4}$"),
    AfterValidator(lambda v: v.upper()),
]

IataCodeParam = Annotated[
    str,
    StringConstraints(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$"),
    AfterValidator(lambda v: v.upper()),
]


class AirportBase(CustomModel):
    icao: str  # ICAO code
    iata: str  # IATA code
    name: str  # Airport name
    city: str
    country: str
    longitude: float
    latitude: float

    @field_validator("icao", "iata", "name", "city", "country")
    def not_empty(cls, v: str) -> str:
        v2 = v.strip()
        if not v2:
            raise ValueError("Must not be empty or whitespace")
        return v2

    @field_validator("icao")
    def icao_upper(cls, v: str) -> str:
        if len(v) != 4 or not v.isalpha():
            raise ValueError("ICAO code must be 4 letters")
        return v.upper()

    @field_validator("iata")
    def iata_upper(cls, v: str) -> str:
        if len(v) != 3 or not v.isalpha():
            raise ValueError("IATA code must be 3 letters")
        return v.upper()

    @field_validator("longitude")
    def longitude_range(cls, v: float) -> float:
        if not -180.0 <= v <= 180.0:
            raise ValueError("Longitude must be between -180 and 180")
        return v

    @field_validator("latitude")
    def latitude_range(cls, v: float) -> float:
        if not -90.0 <= v <= 90.0:
            raise ValueError("Latitude must be between -90 and 90")
        return v


class Airport(AirportBase):
    id: MongoId | None = Field(default=None, alias="_id")
    created_at: datetime
    updated_at: datetime | None = None


class AirportCreate(AirportBase):
    pass
