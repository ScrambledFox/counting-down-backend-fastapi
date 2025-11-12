from app.schemas.v1.base import CustomModel

type Coordinates = tuple[float, float]


class Airport(CustomModel):
    icao: str  # ICAO code
    name: str  # Airport name
    city: str
    country: str
    coordinates: Coordinates
