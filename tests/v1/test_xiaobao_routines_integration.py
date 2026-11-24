from collections.abc import AsyncGenerator
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from bson import ObjectId

from app.core.config import get_settings
from app.db.mongo_client import get_test_db
from app.models.mongo import AsyncDB
from app.repositories.xiaobao import (
    XiaoBaoConversationRepository,
    XiaoBaoMessageRepository,
    XiaoBaoProposalRepository,
    ensure_xiaobao_indexes,
)
from app.repositories.xiaobao_routine import (
    XiaoBaoRoutineRepository,
    XiaoBaoRoutineRunRepository,
    ensure_xiaobao_routine_indexes,
)
from app.schemas.v1.exceptions import BadRequestException, ConflictException, NotFoundException
from app.schemas.v1.user import UserType
from app.schemas.v1.xiaobao import (
    XiaoBaoConversationPurpose,
    XiaoBaoMessage,
    XiaoBaoMessageRole,
    XiaoBaoMessageSource,
    XiaoBaoMessageStatus,
    XiaoBaoProposal,
    XiaoBaoProposalType,
)
from app.schemas.v1.xiaobao_routine import (
    XiaoBaoRoutine,
    XiaoBaoRoutineContextProfile,
    XiaoBaoRoutineFrequency,
    XiaoBaoRoutineKind,
    XiaoBaoRoutinePauseReason,
    XiaoBaoRoutineRun,
    XiaoBaoRoutineRunStatus,
    XiaoBaoRoutineSchedule,
)
from app.services.xiaobao_routine import XiaoBaoRoutineService
from app.services.xiaobao_routine_execution import XiaoBaoRoutineExecutionService
from app.services.xiaobao_routine_policy import XIAOBAO_ROUTINE_UNREAD_INACTIVITY_THRESHOLD
from app.util.time import utc_now
from app.workers.xiaobao_routine_clock import process_xiaobao_routine_clock_iteration
from app.workers.xiaobao_routine_worker import process_one_xiaobao_routine_work_item

settings = get_settings()


@pytest_asyncio.fixture
async def routine_test_db() -> AsyncGenerator[AsyncDB]:
    db = get_test_db()
    await db[settings.xiaobao_routine_runs_collection_name].delete_many({})
    await db[settings.xiaobao_routines_collection_name].delete_many({})
    await db[settings.xiaobao_messages_collection_name].delete_many({})
    await db[settings.xiaobao_conversations_collection_name].delete_many({})
    await db[settings.xiaobao_proposals_collection_name].delete_many({})
    await ensure_xiaobao_indexes(db)
    await ensure_xiaobao_routine_indexes(db)
    yield db
    await db[settings.xiaobao_routine_runs_collection_name].delete_many({})
    await db[settings.xiaobao_routines_collection_name].delete_many({})
    await db[settings.xiaobao_messages_collection_name].delete_many({})
    await db[settings.xiaobao_conversations_collection_name].delete_many({})
    await db[settings.xiaobao_proposals_collection_name].delete_many({})


@pytest.mark.asyncio
async def test_legacy_chat_lookup_and_delete_exclude_routine_inbox(
    routine_test_db: AsyncDB,
) -> None:
    collection = routine_test_db[settings.xiaobao_conversations_collection_name]
    now = utc_now()
    legacy_id = ObjectId()
    inbox_id = ObjectId()
    await collection.insert_many(
        [
            {
                "_id": legacy_id,
                "owner_user_type": UserType.JORIS,
                "title": "Legacy chat",
                "created_at": now,
                "updated_at": now,
            },
            {
                "_id": inbox_id,
                "owner_user_type": UserType.JORIS,
                "purpose": XiaoBaoConversationPurpose.ROUTINE_INBOX,
                "title": "Routines inbox",
                "created_at": now,
                "updated_at": now,
            },
        ]
    )
    conversations = XiaoBaoConversationRepository(routine_test_db)

    listed = await conversations.list_owned(UserType.JORIS, limit=20)

    assert [item.id for item in listed] == [str(legacy_id)]
    assert await conversations.get_owned(
        str(legacy_id), UserType.JORIS, XiaoBaoConversationPurpose.CHAT
    )
    assert (
        await conversations.get_owned(
            str(inbox_id), UserType.JORIS, XiaoBaoConversationPurpose.CHAT
        )
        is None
    )
    assert not await conversations.delete_owned(str(inbox_id), UserType.JORIS)
    assert await collection.find_one({"_id": inbox_id}) is not None
    assert await conversations.delete_owned(str(legacy_id), UserType.JORIS)


@pytest.mark.asyncio
async def test_one_time_local_date_is_bson_safe_for_proposal_and_routine_records(
    routine_test_db: AsyncDB,
) -> None:
    now = utc_now()
    schedule = XiaoBaoRoutineSchedule(
        frequency=XiaoBaoRoutineFrequency.ONCE,
        local_date=date(2026, 8, 28),
        local_time="12:00",
        timezone="Europe/Amsterdam",
    )
    payload = {
        "kind": XiaoBaoRoutineKind.REMINDER,
        "name": "Synthetic reminder",
        "message": "Watch a synthetic movie.",
        "schedule": schedule,
        "context_profile": XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
    }
    proposal = await XiaoBaoProposalRepository(routine_test_db).create(
        XiaoBaoProposal(
            conversation_id=str(ObjectId()),
            message_id=str(ObjectId()),
            owner_user_type=UserType.JORIS,
            type=XiaoBaoProposalType.REMINDER,
            payload=payload,
            created_at=now,
            updated_at=now,
        )
    )
    routine = await XiaoBaoRoutineRepository(routine_test_db).create(
        XiaoBaoRoutine(
            owner_user_type=UserType.JORIS,
            kind=XiaoBaoRoutineKind.REMINDER,
            name="Synthetic reminder",
            message="Watch a synthetic movie.",
            schedule=schedule,
            context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
            next_run_at=now + timedelta(days=1),
            created_at=now,
            updated_at=now,
        )
    )

    assert proposal.payload.schedule.local_date == date(2026, 8, 28)
    assert routine.schedule.local_date == date(2026, 8, 28)


@pytest.mark.asyncio
async def test_materialization_and_claim_are_idempotent_and_owner_scoped(
    routine_test_db: AsyncDB,
) -> None:
    routines = XiaoBaoRoutineRepository(routine_test_db)
    runs = XiaoBaoRoutineRunRepository(routine_test_db)
    now = utc_now()
    routine = await routines.create(
        XiaoBaoRoutine(
            owner_user_type=UserType.JORIS,
            name="Morning idea",
            instruction="Give me one small idea",
            schedule=XiaoBaoRoutineSchedule(
                frequency=XiaoBaoRoutineFrequency.DAILY,
                local_time="09:00",
                timezone="Europe/Amsterdam",
            ),
            context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
            next_run_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    assert routine.id
    pending = XiaoBaoRoutineRun(
        routine_id=str(routine.id),
        owner_user_type=UserType.JORIS,
        status=XiaoBaoRoutineRunStatus.PENDING,
        scheduled_for=now,
        local_scheduled_at=now.isoformat(timespec="minutes"),
        timezone_snapshot="Europe/Amsterdam",
        available_at=now,
        created_at=now,
        updated_at=now,
    )

    first = await runs.materialize(pending)
    second = await runs.materialize(pending)
    claimed = await runs.claim_next(lease_seconds=300)
    no_second_claim = await runs.claim_next(lease_seconds=300)

    assert first.id == second.id
    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.status == XiaoBaoRoutineRunStatus.PROCESSING
    assert claimed.attempt_count == 1
    assert no_second_claim is None
    assert await routines.list_owned(UserType.DANFENG) == []

    completed = await runs.mark_completed(
        str(claimed.id),
        claimed.lease_token or "",
        output_message_id="64a7f0c2f1d2c4b5a6e7d8f9",
        model="test-model",
        input_tokens=10,
        output_tokens=5,
    )
    assert completed is not None
    assert completed.status == XiaoBaoRoutineRunStatus.COMPLETED
    assert completed.lease_token is None
    assert completed.completed_at is not None

    # A completed occurrence remains unique even if the clock sees it again after a crash.
    duplicate = pending.model_copy(update={"available_at": now + timedelta(hours=1)})
    rematerialized = await runs.materialize(duplicate)
    assert rematerialized.id == completed.id
    assert rematerialized.status == XiaoBaoRoutineRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_pause_and_resume_invalidate_an_already_claimed_revision(
    routine_test_db: AsyncDB,
) -> None:
    routines = XiaoBaoRoutineRepository(routine_test_db)
    now = utc_now()
    created = await routines.create(
        XiaoBaoRoutine(
            owner_user_type=UserType.JORIS,
            name="Morning idea",
            instruction="Give me one small idea",
            schedule=XiaoBaoRoutineSchedule(
                frequency=XiaoBaoRoutineFrequency.DAILY,
                local_time="09:00",
                timezone="Europe/Amsterdam",
            ),
            context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
            next_run_at=now,
            revision=1,
            created_at=now,
            updated_at=now,
        )
    )
    assert created.id

    paused = await routines.pause_owned(str(created.id), UserType.JORIS)
    assert paused is not None
    assert paused.enabled is False
    assert paused.revision == 2
    assert paused.pause_reason == XiaoBaoRoutinePauseReason.MANUAL
    assert paused.paused_at is not None

    resumed = await routines.resume_owned(str(created.id), UserType.JORIS, now + timedelta(days=1))
    assert resumed is not None
    assert resumed.enabled is True
    assert resumed.revision == 3
    assert resumed.pause_reason is None
    assert resumed.paused_at is None

    assert not await routines.reserve_delivery(
        str(created.id),
        UserType.JORIS,
        revision=1,
        run_id="64a7f0c2f1d2c4b5a6e7d8f8",
        expires_at=now + timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_staged_delivery_is_invisible_until_durable_commit(
    routine_test_db: AsyncDB,
) -> None:
    routines = XiaoBaoRoutineRepository(routine_test_db)
    runs = XiaoBaoRoutineRunRepository(routine_test_db)
    conversations = XiaoBaoConversationRepository(routine_test_db)
    messages = XiaoBaoMessageRepository(routine_test_db)
    now = utc_now()
    routine = await routines.create(
        XiaoBaoRoutine(
            owner_user_type=UserType.JORIS,
            name="Morning idea",
            instruction="Give me one small idea",
            schedule=XiaoBaoRoutineSchedule(
                frequency=XiaoBaoRoutineFrequency.DAILY,
                local_time="09:00",
                timezone="Europe/Amsterdam",
            ),
            context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
            next_run_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    inbox = await conversations.get_or_create_inbox(UserType.JORIS)
    assert routine.id and inbox.id
    materialized = await runs.materialize(
        XiaoBaoRoutineRun(
            routine_id=str(routine.id),
            owner_user_type=UserType.JORIS,
            status=XiaoBaoRoutineRunStatus.PENDING,
            scheduled_for=now,
            local_scheduled_at=now.isoformat(timespec="minutes"),
            timezone_snapshot="Europe/Amsterdam",
            available_at=now,
            routine_revision=routine.revision,
            created_at=now,
            updated_at=now,
        )
    )
    claimed = await runs.claim_next(lease_seconds=300)
    assert claimed is not None and claimed.id == materialized.id
    run_id = str(claimed.id)
    assert await routines.reserve_delivery(
        str(routine.id),
        UserType.JORIS,
        revision=routine.revision,
        run_id=run_id,
        expires_at=now + timedelta(minutes=5),
    )
    staged = await messages.stage_routine_output(
        XiaoBaoMessage(
            conversation_id=str(inbox.id),
            role=XiaoBaoMessageRole.ASSISTANT,
            status=XiaoBaoMessageStatus.PENDING_DELIVERY,
            source=XiaoBaoMessageSource.ROUTINE,
            content="A private idea",
            routine_id=str(routine.id),
            routine_run_id=run_id,
            created_at=now,
            updated_at=now,
        )
    )
    assert staged.id
    assert "delivery_cleanup_at" not in staged.model_dump()

    hidden, _ = await messages.list_routine_inbox(str(inbox.id), limit=10)
    assert hidden == []
    assert await messages.count_unread_for_conversation(str(inbox.id)) == 0

    assert await routines.commit_delivery(
        str(routine.id),
        UserType.JORIS,
        revision=routine.revision,
        run_id=run_id,
    )
    paused = await routines.pause_owned(str(routine.id), UserType.JORIS)
    assert paused is not None and not paused.enabled
    # The durable marker remains authoritative after arbitrary downtime and state changes.
    assert await routines.commit_delivery(
        str(routine.id),
        UserType.JORIS,
        revision=routine.revision,
        run_id=run_id,
    )
    service = XiaoBaoRoutineExecutionService(
        routines,
        runs,
        conversations,
        messages,
        SimpleNamespace(),
        SimpleNamespace(),
    )
    await service.process(claimed)

    inbox_messages, _ = await messages.list_routine_inbox(str(inbox.id), limit=10)
    assert [item.content for item in inbox_messages] == ["A private idea"]
    assert await messages.count_unread_for_conversation(str(inbox.id)) == 1
    history, _ = await runs.list_owned(str(routine.id), UserType.JORIS, limit=10)
    assert history[0].status == XiaoBaoRoutineRunStatus.COMPLETED
    assert history[0].output_message_id == str(staged.id)
    repaired_routine = await routines.get_for_execution(str(routine.id))
    assert repaired_routine is not None
    assert repaired_routine.last_committed_delivery_run_id == run_id
    assert repaired_routine.committed_delivery_pending_run_id is None


@pytest.mark.asyncio
async def test_duplicate_worker_repairs_committed_delivery_and_completes_current_lease(
    routine_test_db: AsyncDB,
) -> None:
    routines = XiaoBaoRoutineRepository(routine_test_db)
    runs = XiaoBaoRoutineRunRepository(routine_test_db)
    conversations = XiaoBaoConversationRepository(routine_test_db)
    messages = XiaoBaoMessageRepository(routine_test_db)
    now = utc_now()
    routine = await routines.create(
        XiaoBaoRoutine(
            owner_user_type=UserType.JORIS,
            name="Morning idea",
            instruction="Give me one small idea",
            schedule=XiaoBaoRoutineSchedule(
                frequency=XiaoBaoRoutineFrequency.DAILY,
                local_time="09:00",
                timezone="Europe/Amsterdam",
            ),
            context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
            next_run_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    assert routine.id
    materialized = await runs.materialize(
        XiaoBaoRoutineRun(
            routine_id=str(routine.id),
            owner_user_type=UserType.JORIS,
            status=XiaoBaoRoutineRunStatus.PENDING,
            scheduled_for=now,
            local_scheduled_at=now.isoformat(timespec="minutes"),
            timezone_snapshot="Europe/Amsterdam",
            available_at=now,
            routine_revision=routine.revision,
            created_at=now,
            updated_at=now,
        )
    )
    worker_a = await runs.claim_next(lease_seconds=300)
    assert worker_a is not None and worker_a.id == materialized.id
    await routine_test_db[settings.xiaobao_routine_runs_collection_name].update_one(
        {"_id": ObjectId(str(worker_a.id))},
        {"$set": {"lease_expires_at": now - timedelta(seconds=1)}},
    )
    worker_b = await runs.claim_next(lease_seconds=300)
    assert worker_b is not None and worker_b.id == worker_a.id
    assert worker_b.lease_token != worker_a.lease_token

    inbox = await conversations.get_or_create_inbox(UserType.JORIS)
    assert inbox.id
    assert await routines.reserve_delivery(
        str(routine.id),
        UserType.JORIS,
        revision=routine.revision,
        run_id=str(worker_a.id),
        expires_at=now + timedelta(minutes=5),
    )
    staged = await messages.stage_routine_output(
        XiaoBaoMessage(
            conversation_id=str(inbox.id),
            role=XiaoBaoMessageRole.ASSISTANT,
            status=XiaoBaoMessageStatus.PENDING_DELIVERY,
            source=XiaoBaoMessageSource.ROUTINE,
            content="A committed private idea",
            routine_id=str(routine.id),
            routine_run_id=str(worker_a.id),
            created_at=now,
            updated_at=now,
        )
    )
    assert staged.id
    assert await routines.commit_delivery(
        str(routine.id),
        UserType.JORIS,
        revision=routine.revision,
        run_id=str(worker_a.id),
    )
    assert await routines.commit_delivery(
        str(routine.id),
        UserType.JORIS,
        revision=routine.revision,
        run_id=str(worker_a.id),
    )
    assert await messages.finalize_staged_routine_output(str(staged.id)) is not None

    service = XiaoBaoRoutineExecutionService(
        routines,
        runs,
        conversations,
        messages,
        SimpleNamespace(),
        SimpleNamespace(),
    )
    await service.process(worker_b)

    history, _ = await runs.list_owned(str(routine.id), UserType.JORIS, limit=10)
    assert len(history) == 1
    assert history[0].status == XiaoBaoRoutineRunStatus.COMPLETED
    assert history[0].output_message_id == str(staged.id)
    inbox_messages, _ = await messages.list_routine_inbox(str(inbox.id), limit=10)
    assert [item.id for item in inbox_messages] == [staged.id]
    completed_routine = await routines.get_for_execution(str(routine.id))
    assert completed_routine is not None
    assert completed_routine.last_committed_delivery_run_id == str(worker_a.id)
    assert completed_routine.committed_delivery_pending_run_id is None


@pytest.mark.asyncio
async def test_final_attempt_committed_delivery_remains_repairable_after_lease_expiry(
    routine_test_db: AsyncDB,
) -> None:
    routines = XiaoBaoRoutineRepository(routine_test_db)
    runs = XiaoBaoRoutineRunRepository(routine_test_db)
    conversations = XiaoBaoConversationRepository(routine_test_db)
    messages = XiaoBaoMessageRepository(routine_test_db)
    now = utc_now()
    routine = await routines.create(
        XiaoBaoRoutine(
            owner_user_type=UserType.JORIS,
            name="Morning idea",
            instruction="Give me one small idea",
            schedule=XiaoBaoRoutineSchedule(
                frequency=XiaoBaoRoutineFrequency.DAILY,
                local_time="09:00",
                timezone="Europe/Amsterdam",
            ),
            context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
            next_run_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    assert routine.id
    materialized = await runs.materialize(
        XiaoBaoRoutineRun(
            routine_id=str(routine.id),
            owner_user_type=UserType.JORIS,
            status=XiaoBaoRoutineRunStatus.PENDING,
            scheduled_for=now,
            local_scheduled_at=now.isoformat(timespec="minutes"),
            timezone_snapshot="Europe/Amsterdam",
            available_at=now,
            attempt_count=settings.xiaobao_routine_max_attempts - 1,
            routine_revision=routine.revision,
            created_at=now,
            updated_at=now,
        )
    )
    final_attempt = await runs.claim_next(lease_seconds=300)
    assert final_attempt is not None and final_attempt.id == materialized.id
    assert final_attempt.attempt_count == settings.xiaobao_routine_max_attempts
    inbox = await conversations.get_or_create_inbox(UserType.JORIS)
    assert inbox.id
    assert await routines.reserve_delivery(
        str(routine.id),
        UserType.JORIS,
        revision=routine.revision,
        run_id=str(final_attempt.id),
        expires_at=now + timedelta(minutes=5),
    )
    staged = await messages.stage_routine_output(
        XiaoBaoMessage(
            conversation_id=str(inbox.id),
            role=XiaoBaoMessageRole.ASSISTANT,
            status=XiaoBaoMessageStatus.PENDING_DELIVERY,
            source=XiaoBaoMessageSource.ROUTINE,
            content="A final-attempt idea",
            routine_id=str(routine.id),
            routine_run_id=str(final_attempt.id),
            created_at=now,
            updated_at=now,
        )
    )
    assert staged.id
    assert await routines.commit_delivery(
        str(routine.id),
        UserType.JORIS,
        revision=routine.revision,
        run_id=str(final_attempt.id),
    )
    # Simulate the final normal attempt crashing after commit and before finalize/link/release.
    await routine_test_db[settings.xiaobao_routine_runs_collection_name].update_one(
        {"_id": ObjectId(str(final_attempt.id))},
        {"$set": {"lease_expires_at": now - timedelta(seconds=1)}},
    )

    candidates = await routines.list_committed_delivery_repairs(limit=10)
    assert [item.id for item in candidates] == [routine.id]
    repair = await runs.claim_delivery_repair(str(final_attempt.id), lease_seconds=300)
    assert repair is not None
    assert repair.attempt_count == settings.xiaobao_routine_max_attempts
    assert repair.lease_token != final_attempt.lease_token
    service = XiaoBaoRoutineExecutionService(
        routines,
        runs,
        conversations,
        messages,
        SimpleNamespace(),
        SimpleNamespace(),
    )
    await service.repair_committed_delivery(repair)

    history, _ = await runs.list_owned(str(routine.id), UserType.JORIS, limit=10)
    assert history[0].status == XiaoBaoRoutineRunStatus.COMPLETED
    assert history[0].output_message_id == str(staged.id)
    repaired_routine = await routines.get_for_execution(str(routine.id))
    assert repaired_routine is not None
    assert repaired_routine.committed_delivery_pending_run_id is None
    inbox_messages, _ = await messages.list_routine_inbox(str(inbox.id), limit=10)
    assert [item.id for item in inbox_messages] == [staged.id]

    # Releasing the repair barrier allows a later run to reserve its own delivery.
    assert await routines.reserve_delivery(
        str(routine.id),
        UserType.JORIS,
        revision=routine.revision,
        run_id="64a7f0c2f1d2c4b5a6e7d8fa",
        expires_at=now + timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_guarded_repair_backoff_does_not_block_unrelated_routine(
    routine_test_db: AsyncDB,
) -> None:
    routines = XiaoBaoRoutineRepository(routine_test_db)
    runs = XiaoBaoRoutineRunRepository(routine_test_db)
    now = utc_now()
    schedule = XiaoBaoRoutineSchedule(
        frequency=XiaoBaoRoutineFrequency.DAILY,
        local_time="09:00",
        timezone="Europe/Amsterdam",
    )
    routine_a = await routines.create(
        XiaoBaoRoutine(
            owner_user_type=UserType.JORIS,
            name="Guarded A",
            instruction="Idea A",
            schedule=schedule,
            context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
            next_run_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    routine_b = await routines.create(
        XiaoBaoRoutine(
            owner_user_type=UserType.DANFENG,
            name="Runnable B",
            instruction="Idea B",
            schedule=schedule,
            context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
            next_run_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    assert routine_a.id and routine_b.id
    run_a = await runs.materialize(
        XiaoBaoRoutineRun(
            routine_id=str(routine_a.id),
            owner_user_type=UserType.JORIS,
            status=XiaoBaoRoutineRunStatus.FAILED,
            scheduled_for=now,
            local_scheduled_at=now.isoformat(timespec="minutes"),
            timezone_snapshot="Europe/Amsterdam",
            available_at=now + timedelta(hours=1),
            attempt_count=settings.xiaobao_routine_max_attempts,
            routine_revision=routine_a.revision,
            created_at=now,
            updated_at=now,
        )
    )
    assert run_a.id
    assert await routines.reserve_delivery(
        str(routine_a.id),
        UserType.JORIS,
        revision=routine_a.revision,
        run_id=str(run_a.id),
        expires_at=now + timedelta(minutes=5),
    )
    # Deliberately create the durable marker without a staged message to model corruption.
    assert await routines.commit_delivery(
        str(routine_a.id),
        UserType.JORIS,
        revision=routine_a.revision,
        run_id=str(run_a.id),
    )
    stale_guarded = await runs.materialize(
        XiaoBaoRoutineRun(
            routine_id=str(routine_a.id),
            owner_user_type=UserType.JORIS,
            status=XiaoBaoRoutineRunStatus.PROCESSING,
            scheduled_for=now + timedelta(minutes=1),
            local_scheduled_at=(now + timedelta(minutes=1)).isoformat(timespec="minutes"),
            timezone_snapshot="Europe/Amsterdam",
            available_at=now,
            attempt_count=settings.xiaobao_routine_max_attempts,
            lease_token="expired-guarded-lease",
            lease_expires_at=now - timedelta(seconds=1),
            routine_revision=routine_a.revision,
            created_at=now,
            updated_at=now,
        )
    )
    run_b = await runs.materialize(
        XiaoBaoRoutineRun(
            routine_id=str(routine_b.id),
            owner_user_type=UserType.DANFENG,
            status=XiaoBaoRoutineRunStatus.PENDING,
            scheduled_for=now + timedelta(minutes=2),
            local_scheduled_at=(now + timedelta(minutes=2)).isoformat(timespec="minutes"),
            timezone_snapshot="Europe/Amsterdam",
            available_at=now,
            routine_revision=routine_b.revision,
            created_at=now,
            updated_at=now,
        )
    )
    service = SimpleNamespace(
        repair_committed_delivery=AsyncMock(),
        process=AsyncMock(),
    )

    processed = await process_one_xiaobao_routine_work_item(service, routines, runs)

    assert processed is True
    service.repair_committed_delivery.assert_not_awaited()
    service.process.assert_awaited_once()
    claimed_b = service.process.await_args.args[0]
    assert claimed_b.id == run_b.id
    assert claimed_b.routine_id == str(routine_b.id)
    guarded_history, _ = await runs.list_owned(str(routine_a.id), UserType.JORIS, limit=10)
    by_id = {item.id: item for item in guarded_history}
    assert by_id[run_a.id].status == XiaoBaoRoutineRunStatus.FAILED
    assert by_id[stale_guarded.id].status == XiaoBaoRoutineRunStatus.PROCESSING
    still_guarded = await routines.get_for_execution(str(routine_a.id))
    assert still_guarded is not None
    assert still_guarded.committed_delivery_pending_run_id == str(run_a.id)


@pytest.mark.asyncio
async def test_delivery_timestamp_and_unread_inactivity_boundary(
    routine_test_db: AsyncDB,
) -> None:
    conversations = XiaoBaoConversationRepository(routine_test_db)
    messages = XiaoBaoMessageRepository(routine_test_db)
    inbox = await conversations.get_or_create_inbox(UserType.JORIS)
    assert inbox.id
    now = utc_now()
    threshold = now - XIAOBAO_ROUTINE_UNREAD_INACTIVITY_THRESHOLD

    hidden_routine_id = str(ObjectId())
    hidden = await messages.stage_routine_output(
        XiaoBaoMessage(
            conversation_id=str(inbox.id),
            role=XiaoBaoMessageRole.ASSISTANT,
            status=XiaoBaoMessageStatus.PENDING_DELIVERY,
            source=XiaoBaoMessageSource.ROUTINE,
            content="Hidden for a long time",
            routine_id=hidden_routine_id,
            routine_run_id=str(ObjectId()),
            created_at=now - timedelta(days=20),
            updated_at=now - timedelta(days=20),
        )
    )
    assert hidden.id
    assert not await messages.has_unread_routine_output_at_or_before(
        hidden_routine_id, str(inbox.id), threshold=threshold
    )
    visible = await messages.finalize_staged_routine_output(str(hidden.id))
    assert visible is not None and visible.delivered_at is not None
    first_delivered_at = visible.delivered_at
    replay = await messages.finalize_staged_routine_output(str(hidden.id))
    assert replay is not None and replay.delivered_at == first_delivered_at
    assert not await messages.has_unread_routine_output_at_or_before(
        hidden_routine_id, str(inbox.id), threshold=threshold
    )

    exact_routine_id = str(ObjectId())
    exact = await messages.create_assistant(
        XiaoBaoMessage(
            conversation_id=str(inbox.id),
            role=XiaoBaoMessageRole.ASSISTANT,
            status=XiaoBaoMessageStatus.COMPLETE,
            source=XiaoBaoMessageSource.ROUTINE,
            content="Exactly five days visible",
            routine_id=exact_routine_id,
            delivered_at=threshold,
            created_at=threshold - timedelta(days=1),
            updated_at=threshold,
        )
    )
    assert exact.id
    assert await messages.has_unread_routine_output_at_or_before(
        exact_routine_id, str(inbox.id), threshold=threshold
    )
    assert await messages.mark_routine_message_read(str(exact.id), str(inbox.id))
    assert not await messages.has_unread_routine_output_at_or_before(
        exact_routine_id, str(inbox.id), threshold=threshold
    )

    just_after_routine_id = str(ObjectId())
    await messages.create_assistant(
        XiaoBaoMessage(
            conversation_id=str(inbox.id),
            role=XiaoBaoMessageRole.ASSISTANT,
            status=XiaoBaoMessageStatus.COMPLETE,
            source=XiaoBaoMessageSource.ROUTINE,
            content="Not yet five full days visible",
            routine_id=just_after_routine_id,
            delivered_at=threshold + timedelta(seconds=1),
            created_at=threshold - timedelta(days=1),
            updated_at=threshold,
        )
    )
    assert not await messages.has_unread_routine_output_at_or_before(
        just_after_routine_id, str(inbox.id), threshold=threshold
    )

    legacy_routine_id = str(ObjectId())
    await messages.create_assistant(
        XiaoBaoMessage(
            conversation_id=str(inbox.id),
            role=XiaoBaoMessageRole.ASSISTANT,
            status=XiaoBaoMessageStatus.COMPLETE,
            source=XiaoBaoMessageSource.ROUTINE,
            content="Legacy visible output",
            routine_id=legacy_routine_id,
            created_at=threshold,
            updated_at=threshold,
        )
    )
    assert await messages.has_unread_routine_output_at_or_before(
        legacy_routine_id, str(inbox.id), threshold=threshold
    )


@pytest.mark.asyncio
async def test_clock_auto_pause_is_routine_scoped_and_precedes_materialization(
    routine_test_db: AsyncDB,
) -> None:
    routines = XiaoBaoRoutineRepository(routine_test_db)
    runs = XiaoBaoRoutineRunRepository(routine_test_db)
    conversations = XiaoBaoConversationRepository(routine_test_db)
    messages = XiaoBaoMessageRepository(routine_test_db)
    now = utc_now()
    schedule = XiaoBaoRoutineSchedule(
        frequency=XiaoBaoRoutineFrequency.DAILY,
        local_time="09:00",
        timezone="Europe/Amsterdam",
    )
    routine_a = await routines.create(
        XiaoBaoRoutine(
            owner_user_type=UserType.JORIS,
            name="Unread A",
            instruction="Idea A",
            schedule=schedule,
            context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
            next_run_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    routine_b = await routines.create(
        XiaoBaoRoutine(
            owner_user_type=UserType.DANFENG,
            name="Active B",
            instruction="Idea B",
            schedule=schedule,
            context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
            next_run_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    inbox_a = await conversations.get_or_create_inbox(UserType.JORIS)
    inbox_b = await conversations.get_or_create_inbox(UserType.DANFENG)
    assert routine_a.id and routine_b.id and inbox_a.id and inbox_b.id

    qualifying = await messages.create_assistant(
        XiaoBaoMessage(
            conversation_id=str(inbox_a.id),
            role=XiaoBaoMessageRole.ASSISTANT,
            status=XiaoBaoMessageStatus.COMPLETE,
            source=XiaoBaoMessageSource.ROUTINE,
            content="Unread A output",
            routine_id=str(routine_a.id),
            delivered_at=now - timedelta(days=6),
            created_at=now - timedelta(days=6),
            updated_at=now - timedelta(days=6),
        )
    )
    assert qualifying.id
    # A stale B message in A's inbox must not affect B, whose owner has a different inbox.
    await messages.create_assistant(
        XiaoBaoMessage(
            conversation_id=str(inbox_a.id),
            role=XiaoBaoMessageRole.ASSISTANT,
            status=XiaoBaoMessageStatus.COMPLETE,
            source=XiaoBaoMessageSource.ROUTINE,
            content="Wrong-owner B output",
            routine_id=str(routine_b.id),
            delivered_at=now - timedelta(days=6),
            created_at=now - timedelta(days=6),
            updated_at=now - timedelta(days=6),
        )
    )
    await messages.create_assistant(
        XiaoBaoMessage(
            conversation_id=str(inbox_b.id),
            role=XiaoBaoMessageRole.ASSISTANT,
            status=XiaoBaoMessageStatus.COMPLETE,
            source=XiaoBaoMessageSource.ROUTINE,
            content="Read B output",
            routine_id=str(routine_b.id),
            delivered_at=now - timedelta(days=6),
            read_at=now - timedelta(days=1),
            created_at=now - timedelta(days=6),
            updated_at=now - timedelta(days=1),
        )
    )
    await messages.stage_routine_output(
        XiaoBaoMessage(
            conversation_id=str(inbox_b.id),
            role=XiaoBaoMessageRole.ASSISTANT,
            status=XiaoBaoMessageStatus.PENDING_DELIVERY,
            source=XiaoBaoMessageSource.ROUTINE,
            content="Hidden B output",
            routine_id=str(routine_b.id),
            routine_run_id=str(ObjectId()),
            created_at=now - timedelta(days=20),
            updated_at=now - timedelta(days=20),
        )
    )

    old_run = await runs.materialize(
        XiaoBaoRoutineRun(
            routine_id=str(routine_a.id),
            owner_user_type=UserType.JORIS,
            status=XiaoBaoRoutineRunStatus.PENDING,
            scheduled_for=now - timedelta(minutes=1),
            local_scheduled_at=(now - timedelta(minutes=1)).isoformat(timespec="minutes"),
            timezone_snapshot="Europe/Amsterdam",
            available_at=now - timedelta(minutes=1),
            routine_revision=routine_a.revision,
            created_at=now - timedelta(minutes=1),
            updated_at=now - timedelta(minutes=1),
        )
    )
    claimed = await runs.claim_next(lease_seconds=300)
    assert claimed is not None and claimed.id == old_run.id
    assert await routines.reserve_delivery(
        str(routine_a.id),
        UserType.JORIS,
        revision=routine_a.revision,
        run_id=str(claimed.id),
        expires_at=now + timedelta(minutes=5),
    )
    assert await routines.commit_delivery(
        str(routine_a.id),
        UserType.JORIS,
        revision=routine_a.revision,
        run_id=str(claimed.id),
    )

    materialized = await process_xiaobao_routine_clock_iteration(
        routines, runs, conversations, messages
    )

    assert materialized == 1
    paused_a = await routines.get_for_execution(str(routine_a.id))
    active_b = await routines.get_for_execution(str(routine_b.id))
    assert paused_a is not None and active_b is not None
    assert paused_a.enabled is False
    assert paused_a.pause_reason == XiaoBaoRoutinePauseReason.UNREAD_INACTIVITY
    assert paused_a.paused_at is not None
    assert paused_a.revision == routine_a.revision + 1
    assert paused_a.last_scheduled_for is None
    assert paused_a.next_run_at == routine_a.next_run_at
    assert paused_a.pending_delivery_run_id is None
    assert paused_a.committed_delivery_pending_run_id == str(claimed.id)
    assert active_b.enabled is True
    assert active_b.last_scheduled_for == routine_b.next_run_at
    history_a, _ = await runs.list_owned(str(routine_a.id), UserType.JORIS, limit=10)
    history_b, _ = await runs.list_owned(str(routine_b.id), UserType.DANFENG, limit=10)
    assert [item.id for item in history_a] == [claimed.id]
    assert history_a[0].status == XiaoBaoRoutineRunStatus.PROCESSING
    assert len(history_b) == 1 and history_b[0].status == XiaoBaoRoutineRunStatus.PENDING
    assert not await routines.reserve_delivery(
        str(routine_a.id),
        UserType.JORIS,
        revision=routine_a.revision,
        run_id=str(ObjectId()),
        expires_at=now + timedelta(minutes=5),
    )

    # A second clock pass is idempotent and does not increment the paused routine's revision.
    await process_xiaobao_routine_clock_iteration(routines, runs, conversations, messages)
    paused_again = await routines.get_for_execution(str(routine_a.id))
    assert paused_again is not None and paused_again.revision == paused_a.revision

    service = XiaoBaoRoutineService(routines, runs, conversations, messages)
    repeated_pause = await service.pause(str(routine_a.id), UserType.JORIS)
    assert repeated_pause.pause_reason == XiaoBaoRoutinePauseReason.UNREAD_INACTIVITY
    assert repeated_pause.updated_at == paused_a.updated_at
    with pytest.raises(ConflictException) as exc_info:
        await service.resume(str(routine_a.id), UserType.JORIS)
    assert exc_info.value.status_code == 409
    await messages.mark_routine_message_read(str(qualifying.id), str(inbox_a.id))
    resumed = await service.resume(str(routine_a.id), UserType.JORIS)
    assert resumed.enabled is True
    assert resumed.pause_reason is None
    assert resumed.paused_at is None


@pytest.mark.asyncio
async def test_filtered_inbox_cursor_reaches_old_blocker_without_owner_leakage(
    routine_test_db: AsyncDB,
) -> None:
    routines = XiaoBaoRoutineRepository(routine_test_db)
    runs = XiaoBaoRoutineRunRepository(routine_test_db)
    conversations = XiaoBaoConversationRepository(routine_test_db)
    messages = XiaoBaoMessageRepository(routine_test_db)
    now = utc_now()
    schedule = XiaoBaoRoutineSchedule(
        frequency=XiaoBaoRoutineFrequency.DAILY,
        local_time="09:00",
        timezone="Europe/Amsterdam",
    )

    async def create_routine(owner: UserType, name: str) -> XiaoBaoRoutine:
        return await routines.create(
            XiaoBaoRoutine(
                owner_user_type=owner,
                name=name,
                instruction=f"Instruction for {name}",
                schedule=schedule,
                context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
                next_run_at=now + timedelta(days=1),
                created_at=now,
                updated_at=now,
            )
        )

    target = await create_routine(UserType.JORIS, "Target")
    other = await create_routine(UserType.JORIS, "Other")
    wrong_owner = await create_routine(UserType.DANFENG, "Private")
    inbox = await conversations.get_or_create_inbox(UserType.JORIS)
    assert target.id and other.id and wrong_owner.id and inbox.id

    docs = []
    target_ids: list[str] = []
    base_created_at = now - timedelta(days=10)
    for index in range(61):
        # Pairs share a timestamp so pagination must use the ObjectId tie-breaker.
        created_at = base_created_at + timedelta(seconds=index // 2)
        for routine, label in ((target, "target"), (other, "other")):
            message_id = ObjectId()
            run_id = str(ObjectId())
            if routine.id == target.id:
                target_ids.append(str(message_id))
            message = XiaoBaoMessage(
                conversation_id=str(inbox.id),
                role=XiaoBaoMessageRole.ASSISTANT,
                status=XiaoBaoMessageStatus.COMPLETE,
                source=XiaoBaoMessageSource.ROUTINE,
                content=f"{label}-{index}",
                routine_id=str(routine.id),
                routine_run_id=run_id,
                delivered_at=(
                    now - timedelta(days=6) if routine.id == target.id and index == 0 else now
                ),
                created_at=created_at,
                updated_at=created_at,
            )
            doc = message.model_dump(mode="python", by_alias=True, exclude_none=True)
            doc["_id"] = message_id
            docs.append(doc)
    await routine_test_db[settings.xiaobao_messages_collection_name].insert_many(docs)

    service = XiaoBaoRoutineService(routines, runs, conversations, messages)
    first_unfiltered = await service.inbox(UserType.JORIS, limit=50)
    assert first_unfiltered.has_more_messages is True
    assert first_unfiltered.next_cursor is not None
    assert target_ids[0] not in {item.id for item in first_unfiltered.messages}

    seen_ids: list[str] = []
    cursor: str | None = None
    page_count = 0
    while True:
        page = await service.inbox(
            UserType.JORIS,
            limit=20,
            routine_id=str(target.id),
            cursor=cursor,
        )
        page_count += 1
        seen_ids.extend(item.id for item in page.messages)
        assert page.unread_count == 122
        if not page.has_more_messages:
            assert page.next_cursor is None
            break
        assert page.next_cursor is not None
        cursor = page.next_cursor

    assert page_count == 4
    assert len(seen_ids) == len(set(seen_ids)) == 61
    assert set(seen_ids) == set(target_ids)
    assert target_ids[0] in seen_ids[40:]

    with pytest.raises(NotFoundException) as not_found:
        await service.inbox(
            UserType.JORIS,
            limit=20,
            routine_id=str(wrong_owner.id),
        )
    assert not_found.value.status_code == 404
    with pytest.raises(BadRequestException) as invalid_cursor:
        await service.inbox(
            UserType.JORIS,
            limit=20,
            routine_id=str(target.id),
            cursor="not-a-valid-cursor",
        )
    assert invalid_cursor.value.status_code == 400
