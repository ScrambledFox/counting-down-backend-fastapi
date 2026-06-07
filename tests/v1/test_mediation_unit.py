from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.api.v1.mediation import create_mediation_session
from app.schemas.v1.exceptions import ConflictException
from app.schemas.v1.mediation import (
    AIJobStatus,
    MediationAIJob,
    MediationAIJobType,
    MediationModerationResult,
    MediationPerspective,
    MediationPerspectiveDraftUpdate,
    MediationProvider,
    MediationSession,
    MediationSessionCreate,
    MediationSessionStatus,
    PerspectiveStatus,
    SafetyStatus,
)
from app.schemas.v1.session import SessionResponse
from app.schemas.v1.user import UserType
from app.services.mediation import MediationService
from app.services.mediation_ai import MediationAIService
from app.services.mediation_safety import MediationSafetyService, ModerationDecision

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SESSION_ID = "64a7f0c2f1d2c4b5a6e7d8f1"
PERSPECTIVE_ID = "64a7f0c2f1d2c4b5a6e7d8f2"
MODERATION_ID = "64a7f0c2f1d2c4b5a6e7d8f3"


def make_session(
    status: MediationSessionStatus = MediationSessionStatus.AWAITING_PERSPECTIVES,
    resolved_by_user_types: list[UserType] | None = None,
    archived_by_user_types: list[UserType] | None = None,
) -> MediationSession:
    return MediationSession(
        id=SESSION_ID,
        title="Planning conflict",
        description=None,
        created_by_user_type=UserType.JORIS,
        status=status,
        safety_status=SafetyStatus.NORMAL,
        created_at=NOW,
        updated_at=NOW,
        resolved_by_user_types=resolved_by_user_types or [],
        archived_by_user_types=archived_by_user_types or [],
    )


def make_perspective(status: PerspectiveStatus = PerspectiveStatus.DRAFT) -> MediationPerspective:
    return MediationPerspective(
        id=PERSPECTIVE_ID,
        session_id=SESSION_ID,
        user_type=UserType.JORIS,
        what_happened="We disagreed about planning the weekend and both became defensive.",
        what_i_felt="I felt dismissed and tense.",
        what_i_needed="I needed clarity and reassurance.",
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )


def make_moderation() -> MediationModerationResult:
    return MediationModerationResult(
        id=MODERATION_ID,
        entity_type="PERSPECTIVE",
        entity_id=PERSPECTIVE_ID,
        provider=MediationProvider.INTERNAL,
        flagged=False,
        safety_status=SafetyStatus.NORMAL,
        categories={},
        created_at=NOW,
    )


def normal_decision() -> ModerationDecision:
    return ModerationDecision(
        flagged=False,
        safety_status=SafetyStatus.NORMAL,
        categories={},
        category_scores=None,
        raw_result=None,
        should_block_normal_mediation=False,
    )


def blocked_decision() -> ModerationDecision:
    return ModerationDecision(
        flagged=True,
        safety_status=SafetyStatus.BLOCKED,
        categories={"violence": True},
        category_scores=None,
        raw_result=None,
        should_block_normal_mediation=True,
        user_message="This mediation needs to pause because the content may involve safety risk.",
    )


def make_service() -> tuple[MediationService, dict[str, AsyncMock]]:
    repos = {
        "sessions": AsyncMock(),
        "perspectives": AsyncMock(),
        "ai": AsyncMock(),
        "comments": AsyncMock(),
        "moderation": AsyncMock(),
        "jobs": AsyncMock(),
        "safety": AsyncMock(spec=MediationSafetyService),
    }
    return (
        MediationService(
            session_repo=repos["sessions"],
            perspective_repo=repos["perspectives"],
            ai_repo=repos["ai"],
            comment_repo=repos["comments"],
            moderation_repo=repos["moderation"],
            job_repo=repos["jobs"],
            safety_service=repos["safety"],
        ),
        repos,
    )


def make_ai_service() -> tuple[MediationAIService, dict[str, AsyncMock]]:
    repos = {
        "sessions": AsyncMock(),
        "perspectives": AsyncMock(),
        "ai": AsyncMock(),
        "comments": AsyncMock(),
        "moderation": AsyncMock(),
        "jobs": AsyncMock(),
        "safety": AsyncMock(spec=MediationSafetyService),
        "openai": AsyncMock(),
    }
    return (
        MediationAIService(
            session_repo=repos["sessions"],
            perspective_repo=repos["perspectives"],
            ai_repo=repos["ai"],
            comment_repo=repos["comments"],
            moderation_repo=repos["moderation"],
            job_repo=repos["jobs"],
            safety_service=repos["safety"],
            openai_client=repos["openai"],
        ),
        repos,
    )


@pytest.mark.asyncio
async def test_route_uses_session_user_type_when_creating_mediation_session() -> None:
    service = AsyncMock()
    payload = MediationSessionCreate(title="Argument about planning")
    session = SessionResponse(
        session_id="session-token",
        user_type=UserType.DANFENG,
        created_at=NOW,
        expires_at=NOW,
    )
    expected = make_session()
    service.create_session.return_value = expected

    result = await create_mediation_session(payload, service, session)

    assert result == expected
    service.create_session.assert_awaited_once_with(UserType.DANFENG, payload)


@pytest.mark.asyncio
async def test_cannot_update_locked_perspective() -> None:
    service, repos = make_service()
    repos["sessions"].get_by_id.return_value = make_session()
    repos["perspectives"].get_by_session_and_user.return_value = make_perspective(
        PerspectiveStatus.LOCKED
    )

    with pytest.raises(ConflictException):
        await service.upsert_my_perspective_draft(
            SESSION_ID,
            UserType.JORIS,
            MediationPerspectiveDraftUpdate(what_happened="A new draft attempt"),
        )

    repos["perspectives"].upsert_draft.assert_not_called()


@pytest.mark.asyncio
async def test_submit_marks_pending_review_and_creates_moderation_job() -> None:
    service, repos = make_service()
    session = make_session()
    pending = make_perspective(PerspectiveStatus.SUBMITTED_PENDING_REVIEW)
    repos["sessions"].get_by_id.return_value = session
    repos["perspectives"].get_by_session_and_user.return_value = make_perspective()
    repos["perspectives"].mark_pending_review.return_value = pending

    async def echo_job(job: MediationAIJob) -> MediationAIJob:
        return job

    repos["jobs"].create_job_if_not_exists.side_effect = echo_job

    response = await service.submit_my_perspective(SESSION_ID, UserType.JORIS)

    assert response.perspective.status == PerspectiveStatus.SUBMITTED_PENDING_REVIEW
    assert response.session.status == MediationSessionStatus.AWAITING_PERSPECTIVES
    assert len(response.created_jobs) == 1
    assert response.created_jobs[0].job_type == MediationAIJobType.PERSPECTIVE_MODERATION
    assert response.created_jobs[0].idempotency_key == (
        f"perspective_moderation:{SESSION_ID}:{PERSPECTIVE_ID}"
    )
    repos["safety"].moderate_perspective.assert_not_called()
    repos["moderation"].insert.assert_not_called()
    repos["perspectives"].lock_perspective.assert_not_called()


@pytest.mark.asyncio
async def test_cannot_submit_pending_review_or_locked_perspective_twice() -> None:
    service, repos = make_service()
    repos["sessions"].get_by_id.return_value = make_session()
    repos["perspectives"].get_by_session_and_user.return_value = make_perspective(
        PerspectiveStatus.SUBMITTED_PENDING_REVIEW
    )

    with pytest.raises(ConflictException):
        await service.submit_my_perspective(SESSION_ID, UserType.JORIS)

    repos["perspectives"].get_by_session_and_user.return_value = make_perspective(
        PerspectiveStatus.LOCKED
    )

    with pytest.raises(ConflictException):
        await service.submit_my_perspective(SESSION_ID, UserType.JORIS)

    repos["perspectives"].mark_pending_review.assert_not_called()


@pytest.mark.asyncio
async def test_perspective_moderation_job_locks_and_creates_private_reflection_job() -> None:
    service, repos = make_ai_service()
    pending = make_perspective(PerspectiveStatus.SUBMITTED_PENDING_REVIEW)
    locked = make_perspective(PerspectiveStatus.LOCKED)
    job = MediationAIJob(
        job_type=MediationAIJobType.PERSPECTIVE_MODERATION,
        status=AIJobStatus.PROCESSING,
        session_id=SESSION_ID,
        source_entity_id=PERSPECTIVE_ID,
        source_entity_type="PERSPECTIVE",
        idempotency_key=f"perspective_moderation:{SESSION_ID}:{PERSPECTIVE_ID}",
        created_at=NOW,
        updated_at=NOW,
    )
    repos["perspectives"].get_by_id.return_value = pending
    repos["safety"].moderate_perspective.return_value = normal_decision()
    repos["moderation"].insert.return_value = make_moderation()
    repos["perspectives"].lock_perspective.return_value = locked
    repos["perspectives"].count_locked_for_session.return_value = 1
    repos["jobs"].create_job_if_not_exists.side_effect = lambda item: item

    await service.moderate_perspective_submission(job)

    repos["safety"].moderate_perspective.assert_awaited_once()
    repos["perspectives"].lock_perspective.assert_awaited_once_with(
        PERSPECTIVE_ID, MODERATION_ID
    )
    repos["sessions"].set_status.assert_awaited_once_with(
        SESSION_ID, MediationSessionStatus.PARTIAL_PERSPECTIVE_SUBMITTED
    )
    assert repos["jobs"].create_job_if_not_exists.await_args.args[0].job_type == (
        MediationAIJobType.PRIVATE_REFLECTION
    )


@pytest.mark.asyncio
async def test_perspective_moderation_job_creates_shared_advice_for_second_lock() -> None:
    service, repos = make_ai_service()
    pending = make_perspective(PerspectiveStatus.SUBMITTED_PENDING_REVIEW)
    locked = make_perspective(PerspectiveStatus.LOCKED)
    job = MediationAIJob(
        job_type=MediationAIJobType.PERSPECTIVE_MODERATION,
        status=AIJobStatus.PROCESSING,
        session_id=SESSION_ID,
        source_entity_id=PERSPECTIVE_ID,
        source_entity_type="PERSPECTIVE",
        idempotency_key=f"perspective_moderation:{SESSION_ID}:{PERSPECTIVE_ID}",
        created_at=NOW,
        updated_at=NOW,
    )
    repos["perspectives"].get_by_id.return_value = pending
    repos["safety"].moderate_perspective.return_value = normal_decision()
    repos["moderation"].insert.return_value = make_moderation()
    repos["perspectives"].lock_perspective.return_value = locked
    repos["perspectives"].count_locked_for_session.return_value = 2
    repos["jobs"].create_job_if_not_exists.side_effect = lambda item: item

    await service.moderate_perspective_submission(job)

    repos["sessions"].set_status.assert_awaited_once_with(
        SESSION_ID, MediationSessionStatus.AI_MEDIATION_PROCESSING
    )
    created_types = [
        call.args[0].job_type for call in repos["jobs"].create_job_if_not_exists.await_args_list
    ]
    assert created_types == [
        MediationAIJobType.PRIVATE_REFLECTION,
        MediationAIJobType.SHARED_MEDIATION_ADVICE,
    ]


@pytest.mark.asyncio
async def test_perspective_moderation_job_blocks_unsafe_perspective() -> None:
    service, repos = make_ai_service()
    pending = make_perspective(PerspectiveStatus.SUBMITTED_PENDING_REVIEW)
    job = MediationAIJob(
        job_type=MediationAIJobType.PERSPECTIVE_MODERATION,
        status=AIJobStatus.PROCESSING,
        session_id=SESSION_ID,
        source_entity_id=PERSPECTIVE_ID,
        source_entity_type="PERSPECTIVE",
        idempotency_key=f"perspective_moderation:{SESSION_ID}:{PERSPECTIVE_ID}",
        created_at=NOW,
        updated_at=NOW,
    )
    repos["perspectives"].get_by_id.return_value = pending
    repos["safety"].moderate_perspective.return_value = blocked_decision()
    repos["moderation"].insert.return_value = make_moderation()

    await service.moderate_perspective_submission(job)

    repos["perspectives"].mark_flagged.assert_awaited_once_with(PERSPECTIVE_ID, MODERATION_ID)
    repos["sessions"].set_safety_status.assert_awaited_once_with(
        SESSION_ID, SafetyStatus.BLOCKED
    )
    repos["jobs"].create_job_if_not_exists.assert_not_called()


@pytest.mark.asyncio
async def test_shared_advice_generation_ignores_pending_review_perspectives() -> None:
    service, repos = make_ai_service()
    job = MediationAIJob(
        job_type=MediationAIJobType.SHARED_MEDIATION_ADVICE,
        status=AIJobStatus.PROCESSING,
        session_id=SESSION_ID,
        source_entity_id=None,
        source_entity_type=None,
        idempotency_key=f"shared_advice:{SESSION_ID}",
        created_at=NOW,
        updated_at=NOW,
    )
    repos["sessions"].get_by_id.return_value = make_session(
        MediationSessionStatus.AI_MEDIATION_PROCESSING
    )
    repos["perspectives"].list_locked_for_session.return_value = [
        make_perspective(PerspectiveStatus.LOCKED)
    ]

    with pytest.raises(RuntimeError, match="Shared advice requires both perspectives"):
        await service.generate_shared_advice(job)

    repos["openai"].create_structured_response.assert_not_called()


@pytest.mark.asyncio
async def test_cannot_comment_before_advice_is_available() -> None:
    service, repos = make_service()
    repos["sessions"].get_by_id.return_value = make_session(
        MediationSessionStatus.PARTIAL_PERSPECTIVE_SUBMITTED
    )

    with pytest.raises(ConflictException):
        await service.list_comments(SESSION_ID, UserType.JORIS)

    repos["comments"].list_for_session.assert_not_called()


@pytest.mark.asyncio
async def test_job_repository_duplicate_result_shape_is_preserved() -> None:
    job = MediationAIJob(
        job_type=MediationAIJobType.PRIVATE_REFLECTION,
        status=AIJobStatus.PENDING,
        session_id=SESSION_ID,
        source_entity_id=PERSPECTIVE_ID,
        source_entity_type="PERSPECTIVE",
        idempotency_key=f"private_reflection:{SESSION_ID}:{PERSPECTIVE_ID}",
        created_at=NOW,
        updated_at=NOW,
    )

    assert job.idempotency_key.endswith(PERSPECTIVE_ID)
    assert job.status == AIJobStatus.PENDING


@pytest.mark.asyncio
async def test_first_resolve_mark_does_not_finalize_session() -> None:
    service, repos = make_service()
    session = make_session()
    repos["sessions"].get_by_id.return_value = session
    repos["sessions"].mark_resolved.return_value = session

    await service.resolve_session(SESSION_ID, UserType.JORIS)

    repos["sessions"].mark_resolved.assert_awaited_once()
    args = repos["sessions"].mark_resolved.await_args.args
    assert args[0] == SESSION_ID
    assert set(args[1]) == {UserType.JORIS}
    assert args[2] is False


@pytest.mark.asyncio
async def test_second_resolve_mark_finalizes_session() -> None:
    service, repos = make_service()
    session = make_session(resolved_by_user_types=[UserType.JORIS])
    repos["sessions"].get_by_id.return_value = session
    repos["sessions"].mark_resolved.return_value = make_session(
        MediationSessionStatus.RESOLVED,
        resolved_by_user_types=[UserType.JORIS, UserType.DANFENG],
    )

    await service.resolve_session(SESSION_ID, UserType.DANFENG)

    args = repos["sessions"].mark_resolved.await_args.args
    assert set(args[1]) == {UserType.JORIS, UserType.DANFENG}
    assert args[2] is True


@pytest.mark.asyncio
async def test_duplicate_pending_resolve_mark_is_idempotent() -> None:
    service, repos = make_service()
    session = make_session(resolved_by_user_types=[UserType.JORIS])
    repos["sessions"].get_by_id.return_value = session
    repos["sessions"].mark_resolved.return_value = session

    await service.resolve_session(SESSION_ID, UserType.JORIS)

    args = repos["sessions"].mark_resolved.await_args.args
    assert set(args[1]) == {UserType.JORIS}
    assert args[2] is False


@pytest.mark.asyncio
async def test_unresolve_removes_only_current_user_pending_mark() -> None:
    service, repos = make_service()
    session = make_session(resolved_by_user_types=[UserType.JORIS, UserType.DANFENG])
    repos["sessions"].get_by_id.return_value = session
    repos["sessions"].unmark_resolved.return_value = session

    await service.unresolve_session(SESSION_ID, UserType.JORIS)

    repos["sessions"].unmark_resolved.assert_awaited_once()
    args = repos["sessions"].unmark_resolved.await_args.args
    assert args[0] == SESSION_ID
    assert set(args[1]) == {UserType.DANFENG}


@pytest.mark.asyncio
async def test_unresolve_after_resolved_raises_conflict() -> None:
    service, repos = make_service()
    repos["sessions"].get_by_id.return_value = make_session(MediationSessionStatus.RESOLVED)

    with pytest.raises(ConflictException):
        await service.unresolve_session(SESSION_ID, UserType.JORIS)

    repos["sessions"].unmark_resolved.assert_not_called()


@pytest.mark.asyncio
async def test_first_unresolved_archive_mark_does_not_finalize_session() -> None:
    service, repos = make_service()
    session = make_session()
    repos["sessions"].get_by_id.return_value = session
    repos["sessions"].mark_archived.return_value = session

    await service.archive_session(SESSION_ID, UserType.JORIS)

    args = repos["sessions"].mark_archived.await_args.args
    assert args[0] == SESSION_ID
    assert set(args[1]) == {UserType.JORIS}
    assert args[2] is False


@pytest.mark.asyncio
async def test_second_unresolved_archive_mark_finalizes_session() -> None:
    service, repos = make_service()
    session = make_session(archived_by_user_types=[UserType.JORIS])
    repos["sessions"].get_by_id.return_value = session
    repos["sessions"].mark_archived.return_value = make_session(
        MediationSessionStatus.ARCHIVED,
        archived_by_user_types=[UserType.JORIS, UserType.DANFENG],
    )

    await service.archive_session(SESSION_ID, UserType.DANFENG)

    args = repos["sessions"].mark_archived.await_args.args
    assert set(args[1]) == {UserType.JORIS, UserType.DANFENG}
    assert args[2] is True


@pytest.mark.asyncio
async def test_resolved_archive_mark_finalizes_immediately() -> None:
    service, repos = make_service()
    session = make_session(MediationSessionStatus.RESOLVED)
    repos["sessions"].get_by_id.return_value = session
    repos["sessions"].mark_archived.return_value = session

    await service.archive_session(SESSION_ID, UserType.JORIS)

    args = repos["sessions"].mark_archived.await_args.args
    assert set(args[1]) == {UserType.JORIS}
    assert args[2] is True


@pytest.mark.asyncio
async def test_unarchive_removes_only_current_user_pending_mark() -> None:
    service, repos = make_service()
    session = make_session(archived_by_user_types=[UserType.JORIS, UserType.DANFENG])
    repos["sessions"].get_by_id.return_value = session
    repos["sessions"].unmark_archived.return_value = session

    await service.unarchive_session(SESSION_ID, UserType.DANFENG)

    args = repos["sessions"].unmark_archived.await_args.args
    assert args[0] == SESSION_ID
    assert set(args[1]) == {UserType.JORIS}
