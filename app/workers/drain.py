"""Run background jobs from the command line.

Usage:
    python -m app.workers.drain                 # process available work, then exit
    python -m app.workers.drain --loop          # keep polling (local development, Heroku)
    python -m app.workers.drain --kinds push,clock --max-seconds 120
"""

import argparse
import asyncio
import signal
import time
from collections.abc import Iterable

from app.core.logging import get_logger, setup_logging
from app.db.mongo_client import get_db
from app.workers.job_handlers import build_job_handlers
from app.workers.job_runner import JobKind, JobRunSummary, log_job_run_summary, run_jobs

logger = get_logger(__name__)

DEFAULT_MAX_SECONDS = 600.0


def parse_kinds(value: str | None) -> list[JobKind]:
    if not value:
        return list(JobKind)
    try:
        return [JobKind(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        valid = ", ".join(kind.value for kind in JobKind)
        raise argparse.ArgumentTypeError(f"unknown job kind; expected any of: {valid}") from exc


async def drain(
    kinds: Iterable[JobKind],
    *,
    continuous: bool,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    stop_event: asyncio.Event | None = None,
) -> JobRunSummary:
    handlers = build_job_handlers(get_db(), kinds)
    deadline = None if continuous else time.monotonic() + max_seconds
    return await run_jobs(handlers, deadline=deadline, continuous=continuous, stop_event=stop_event)


async def _main(kinds: list[JobKind], *, continuous: bool, max_seconds: float) -> None:
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    if task is not None:
        # Stop promptly on dyno restarts. An interrupted item keeps its lease and is retried.
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, task.cancel)
    summary = await drain(kinds, continuous=continuous, max_seconds=max_seconds)
    log_job_run_summary(summary, job_kinds=[kind.value for kind in kinds])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--loop", action="store_true", help="keep polling until stopped")
    parser.add_argument(
        "--kinds", type=parse_kinds, default=list(JobKind), help="comma-separated job kinds"
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=DEFAULT_MAX_SECONDS,
        help="time budget for a single (non --loop) run",
    )
    args = parser.parse_args(argv)
    setup_logging()
    try:
        asyncio.run(_main(args.kinds, continuous=args.loop, max_seconds=args.max_seconds))
    except asyncio.CancelledError:
        logger.info("Background jobs stopped")


if __name__ == "__main__":
    main()
