"""AWS Lambda entry point for background jobs.

Invoked by a recurring EventBridge Scheduler schedule and by asynchronous wake-ups from the API.
Each invocation processes the available work across all queues and returns before the Lambda
timeout. Event payloads are hints only (``{"kinds": [...]}``); MongoDB is the source of truth.
Every invocation serves every queue, so a run triggered by slow work still delivers pushes and
materializes due routines.

Deployment tasks (``{"task": "smoke"}`` and ``{"task": "ensure_indexes"}``) run no jobs; CI
invokes them on a newly published version before moving the ``live`` alias.

The event loop and handlers live at module level. Lambda reuses the execution environment
between invocations, and the MongoDB driver binds its client to the event loop it first ran on,
so ``asyncio.run`` per invocation would break the cached client.
"""

import asyncio
import time
from typing import Any

from app.core.ssm import load_parameters_into_environ

# Secrets must be in the environment before any application module reads settings.
_LOADED_PARAMETERS = load_parameters_into_environ()

from app.core.config import get_settings  # noqa: E402
from app.core.logging import error_fields, get_logger, setup_logging  # noqa: E402
from app.db.indexes import ensure_all_indexes  # noqa: E402
from app.db.mongo_client import get_db  # noqa: E402
from app.util.time import utc_now  # noqa: E402
from app.workers.job_handlers import build_job_handlers  # noqa: E402
from app.workers.job_health import overdue_work_seconds  # noqa: E402
from app.workers.job_runner import (  # noqa: E402
    JobHandler,
    JobKind,
    JobRunSummary,
    log_job_run_summary,
    run_jobs,
)

# Leave time to log and return after the runner's own deadline margin.
LAMBDA_SAFETY_MARGIN_SECONDS = 10.0

logger = get_logger(__name__)
_loop = asyncio.new_event_loop()
_handlers: list[JobHandler] | None = None


def requested_kinds(event: Any) -> list[str]:
    """Return the known job kinds named by a wake-up, for logging only."""
    raw = event.get("kinds") if isinstance(event, dict) else None
    if not isinstance(raw, list):
        return []
    known = {kind.value for kind in JobKind}
    return sorted({item for item in raw if isinstance(item, str) and item in known})


async def _run(remaining_seconds: float) -> JobRunSummary:
    global _handlers
    if _handlers is None:
        _handlers = build_job_handlers(get_db(), JobKind)
    deadline = time.monotonic() + remaining_seconds - LAMBDA_SAFETY_MARGIN_SECONDS
    return await run_jobs(_handlers, deadline=deadline)


async def _overdue_work() -> dict[str, int]:
    try:
        return await overdue_work_seconds(get_db(), utc_now())
    except Exception as exc:
        logger.warning(
            "Overdue work check failed", extra={"event": "job_health_failed", **error_fields(exc)}
        )
        return {}


async def _smoke() -> dict[str, object]:
    """Verify connectivity and configuration without processing any job."""
    settings = get_settings()
    await get_db().command("ping")
    return {
        "task": "smoke",
        "mongo": "ok",
        "push_configured": settings.xiaobao_web_push_ready,
        "openai_configured": bool(settings.openai_api_key),
        "parameters_loaded": len(_LOADED_PARAMETERS),
    }


async def _ensure_indexes() -> dict[str, object]:
    await ensure_all_indexes(get_db())
    return {"task": "ensure_indexes", "ok": True}


_TASKS = {"smoke": _smoke, "ensure_indexes": _ensure_indexes}


def handler(event: Any, context: Any) -> dict[str, object]:
    """Run once and return the counts, or run a deployment task.

    A job run succeeds even when individual items failed or timed out: those items are retried
    through their queues, and monitoring alarms on the ``job_run_summary`` log event.
    """
    setup_logging()
    asyncio.set_event_loop(_loop)
    task = event.get("task") if isinstance(event, dict) else None
    if task is not None:
        if task not in _TASKS:
            raise ValueError("Unknown task")
        result = _loop.run_until_complete(_TASKS[task]())
        logger.info("Deployment task finished", extra={"event": "job_task", "task": task})
        return result

    remaining_seconds = context.get_remaining_time_in_millis() / 1000
    summary = _loop.run_until_complete(_run(remaining_seconds))
    health = _loop.run_until_complete(_overdue_work())
    log_job_run_summary(summary, requested_kinds=requested_kinds(event), **health)
    return {**summary.as_log_fields(), **health}
