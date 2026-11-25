"""Consolidated background job runner.

Every queue in this application is a durable MongoDB collection with leases, attempt limits and
duplicate guards. The runner only decides *when* to call each queue's existing "process one
item" function; it holds no job state itself. Stopping it at any point is equivalent to a crash
that the queues already recover from when their leases expire.

Each queue runs in its own lane, concurrently with the others, and processes one item at a time:

* the fast lane (routine clock and push delivery) keeps polling while slow work runs, so a long AI
  generation never delays notifications or the materialization of due routines;
* routine runs, mediation AI and image processing each have their own lane, so a slow or failing
  queue never blocks another one (the previous web process also ran image and mediation work in
  separate tasks).

The same logic runs in two modes. Finite mode drains available work and returns before a deadline
(serverless invocations, one-off commands). Continuous mode polls until a stop event is set
(local development, Heroku, in-process web workers).
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.core.logging import error_fields, get_logger

logger = get_logger(__name__)

# Time kept free at the end of a finite run so the process can report before its hard limit.
DEADLINE_MARGIN_SECONDS = 5.0
# How often an idle fast lane checks for push work while slow lanes are still producing it.
FAST_LANE_FOLLOW_SECONDS = 1.0


class JobKind(StrEnum):
    CLOCK = "clock"
    PUSH = "push"
    ROUTINE = "routine"
    MEDIATION = "mediation"
    IMAGE = "image"


FAST_KINDS = frozenset({JobKind.CLOCK, JobKind.PUSH})


class JobResult(StrEnum):
    """Outcome of one ``process_one`` call. Timeouts are recorded by the runner itself."""

    IDLE = "idle"  # no work was available
    PROCESSED = "processed"  # work completed successfully
    TERMINAL = "terminal"  # expected final outcome, e.g. a revoked push subscription
    FAILED = "failed"  # unexpected failure; the queue persisted a retry or failure state


@dataclass(frozen=True)
class JobHandler:
    """One durable queue.

    ``process_one`` claims and processes at most one item and reports a ``JobResult``.
    ``timeout_seconds`` must stay below the queue's lease so a cancelled item is retried by the
    next runner instead of overlapping with a still-running one. ``idle_interval_seconds`` is the
    pause before polling an empty or failing queue again.
    """

    kind: JobKind
    process_one: Callable[[], Awaitable[JobResult]]
    timeout_seconds: float
    idle_interval_seconds: float


@dataclass
class JobRunSummary:
    processed: dict[str, int] = field(default_factory=dict)
    terminal: dict[str, int] = field(default_factory=dict)
    timed_out: dict[str, int] = field(default_factory=dict)
    failed: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0

    def count(self, bucket: dict[str, int], kind: JobKind) -> None:
        bucket[kind.value] = bucket.get(kind.value, 0) + 1

    @property
    def unsuccessful(self) -> bool:
        return bool(self.failed or self.timed_out)

    def as_log_fields(self) -> dict[str, object]:
        """Counts only; safe to log and to return from a Lambda invocation."""
        return {
            "processed": self.processed,
            "terminal": self.terminal,
            "failed": self.failed,
            "timed_out": self.timed_out,
            "processed_total": sum(self.processed.values()),
            "terminal_total": sum(self.terminal.values()),
            "failed_total": sum(self.failed.values()),
            "timed_out_total": sum(self.timed_out.values()),
            "duration_ms": self.duration_ms,
        }


def log_job_run_summary(summary: JobRunSummary, **fields: object) -> None:
    """Emit the ``job_run_summary`` event that monitoring alarms on.

    A run can finish normally while individual items failed or timed out, so alarms key on
    ``failed_total`` and ``timed_out_total`` rather than on the process outcome.
    """
    logger.log(
        logging.WARNING if summary.unsuccessful else logging.INFO,
        "Background job run finished",
        extra={
            "event": "job_run_summary",
            "outcome": "unsuccessful_items" if summary.unsuccessful else "ok",
            **summary.as_log_fields(),
            **fields,
        },
    )


class _Lane:
    def __init__(
        self,
        handlers: Sequence[JobHandler],
        *,
        deadline: float | None,
        summary: JobRunSummary,
        clock: Callable[[], float],
    ) -> None:
        self._handlers = list(handlers)
        self._deadline = deadline
        self._summary = summary
        self._clock = clock
        self._next_due = {handler.kind: 0.0 for handler in handlers}

    def _fits_deadline(self, handler: JobHandler) -> bool:
        if self._deadline is None:
            return True
        return self._clock() + handler.timeout_seconds + DEADLINE_MARGIN_SECONDS <= self._deadline

    async def _run_one(self, handler: JobHandler) -> JobResult | None:
        """Run one item; return its result, or None when it timed out."""
        started = self._clock()
        try:
            result = await asyncio.wait_for(handler.process_one(), handler.timeout_seconds)
        except TimeoutError:
            # The item's lease outlives this timeout, so another run retries it safely.
            logger.warning(
                "Background job timed out",
                extra={
                    "event": "job_timeout",
                    "job_kind": handler.kind.value,
                    "duration_ms": round((self._clock() - started) * 1000),
                },
            )
            self._summary.count(self._summary.timed_out, handler.kind)
            return None
        except Exception as exc:
            # Never log the exception message: it may hold provider bodies or private content.
            logger.error(
                "Background job failed",
                extra={
                    "event": "job_failed",
                    "job_kind": handler.kind.value,
                    "duration_ms": round((self._clock() - started) * 1000),
                    **error_fields(exc),
                },
            )
            result = JobResult.FAILED
        bucket = {
            JobResult.PROCESSED: self._summary.processed,
            JobResult.TERMINAL: self._summary.terminal,
            JobResult.FAILED: self._summary.failed,
        }.get(result)
        if bucket is not None:
            self._summary.count(bucket, handler.kind)
        return result

    async def run_pass(self) -> bool:
        """Give every due handler one turn; return whether any of them found work."""
        worked_any = False
        for handler in self._handlers:
            if self._clock() < self._next_due[handler.kind] or not self._fits_deadline(handler):
                continue
            result = await self._run_one(handler)
            # Successful or terminal work may be followed by more; a timed-out item keeps its
            # lease, so the queue may hold other items. Empty and failing queues back off,
            # which rules out busy loops on persistent failures.
            worked = result in (JobResult.PROCESSED, JobResult.TERMINAL, None)
            worked_any = worked_any or worked
            self._next_due[handler.kind] = (
                self._clock() if worked else self._clock() + handler.idle_interval_seconds
            )
        return worked_any

    def seconds_until_next_due(self) -> float:
        runnable = [
            self._next_due[handler.kind]
            for handler in self._handlers
            if self._fits_deadline(handler)
        ]
        if not runnable:
            return 0.0
        return max(0.0, min(runnable) - self._clock())

    @property
    def empty(self) -> bool:
        return not self._handlers

    def make_all_due(self) -> None:
        self._next_due = {handler.kind: 0.0 for handler in self._handlers}

    def can_run_anything(self) -> bool:
        return any(self._fits_deadline(handler) for handler in self._handlers)

    def has_due_work(self) -> bool:
        now = self._clock()
        return any(
            self._next_due[handler.kind] <= now and self._fits_deadline(handler)
            for handler in self._handlers
        )


async def _sleep(seconds: float, wake_event: asyncio.Event | None) -> None:
    if seconds <= 0:
        await asyncio.sleep(0)
        return
    if wake_event is None:
        await asyncio.sleep(seconds)
        return
    try:
        await asyncio.wait_for(wake_event.wait(), seconds)
    except TimeoutError:
        pass


async def run_jobs(
    handlers: Sequence[JobHandler],
    *,
    deadline: float | None = None,
    stop_event: asyncio.Event | None = None,
    continuous: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> JobRunSummary:
    """Process background work.

    ``deadline`` is a ``clock()`` timestamp; no item starts unless its timeout fits before it.
    In finite mode the runner returns once every queue has been found empty (or the deadline
    leaves no room). In continuous mode it keeps polling until ``stop_event`` is set.
    """
    if not continuous and deadline is None:
        raise ValueError("finite job runs require a deadline")
    started = clock()
    summary = JobRunSummary()

    def lane(lane_handlers: Sequence[JobHandler]) -> _Lane:
        return _Lane(lane_handlers, deadline=deadline, summary=summary, clock=clock)

    fast = lane([h for h in handlers if h.kind in FAST_KINDS])
    slow_lanes = [lane([h]) for h in handlers if h.kind not in FAST_KINDS]
    slow_remaining = len(slow_lanes)
    slow_done = asyncio.Event()
    if not slow_lanes:
        slow_done.set()
    fast_primed = asyncio.Event()

    def stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    async def run_fast() -> None:
        try:
            if fast.empty:
                return
            final_pass_done = False
            while not stopped():
                worked = await fast.run_pass()
                # Due routines are materialized before the routine lane looks for runs.
                fast_primed.set()
                if worked:
                    continue
                if continuous:
                    await _sleep(fast.seconds_until_next_due(), stop_event)
                    continue
                if not fast.can_run_anything():
                    return
                if slow_done.is_set():
                    if final_pass_done:
                        return
                    # Pick up pushes that slow lanes created after the previous pass.
                    fast.make_all_due()
                    final_pass_done = True
                    continue
                # Keep delivering pushes that slow work produces while it is still running, and
                # do the final pass as soon as the last slow lane finishes.
                await _sleep(
                    min(FAST_LANE_FOLLOW_SECONDS, fast.seconds_until_next_due()), slow_done
                )
        finally:
            fast_primed.set()

    async def run_slow(slow: _Lane) -> None:
        nonlocal slow_remaining
        try:
            if not continuous:
                await fast_primed.wait()
            while not stopped():
                worked = await slow.run_pass()
                if worked or slow.has_due_work():
                    continue
                if not continuous:
                    return
                await _sleep(slow.seconds_until_next_due(), stop_event)
        finally:
            slow_remaining -= 1
            if slow_remaining == 0:
                slow_done.set()

    await asyncio.gather(run_fast(), *(run_slow(slow) for slow in slow_lanes))
    summary.duration_ms = round((clock() - started) * 1000)
    return summary
