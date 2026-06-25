from app.schemas.v1.base import CustomModel


class FlightLookupAirport(CustomModel):
    iata: str | None = None
    icao: str | None = None
    name: str | None = None
    city: str | None = None
    country: str | None = None


class FlightLookupCandidate(CustomModel):
    id: str
    flight_number: str
    airline_name: str | None = None
    airline_code: str | None = None
    departure_airport: FlightLookupAirport
    arrival_airport: FlightLookupAirport
    scheduled_departure_time_local: str | None = None
    scheduled_arrival_time_local: str | None = None
    scheduled_departure_time_utc: str | None = None
    scheduled_arrival_time_utc: str | None = None
    status: str | None = None
    source: str = "AeroDataBox"


class FlightLookupResponse(CustomModel):
    query: str
    normalized_flight_number: str
    cached: bool
    candidates: list[FlightLookupCandidate]
