from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models.flight import Flight
from app.schemas.v1.flight_lookup import FlightLookupCandidate


class FlightAirportRepairError(ValueError):
    """Raised when an orphaned airport reference cannot be repaired safely."""


@dataclass(frozen=True)
class AirportCatalogEntry:
    id: str
    icao: str


@dataclass(frozen=True)
class FlightAirportRepair:
    flight_id: str
    departure_airport_id: str
    arrival_airport_id: str


def _parse_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _candidate_airport_ids(
    candidate: FlightLookupCandidate,
    catalog_by_icao: dict[str, AirportCatalogEntry],
) -> tuple[str, str] | None:
    departure_icao = candidate.departure_airport.icao
    arrival_icao = candidate.arrival_airport.icao
    if not departure_icao or not arrival_icao:
        return None

    departure = catalog_by_icao.get(departure_icao.upper())
    arrival = catalog_by_icao.get(arrival_icao.upper())
    if departure is None or arrival is None:
        return None
    return departure.id, arrival.id


def resolve_flight_airports(
    flight: Flight,
    candidates: list[FlightLookupCandidate],
    catalog_by_icao: dict[str, AirportCatalogEntry],
    existing_airport_ids: set[str],
    max_time_delta: timedelta,
) -> FlightAirportRepair:
    """Resolve a single route without revealing or guessing around conflicting data."""
    if flight.id is None:
        raise FlightAirportRepairError("Flight has no identifier")

    departure_at = flight.departure_at
    if departure_at.tzinfo is None:
        departure_at = departure_at.replace(tzinfo=UTC)
    departure_at = departure_at.astimezone(UTC)
    normalized_flight_number = flight.flight_number.upper().replace(" ", "").replace("-", "")

    matches: list[tuple[timedelta, str, str]] = []
    for candidate in candidates:
        candidate_flight_number = candidate.flight_number.upper().replace(" ", "").replace("-", "")
        if candidate_flight_number != normalized_flight_number:
            continue
        airport_ids = _candidate_airport_ids(candidate, catalog_by_icao)
        candidate_departure = _parse_utc(candidate.scheduled_departure_time_utc)
        if airport_ids is None or candidate_departure is None:
            continue

        departure_id, arrival_id = airport_ids
        if (
            flight.departure_airport_id in existing_airport_ids
            and flight.departure_airport_id != departure_id
        ):
            continue
        if (
            flight.arrival_airport_id in existing_airport_ids
            and flight.arrival_airport_id != arrival_id
        ):
            continue

        delta = abs(candidate_departure - departure_at)
        if delta <= max_time_delta:
            matches.append((delta, departure_id, arrival_id))

    if not matches:
        raise FlightAirportRepairError("No candidate matches the stored route and departure time")

    matches.sort(key=lambda match: match[0])
    best_delta = matches[0][0]
    best_routes = {
        (departure_id, arrival_id)
        for delta, departure_id, arrival_id in matches
        if delta == best_delta
    }
    if len(best_routes) != 1:
        raise FlightAirportRepairError("Multiple routes are equally plausible")

    departure_id, arrival_id = best_routes.pop()
    return FlightAirportRepair(
        flight_id=str(flight.id),
        departure_airport_id=departure_id,
        arrival_airport_id=arrival_id,
    )


def register_reference_mapping(
    mappings: dict[str, str],
    old_airport_id: str,
    new_airport_id: str,
) -> None:
    existing = mappings.get(old_airport_id)
    if existing is not None and existing != new_airport_id:
        raise FlightAirportRepairError("An orphaned reference resolves inconsistently")
    mappings[old_airport_id] = new_airport_id


def repair_from_reference_mappings(
    flight: Flight,
    mappings: dict[str, str],
    existing_airport_ids: set[str],
) -> FlightAirportRepair | None:
    if flight.id is None:
        raise FlightAirportRepairError("Flight has no identifier")

    departure_id = (
        flight.departure_airport_id
        if flight.departure_airport_id in existing_airport_ids
        else mappings.get(flight.departure_airport_id)
    )
    arrival_id = (
        flight.arrival_airport_id
        if flight.arrival_airport_id in existing_airport_ids
        else mappings.get(flight.arrival_airport_id)
    )
    if departure_id is None or arrival_id is None:
        return None
    return FlightAirportRepair(
        flight_id=str(flight.id),
        departure_airport_id=departure_id,
        arrival_airport_id=arrival_id,
    )
