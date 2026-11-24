import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable

import pytest

from app.workers import job_runner
from app.workers.job_runner import JobHandler, JobKind, run_jobs


@pytest.fixture(autouse=True)
def fast_timings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_runner, "DEADLINE_MARGIN_SECONDS", 0.01)
    monkeypatch.setattr(job_runner, "FAST_LANE_FOLLOW_SECONDS", 0.01)


class FakeQueue:
    """An in-memory queue whose claim is atomic, like a MongoDB find_one_and_update."""

    def __init__(self, items: list[str] | None = None) -> None:
        self.items: deque[str] = deque(items or [])
        self.done: list[str] = []
        self.calls = 0

    def handler(
        self,
        kind: JobKind,
        *,
        work: Callable[[str], Awaitable[None]] | None = None,
        timeout: float = 1.0,
        idle: float = 0.05,
    ) -> JobHandler:
        async def process_one() -> bool:
            self.calls += 1
            if not self.items:
                return False
            item = self.items.popleft()
            if work:
                await work(item)
            self.done.append(item)
            return True

        return JobHandler(
            kind=kind, process_one=process_one, timeout_seconds=timeout, idle_interval_seconds=idle
        )


def soon(seconds: float = 5.0) -> float:
    return time.monotonic() + seconds


@pytest.mark.asyncio
async def test_finite_run_drains_every_queue_and_returns() -> None:
    queues = {kind: FakeQueue([f"{kind.value}-{i}" for i in range(3)]) for kind in JobKind}

    summary = await run_jobs([q.handler(kind) for kind, q in queues.items()], deadline=soon())

    assert all(len(q.done) == 3 and not q.items for q in queues.values())
    assert summary.processed == {kind.value: 3 for kind in JobKind}
    assert not summary.timed_out and not summary.failed


@pytest.mark.asyncio
async def test_push_is_not_delayed_by_long_running_slow_job() -> None:
    push = FakeQueue()
    delivered_at: dict[str, float] = {}
    finished_at: dict[str, float] = {}

    async def long_generation(item: str) -> None:
        # The routine output is committed (and its push queued) early in a long job.
        push.items.append("push-for-" + item)
        await asyncio.sleep(0.5)
        finished_at[item] = time.monotonic()

    async def deliver(item: str) -> None:
        delivered_at[item] = time.monotonic()

    routine = FakeQueue(["routine-1"])
    await run_jobs(
        [
            routine.handler(JobKind.ROUTINE, work=long_generation),
            push.handler(JobKind.PUSH, work=deliver),
        ],
        deadline=soon(),
    )

    assert delivered_at["push-for-routine-1"] < finished_at["routine-1"]


@pytest.mark.asyncio
async def test_push_created_as_slow_work_finishes_is_delivered_before_returning() -> None:
    push = FakeQueue()

    async def enqueue_push_at_end(item: str) -> None:
        await asyncio.sleep(0.05)
        push.items.append("push-for-" + item)

    routine = FakeQueue(["routine-1"])
    await run_jobs(
        [
            routine.handler(JobKind.ROUTINE, work=enqueue_push_at_end),
            # A long idle interval would normally postpone the next push poll.
            push.handler(JobKind.PUSH, idle=30.0),
        ],
        deadline=soon(),
    )

    assert push.done == ["push-for-routine-1"]


@pytest.mark.asyncio
async def test_clock_materializes_runs_before_slow_lane_looks_for_them() -> None:
    routine = FakeQueue()
    clock = FakeQueue(["tick"])

    async def materialize(_item: str) -> None:
        routine.items.append("due-run")

    await run_jobs(
        [
            routine.handler(JobKind.ROUTINE),
            clock.handler(JobKind.CLOCK, work=materialize, idle=30.0),
        ],
        deadline=soon(),
    )

    assert routine.done == ["due-run"]


@pytest.mark.asyncio
async def test_slow_queues_take_turns() -> None:
    order: list[str] = []

    def record(item: str) -> Awaitable[None]:
        order.append(item)
        return asyncio.sleep(0)

    mediation = FakeQueue(["m1", "m2"])
    image = FakeQueue(["i1", "i2"])
    await run_jobs(
        [
            mediation.handler(JobKind.MEDIATION, work=record),
            image.handler(JobKind.IMAGE, work=record),
        ],
        deadline=soon(),
    )

    assert order == ["m1", "i1", "m2", "i2"]


@pytest.mark.asyncio
async def test_hung_item_is_cancelled_at_its_timeout_and_the_run_continues() -> None:
    async def hang(item: str) -> None:
        if item == "stuck":
            await asyncio.sleep(10)

    mediation = FakeQueue(["stuck", "next"])
    started = time.monotonic()
    summary = await run_jobs(
        [mediation.handler(JobKind.MEDIATION, work=hang, timeout=0.1)], deadline=soon()
    )

    assert time.monotonic() - started < 2
    assert summary.timed_out == {"mediation": 1}
    assert mediation.done == ["next"]


@pytest.mark.asyncio
async def test_items_that_cannot_finish_before_the_deadline_are_not_claimed() -> None:
    routine = FakeQueue(["too-long"])

    await run_jobs([routine.handler(JobKind.ROUTINE, timeout=10.0)], deadline=soon(1.0))

    assert routine.calls == 0
    assert routine.items == deque(["too-long"])


@pytest.mark.asyncio
async def test_failing_queue_backs_off_instead_of_spinning() -> None:
    calls = 0

    async def broken() -> bool:
        nonlocal calls
        calls += 1
        raise RuntimeError("database unavailable")

    stop = asyncio.Event()
    runner = asyncio.create_task(
        run_jobs(
            [JobHandler(JobKind.PUSH, broken, timeout_seconds=1, idle_interval_seconds=0.1)],
            continuous=True,
            stop_event=stop,
        )
    )
    await asyncio.sleep(0.35)
    stop.set()
    summary = await runner

    assert 2 <= calls <= 5
    assert summary.failed["push"] == calls


@pytest.mark.asyncio
async def test_continuous_mode_keeps_polling_until_stopped() -> None:
    push = FakeQueue()
    stop = asyncio.Event()
    runner = asyncio.create_task(
        run_jobs([push.handler(JobKind.PUSH, idle=0.02)], continuous=True, stop_event=stop)
    )

    await asyncio.sleep(0.05)
    push.items.append("late-push")
    await asyncio.sleep(0.1)
    stop.set()
    await asyncio.wait_for(runner, 1)

    assert push.done == ["late-push"]


@pytest.mark.asyncio
async def test_concurrent_runners_process_each_item_once() -> None:
    queue = FakeQueue([f"item-{i}" for i in range(20)])

    async def slow(_item: str) -> None:
        await asyncio.sleep(0.005)

    await asyncio.gather(
        run_jobs([queue.handler(JobKind.MEDIATION, work=slow)], deadline=soon()),
        run_jobs([queue.handler(JobKind.MEDIATION, work=slow)], deadline=soon()),
    )

    assert sorted(queue.done) == sorted(f"item-{i}" for i in range(20))


@pytest.mark.asyncio
async def test_finite_runs_require_a_deadline() -> None:
    with pytest.raises(ValueError):
        await run_jobs([])


@pytest.mark.asyncio
async def test_empty_handler_list_returns_immediately() -> None:
    summary = await asyncio.wait_for(run_jobs([], deadline=soon()), 1)

    assert summary.processed == {}
