from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from app.core.config import get_settings
from app.db.mongo_client import AsyncDB, get_test_db
from app.repositories.relationship_care import (
    AgreementAcceptanceRepository,
    AgreementResponseRepository,
    AgreementRevisionRepository,
    PersonalBoundaryRepository,
    PersonalGoalRepository,
    RelationshipAgreementRepository,
    RelationshipRequestRepository,
    ensure_relationship_care_indexes,
)
from app.schemas.v1.exceptions import ForbiddenException, NotFoundException
from app.schemas.v1.relationship_care import (
    AgreementCreate,
    AgreementRevisionCreate,
    AgreementStatus,
    FairnessType,
    GoalVisibility,
    MyAgreementPerspective,
    PersonalBoundaryCreate,
    PersonalGoalCategory,
    PersonalGoalCreate,
    PersonalGoalUpdate,
    RelationshipCareCategory,
    RelationshipRequestCreate,
)
from app.schemas.v1.user import UserType
from app.services.relationship_care import RelationshipCareService

settings = get_settings()


@pytest_asyncio.fixture
async def relationship_care_service() -> AsyncGenerator[RelationshipCareService]:
    db: AsyncDB = get_test_db()
    collection_names = [
        settings.relationship_boundaries_collection_name,
        settings.relationship_requests_collection_name,
        settings.personal_goals_collection_name,
        settings.relationship_agreements_collection_name,
        settings.agreement_revisions_collection_name,
        settings.agreement_acceptances_collection_name,
        settings.agreement_responses_collection_name,
    ]
    for name in collection_names:
        await db[name].delete_many({})
    await ensure_relationship_care_indexes(db)
    yield RelationshipCareService(
        boundary_repo=PersonalBoundaryRepository(db),
        request_repo=RelationshipRequestRepository(db),
        goal_repo=PersonalGoalRepository(db),
        agreement_repo=RelationshipAgreementRepository(db),
        revision_repo=AgreementRevisionRepository(db),
        acceptance_repo=AgreementAcceptanceRepository(db),
        response_repo=AgreementResponseRepository(db),
    )
    for name in collection_names:
        await db[name].delete_many({})


@pytest.mark.asyncio
async def test_exact_revision_consent_and_history_workflow(
    relationship_care_service: RelationshipCareService,
) -> None:
    service = relationship_care_service
    draft = await service.create_agreement(
        AgreementCreate(
            title="Protecting us during conflict",
            why_it_matters="Arguments should not make the relationship feel unsafe.",
            agreement_text="Either person may pause and commits to return later.",
            fairness_type=FairnessType.SYMMETRIC,
            my_perspective=MyAgreementPerspective(
                what_i_need="Disagreement without threats.",
                what_i_commit_to="I will pause instead of speaking cruelly.",
            ),
        ),
        UserType.JORIS,
    )
    agreement_id = str(draft.agreement.id)
    first_revision_id = str(draft.current_revision.revision.id)
    assert draft.agreement.status == AgreementStatus.DRAFT

    proposed = await service.propose_agreement(agreement_id, UserType.JORIS)
    assert proposed.agreement.status == AgreementStatus.PROPOSED

    changed = await service.create_revision(
        agreement_id,
        AgreementRevisionCreate(
            expected_current_revision_id=first_revision_id,
            title="Protecting us during conflict",
            why_it_matters="Arguments should not make the relationship feel unsafe.",
            agreement_text=(
                "Either person may pause, say when they will return, and then reconnect."
            ),
            fairness_type=FairnessType.SYMMETRIC,
            my_perspective=MyAgreementPerspective(
                what_i_need="A clear time to reconnect.",
                what_i_commit_to="I will respect a pause without pursuing the argument.",
            ),
        ),
        UserType.DANFENG,
    )
    second_revision_id = str(changed.current_revision.revision.id)
    assert changed.agreement.status == AgreementStatus.DISCUSSING
    assert second_revision_id != first_revision_id
    assert changed.current_revision.acceptances == []

    one_acceptance = await service.accept_revision(second_revision_id, UserType.JORIS)
    assert one_acceptance.agreement.status == AgreementStatus.DISCUSSING
    active_acceptances = [
        item for item in one_acceptance.current_revision.acceptances if not item.revoked_at
    ]
    assert len(active_acceptances) == 1

    agreed = await service.accept_revision(second_revision_id, UserType.DANFENG)
    assert agreed.agreement.status == AgreementStatus.AGREED
    assert agreed.agreement.last_agreed_revision_id == second_revision_id
    assert agreed.current_revision.revision.agreed_at is not None

    revisited = await service.create_revision(
        agreement_id,
        AgreementRevisionCreate(
            expected_current_revision_id=second_revision_id,
            title="Protecting us during conflict",
            why_it_matters="Arguments should not make the relationship feel unsafe.",
            agreement_text=(
                "Either person may pause and proposes a reconnection time within one day."
            ),
            fairness_type=FairnessType.SYMMETRIC,
        ),
        UserType.JORIS,
    )
    assert revisited.agreement.status == AgreementStatus.REVISIT
    assert revisited.current_revision.acceptances == []
    historical = next(
        item for item in revisited.history if str(item.revision.id) == second_revision_id
    )
    assert historical.revision.agreed_at is not None
    assert {item.user_type for item in historical.acceptances if not item.revoked_at} == {
        UserType.JORIS,
        UserType.DANFENG,
    }


@pytest.mark.asyncio
async def test_personal_items_can_be_archived_and_restored(
    relationship_care_service: RelationshipCareService,
) -> None:
    service = relationship_care_service
    boundary = await service.create_boundary(
        PersonalBoundaryCreate(
            title="Respectful pauses",
            what_i_need="Conversations without insults.",
            what_i_will_do="I will pause and return later.",
            category=RelationshipCareCategory.CONFLICT,
        ),
        UserType.JORIS,
    )
    request = await service.create_request(
        RelationshipRequestCreate(
            title="A bedtime call",
            description="A short call before sleeping when we are apart.",
            why_it_matters="It helps me feel connected.",
            category=RelationshipCareCategory.COMMUNICATION,
        ),
        UserType.JORIS,
    )

    await service.archive_boundary(boundary.id, UserType.JORIS)
    await service.archive_request(request.id, UserType.JORIS)
    archived = await service.overview(UserType.JORIS)
    assert [item.id for item in archived.archived_boundaries] == [boundary.id]
    assert [item.id for item in archived.archived_requests] == [request.id]
    assert archived.boundaries == []
    assert archived.requests == []

    restored_boundary = await service.restore_boundary(boundary.id, UserType.JORIS)
    restored_request = await service.restore_request(request.id, UserType.JORIS)
    assert restored_boundary.archived_at is None
    assert restored_request.archived_at is None
    restored = await service.overview(UserType.JORIS)
    assert [item.id for item in restored.boundaries] == [boundary.id]
    assert [item.id for item in restored.requests] == [request.id]
    assert restored.archived_boundaries == []
    assert restored.archived_requests == []


@pytest.mark.asyncio
async def test_personal_goal_privacy_sharing_and_archive_lifecycle(
    relationship_care_service: RelationshipCareService,
) -> None:
    service = relationship_care_service
    goal = await service.create_goal(
        PersonalGoalCreate(
            title="Pause before reacting",
            goal="Notice strong feelings and take one breath before responding.",
            why_it_matters="I want conflict to feel safer.",
            trigger="When I feel misunderstood.",
            practice="Name the feeling before answering.",
            reminder="Slowing down is caring for both of us.",
            category=PersonalGoalCategory.EMOTIONAL_REGULATION,
        ),
        UserType.JORIS,
    )
    assert goal.visibility == GoalVisibility.PRIVATE
    assert goal.is_mine is True

    partner_overview = await service.overview(UserType.DANFENG)
    assert partner_overview.goals == []
    with pytest.raises(NotFoundException):
        await service.get_goal(goal.id, UserType.DANFENG)
    with pytest.raises(NotFoundException):
        await service.update_goal(
            goal.id,
            PersonalGoalUpdate(title="A guessed private goal"),
            UserType.DANFENG,
        )

    shared = await service.update_goal(
        goal.id,
        PersonalGoalUpdate(
            title="Pause and respond with care",
            visibility=GoalVisibility.SHARED_WITH_PARTNER,
        ),
        UserType.JORIS,
    )
    assert shared.title == "Pause and respond with care"
    assert shared.visibility == GoalVisibility.SHARED_WITH_PARTNER
    assert [item.id for item in (await service.overview(UserType.DANFENG)).goals] == [goal.id]
    partner_view = await service.get_goal(goal.id, UserType.DANFENG)
    assert partner_view.is_mine is False
    assert partner_view.practice == "Name the feeling before answering."
    with pytest.raises(ForbiddenException):
        await service.update_goal(
            goal.id,
            PersonalGoalUpdate(title="Partner edit"),
            UserType.DANFENG,
        )
    with pytest.raises(ForbiddenException):
        await service.archive_goal(goal.id, UserType.DANFENG)

    await service.update_goal(
        goal.id,
        PersonalGoalUpdate(visibility=GoalVisibility.PRIVATE),
        UserType.JORIS,
    )
    with pytest.raises(NotFoundException):
        await service.get_goal(goal.id, UserType.DANFENG)
    with pytest.raises(NotFoundException):
        await service.restore_goal(goal.id, UserType.DANFENG)

    await service.update_goal(
        goal.id,
        PersonalGoalUpdate(visibility=GoalVisibility.SHARED_WITH_PARTNER),
        UserType.JORIS,
    )
    archived = await service.archive_goal(goal.id, UserType.JORIS)
    assert archived.archived_at is not None
    with pytest.raises(NotFoundException):
        await service.get_goal(goal.id, UserType.DANFENG)
    owner_overview = await service.overview(UserType.JORIS)
    assert owner_overview.goals == []
    assert [item.id for item in owner_overview.archived_goals] == [goal.id]
    assert (await service.overview(UserType.DANFENG)).archived_goals == []

    restored = await service.restore_goal(goal.id, UserType.JORIS)
    assert restored.archived_at is None
    assert [item.id for item in (await service.overview(UserType.DANFENG)).goals] == [goal.id]
