"""Create or verify all MongoDB indexes.

Idempotent and safe to run on every deploy, so web and job processes do not need to create
indexes when they start.

Usage:
    python scripts/ensure_indexes.py
"""

import asyncio

from app.core.logging import get_logger, setup_logging
from app.db.indexes import ensure_all_indexes
from app.db.mongo_client import get_db

logger = get_logger(__name__)


async def main() -> None:
    setup_logging()
    await ensure_all_indexes(get_db())
    logger.info("MongoDB indexes are up to date")


if __name__ == "__main__":
    asyncio.run(main())
