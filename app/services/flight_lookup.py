import hashlib
import re
import time
from datetime import date, timedelta

from app.core.config import get_settings
from app.integrations.aerodatabox_client import AeroDataBoxError, RawFlightData, aerodatabox_client
from app.schemas.v1.exceptions import BadRequestException, ServiceUnavailableException
from app.schemas.v1.flight_lookup import FlightLookupAirport, FlightLookupCandidate, FlightLookupResponse

settings = get_settings()

# Module-level TTL cache: (normalized_flight_number, date_window_key) -> (monotonic_time, response)
_cache: dict[tuple[str, str], tuple[float, FlightLookupResponse]] = {}

_FLIGHT_NUMBER_RE = re.compile(r"^[A-Z]{2,3}\d+$")


def normalize_flight_number(raw: str) -> str:
    """Strip, uppercase, and remove internal spaces. Reject invalid values with BadRequestException."""
    stripped = raw.strip().upper().replace(" ", "").replace("-", "")
    if len(stripped) < 2:
        raise BadRequestException("Flight number is too short")
    if not _FLIGHT_NUMBER_RE.match(stripped):
        raise BadRequestException(f"'{raw}' does not appear to be a valid flight number")
    return stripped


def _make_candidate_id(
    flight_number: str,
    dep_iata: str | None,
    arr_iata: str | None,
    dep_time_utc: str | None,
) -> str:
    key = f"{flight_number}|{dep_iata}|{arr_iata}|{dep_time_utc}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _normalize_candidate(raw: dict) -> FlightLookupCandidate:
    dep = raw.get("departure") or {}
    arr = raw.get("arrival") or {}
    dep_ap = dep.get("airport") or {}
    arr_ap = arr.get("airport") or {}
    airline = raw.get("airline") or {}

    departure_airport = FlightLookupAirport(
        iata=dep_ap.get("iata"),
        icao=dep_ap.get("icao"),
        name=dep_ap.get("name"),
        city=dep_ap.get("municipalityName"),
        country=dep_ap.get("countryCode"),
    )
    arrival_airport = FlightLookupAirport(
        iata=arr_ap.get("iata"),
        icao=arr_ap.get("icao"),
        name=arr_ap.get("name"),
        city=arr_ap.get("municipalityName"),
        country=arr_ap.get("countryCode"),
    )

    flight_number = (raw.get("number") or "").upper()
    dep_time_utc = dep.get("scheduledTimeUtc")

    return FlightLookupCandidate(
        id=_make_candidate_id(flight_number, departure_airport.iata, arrival_airport.iata, dep_time_utc),
        flight_number=flight_number,
        airline_name=airline.get("name"),
        airline_code=airline.get("iata"),
        departure_airport=departure_airport,
        arrival_airport=arrival_airport,
        scheduled_departure_time_local=dep.get("scheduledTimeLocal"),
        scheduled_arrival_time_local=arr.get("scheduledTimeLocal"),
        scheduled_departure_time_utc=dep_time_utc,
        scheduled_arrival_time_utc=arr.get("scheduledTimeUtc"),
        status=raw.get("status"),
    )


async def lookup_flight(raw_flight_number: str) -> FlightLookupResponse:
    """Validate, cache-check, call AeroDataBox, normalize, and cache the result."""
    normalized = normalize_flight_number(raw_flight_number)

    today = date.today()
    date_to = today + timedelta(days=settings.aerodatabox_lookup_window_days)
    date_from_str = today.isoformat()
    date_to_str = date_to.isoformat()
    window_key = f"{date_from_str}:{date_to_str}"
    cache_key = (normalized, window_key)

    cached_entry = _cache.get(cache_key)
    if cached_entry:
        inserted_at, cached_response = cached_entry
        ttl = (
            settings.aerodatabox_cache_ttl_success_seconds
            if cached_response.candidates
            else settings.aerodatabox_cache_ttl_no_results_seconds
        )
        if time.monotonic() - inserted_at < ttl:
            return cached_response.model_copy(update={"cached": True})

    try:
        raw_flights: list[RawFlightData] = await aerodatabox_client.get_flights_by_number(
            normalized, date_from_str, date_to_str
        )
    except AeroDataBoxError as exc:
        raise ServiceUnavailableException(
            "Flight lookup is temporarily unavailable. You can still enter the flight manually."
        ) from exc

    candidates = sorted(
        [_normalize_candidate(r.data) for r in raw_flights],
        key=lambda c: c.scheduled_departure_time_utc or "",
    )

    response = FlightLookupResponse(
        query=raw_flight_number,
        normalized_flight_number=normalized,
        cached=False,
        candidates=candidates,
    )
    _cache[cache_key] = (time.monotonic(), response)
    return response
