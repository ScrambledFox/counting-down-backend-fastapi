"""AWS Lambda entry point for background jobs.

Invoked by a recurring EventBridge Scheduler schedule and by asynchronous wake-ups from the API.
Each invocation processes the available work across all queues and returns before the Lambda
timeout. Event payloads are hints only (``{"kinds": [...]}``); MongoDB is the source of truth.
Every invocation serves every queue, so a run triggered by slow work still delivers pushes and
materializes due routines.

The event loop and handlers live at module level. Lambda reuses the execution environment
between invocations, and the MongoDB driver binds its client to the event loop it first ran on,
so ``asyncio.run`` per invocation would break the cached client.
"""

import asyncio
import time
from typing import Any

from app.core.logging import setup_logging
from app.db.mongo_client import get_db
from app.workers.job_handlers import build_job_handlers
from app.workers.job_runner import (
    JobHandler,
    JobKind,
    JobRunSummary,
    log_job_run_summary,
    run_jobs,
)

# Leave time to log and return after the runner's own deadline margin.
LAMBDA_SAFETY_MARGIN_SECONDS = 10.0

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


def handler(event: Any, context: Any) -> dict[str, object]:
    """Run once and return the counts.

    The invocation succeeds even when individual items failed or timed out: those items are
    retried through their queues, and monitoring alarms on the ``job_run_summary`` log event.
    """
    setup_logging()
    asyncio.set_event_loop(_loop)
    remaining_seconds = context.get_remaining_time_in_millis() / 1000
    summary = _loop.run_until_complete(_run(remaining_seconds))
    log_job_run_summary(summary, requested_kinds=requested_kinds(event))
    return summary.as_log_fields()
