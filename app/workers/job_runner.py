"""Consolidated background job runner.

Every queue in this application is a durable MongoDB collection with leases, attempt limits and
duplicate guards. The runner therefore only decides *when* to call each queue's existing
"process one item" function; it never holds job state itself. Stopping it at any point is
equivalent to a crash that the queues already recover from when their leases expire.

Work is split into two lanes that run concurrently:

* the fast lane (routine clock and push delivery) never waits behind slow work, so a long AI
  generation cannot delay notifications or the materialization of due routines;
* the slow lane (routine runs, mediation AI, image processing) handles one item at a time,
  round-robin across queues so that no queue starves another.

The same logic runs in two modes. Finite mode drains available work and returns before a deadline
(serverless invocations, one-off commands). Continuous mode polls until a stop event is set
(local development, Heroku, in-process web workers).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.core.logging import get_logger

logger = get_logger(__name__)

# Time kept free at the end of a finite run so the process can report before its hard limit.
DEADLINE_MARGIN_SECONDS = 5.0
# How often an idle fast lane checks for push work while the slow lane is still producing it.
FAST_LANE_FOLLOW_SECONDS = 1.0


class JobKind(StrEnum):
    CLOCK = "clock"
    PUSH = "push"
    ROUTINE = "routine"
    MEDIATION = "mediation"
    IMAGE = "image"


FAST_KINDS = frozenset({JobKind.CLOCK, JobKind.PUSH})


@dataclass(frozen=True)
class JobHandler:
    """One durable queue.

    ``process_one`` claims and processes at most one item and returns whether it found work.
    ``timeout_seconds`` must stay below the queue's lease so a cancelled item is retried by the
    next runner instead of overlapping with a still-running one. ``idle_interval_seconds`` is the
    pause before polling an empty queue again.
    """

    kind: JobKind
    process_one: Callable[[], Awaitable[bool]]
    timeout_seconds: float
    idle_interval_seconds: float


@dataclass
class JobRunSummary:
    processed: dict[str, int] = field(default_factory=dict)
    timed_out: dict[str, int] = field(default_factory=dict)
    failed: dict[str, int] = field(default_factory=dict)

    def count(self, bucket: dict[str, int], kind: JobKind) -> None:
        bucket[kind.value] = bucket.get(kind.value, 0) + 1

    def as_log_fields(self) -> dict[str, dict[str, int]]:
        return {"processed": self.processed, "timed_out": self.timed_out, "failed": self.failed}


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

    async def _run_one(self, handler: JobHandler) -> bool:
        try:
            worked = await asyncio.wait_for(handler.process_one(), handler.timeout_seconds)
        except TimeoutError:
            # The item's lease outlives this timeout, so another run retries it safely.
            logger.warning("Background job timed out", extra={"job_kind": handler.kind.value})
            self._summary.count(self._summary.timed_out, handler.kind)
            return True
        except Exception as exc:
            logger.exception(
                "Background job failed",
                extra={"job_kind": handler.kind.value, "error_type": type(exc).__name__},
            )
            self._summary.count(self._summary.failed, handler.kind)
            return False
        if worked:
            self._summary.count(self._summary.processed, handler.kind)
        return worked

    async def run_pass(self) -> bool:
        """Give every due handler one turn; return whether any of them found work."""
        worked_any = False
        for handler in self._handlers:
            if self._clock() < self._next_due[handler.kind] or not self._fits_deadline(handler):
                continue
            worked = await self._run_one(handler)
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


async def _sleep(seconds: float, stop_event: asyncio.Event | None) -> None:
    if seconds <= 0:
        await asyncio.sleep(0)
        return
    if stop_event is None:
        await asyncio.sleep(seconds)
        return
    try:
        await asyncio.wait_for(stop_event.wait(), seconds)
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
    summary = JobRunSummary()
    fast = _Lane(
        [h for h in handlers if h.kind in FAST_KINDS],
        deadline=deadline,
        summary=summary,
        clock=clock,
    )
    slow = _Lane(
        [h for h in handlers if h.kind not in FAST_KINDS],
        deadline=deadline,
        summary=summary,
        clock=clock,
    )
    slow_done = asyncio.Event()
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
                # Due routines are materialized before the slow lane looks for runs.
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
                    # Pick up pushes that the slow lane created after the previous pass.
                    fast.make_all_due()
                    final_pass_done = True
                    continue
                # Keep delivering pushes that slow work produces while it is still running, and
                # do the final pass as soon as the slow lane finishes.
                await _sleep(
                    min(FAST_LANE_FOLLOW_SECONDS, fast.seconds_until_next_due()), slow_done
                )
        finally:
            fast_primed.set()

    async def run_slow() -> None:
        try:
            if slow.empty:
                return
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
            slow_done.set()

    await asyncio.gather(run_fast(), run_slow())
    return summary
