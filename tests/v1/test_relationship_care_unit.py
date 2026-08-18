from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.schemas.v1.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.schemas.v1.relationship_care import (
    AgreementAcceptance,
    AgreementCreate,
    AgreementRevision,
    AgreementRevisionCreate,
    AgreementStatus,
    FairnessType,
    GoalVisibility,
    PersonalBoundary,
    PersonalBoundaryUpdate,
    PersonalGoalCreate,
    PersonalGoalUpdate,
    RelationshipAgreement,
)
from app.schemas.v1.user import UserType
from app.services.relationship_care import RelationshipCareService

NOW = datetime(2026, 8, 18, tzinfo=UTC)
AGREEMENT_ID = "64a7f0c2f1d2c4b5a6e7d8f1"
REVISION_ID = "64a7f0c2f1d2c4b5a6e7d8f2"
NEW_REVISION_ID = "64a7f0c2f1d2c4b5a6e7d8f3"
BOUNDARY_ID = "64a7f0c2f1d2c4b5a6e7d8f4"


def make_agreement(status: AgreementStatus = AgreementStatus.PROPOSED) -> RelationshipAgreement:
    return RelationshipAgreement(
        id=AGREEMENT_ID,
        created_by_user_type=UserType.JORIS,
        status=status,
        current_revision_id=REVISION_ID,
        current_revision_number=1,
        proposed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def make_revision(revision_id: str = REVISION_ID, number: int = 1) -> AgreementRevision:
    return AgreementRevision(
        id=revision_id,
        agreement_id=AGREEMENT_ID,
        revision_number=number,
        title="Protecting us during conflict",
        why_it_matters="Conflict should remain emotionally safe.",
        agreement_text="Either person may pause and commits to return later.",
        fairness_type=FairnessType.SYMMETRIC,
        created_by_user_type=UserType.JORIS,
        created_at=NOW,
    )


def make_acceptance(user_type: UserType) -> AgreementAcceptance:
    return AgreementAcceptance(
        agreement_id=AGREEMENT_ID,
        revision_id=REVISION_ID,
        user_type=user_type,
        accepted_at=NOW,
    )


def make_service() -> tuple[RelationshipCareService, dict[str, AsyncMock]]:
    repos = {
        "boundaries": AsyncMock(),
        "requests": AsyncMock(),
        "goals": AsyncMock(),
        "agreements": AsyncMock(),
        "revisions": AsyncMock(),
        "acceptances": AsyncMock(),
        "responses": AsyncMock(),
    }
    service = RelationshipCareService(
        boundary_repo=repos["boundaries"],
        request_repo=repos["requests"],
        goal_repo=repos["goals"],
        agreement_repo=repos["agreements"],
        revision_repo=repos["revisions"],
        acceptance_repo=repos["acceptances"],
        response_repo=repos["responses"],
    )
    service.get_agreement_detail = AsyncMock()  # type: ignore[method-assign]
    return service, repos


def revision_payload() -> AgreementRevisionCreate:
    return AgreementRevisionCreate(
        expected_current_revision_id=REVISION_ID,
        title="Protecting us during conflict",
        why_it_matters="Conflict should remain emotionally safe.",
        agreement_text="We pause before speaking cruelly and return later.",
        fairness_type=FairnessType.SYMMETRIC,
    )


def test_asymmetric_agreement_requires_explanation() -> None:
    with pytest.raises(ValidationError):
        AgreementCreate(
            title="Different schedules",
            why_it_matters="We have different working hours.",
            agreement_text="One person handles mornings and the other evenings.",
            fairness_type=FairnessType.ASYMMETRIC,
        )


def test_personal_goal_defaults_private_and_validates_required_fields() -> None:
    goal = PersonalGoalCreate(title="A calmer response", goal="Pause before replying.")
    assert goal.visibility == GoalVisibility.PRIVATE

    with pytest.raises(ValidationError):
        PersonalGoalCreate(title="  ", goal="Pause before replying.")
    with pytest.raises(ValidationError):
        PersonalGoalCreate(title="A calmer response", goal="  ")
    with pytest.raises(ValidationError):
        PersonalGoalUpdate(goal="  ")


@pytest.mark.asyncio
async def test_partner_cannot_edit_personal_boundary() -> None:
    service, repos = make_service()
    repos["boundaries"].get_by_id.return_value = PersonalBoundary(
        id=BOUNDARY_ID,
        owner_user_type=UserType.JORIS,
        title="Respectful pauses",
        what_i_need="I need conversations without insults.",
        what_i_will_do="I will pause when a conversation becomes insulting.",
        created_at=NOW,
        updated_at=NOW,
    )

    with pytest.raises(ForbiddenException):
        await service.update_boundary(
            BOUNDARY_ID,
            PersonalBoundaryUpdate(title="Changed by partner"),
            UserType.DANFENG,
        )

    repos["boundaries"].update_owned.assert_not_called()


@pytest.mark.asyncio
async def test_partner_cannot_restore_personal_boundary() -> None:
    service, repos = make_service()
    repos["boundaries"].get_by_id.return_value = PersonalBoundary(
        id=BOUNDARY_ID,
        owner_user_type=UserType.JORIS,
        title="Respectful pauses",
        what_i_need="I need conversations without insults.",
        what_i_will_do="I will pause when a conversation becomes insulting.",
        created_at=NOW,
        updated_at=NOW,
        archived_at=NOW,
    )

    with pytest.raises(ForbiddenException):
        await service.restore_boundary(BOUNDARY_ID, UserType.DANFENG)

    repos["boundaries"].restore_owned.assert_not_called()


@pytest.mark.asyncio
async def test_partner_cannot_see_private_draft() -> None:
    service, repos = make_service()
    draft = make_agreement(AgreementStatus.DRAFT)
    draft.proposed_at = None
    repos["agreements"].get_by_id.return_value = draft

    with pytest.raises(NotFoundException):
        await service._get_visible_agreement(AGREEMENT_ID, UserType.DANFENG)


@pytest.mark.asyncio
async def test_proposal_does_not_create_acceptance() -> None:
    service, repos = make_service()
    draft = make_agreement(AgreementStatus.DRAFT)
    draft.proposed_at = None
    repos["agreements"].get_by_id.return_value = draft
    repos["agreements"].set_status.return_value = make_agreement(AgreementStatus.PROPOSED)

    await service.propose_agreement(AGREEMENT_ID, UserType.JORIS)

    repos["acceptances"].accept.assert_not_called()
    repos["agreements"].set_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_one_acceptance_is_not_enough() -> None:
    service, repos = make_service()
    agreement = make_agreement()
    revision = make_revision()
    repos["revisions"].get_by_id.return_value = revision
    repos["agreements"].get_by_id.return_value = agreement
    repos["acceptances"].list_active_for_revision.side_effect = [
        [],
        [make_acceptance(UserType.JORIS)],
    ]

    await service.accept_revision(REVISION_ID, UserType.JORIS)

    repos["acceptances"].accept.assert_awaited_once()
    repos["agreements"].set_status.assert_not_called()


@pytest.mark.asyncio
async def test_both_acceptances_activate_exact_revision() -> None:
    service, repos = make_service()
    agreement = make_agreement(AgreementStatus.DISCUSSING)
    revision = make_revision()
    repos["revisions"].get_by_id.return_value = revision
    repos["agreements"].get_by_id.return_value = agreement
    repos["acceptances"].list_active_for_revision.side_effect = [
        [make_acceptance(UserType.JORIS)],
        [make_acceptance(UserType.JORIS), make_acceptance(UserType.DANFENG)],
    ]
    repos["agreements"].set_status.return_value = make_agreement(AgreementStatus.AGREED)

    await service.accept_revision(REVISION_ID, UserType.DANFENG)

    repos["agreements"].set_status.assert_awaited_once_with(
        AGREEMENT_ID,
        AgreementStatus.AGREED,
        expected_revision_id=REVISION_ID,
        extra={"last_agreed_revision_id": REVISION_ID},
    )
    repos["revisions"].mark_agreed.assert_awaited_once_with(REVISION_ID)


@pytest.mark.asyncio
async def test_cannot_accept_stale_revision() -> None:
    service, repos = make_service()
    agreement = make_agreement()
    agreement.current_revision_id = NEW_REVISION_ID
    repos["revisions"].get_by_id.return_value = make_revision()
    repos["agreements"].get_by_id.return_value = agreement

    with pytest.raises(ConflictException):
        await service.accept_revision(REVISION_ID, UserType.JORIS)

    repos["acceptances"].accept.assert_not_called()


@pytest.mark.asyncio
async def test_editing_agreed_content_creates_unaccepted_revisit_revision() -> None:
    service, repos = make_service()
    agreement = make_agreement(AgreementStatus.AGREED)
    agreement.last_agreed_revision_id = REVISION_ID
    previous = make_revision()
    created = make_revision(NEW_REVISION_ID, 2)
    repos["agreements"].get_by_id.return_value = agreement
    repos["revisions"].get_by_id.return_value = previous
    repos["revisions"].create.return_value = created
    repos["agreements"].replace_current_revision.return_value = make_agreement(
        AgreementStatus.REVISIT
    )

    await service.create_revision(AGREEMENT_ID, revision_payload(), UserType.JORIS)

    args = repos["agreements"].replace_current_revision.await_args.args
    assert args[:5] == (
        AGREEMENT_ID,
        REVISION_ID,
        NEW_REVISION_ID,
        2,
        AgreementStatus.REVISIT,
    )
    repos["acceptances"].accept.assert_not_called()


@pytest.mark.asyncio
async def test_first_shared_archive_request_revisits_but_does_not_archive() -> None:
    service, repos = make_service()
    agreement = make_agreement(AgreementStatus.AGREED)
    agreement.last_agreed_revision_id = REVISION_ID
    repos["agreements"].get_by_id.return_value = agreement

    await service.request_archive(AGREEMENT_ID, UserType.JORIS)

    repos["acceptances"].revoke.assert_awaited_once_with(REVISION_ID, UserType.JORIS)
    kwargs = repos["agreements"].set_archive_requests.await_args.kwargs
    assert kwargs["status"] == AgreementStatus.REVISIT
    assert kwargs["finalize"] is False


@pytest.mark.asyncio
async def test_second_shared_archive_request_finalizes() -> None:
    service, repos = make_service()
    agreement = make_agreement(AgreementStatus.REVISIT)
    agreement.archive_requested_by_user_types = [UserType.JORIS]
    agreement.last_agreed_revision_id = REVISION_ID
    repos["agreements"].get_by_id.return_value = agreement

    await service.request_archive(AGREEMENT_ID, UserType.DANFENG)

    kwargs = repos["agreements"].set_archive_requests.await_args.kwargs
    assert kwargs["finalize"] is True
