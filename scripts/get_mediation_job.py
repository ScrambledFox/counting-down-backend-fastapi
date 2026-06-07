import argparse
import asyncio

from app.core.config import get_settings
from app.db.mongo_client import get_db


async def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a mediation AI job.")
    parser.add_argument("idempotency_key")
    args = parser.parse_args()

    settings = get_settings()
    db = get_db()
    job = await db[settings.mediation_ai_jobs_collection_name].find_one(
        {"idempotency_key": args.idempotency_key},
        {"_id": 0, "status": 1, "attempts": 1, "max_attempts": 1, "error_message": 1},
    )
    print(job)


if __name__ == "__main__":
    asyncio.run(main())
