"""Safely diagnose and repair flight references to deleted airports.

Dry run is the default. The command deliberately prints aggregate information
only; it never logs flight numbers, routes, timestamps, or Mongo identifiers.

Usage:
    uv run python scripts/repair_orphaned_flight_airports.py
    uv run python scripts/repair_orphaned_flight_airports.py --apply --confirm-database DB_NAME
"""

import argparse
import asyncio
import logging
from datetime import timedelta
from uuid import uuid4

from pymongo import ASCENDING, UpdateOne

from app.core.config import get_settings
from app.db.mongo_client import get_db
from app.models.flight import Flight
from app.services.flight_airport_repair import (
    AirportCatalogEntry,
    FlightAirportRepair,
    FlightAirportRepairError,
    register_reference_mapping,
    repair_from_reference_mappings,
    resolve_flight_airports,
)
from app.services.flight_lookup import lookup_flight
from app.util.time import utc_now

BACKUP_COLLECTION = "flight_airport_repair_backups"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run or repair orphaned airport references on flights."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Back up and update affected flights. Without this flag no data is changed.",
    )
    parser.add_argument(
        "--confirm-database",
        help="Required with --apply and must exactly match MONGO_APP_NAME.",
    )
    parser.add_argument(
        "--max-time-delta-hours",
        type=float,
        default=12.0,
        help="Maximum difference between stored and looked-up departure time (default: 12).",
    )
    return parser.parse_args()


async def _load_state() -> tuple[list[dict], dict[str, AirportCatalogEntry], set[str]]:
    settings = get_settings()
    db = get_db()
    airport_docs = (
        await db[settings.airports_collection_name]
        .find({}, {"_id": 1, "icao": 1})
        .to_list(length=None)
    )
    flight_docs = await db[settings.flights_collection_name].find().to_list(length=None)

    catalog = {
        airport["icao"].upper(): AirportCatalogEntry(
            id=str(airport["_id"]), icao=airport["icao"].upper()
        )
        for airport in airport_docs
        if airport.get("icao")
    }
    existing_ids = {airport.id for airport in catalog.values()}
    return flight_docs, catalog, existing_ids


async def _build_repairs(
    affected_docs: list[dict],
    catalog: dict[str, AirportCatalogEntry],
    existing_ids: set[str],
    max_time_delta: timedelta,
) -> tuple[list[FlightAirportRepair], int]:
    repairs: list[FlightAirportRepair] = []
    reference_mappings: dict[str, str] = {}
    unresolved_flights: list[Flight] = []
    mapping_conflict = False

    for doc in affected_docs:
        flight = Flight.model_validate(doc)
        try:
            response = await lookup_flight(flight.flight_number, flight.departure_at.date())
            repair = resolve_flight_airports(
                flight,
                response.candidates,
                catalog,
                existing_ids,
                max_time_delta,
            )
            if flight.departure_airport_id not in existing_ids:
                register_reference_mapping(
                    reference_mappings,
                    flight.departure_airport_id,
                    repair.departure_airport_id,
                )
            if flight.arrival_airport_id not in existing_ids:
                register_reference_mapping(
                    reference_mappings,
                    flight.arrival_airport_id,
                    repair.arrival_airport_id,
                )
            repairs.append(repair)
        except FlightAirportRepairError as exc:
            mapping_conflict = mapping_conflict or "inconsistently" in str(exc)
            unresolved_flights.append(flight)
        except Exception:  # noqa: BLE001 - report aggregate failure and refuse writes
            unresolved_flights.append(flight)

    if mapping_conflict:
        return [], len(affected_docs)

    still_unresolved = 0
    for flight in unresolved_flights:
        propagated_repair = repair_from_reference_mappings(flight, reference_mappings, existing_ids)
        if propagated_repair is None:
            still_unresolved += 1
        else:
            repairs.append(propagated_repair)

    return repairs, still_unresolved


async def _apply_repairs(affected_docs: list[dict], repairs: list[FlightAirportRepair]) -> str:
    settings = get_settings()
    db = get_db()
    flights = db[settings.flights_collection_name]
    backups = db[BACKUP_COLLECTION]
    batch_id = str(uuid4())
    backed_up_at = utc_now()

    await backups.create_index(
        [("repair_batch_id", ASCENDING), ("flight_id", ASCENDING)], unique=True
    )
    await backups.insert_many(
        [
            {
                "repair_batch_id": batch_id,
                "flight_id": doc["_id"],
                "backed_up_at": backed_up_at,
                "original_document": doc,
            }
            for doc in affected_docs
        ],
        ordered=True,
    )

    by_flight_id = {str(doc["_id"]): doc["_id"] for doc in affected_docs}
    original_by_flight_id = {str(doc["_id"]): doc for doc in affected_docs}
    result = await flights.bulk_write(
        [
            UpdateOne(
                {
                    "_id": by_flight_id[repair.flight_id],
                    "departure_airport_id": original_by_flight_id[repair.flight_id][
                        "departure_airport_id"
                    ],
                    "arrival_airport_id": original_by_flight_id[repair.flight_id][
                        "arrival_airport_id"
                    ],
                },
                {
                    "$set": {
                        "departure_airport_id": repair.departure_airport_id,
                        "arrival_airport_id": repair.arrival_airport_id,
                        "updated_at": backed_up_at,
                    }
                },
            )
            for repair in repairs
        ],
        ordered=True,
    )
    if result.matched_count != len(repairs) or result.modified_count != len(repairs):
        raise RuntimeError("Repair update count did not match the validated plan")
    return batch_id


async def main() -> int:
    args = _parse_args()
    # Keep the command's output aggregate-only even when the upstream lookup fails.
    logging.getLogger("app.integrations.aerodatabox_client").disabled = True
    settings = get_settings()
    if args.max_time_delta_hours <= 0:
        raise SystemExit("--max-time-delta-hours must be positive")
    if args.apply and args.confirm_database != settings.mongo_app_name:
        raise SystemExit("--apply requires --confirm-database matching MONGO_APP_NAME exactly")

    flight_docs, catalog, existing_ids = await _load_state()
    affected_docs = [
        doc
        for doc in flight_docs
        if str(doc.get("departure_airport_id")) not in existing_ids
        or str(doc.get("arrival_airport_id")) not in existing_ids
    ]
    missing_departure = sum(
        str(doc.get("departure_airport_id")) not in existing_ids for doc in flight_docs
    )
    missing_arrival = sum(
        str(doc.get("arrival_airport_id")) not in existing_ids for doc in flight_docs
    )

    print(f"airports={len(catalog)}")
    print(f"flights={len(flight_docs)}")
    print(f"affected_flights={len(affected_docs)}")
    print(f"missing_departure={missing_departure}")
    print(f"missing_arrival={missing_arrival}")
    if not affected_docs:
        print("status=clean")
        return 0

    repairs, unresolved = await _build_repairs(
        affected_docs,
        catalog,
        existing_ids,
        timedelta(hours=args.max_time_delta_hours),
    )
    print(f"resolved_flights={len(repairs)}")
    print(f"unresolved_flights={unresolved}")
    if unresolved or len(repairs) != len(affected_docs):
        print("status=blocked")
        print(
            "action=No data was changed; every affected flight must resolve "
            "before apply is allowed."
        )
        return 2

    if not args.apply:
        print("status=ready")
        print("mode=dry-run")
        return 0

    batch_id = await _apply_repairs(affected_docs, repairs)
    print("status=repaired")
    print(f"updated_flights={len(repairs)}")
    print(f"backup_batch={batch_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
