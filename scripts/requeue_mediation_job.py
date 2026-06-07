import argparse
import asyncio

from app.core.config import get_settings
from app.db.mongo_client import get_db
from app.util.time import utc_now


async def main() -> None:
    parser = argparse.ArgumentParser(description="Requeue an exhausted mediation AI job.")
    parser.add_argument("idempotency_key")
    args = parser.parse_args()

    settings = get_settings()
    db = get_db()
    result = await db[settings.mediation_ai_jobs_collection_name].update_one(
        {"idempotency_key": args.idempotency_key, "status": "FAILED"},
        {
            "$set": {
                "status": "PENDING",
                "attempts": 0,
                "error_message": None,
                "updated_at": utc_now(),
            },
            "$unset": {"started_at": "", "completed_at": ""},
        },
    )
    print({"matched": result.matched_count, "modified": result.modified_count})


if __name__ == "__main__":
    asyncio.run(main())
