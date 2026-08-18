from datetime import UTC, datetime, timedelta

import pytest

from app.models.flight import Flight, FlightStatus
from app.schemas.v1.flight_lookup import FlightLookupAirport, FlightLookupCandidate
from app.services.flight_airport_repair import (
    AirportCatalogEntry,
    FlightAirportRepairError,
    register_reference_mapping,
    repair_from_reference_mappings,
    resolve_flight_airports,
)

OLD_DEPARTURE_ID = "64a7f0c2f1d2c4b5a6e7d901"
OLD_ARRIVAL_ID = "64a7f0c2f1d2c4b5a6e7d902"
NEW_DEPARTURE_ID = "74a7f0c2f1d2c4b5a6e7d901"
NEW_ARRIVAL_ID = "74a7f0c2f1d2c4b5a6e7d902"


def _flight(
    departure_airport_id: str = OLD_DEPARTURE_ID,
    arrival_airport_id: str = OLD_ARRIVAL_ID,
) -> Flight:
    return Flight(
        id="64a7f0c2f1d2c4b5a6e7d999",
        flight_number="ZZ123",
        departure_airport_id=departure_airport_id,
        arrival_airport_id=arrival_airport_id,
        departure_at=datetime(2026, 8, 18, 10, 0, tzinfo=UTC),
        arrival_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
        status=FlightStatus.ACTIVE,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _candidate(
    departure_icao: str = "TEST",
    arrival_icao: str = "TST2",
    departure_time: str = "2026-08-18T10:05:00Z",
) -> FlightLookupCandidate:
    return FlightLookupCandidate(
        id="candidate",
        flight_number="ZZ123",
        departure_airport=FlightLookupAirport(icao=departure_icao),
        arrival_airport=FlightLookupAirport(icao=arrival_icao),
        scheduled_departure_time_utc=departure_time,
    )


@pytest.fixture
def catalog() -> dict[str, AirportCatalogEntry]:
    return {
        "TEST": AirportCatalogEntry(id=NEW_DEPARTURE_ID, icao="TEST"),
        "TST2": AirportCatalogEntry(id=NEW_ARRIVAL_ID, icao="TST2"),
        "DIFF": AirportCatalogEntry(id="74a7f0c2f1d2c4b5a6e7d903", icao="DIFF"),
    }


def test_resolves_closest_complete_catalog_route(catalog: dict[str, AirportCatalogEntry]):
    repair = resolve_flight_airports(
        _flight(),
        [_candidate(departure_time="2026-08-18T11:00:00Z"), _candidate()],
        catalog,
        set(catalog_entry.id for catalog_entry in catalog.values()),
        timedelta(hours=12),
    )

    assert repair.departure_airport_id == NEW_DEPARTURE_ID
    assert repair.arrival_airport_id == NEW_ARRIVAL_ID


def test_rejects_candidate_that_conflicts_with_still_valid_reference(
    catalog: dict[str, AirportCatalogEntry],
):
    flight = _flight(departure_airport_id=NEW_DEPARTURE_ID)

    with pytest.raises(FlightAirportRepairError, match="No candidate"):
        resolve_flight_airports(
            flight,
            [_candidate(departure_icao="DIFF")],
            catalog,
            {entry.id for entry in catalog.values()},
            timedelta(hours=12),
        )


def test_rejects_equally_close_different_routes(catalog: dict[str, AirportCatalogEntry]):
    with pytest.raises(FlightAirportRepairError, match="equally plausible"):
        resolve_flight_airports(
            _flight(),
            [
                _candidate(departure_time="2026-08-18T09:00:00Z"),
                _candidate(
                    departure_icao="DIFF",
                    departure_time="2026-08-18T11:00:00Z",
                ),
            ],
            catalog,
            {entry.id for entry in catalog.values()},
            timedelta(hours=12),
        )


def test_rejects_inconsistent_mapping_for_same_orphaned_id():
    mappings = {OLD_DEPARTURE_ID: NEW_DEPARTURE_ID}

    with pytest.raises(FlightAirportRepairError, match="inconsistently"):
        register_reference_mapping(mappings, OLD_DEPARTURE_ID, NEW_ARRIVAL_ID)


def test_reuses_proven_reference_mappings_without_guessing():
    repair = repair_from_reference_mappings(
        _flight(),
        {
            OLD_DEPARTURE_ID: NEW_DEPARTURE_ID,
            OLD_ARRIVAL_ID: NEW_ARRIVAL_ID,
        },
        {NEW_DEPARTURE_ID, NEW_ARRIVAL_ID},
    )

    assert repair is not None
    assert repair.departure_airport_id == NEW_DEPARTURE_ID
    assert repair.arrival_airport_id == NEW_ARRIVAL_ID


def test_does_not_reuse_incomplete_reference_mappings():
    repair = repair_from_reference_mappings(
        _flight(),
        {OLD_DEPARTURE_ID: NEW_DEPARTURE_ID},
        {NEW_DEPARTURE_ID, NEW_ARRIVAL_ID},
    )

    assert repair is None
