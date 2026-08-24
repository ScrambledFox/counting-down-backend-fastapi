import asyncio
from datetime import datetime

from app.core import logging
from app.core.config import get_settings
from app.db.mongo_client import get_db
from app.repositories.xiaobao import (
    XiaoBaoConversationRepository,
    XiaoBaoMessageRepository,
    ensure_xiaobao_indexes,
)
from app.repositories.xiaobao_routine import (
    XiaoBaoRoutineRepository,
    XiaoBaoRoutineRunRepository,
    ensure_xiaobao_routine_indexes,
)
from app.schemas.v1.xiaobao_routine import (
    XiaoBaoRoutineFrequency,
    XiaoBaoRoutineRun,
    XiaoBaoRoutineRunStatus,
)
from app.services.xiaobao_routine_policy import XIAOBAO_ROUTINE_UNREAD_INACTIVITY_THRESHOLD
from app.services.xiaobao_schedule import local_schedule_snapshot, next_scheduled_at
from app.util.time import utc_now

settings = get_settings()
logger = logging.get_logger(__name__)


async def materialize_due_routines(
    routines: XiaoBaoRoutineRepository,
    runs: XiaoBaoRoutineRunRepository,
    *,
    now: datetime | None = None,
    excluded_routine_ids: set[str] | None = None,
) -> int:
    now = now or utc_now()
    excluded_routine_ids = excluded_routine_ids or set()
    due = await routines.list_due(now, limit=settings.xiaobao_routine_materialize_batch_size)
    materialized = 0
    for routine in due:
        if not routine.id or str(routine.id) in excluded_routine_ids:
            continue
        scheduled_for = routine.next_run_at
        await runs.materialize(
            XiaoBaoRoutineRun(
                routine_id=str(routine.id),
                owner_user_type=routine.owner_user_type,
                status=XiaoBaoRoutineRunStatus.PENDING,
                scheduled_for=scheduled_for,
                local_scheduled_at=local_schedule_snapshot(
                    scheduled_for, routine.schedule.timezone
                ),
                timezone_snapshot=routine.schedule.timezone,
                available_at=now,
                routine_revision=routine.revision,
                created_at=now,
                updated_at=now,
            )
        )
        # A one-time schedule is consumed after its unique run is materialized. It deliberately
        # stays enabled at the same revision until that run has passed the delivery guard.
        # Recurring schedules skip missed intervals rather than creating a catch-up burst.
        next_run = (
            None
            if routine.schedule.frequency == XiaoBaoRoutineFrequency.ONCE
            else next_scheduled_at(routine.schedule, after=max(now, scheduled_for))
        )
        if await routines.advance_if_due(str(routine.id), scheduled_for, next_run):
            materialized += 1
    return materialized


async def auto_pause_unread_inactive_routines(
    routines: XiaoBaoRoutineRepository,
    runs: XiaoBaoRoutineRunRepository,
    conversations: XiaoBaoConversationRepository,
    messages: XiaoBaoMessageRepository,
    *,
    now: datetime,
) -> set[str]:
    threshold = now - XIAOBAO_ROUTINE_UNREAD_INACTIVITY_THRESHOLD
    qualifying_routine_ids: set[str] = set()
    inboxes = {}
    for routine in await routines.list_active():
        if not routine.id:
            continue
        if routine.owner_user_type not in inboxes:
            inboxes[routine.owner_user_type] = await conversations.get_inbox(
                routine.owner_user_type
            )
        inbox = inboxes[routine.owner_user_type]
        if not inbox or not inbox.id:
            continue
        qualifies = await messages.has_unread_routine_output_at_or_before(
            str(routine.id),
            str(inbox.id),
            threshold=threshold,
        )
        if not qualifies:
            continue
        # Re-check immediately before the routine CAS. This lookup is the cross-collection
        # decision point: a read committed before it prevents pausing; a concurrent read after
        # it does not undo the observed inactivity decision.
        qualifies = await messages.has_unread_routine_output_at_or_before(
            str(routine.id),
            str(inbox.id),
            threshold=threshold,
        )
        if not qualifies:
            continue
        routine_id = str(routine.id)
        qualifying_routine_ids.add(routine_id)
        paused = await routines.auto_pause_for_unread_inactivity(
            routine_id,
            routine.owner_user_type,
            revision=routine.revision,
        )
        if paused:
            await runs.cancel_pending_for_routine(routine_id)
    return qualifying_routine_ids


async def process_xiaobao_routine_clock_iteration(
    routines: XiaoBaoRoutineRepository,
    runs: XiaoBaoRoutineRunRepository,
    conversations: XiaoBaoConversationRepository,
    messages: XiaoBaoMessageRepository,
) -> int:
    now = utc_now()
    qualifying_routine_ids = await auto_pause_unread_inactive_routines(
        routines,
        runs,
        conversations,
        messages,
        now=now,
    )
    return await materialize_due_routines(
        routines,
        runs,
        now=now,
        excluded_routine_ids=qualifying_routine_ids,
    )


async def run_xiaobao_routine_clock(stop_event: asyncio.Event | None = None) -> None:
    db = get_db()
    await ensure_xiaobao_indexes(db)
    await ensure_xiaobao_routine_indexes(db)
    routines = XiaoBaoRoutineRepository(db)
    runs = XiaoBaoRoutineRunRepository(db)
    conversations = XiaoBaoConversationRepository(db)
    messages = XiaoBaoMessageRepository(db)
    while stop_event is None or not stop_event.is_set():
        try:
            await process_xiaobao_routine_clock_iteration(routines, runs, conversations, messages)
        except Exception:
            logger.exception("Xiao Bao routine clock iteration failed")
        await asyncio.sleep(settings.xiaobao_routine_clock_poll_interval_seconds)


if __name__ == "__main__":
    asyncio.run(run_xiaobao_routine_clock())
