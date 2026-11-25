"""Age of the oldest overdue background work, for monitoring.

Reported in each ``job_run_summary`` so an alarm can detect work that should have run but did
not (for example a stuck schedule or a queue that keeps failing). Only timestamps are read.
"""

from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings
from app.models.mongo import AsyncDB
from app.schemas.v1.xiaobao_push import XiaoBaoPushDeliveryStatus
from app.schemas.v1.xiaobao_routine import XiaoBaoRoutineRunStatus

settings = get_settings()


def _age_seconds(value: Any, now: datetime) -> int:
    if not isinstance(value, datetime):
        return 0
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return max(0, round((now - value).total_seconds()))


async def _oldest(db: AsyncDB, collection: str, query: dict[str, Any], field: str) -> Any:
    doc = await db[collection].find_one(query, sort=[(field, 1)], projection={field: 1})
    return doc.get(field) if doc else None


async def overdue_work_seconds(db: AsyncDB, now: datetime) -> dict[str, int]:
    """Seconds since the oldest routine (or routine run) and push became due but stayed unrun."""
    due_routine = await _oldest(
        db,
        settings.xiaobao_routines_collection_name,
        {"enabled": True, "deleted_at": None, "next_run_at": {"$type": "date", "$lte": now}},
        "next_run_at",
    )
    pending_run = await _oldest(
        db,
        settings.xiaobao_routine_runs_collection_name,
        {
            "status": XiaoBaoRoutineRunStatus.PENDING,
            "available_at": {"$lte": now},
            "attempt_count": {"$lt": settings.xiaobao_routine_max_attempts},
        },
        "available_at",
    )
    pending_push = await _oldest(
        db,
        settings.xiaobao_push_deliveries_collection_name,
        {
            "status": XiaoBaoPushDeliveryStatus.PENDING,
            "available_at": {"$lte": now},
            "attempt_count": {"$lt": settings.xiaobao_web_push_max_attempts},
        },
        "available_at",
    )
    return {
        "oldest_overdue_routine_seconds": max(
            _age_seconds(due_routine, now), _age_seconds(pending_run, now)
        ),
        "oldest_pending_push_seconds": _age_seconds(pending_push, now),
    }
