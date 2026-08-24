import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.xiaobao import get_routine_inbox, resume_routine
from app.core.config import get_settings
from app.integrations.openai_client import OpenAIStreamedResult
from app.schemas.v1.exceptions import BadRequestException, ConflictException
from app.schemas.v1.todo import Todo
from app.schemas.v1.user import UserType
from app.schemas.v1.xiaobao import (
    XiaoBaoConversation,
    XiaoBaoMessage,
    XiaoBaoMessageRole,
    XiaoBaoMessageSource,
    XiaoBaoMessageStatus,
    XiaoBaoProposal,
    XiaoBaoProposalStatus,
    XiaoBaoProposalType,
)
from app.schemas.v1.xiaobao_routine import (
    XiaoBaoRoutine,
    XiaoBaoRoutineContextProfile,
    XiaoBaoRoutineCreate,
    XiaoBaoRoutineFrequency,
    XiaoBaoRoutineKind,
    XiaoBaoRoutinePauseReason,
    XiaoBaoRoutineResponse,
    XiaoBaoRoutineRun,
    XiaoBaoRoutineRunStatus,
    XiaoBaoRoutineSchedule,
    XiaoBaoRoutineUpdate,
)
from app.services.xiaobao_context import RelationshipContextService
from app.services.xiaobao_proposals import XiaoBaoProposalService
from app.services.xiaobao_routine import XiaoBaoRoutineService
from app.services.xiaobao_routine_execution import XiaoBaoRoutineExecutionService
from app.services.xiaobao_schedule import next_scheduled_at
from app.util.time import utc_now
from app.workers import xiaobao_routine_clock
from app.workers.xiaobao_routine_clock import (
    auto_pause_unread_inactive_routines,
    materialize_due_routines,
)
from app.workers.xiaobao_routine_worker import (
    _finish_terminal_reminder_failure,
    process_one_xiaobao_routine_work_item,
)
from app.xiaobao.tools import XiaoBaoToolContext, execute_xiaobao_tool

OID_1 = "64a7f0c2f1d2c4b5a6e7d8f1"
OID_2 = "64a7f0c2f1d2c4b5a6e7d8f2"
OID_3 = "64a7f0c2f1d2c4b5a6e7d8f3"
OID_4 = "64a7f0c2f1d2c4b5a6e7d8f4"
settings = get_settings()


def test_routine_openapi_exposes_only_minimal_run_and_inbox_fields() -> None:
    from app.main import app

    schema = app.openapi()
    components = schema["components"]["schemas"]
    assert set(components["XiaoBaoRoutineRunResponse"]["properties"]) == {
        "id",
        "routine_id",
        "status",
        "scheduled_for",
        "local_scheduled_at",
        "timezone_snapshot",
        "attempt_count",
        "output_message_id",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
    }
    assert set(components["XiaoBaoInbox"]["properties"]) == {
        "messages",
        "has_more_messages",
        "next_cursor",
        "unread_count",
    }
    assert set(components["XiaoBaoInboxMessageResponse"]["properties"]) == {
        "id",
        "content",
        "mascot_mood",
        "routine_id",
        "routine_run_id",
        "read_at",
        "created_at",
        "updated_at",
    }
    assert "delivery_cleanup_at" not in components["XiaoBaoMessage"]["properties"]
    mark_read = schema["paths"]["/api/v1/xiaobao/inbox/{message_id}/read"]["post"]
    response_schema = mark_read["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"].endswith("/XiaoBaoInboxMessageResponse")
    routine_properties = components["XiaoBaoRoutineResponse"]["properties"]
    assert routine_properties["pause_reason"]["anyOf"][0]["$ref"].endswith(
        "/XiaoBaoRoutinePauseReason"
    )
    assert components["XiaoBaoRoutinePauseReason"]["enum"] == [
        "MANUAL",
        "UNREAD_INACTIVITY",
    ]
    resume = schema["paths"]["/api/v1/xiaobao/routines/{routine_id}/resume"]["post"]
    assert "409" in resume["responses"]
    inbox_parameters = schema["paths"]["/api/v1/xiaobao/inbox"]["get"]["parameters"]
    assert {item["name"] for item in inbox_parameters} == {
        "limit",
        "routine_id",
        "cursor",
        "session_id",
    }


def test_daily_schedule_preserves_wall_time_across_dst() -> None:
    schedule = XiaoBaoRoutineSchedule(
        frequency=XiaoBaoRoutineFrequency.DAILY,
        local_time="09:00",
        timezone="Europe/Amsterdam",
    )
    before_dst = next_scheduled_at(schedule, after=datetime(2026, 3, 28, 9, 0, tzinfo=UTC))
    after_dst = next_scheduled_at(schedule, after=before_dst)

    assert before_dst == datetime(2026, 3, 29, 7, 0, tzinfo=UTC)
    assert after_dst == datetime(2026, 3, 30, 7, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_committed_delivery_repair_runs_before_exhaustion_handling() -> None:
    now = utc_now()
    run = XiaoBaoRoutineRun(
        id=OID_2,
        routine_id=OID_1,
        owner_user_type=UserType.JORIS,
        status=XiaoBaoRoutineRunStatus.PROCESSING,
        scheduled_for=now,
        local_scheduled_at="2026-08-24T09:00+02:00",
        timezone_snapshot="Europe/Amsterdam",
        available_at=now,
        attempt_count=settings.xiaobao_routine_max_attempts,
        lease_token="repair-lease",
        lease_expires_at=now,
        created_at=now,
        updated_at=now,
    )
    routine = SimpleNamespace(id=OID_1, committed_delivery_pending_run_id=OID_2)
    service = SimpleNamespace(repair_committed_delivery=AsyncMock())
    routines = SimpleNamespace(
        list_committed_delivery_repairs=AsyncMock(return_value=[routine]),
        list_committed_delivery_guarded_routine_ids=AsyncMock(return_value=[OID_1]),
    )
    runs = SimpleNamespace(
        claim_delivery_repair=AsyncMock(return_value=run),
        fail_exhausted_stale=AsyncMock(),
        list_terminal_failures=AsyncMock(return_value=[]),
        claim_next=AsyncMock(),
        mark_failed_or_retry=AsyncMock(),
    )

    processed = await process_one_xiaobao_routine_work_item(service, routines, runs)

    assert processed is True
    service.repair_committed_delivery.assert_awaited_once_with(run)
    runs.fail_exhausted_stale.assert_not_awaited()
    runs.claim_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_corrupt_guarded_repair_does_not_stall_unrelated_routine() -> None:
    now = utc_now()
    repair = XiaoBaoRoutineRun(
        id=OID_2,
        routine_id=OID_1,
        owner_user_type=UserType.JORIS,
        status=XiaoBaoRoutineRunStatus.PROCESSING,
        scheduled_for=now,
        local_scheduled_at="2026-08-24T09:00+02:00",
        timezone_snapshot="Europe/Amsterdam",
        available_at=now,
        attempt_count=settings.xiaobao_routine_max_attempts,
        lease_token="repair-lease",
        lease_expires_at=now,
        created_at=now,
        updated_at=now,
    )
    unrelated = repair.model_copy(
        update={
            "id": OID_4,
            "routine_id": OID_3,
            "attempt_count": 1,
            "lease_token": "normal-lease",
        }
    )
    guarded = SimpleNamespace(
        id=OID_1,
        committed_delivery_pending_run_id=OID_2,
    )
    service = SimpleNamespace(
        repair_committed_delivery=AsyncMock(side_effect=RuntimeError("committed message missing")),
        process=AsyncMock(),
    )
    routines = SimpleNamespace(
        list_committed_delivery_repairs=AsyncMock(return_value=[guarded]),
        list_committed_delivery_guarded_routine_ids=AsyncMock(return_value=[OID_1]),
    )
    runs = SimpleNamespace(
        claim_delivery_repair=AsyncMock(return_value=repair),
        fail_exhausted_stale=AsyncMock(return_value=0),
        list_terminal_failures=AsyncMock(return_value=[]),
        claim_next=AsyncMock(return_value=unrelated),
        mark_failed_or_retry=AsyncMock(),
    )

    processed = await process_one_xiaobao_routine_work_item(service, routines, runs)

    assert processed is True
    runs.mark_failed_or_retry.assert_awaited_once_with(repair, "RuntimeError")
    runs.fail_exhausted_stale.assert_awaited_once_with(excluded_routine_ids=[OID_1])
    runs.claim_next.assert_awaited_once_with(
        lease_seconds=settings.xiaobao_routine_lease_seconds,
        excluded_routine_ids=[OID_1],
    )
    service.process.assert_awaited_once_with(unrelated)


@pytest.mark.asyncio
async def test_clock_rechecks_unread_before_auto_pause_cas() -> None:
    now = utc_now()
    routine = XiaoBaoRoutine(
        id=OID_1,
        owner_user_type=UserType.JORIS,
        name="Morning idea",
        instruction="Give me one idea",
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
    inbox = XiaoBaoConversation(
        id=OID_2,
        owner_user_type=UserType.JORIS,
        title="Routines inbox",
        purpose="ROUTINE_INBOX",
        created_at=now,
        updated_at=now,
    )
    routines = SimpleNamespace(
        list_active=AsyncMock(return_value=[routine]),
        auto_pause_for_unread_inactivity=AsyncMock(),
    )
    runs = SimpleNamespace(cancel_pending_for_routine=AsyncMock())
    conversations = SimpleNamespace(get_inbox=AsyncMock(return_value=inbox))
    # The message is read between the candidate lookup and the immediate decision lookup.
    messages = SimpleNamespace(
        has_unread_routine_output_at_or_before=AsyncMock(side_effect=[True, False])
    )

    qualifying = await auto_pause_unread_inactive_routines(
        routines,
        runs,
        conversations,
        messages,
        now=now,
    )

    assert qualifying == set()
    routines.auto_pause_for_unread_inactivity.assert_not_awaited()
    runs.cancel_pending_for_routine.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_rejects_unread_inactivity_pause_with_qualifying_output() -> None:
    now = utc_now()
    routine = XiaoBaoRoutine(
        id=OID_1,
        owner_user_type=UserType.JORIS,
        name="Morning idea",
        instruction="Give me one idea",
        schedule=XiaoBaoRoutineSchedule(
            frequency=XiaoBaoRoutineFrequency.DAILY,
            local_time="09:00",
            timezone="Europe/Amsterdam",
        ),
        context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
        enabled=False,
        next_run_at=now,
        pause_reason=XiaoBaoRoutinePauseReason.UNREAD_INACTIVITY,
        paused_at=now,
        created_at=now,
        updated_at=now,
    )
    inbox = XiaoBaoConversation(
        id=OID_2,
        owner_user_type=UserType.JORIS,
        title="Routines inbox",
        purpose="ROUTINE_INBOX",
        created_at=now,
        updated_at=now,
    )
    routines = SimpleNamespace(
        get_owned=AsyncMock(return_value=routine),
        pause_owned=AsyncMock(),
        resume_owned=AsyncMock(),
    )
    runs = SimpleNamespace(cancel_pending_for_routine=AsyncMock())
    messages = SimpleNamespace(has_unread_routine_output_at_or_before=AsyncMock(return_value=True))
    service = XiaoBaoRoutineService(
        routines,
        runs,
        SimpleNamespace(get_inbox=AsyncMock(return_value=inbox)),
        messages,
    )

    repeated_pause = await service.pause(OID_1, UserType.JORIS)
    assert repeated_pause.pause_reason == XiaoBaoRoutinePauseReason.UNREAD_INACTIVITY
    assert repeated_pause.enabled is False
    assert repeated_pause.updated_at == routine.updated_at
    routines.pause_owned.assert_not_awaited()
    runs.cancel_pending_for_routine.assert_awaited_once_with(OID_1)

    with pytest.raises(ConflictException) as exc_info:
        await service.resume(OID_1, UserType.JORIS)

    assert exc_info.value.status_code == 409
    assert "older inbox messages" in exc_info.value.detail
    routines.resume_owned.assert_not_awaited()
    threshold = messages.has_unread_routine_output_at_or_before.await_args.kwargs["threshold"]
    assert now - timedelta(days=5) <= threshold < now - timedelta(days=5) + timedelta(seconds=1)


@pytest.mark.asyncio
async def test_resume_route_preserves_unread_inactivity_conflict() -> None:
    service = SimpleNamespace(
        resume=AsyncMock(side_effect=ConflictException("Read older routine messages first"))
    )

    with pytest.raises(ConflictException) as exc_info:
        await resume_routine(
            OID_1,
            service,
            SimpleNamespace(user_type=UserType.JORIS),
        )

    assert exc_info.value.status_code == 409
    service.resume.assert_awaited_once_with(OID_1, UserType.JORIS)


@pytest.mark.asyncio
async def test_inbox_route_forwards_owner_safe_filter_and_opaque_cursor() -> None:
    expected = SimpleNamespace()
    service = SimpleNamespace(inbox=AsyncMock(return_value=expected))

    result = await get_routine_inbox(
        service,
        SimpleNamespace(user_type=UserType.JORIS),
        limit=25,
        routine_id=OID_1,
        cursor="opaque-cursor",
    )

    assert result is expected
    service.inbox.assert_awaited_once_with(
        UserType.JORIS,
        limit=25,
        routine_id=OID_1,
        cursor="opaque-cursor",
    )


@pytest.mark.asyncio
async def test_clock_initializes_message_indexes_before_repositories(monkeypatch) -> None:
    calls: list[str] = []

    async def ensure_messages(_db) -> None:
        calls.append("message_indexes")

    async def ensure_routines(_db) -> None:
        calls.append("routine_indexes")

    def repository(name: str):
        def build(_db):
            calls.append(name)
            return MagicMock()

        return build

    monkeypatch.setattr(xiaobao_routine_clock, "get_db", lambda: object())
    monkeypatch.setattr(xiaobao_routine_clock, "ensure_xiaobao_indexes", ensure_messages)
    monkeypatch.setattr(xiaobao_routine_clock, "ensure_xiaobao_routine_indexes", ensure_routines)
    monkeypatch.setattr(
        xiaobao_routine_clock, "XiaoBaoRoutineRepository", repository("routine_repo")
    )
    monkeypatch.setattr(
        xiaobao_routine_clock, "XiaoBaoRoutineRunRepository", repository("run_repo")
    )
    monkeypatch.setattr(
        xiaobao_routine_clock,
        "XiaoBaoConversationRepository",
        repository("conversation_repo"),
    )
    monkeypatch.setattr(
        xiaobao_routine_clock, "XiaoBaoMessageRepository", repository("message_repo")
    )
    stop_event = asyncio.Event()
    stop_event.set()

    await xiaobao_routine_clock.run_xiaobao_routine_clock(stop_event)

    assert calls == [
        "message_indexes",
        "routine_indexes",
        "routine_repo",
        "run_repo",
        "conversation_repo",
        "message_repo",
    ]


def test_nonexistent_local_time_moves_forward_to_first_valid_instant() -> None:
    schedule = XiaoBaoRoutineSchedule(
        frequency=XiaoBaoRoutineFrequency.WEEKLY,
        local_time="02:30",
        timezone="Europe/Amsterdam",
        weekdays=[6],
    )
    occurrence = next_scheduled_at(schedule, after=datetime(2026, 3, 28, 12, 0, tzinfo=UTC))

    assert occurrence == datetime(2026, 3, 29, 1, 0, tzinfo=UTC)


def test_ambiguous_local_time_runs_once_at_first_fold() -> None:
    schedule = XiaoBaoRoutineSchedule(
        frequency=XiaoBaoRoutineFrequency.WEEKLY,
        local_time="02:30",
        timezone="Europe/Amsterdam",
        weekdays=[6],
    )
    occurrence = next_scheduled_at(schedule, after=datetime(2026, 10, 24, 12, 0, tzinfo=UTC))
    following = next_scheduled_at(schedule, after=occurrence)

    assert occurrence == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    assert following == datetime(2026, 11, 1, 1, 30, tzinfo=UTC)


def test_reminder_and_routine_require_distinct_schedule_kinds() -> None:
    reminder_schedule = XiaoBaoRoutineSchedule(
        frequency=XiaoBaoRoutineFrequency.ONCE,
        local_date=date(2026, 8, 28),
        local_time="12:00",
        timezone="Europe/Stockholm",
    )
    reminder = XiaoBaoRoutineCreate(
        kind=XiaoBaoRoutineKind.REMINDER,
        name="Plan date",
        message="Plan our cozy mini-date.",
        schedule=reminder_schedule,
    )
    assert reminder.message == "Plan our cozy mini-date."
    assert reminder.model_dump(mode="python")["schedule"]["local_date"] == "2026-08-28"

    with pytest.raises(ValueError, match="reminders must use a one-time schedule"):
        XiaoBaoRoutineCreate(
            kind=XiaoBaoRoutineKind.REMINDER,
            name="Wrong reminder",
            message="Hello",
            schedule=XiaoBaoRoutineSchedule(
                frequency=XiaoBaoRoutineFrequency.DAILY,
                local_time="12:00",
                timezone="Europe/Stockholm",
            ),
        )
    with pytest.raises(ValueError, match="routines must use a daily or weekly schedule"):
        XiaoBaoRoutineCreate(
            kind=XiaoBaoRoutineKind.ROUTINE,
            name="Wrong routine",
            instruction="Write a fresh idea",
            schedule=reminder_schedule,
        )


def test_one_time_schedule_uses_existing_dst_gap_resolution() -> None:
    with pytest.raises(ValueError, match="local time does not exist"):
        XiaoBaoRoutineSchedule(
            frequency=XiaoBaoRoutineFrequency.ONCE,
            local_date=date(2026, 3, 29),
            local_time="02:30",
            timezone="Europe/Amsterdam",
        )


@pytest.mark.asyncio
async def test_clock_consumes_one_time_reminder_without_revision_change() -> None:
    now = datetime(2026, 8, 24, 10, tzinfo=UTC)
    routine = XiaoBaoRoutine(
        id=OID_1,
        owner_user_type=UserType.JORIS,
        kind=XiaoBaoRoutineKind.REMINDER,
        name="Plan date",
        message="Plan our cozy mini-date.",
        schedule=XiaoBaoRoutineSchedule(
            frequency=XiaoBaoRoutineFrequency.ONCE,
            local_date=date(2026, 8, 24),
            local_time="12:00",
            timezone="Europe/Amsterdam",
        ),
        context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
        next_run_at=now,
        created_at=now,
        updated_at=now,
    )
    routines = SimpleNamespace(
        list_due=AsyncMock(return_value=[routine]), advance_if_due=AsyncMock(return_value=True)
    )
    runs = SimpleNamespace(materialize=AsyncMock())

    await materialize_due_routines(routines, runs, now=now)

    materialized = runs.materialize.await_args.args[0]
    assert materialized.routine_revision == routine.revision
    routines.advance_if_due.assert_awaited_once_with(OID_1, now, None)


@pytest.mark.asyncio
async def test_paused_past_reminder_can_be_rescheduled_to_a_future_time(monkeypatch) -> None:
    now = datetime(2026, 8, 24, 10, tzinfo=UTC)
    monkeypatch.setattr("app.services.xiaobao_routine.utc_now", lambda: now)
    current = XiaoBaoRoutine(
        id=OID_1,
        owner_user_type=UserType.JORIS,
        kind=XiaoBaoRoutineKind.REMINDER,
        name="Plan date",
        message="Plan our cozy mini-date.",
        schedule=XiaoBaoRoutineSchedule(
            frequency=XiaoBaoRoutineFrequency.ONCE,
            local_date=date(2026, 8, 24),
            local_time="10:00",
            timezone="Europe/Amsterdam",
        ),
        context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
        enabled=False,
        paused_at=now,
        pause_reason=XiaoBaoRoutinePauseReason.MANUAL,
        next_run_at=now - timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )
    schedule = XiaoBaoRoutineSchedule(
        frequency=XiaoBaoRoutineFrequency.ONCE,
        local_date=date(2026, 8, 25),
        local_time="12:00",
        timezone="Europe/Amsterdam",
    )
    updated = current.model_copy(
        update={"schedule": schedule, "next_run_at": datetime(2026, 8, 25, 10, tzinfo=UTC)}
    )
    routines = SimpleNamespace(
        get_owned=AsyncMock(return_value=current), update_owned=AsyncMock(return_value=updated)
    )
    runs = SimpleNamespace(cancel_pending_for_routine=AsyncMock())
    service = XiaoBaoRoutineService(routines, runs, SimpleNamespace(), SimpleNamespace())

    result = await service.update(OID_1, XiaoBaoRoutineUpdate(schedule=schedule), UserType.JORIS)

    assert result.enabled is False
    fields = routines.update_owned.await_args.args[2]
    assert fields["next_run_at"] == datetime(2026, 8, 25, 10, tzinfo=UTC)
    runs.cancel_pending_for_routine.assert_awaited_once_with(OID_1)

    with pytest.raises(ConflictException, match="after its scheduled time"):
        await service.update(OID_1, XiaoBaoRoutineUpdate(name="Renamed"), UserType.JORIS)


@pytest.mark.asyncio
async def test_proposal_update_cannot_change_reminder_into_routine() -> None:
    now = utc_now()
    reminder_payload = XiaoBaoRoutineCreate(
        kind=XiaoBaoRoutineKind.REMINDER,
        name="Plan date",
        message="Plan our cozy mini-date.",
        schedule=XiaoBaoRoutineSchedule(
            frequency=XiaoBaoRoutineFrequency.ONCE,
            local_date=now.date() + timedelta(days=1),
            local_time="12:00",
            timezone="Europe/Amsterdam",
        ),
    )
    proposal = XiaoBaoProposal(
        id=OID_1,
        conversation_id=OID_2,
        message_id=OID_3,
        owner_user_type=UserType.JORIS,
        type=XiaoBaoProposalType.REMINDER,
        payload=reminder_payload,
        created_at=now,
        updated_at=now,
    )
    proposals = SimpleNamespace(
        get_owned=AsyncMock(return_value=proposal), update_pending=AsyncMock()
    )
    service = XiaoBaoProposalService(
        proposals, SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), SimpleNamespace()
    )
    replacement = XiaoBaoRoutineCreate(
        kind=XiaoBaoRoutineKind.ROUTINE,
        name="Daily idea",
        instruction="Give one idea",
        schedule=XiaoBaoRoutineSchedule(
            frequency=XiaoBaoRoutineFrequency.DAILY,
            local_time="12:00",
            timezone="Europe/Amsterdam",
        ),
    )

    with pytest.raises(BadRequestException, match="cannot be changed"):
        await service.update(OID_1, UserType.JORIS, replacement.model_dump(mode="json"))

    proposals.update_pending.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_reminder_failure_disables_the_consumed_schedule() -> None:
    now = utc_now()
    failed = XiaoBaoRoutineRun(
        id=OID_2,
        routine_id=OID_1,
        owner_user_type=UserType.JORIS,
        status=XiaoBaoRoutineRunStatus.FAILED,
        scheduled_for=now,
        local_scheduled_at="2026-08-24T12:00+02:00",
        timezone_snapshot="Europe/Amsterdam",
        available_at=now,
        attempt_count=settings.xiaobao_routine_max_attempts,
        routine_revision=4,
        created_at=now,
        updated_at=now,
    )
    reminder = SimpleNamespace(
        kind=XiaoBaoRoutineKind.REMINDER, committed_delivery_pending_run_id=None
    )
    routines = SimpleNamespace(
        get_for_execution=AsyncMock(return_value=reminder), finish_one_time_failure=AsyncMock()
    )

    await _finish_terminal_reminder_failure(routines, failed)

    routines.finish_one_time_failure.assert_awaited_once_with(OID_1, UserType.JORIS, revision=4)


@pytest.mark.asyncio
async def test_routine_context_reads_open_todos_without_querying_mediation() -> None:
    mediation = SimpleNamespace(list_sessions=AsyncMock(side_effect=AssertionError))
    context = RelationshipContextService(
        SimpleNamespace(
            overview=AsyncMock(
                return_value=SimpleNamespace(boundaries=[], requests=[], goals=[], agreements=[])
            )
        ),
        SimpleNamespace(
            get_all=AsyncMock(
                return_value=[
                    Todo(
                        id=OID_1,
                        title="Plan a video date",
                        category="Date",
                        completed=False,
                        created_at=utc_now(),
                    ),
                    Todo(
                        id=OID_2,
                        title="Already done",
                        category="Date",
                        completed=True,
                        created_at=utc_now(),
                    ),
                ]
            )
        ),
        mediation,
        SimpleNamespace(get_ai_context=AsyncMock(return_value=None)),
    )

    authorized = await context.build_for_routine(UserType.JORIS)

    assert [item.data["title"] for item in authorized.public.together_list] == ["Plan a video date"]
    assert authorized.public.mediation_sessions == []
    assert authorized.private_mediation_by_key == {}
    mediation.list_sessions.assert_not_awaited()


@pytest.mark.asyncio
async def test_propose_routine_creates_reviewable_pending_proposal_without_owner_argument() -> None:
    proposal_repo = SimpleNamespace()

    async def create(proposal):
        assert proposal.owner_user_type == UserType.JORIS
        assert proposal.type == XiaoBaoProposalType.ROUTINE
        return proposal.model_copy(update={"id": OID_3})

    proposal_repo.create = AsyncMock(side_effect=create)
    context = XiaoBaoToolContext(
        owner=UserType.JORIS,
        conversation_id=OID_1,
        assistant_message_id=OID_2,
        relationship_context=SimpleNamespace(),
        private_mediation_by_key={},
        loaded_private_mediation_keys=set(),
        proposal_repo=proposal_repo,
        todo_service=SimpleNamespace(),
    )
    arguments = (
        '{"payload":{"name":"Morning idea","instruction":"Give me one small idea",'
        '"schedule":{"frequency":"DAILY","local_time":"09:00",'
        '"timezone":"Europe/Amsterdam","weekdays":[]},'
        '"context_profile":"RELATIONSHIP_CARE"},"rationale":"A gentle daily nudge"}'
    )

    result = await execute_xiaobao_tool("propose_routine", arguments, context)

    assert result.proposal_ids == [OID_3]
    created = proposal_repo.create.await_args.args[0]
    assert created.status == XiaoBaoProposalStatus.PENDING
    assert "owner" not in arguments


@pytest.mark.asyncio
async def test_accepting_routine_proposal_creates_owner_private_routine() -> None:
    now = utc_now()
    payload = XiaoBaoRoutineCreate(
        name="Morning idea",
        instruction="Give me one small idea",
        schedule=XiaoBaoRoutineSchedule(
            frequency=XiaoBaoRoutineFrequency.DAILY,
            local_time="09:00",
            timezone="Europe/Amsterdam",
        ),
    )
    proposal = XiaoBaoProposal(
        id=OID_1,
        conversation_id=OID_2,
        message_id=OID_3,
        owner_user_type=UserType.JORIS,
        type=XiaoBaoProposalType.ROUTINE,
        payload=payload,
        status=XiaoBaoProposalStatus.ACCEPTING,
        created_at=now,
        updated_at=now,
    )
    accepted = proposal.model_copy(
        update={"status": XiaoBaoProposalStatus.ACCEPTED, "created_entity_id": OID_2}
    )
    proposals = SimpleNamespace(
        get_owned=AsyncMock(return_value=proposal),
        claim_acceptance=AsyncMock(return_value=proposal),
        mark_accepted=AsyncMock(return_value=accepted),
    )
    created_routine = XiaoBaoRoutineResponse.from_record(
        XiaoBaoRoutine(
            id=OID_2,
            owner_user_type=UserType.JORIS,
            name=payload.name,
            instruction=payload.instruction,
            schedule=payload.schedule,
            context_profile=payload.context_profile,
            next_run_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    routines = SimpleNamespace(create=AsyncMock(return_value=created_routine))
    service = XiaoBaoProposalService(
        proposals, SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), routines
    )

    result = await service.accept(OID_1, UserType.JORIS)

    assert result.status == XiaoBaoProposalStatus.ACCEPTED
    routines.create.assert_awaited_once()
    assert routines.create.await_args.args[1] == UserType.JORIS


@pytest.mark.asyncio
async def test_routine_execution_uses_no_tools_and_writes_one_inbox_message() -> None:
    now = utc_now()
    schedule = XiaoBaoRoutineSchedule(
        frequency=XiaoBaoRoutineFrequency.DAILY,
        local_time="09:00",
        timezone="Europe/Amsterdam",
    )
    routine = XiaoBaoRoutine(
        id=OID_1,
        owner_user_type=UserType.JORIS,
        name="Morning idea",
        instruction="Give me one small relationship-care idea",
        schedule=schedule,
        context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
        next_run_at=now,
        created_at=now,
        updated_at=now,
    )
    run = XiaoBaoRoutineRun(
        id=OID_2,
        routine_id=OID_1,
        owner_user_type=UserType.JORIS,
        status=XiaoBaoRoutineRunStatus.PROCESSING,
        scheduled_for=now,
        local_scheduled_at="2026-08-24T09:00+02:00",
        timezone_snapshot="Europe/Amsterdam",
        available_at=now,
        attempt_count=1,
        lease_token="lease",
        lease_expires_at=now,
        created_at=now,
        updated_at=now,
    )
    committed_routine = routine.model_copy(update={"last_committed_delivery_run_id": OID_2})
    routines = SimpleNamespace(
        get_for_execution=AsyncMock(side_effect=[routine, committed_routine]),
        reserve_delivery=AsyncMock(return_value=True),
        commit_delivery=AsyncMock(return_value=False),
        release_committed_delivery=AsyncMock(return_value=True),
    )
    runs = SimpleNamespace(mark_completed=AsyncMock(return_value=run))
    inbox = XiaoBaoConversation(
        id=OID_3,
        owner_user_type=UserType.JORIS,
        title="Routines inbox",
        purpose="ROUTINE_INBOX",
        created_at=now,
        updated_at=now,
    )
    conversations = SimpleNamespace(
        get_or_create_inbox=AsyncMock(return_value=inbox), touch=AsyncMock()
    )

    async def create_message(message):
        assert message.source == XiaoBaoMessageSource.ROUTINE
        assert message.routine_run_id == OID_2
        return message.model_copy(update={"id": "64a7f0c2f1d2c4b5a6e7d8f4"})

    async def finalize_message(message_id):
        staged = messages.stage_routine_output.await_args.args[0]
        assert message_id == "64a7f0c2f1d2c4b5a6e7d8f4"
        return staged.model_copy(update={"id": message_id, "status": XiaoBaoMessageStatus.COMPLETE})

    messages = SimpleNamespace(
        get_by_routine_run=AsyncMock(return_value=None),
        list_recent_routine_outputs=AsyncMock(return_value=[]),
        stage_routine_output=AsyncMock(side_effect=create_message),
        finalize_staged_routine_output=AsyncMock(side_effect=finalize_message),
        delete_staged_routine_output=AsyncMock(),
    )
    restricted_context = SimpleNamespace(
        public=SimpleNamespace(model_dump_json=lambda **_: '{"together_list":[]}')
    )
    context_service = SimpleNamespace(build_for_routine=AsyncMock(return_value=restricted_context))
    openai = SimpleNamespace(
        stream_tool_response=AsyncMock(
            return_value=OpenAIStreamedResult(
                text="Send a warm voice note.",
                parsed_output={"content": "Send a warm voice note.", "mood": "LOVE"},
                tool_calls=[],
                output_items=[],
                response_id="response-1",
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
            )
        )
    )
    service = XiaoBaoRoutineExecutionService(
        routines, runs, conversations, messages, context_service, openai
    )

    await service.process(run)

    kwargs = openai.stream_tool_response.await_args.kwargs
    assert kwargs["allow_tools"] is False
    assert kwargs["tools"] == []
    assert len(kwargs["input_items"]) == 4
    assert kwargs["input_items"][-1] == {"role": "user", "content": routine.instruction}
    messages.stage_routine_output.assert_awaited_once()
    messages.finalize_staged_routine_output.assert_awaited_once()
    runs.mark_completed.assert_awaited_once()


@pytest.mark.asyncio
async def test_reminder_delivery_uses_exact_static_text_without_openai_or_context() -> None:
    now = utc_now()
    routine = XiaoBaoRoutine(
        id=OID_1,
        owner_user_type=UserType.JORIS,
        kind=XiaoBaoRoutineKind.REMINDER,
        name="Plan date",
        message="Plan our cozy mini-date.",
        schedule=XiaoBaoRoutineSchedule(
            frequency=XiaoBaoRoutineFrequency.ONCE,
            local_date=now.date(),
            local_time="12:00",
            timezone="Europe/Amsterdam",
        ),
        context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
        next_run_at=None,
        created_at=now,
        updated_at=now,
    )
    committed = routine.model_copy(update={"last_committed_delivery_run_id": OID_2})
    run = XiaoBaoRoutineRun(
        id=OID_2,
        routine_id=OID_1,
        owner_user_type=UserType.JORIS,
        status=XiaoBaoRoutineRunStatus.PROCESSING,
        scheduled_for=now,
        local_scheduled_at="2026-08-24T12:00+02:00",
        timezone_snapshot="Europe/Amsterdam",
        available_at=now,
        attempt_count=1,
        lease_token="lease",
        lease_expires_at=now,
        created_at=now,
        updated_at=now,
    )
    routines = SimpleNamespace(
        get_for_execution=AsyncMock(side_effect=[routine, committed]),
        reserve_delivery=AsyncMock(return_value=True),
        commit_delivery=AsyncMock(return_value=False),
        finish_one_time_delivery=AsyncMock(return_value=True),
        release_committed_delivery=AsyncMock(return_value=True),
    )
    runs = SimpleNamespace(mark_completed=AsyncMock(return_value=run))
    inbox = XiaoBaoConversation(
        id=OID_3,
        owner_user_type=UserType.JORIS,
        title="Routines inbox",
        purpose="ROUTINE_INBOX",
        created_at=now,
        updated_at=now,
    )
    conversations = SimpleNamespace(
        get_or_create_inbox=AsyncMock(return_value=inbox), touch=AsyncMock()
    )

    async def stage(message):
        assert message.content == "Plan our cozy mini-date."
        assert message.model is None
        return message.model_copy(update={"id": OID_4})

    messages = SimpleNamespace(
        get_by_routine_run=AsyncMock(return_value=None),
        stage_routine_output=AsyncMock(side_effect=stage),
        finalize_staged_routine_output=AsyncMock(
            side_effect=lambda _id: messages.stage_routine_output.await_args.args[0].model_copy(
                update={"id": OID_4, "status": XiaoBaoMessageStatus.COMPLETE}
            )
        ),
    )
    context = SimpleNamespace(build_for_routine=AsyncMock())
    openai = SimpleNamespace(stream_tool_response=AsyncMock())
    service = XiaoBaoRoutineExecutionService(
        routines, runs, conversations, messages, context, openai
    )

    await service.process(run)

    context.build_for_routine.assert_not_awaited()
    openai.stream_tool_response.assert_not_awaited()
    routines.finish_one_time_delivery.assert_awaited_once_with(OID_1, UserType.JORIS, run_id=OID_2)


@pytest.mark.asyncio
async def test_reminder_delivery_recovery_terminalizes_before_releasing_commit_marker() -> None:
    now = utc_now()
    routine = XiaoBaoRoutine(
        id=OID_1,
        owner_user_type=UserType.JORIS,
        kind=XiaoBaoRoutineKind.REMINDER,
        name="Plan date",
        message="Plan our cozy mini-date.",
        schedule=XiaoBaoRoutineSchedule(
            frequency=XiaoBaoRoutineFrequency.ONCE,
            local_date=now.date(),
            local_time="12:00",
            timezone="Europe/Amsterdam",
        ),
        context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
        next_run_at=None,
        last_committed_delivery_run_id=OID_2,
        committed_delivery_pending_run_id=OID_2,
        created_at=now,
        updated_at=now,
    )
    run = XiaoBaoRoutineRun(
        id=OID_2,
        routine_id=OID_1,
        owner_user_type=UserType.JORIS,
        status=XiaoBaoRoutineRunStatus.COMPLETED,
        scheduled_for=now,
        local_scheduled_at="2026-08-24T12:00+02:00",
        timezone_snapshot="Europe/Amsterdam",
        available_at=now,
        output_message_id=OID_3,
        created_at=now,
        updated_at=now,
    )
    message = XiaoBaoMessage(
        id=OID_3,
        conversation_id=OID_4,
        role=XiaoBaoMessageRole.ASSISTANT,
        status=XiaoBaoMessageStatus.COMPLETE,
        source=XiaoBaoMessageSource.ROUTINE,
        content="Plan our cozy mini-date.",
        routine_id=OID_1,
        routine_run_id=OID_2,
        created_at=now,
        updated_at=now,
    )
    calls: list[str] = []

    async def finish(*_args, **_kwargs):
        calls.append("finish")
        return True

    async def release(*_args, **_kwargs):
        calls.append("release")
        return True

    routines = SimpleNamespace(
        get_for_execution=AsyncMock(return_value=routine),
        finish_one_time_delivery=AsyncMock(side_effect=finish),
        release_committed_delivery=AsyncMock(side_effect=release),
    )
    conversations = SimpleNamespace(touch=AsyncMock())
    service = XiaoBaoRoutineExecutionService(
        routines,
        SimpleNamespace(),
        conversations,
        SimpleNamespace(get_by_routine_run=AsyncMock(return_value=message)),
        SimpleNamespace(),
        SimpleNamespace(),
    )

    await service.repair_committed_delivery(run)

    assert calls == ["finish", "release"]


@pytest.mark.asyncio
async def test_duplicate_worker_recovers_staged_message_from_commit_marker() -> None:
    now = utc_now()
    routine = XiaoBaoRoutine(
        id=OID_1,
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
    committed = routine.model_copy(update={"last_committed_delivery_run_id": OID_2})
    run = XiaoBaoRoutineRun(
        id=OID_2,
        routine_id=OID_1,
        owner_user_type=UserType.JORIS,
        status=XiaoBaoRoutineRunStatus.PROCESSING,
        scheduled_for=now,
        local_scheduled_at="2026-08-24T09:00+02:00",
        timezone_snapshot="Europe/Amsterdam",
        available_at=now,
        attempt_count=2,
        lease_token="current-lease",
        lease_expires_at=now,
        routine_revision=1,
        created_at=now,
        updated_at=now,
    )
    staged = XiaoBaoMessage(
        id=OID_3,
        conversation_id="64a7f0c2f1d2c4b5a6e7d8f4",
        role=XiaoBaoMessageRole.ASSISTANT,
        status=XiaoBaoMessageStatus.PENDING_DELIVERY,
        source=XiaoBaoMessageSource.ROUTINE,
        content="A committed idea",
        routine_id=OID_1,
        routine_run_id=OID_2,
        created_at=now,
        updated_at=now,
    )
    visible = staged.model_copy(update={"status": XiaoBaoMessageStatus.COMPLETE})
    routines = SimpleNamespace(
        get_for_execution=AsyncMock(side_effect=[routine, committed]),
        reserve_delivery=AsyncMock(return_value=True),
        commit_delivery=AsyncMock(return_value=False),
        release_committed_delivery=AsyncMock(return_value=True),
    )
    runs = SimpleNamespace(
        mark_completed=AsyncMock(return_value=run),
        cancel_claim=AsyncMock(),
    )
    conversations = SimpleNamespace(touch=AsyncMock())
    messages = SimpleNamespace(
        get_by_routine_run=AsyncMock(return_value=staged),
        finalize_staged_routine_output=AsyncMock(return_value=visible),
        delete_staged_routine_output=AsyncMock(),
    )
    service = XiaoBaoRoutineExecutionService(
        routines,
        runs,
        conversations,
        messages,
        SimpleNamespace(),
        SimpleNamespace(),
    )

    await service.process(run)

    messages.finalize_staged_routine_output.assert_awaited_once_with(OID_3)
    messages.delete_staged_routine_output.assert_not_awaited()
    runs.cancel_claim.assert_not_awaited()
    runs.mark_completed.assert_awaited_once()


@pytest.mark.asyncio
async def test_claimed_run_cannot_deliver_after_pause_and_resume_changes_revision() -> None:
    now = utc_now()
    schedule = XiaoBaoRoutineSchedule(
        frequency=XiaoBaoRoutineFrequency.DAILY,
        local_time="09:00",
        timezone="Europe/Amsterdam",
    )
    old_routine = XiaoBaoRoutine(
        id=OID_1,
        owner_user_type=UserType.JORIS,
        name="Morning idea",
        instruction="Give me one small idea",
        schedule=schedule,
        context_profile=XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE,
        next_run_at=now,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    resumed_routine = old_routine.model_copy(update={"revision": 3})
    run = XiaoBaoRoutineRun(
        id=OID_2,
        routine_id=OID_1,
        owner_user_type=UserType.JORIS,
        status=XiaoBaoRoutineRunStatus.PROCESSING,
        scheduled_for=now,
        local_scheduled_at="2026-08-24T09:00+02:00",
        timezone_snapshot="Europe/Amsterdam",
        available_at=now,
        attempt_count=1,
        lease_token="lease",
        lease_expires_at=now,
        routine_revision=1,
        created_at=now,
        updated_at=now,
    )
    routines = SimpleNamespace(
        get_for_execution=AsyncMock(side_effect=[old_routine, resumed_routine]),
        reserve_delivery=AsyncMock(return_value=False),
    )
    runs = SimpleNamespace(cancel_claim=AsyncMock())
    inbox = XiaoBaoConversation(
        id=OID_3,
        owner_user_type=UserType.JORIS,
        title="Routines inbox",
        purpose="ROUTINE_INBOX",
        created_at=now,
        updated_at=now,
    )
    conversations = SimpleNamespace(get_or_create_inbox=AsyncMock(return_value=inbox))
    messages = SimpleNamespace(
        get_by_routine_run=AsyncMock(return_value=None),
        list_recent_routine_outputs=AsyncMock(return_value=[]),
        stage_routine_output=AsyncMock(),
    )
    context = SimpleNamespace(
        build_for_routine=AsyncMock(
            return_value=SimpleNamespace(public=SimpleNamespace(model_dump_json=lambda **_: "{}"))
        )
    )
    openai = SimpleNamespace(
        stream_tool_response=AsyncMock(
            return_value=OpenAIStreamedResult(
                text="A gentle idea",
                parsed_output={"content": "A gentle idea", "mood": "IDLE"},
                tool_calls=[],
                output_items=[],
                response_id="response-1",
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
            )
        )
    )
    service = XiaoBaoRoutineExecutionService(
        routines, runs, conversations, messages, context, openai
    )

    await service.process(run)

    openai.stream_tool_response.assert_awaited_once()
    runs.cancel_claim.assert_awaited_once_with(run, "routine_changed")
    messages.stage_routine_output.assert_not_awaited()


@pytest.mark.asyncio
async def test_message_stays_hidden_when_pause_wins_after_delivery_reservation() -> None:
    now = utc_now()
    routine = XiaoBaoRoutine(
        id=OID_1,
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
    run = XiaoBaoRoutineRun(
        id=OID_2,
        routine_id=OID_1,
        owner_user_type=UserType.JORIS,
        status=XiaoBaoRoutineRunStatus.PROCESSING,
        scheduled_for=now,
        local_scheduled_at="2026-08-24T09:00+02:00",
        timezone_snapshot="Europe/Amsterdam",
        available_at=now,
        attempt_count=1,
        lease_token="lease",
        lease_expires_at=now,
        routine_revision=1,
        created_at=now,
        updated_at=now,
    )
    routines = SimpleNamespace(
        get_for_execution=AsyncMock(return_value=routine),
        reserve_delivery=AsyncMock(return_value=True),
        commit_delivery=AsyncMock(return_value=False),
    )
    runs = SimpleNamespace(cancel_claim=AsyncMock())
    inbox = XiaoBaoConversation(
        id=OID_3,
        owner_user_type=UserType.JORIS,
        title="Routines inbox",
        purpose="ROUTINE_INBOX",
        created_at=now,
        updated_at=now,
    )
    conversations = SimpleNamespace(get_or_create_inbox=AsyncMock(return_value=inbox))

    async def stage(message):
        return message.model_copy(update={"id": "64a7f0c2f1d2c4b5a6e7d8f4"})

    messages = SimpleNamespace(
        get_by_routine_run=AsyncMock(return_value=None),
        list_recent_routine_outputs=AsyncMock(return_value=[]),
        stage_routine_output=AsyncMock(side_effect=stage),
        delete_staged_routine_output=AsyncMock(),
        finalize_staged_routine_output=AsyncMock(),
    )
    context = SimpleNamespace(
        build_for_routine=AsyncMock(
            return_value=SimpleNamespace(public=SimpleNamespace(model_dump_json=lambda **_: "{}"))
        )
    )
    openai = SimpleNamespace(
        stream_tool_response=AsyncMock(
            return_value=OpenAIStreamedResult(
                text="A gentle idea",
                parsed_output={"content": "A gentle idea", "mood": "IDLE"},
                tool_calls=[],
                output_items=[],
                response_id="response-1",
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
            )
        )
    )
    service = XiaoBaoRoutineExecutionService(
        routines, runs, conversations, messages, context, openai
    )

    await service.process(run)

    messages.delete_staged_routine_output.assert_awaited_once()
    messages.finalize_staged_routine_output.assert_not_awaited()
    runs.cancel_claim.assert_awaited_once_with(run, "routine_changed")
