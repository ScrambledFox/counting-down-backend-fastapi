"""Make per-job mediation output deduplication guaranteed with unique indexes.

Mediation reflections, advice and AI comments record the ``ai_job_id`` of the job that produced
them. This explicit migration adds a partial unique index on that field to each collection, so a
second write for the same job is rejected by the database instead of relying on best-effort
checks. It never runs at application startup and never modifies or deletes documents.

Usage:
    # Report duplicates (read-only, default):
    python scripts/migrate_mediation_output_unique_index.py

    # Create the indexes, only if no duplicates exist:
    python scripts/migrate_mediation_output_unique_index.py --apply --confirm-database production

The command prints counts and duplicated job identifiers only, never document content. If
duplicates exist, it refuses to apply; resolve them deliberately first (see ADR 0001).
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from typing import Any

from pymongo.errors import OperationFailure

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.mongo_client import get_db
from app.models.mongo import AsyncDB

INDEX_NAME = "ai_job_id_unique"
JOB_ID_FILTER: dict[str, Any] = {"ai_job_id": {"$type": "string"}}
MAX_REPORTED_JOB_IDS = 10


def output_collections() -> tuple[str, ...]:
    settings = get_settings()
    return (
        settings.mediation_ai_reflections_collection_name,
        settings.mediation_advices_collection_name,
        settings.mediation_comments_collection_name,
    )


@dataclass
class DuplicateReport:
    collection: str
    documents_with_job_id: int
    duplicated_job_ids: int
    documents_in_duplicate_groups: int
    sample_job_ids: list[str]


async def find_duplicates(db: AsyncDB, collection: str) -> DuplicateReport:
    coll = db[collection]
    with_job_id = await coll.count_documents(JOB_ID_FILTER)
    cursor = coll.aggregate(
        [
            {"$match": JOB_ID_FILTER},
            {"$group": {"_id": "$ai_job_id", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}},
            {"$sort": {"_id": 1}},
        ]
    )
    groups = await cursor.to_list(length=None)
    return DuplicateReport(
        collection=collection,
        documents_with_job_id=with_job_id,
        duplicated_job_ids=len(groups),
        documents_in_duplicate_groups=sum(group["count"] for group in groups),
        sample_job_ids=[str(group["_id"]) for group in groups[:MAX_REPORTED_JOB_IDS]],
    )


async def unique_index_exists(db: AsyncDB, collection: str) -> bool:
    indexes = await db[collection].index_information()
    return INDEX_NAME in indexes and bool(indexes[INDEX_NAME].get("unique"))


async def create_unique_index(db: AsyncDB, collection: str) -> None:
    await db[collection].create_index(
        [("ai_job_id", 1)],
        name=INDEX_NAME,
        unique=True,
        partialFilterExpression=JOB_ID_FILTER,
    )


async def run(db: AsyncDB, *, apply: bool) -> int:
    """Return a process exit code: 0 on success, 1 when duplicates block the migration."""
    reports = [await find_duplicates(db, name) for name in output_collections()]
    for report in reports:
        present = await unique_index_exists(db, report.collection)
        print(
            f"{report.collection}: {report.documents_with_job_id} outputs with a job id, "
            f"{report.duplicated_job_ids} duplicated job ids "
            f"({report.documents_in_duplicate_groups} documents), "
            f"unique index {'present' if present else 'absent'}"
        )
        if report.sample_job_ids:
            print(f"  duplicated job ids (first {MAX_REPORTED_JOB_IDS}): {report.sample_job_ids}")

    if any(report.duplicated_job_ids for report in reports):
        print("Duplicates found: no index was created. Resolve them deliberately first.")
        return 1
    if not apply:
        print("No duplicates. Re-run with --apply --confirm-database <name> to create indexes.")
        return 0

    for report in reports:
        if await unique_index_exists(db, report.collection):
            continue
        try:
            await create_unique_index(db, report.collection)
        except OperationFailure as exc:
            # A duplicate written between the check and the build, or an index conflict.
            print(f"{report.collection}: index creation failed ({exc.code}); nothing changed.")
            return 1
        print(f"{report.collection}: created unique index {INDEX_NAME}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="create the unique indexes")
    parser.add_argument(
        "--confirm-database",
        help="required with --apply; must equal the configured MONGO_APP_NAME",
    )
    args = parser.parse_args(argv)
    database = get_settings().mongo_app_name
    if args.apply and args.confirm_database != database:
        parser.error(f"--apply requires --confirm-database {database}")
    setup_logging()
    print(f"Database: {database} ({'apply' if args.apply else 'check only'})")
    return asyncio.run(run(get_db(), apply=args.apply))


if __name__ == "__main__":
    sys.exit(main())
