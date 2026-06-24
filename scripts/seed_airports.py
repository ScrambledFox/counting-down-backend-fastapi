"""Seed the airports collection from the bundled dataset.

The dataset lives at ``app/data/airports.json`` and is committed to the repo, so
this script needs no network access. It is idempotent: airports are upserted by
their (unique) ICAO code, so re-running it never creates duplicates.

Usage:
    python scripts/seed_airports.py
"""

import argparse
import asyncio
import json
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.mongo_client import get_db
from app.repositories.airport import ensure_airport_indexes
from app.schemas.v1.airport import AirportCreate
from app.util.time import utc_now

DATA_FILE = Path(__file__).resolve().parent.parent / "app" / "data" / "airports.json"

logger = get_logger(__name__)


async def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(description="Seed airports from the bundled dataset.")
    parser.add_argument(
        "--data-file",
        type=Path,
        default=DATA_FILE,
        help="Path to the airports JSON dataset (defaults to app/data/airports.json).",
    )
    args = parser.parse_args()

    logger.info("Starting airport seed")
    settings = get_settings()
    db = get_db()

    logger.info("Ensuring airport indexes on collection '%s'", settings.airports_collection_name)
    await ensure_airport_indexes(db)
    collection = db[settings.airports_collection_name]

    logger.info("Loading dataset from %s", args.data_file)
    rows = json.loads(args.data_file.read_text(encoding="utf-8"))
    logger.info("Loaded %d row(s); beginning upserts", len(rows))

    now = utc_now()
    inserted = 0
    skipped = 0
    invalid = 0
    processed = 0
    total = len(rows)
    for row in rows:
        processed += 1
        try:
            airport = AirportCreate.model_validate(row)
        except Exception as exc:  # noqa: BLE001 - report and continue seeding
            invalid += 1
            logger.warning("Skipping invalid row %s: %s", row.get("icao", "?"), exc)
            continue

        result = await collection.update_one(
            {"icao": airport.icao},
            {"$setOnInsert": {**airport.model_dump(), "created_at": now, "updated_at": None}},
            upsert=True,
        )
        if result.upserted_id is not None:
            inserted += 1
            logger.debug("Inserted airport %s", airport.icao)
        else:
            skipped += 1
            logger.debug("Skipped existing airport %s", airport.icao)

        if processed % 100 == 0 or processed == total:
            logger.info(
                "Progress: %d/%d processed (inserted=%d, skipped=%d, invalid=%d)",
                processed,
                total,
                inserted,
                skipped,
                invalid,
            )

    logger.info(
        "Seed complete: inserted=%d, skipped(existing)=%d, invalid=%d, total=%d",
        inserted,
        skipped,
        invalid,
        total,
    )


if __name__ == "__main__":
    asyncio.run(main())
