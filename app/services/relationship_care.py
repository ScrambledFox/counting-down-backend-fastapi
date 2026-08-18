from typing import Annotated

from fastapi import Depends
from pymongo.errors import DuplicateKeyError

from app.repositories.relationship_care import (
    AgreementAcceptanceRepository,
    AgreementResponseRepository,
    AgreementRevisionRepository,
    PersonalBoundaryRepository,
    PersonalGoalRepository,
    RelationshipAgreementRepository,
    RelationshipRequestRepository,
)
from app.schemas.v1.base import MongoId
from app.schemas.v1.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.schemas.v1.relationship_care import (
    AgreementCreate,
    AgreementDetail,
    AgreementPerspective,
    AgreementResponse,
    AgreementResponseCreate,
    AgreementRevision,
    AgreementRevisionCreate,
    AgreementRevisionView,
    AgreementStatus,
    AgreementSummary,
    GoalVisibility,
    MyAgreementPerspective,
    PersonalBoundary,
    PersonalBoundaryCreate,
    PersonalBoundaryUpdate,
    PersonalBoundaryView,
    PersonalGoal,
    PersonalGoalCreate,
    PersonalGoalUpdate,
    PersonalGoalView,
    RelationshipAgreement,
    RelationshipCareOverview,
    RelationshipRequest,
    RelationshipRequestCreate,
    RelationshipRequestUpdate,
    RelationshipRequestView,
)
from app.schemas.v1.user import UserType
from app.util.time import utc_now
from app.util.user import get_other_user_type

ALL_USERS = {UserType.JORIS, UserType.DANFENG}


class RelationshipCareService:
    def __init__(
        self,
        boundary_repo: Annotated[PersonalBoundaryRepository, Depends()],
        request_repo: Annotated[RelationshipRequestRepository, Depends()],
        goal_repo: Annotated[PersonalGoalRepository, Depends()],
        agreement_repo: Annotated[RelationshipAgreementRepository, Depends()],
        revision_repo: Annotated[AgreementRevisionRepository, Depends()],
        acceptance_repo: Annotated[AgreementAcceptanceRepository, Depends()],
        response_repo: Annotated[AgreementResponseRepository, Depends()],
    ) -> None:
        self._boundaries = boundary_repo
        self._requests = request_repo
        self._goals = goal_repo
        self._agreements = agreement_repo
        self._revisions = revision_repo
        self._acceptances = acceptance_repo
        self._responses = response_repo

    async def list_boundaries(self, current_user: UserType) -> list[PersonalBoundaryView]:
        items = await self._boundaries.list_active()
        return [
            PersonalBoundaryView(**item.model_dump(), is_mine=item.owner_user_type == current_user)
            for item in items
        ]

    async def get_boundary(
        self, boundary_id: MongoId, current_user: UserType
    ) -> PersonalBoundaryView:
        item = await self._boundaries.get_by_id(boundary_id)
        if not item or (item.archived_at and item.owner_user_type != current_user):
            raise NotFoundException("Boundary", boundary_id)
        return PersonalBoundaryView(
            **item.model_dump(), is_mine=item.owner_user_type == current_user
        )

    async def create_boundary(
        self, payload: PersonalBoundaryCreate, current_user: UserType
    ) -> PersonalBoundaryView:
        now = utc_now()
        item = await self._boundaries.create(
            PersonalBoundary(
                **payload.model_dump(),
                owner_user_type=current_user,
                created_at=now,
                updated_at=now,
            )
        )
        return PersonalBoundaryView(**item.model_dump(), is_mine=True)

    async def list_archived_boundaries(self, current_user: UserType) -> list[PersonalBoundaryView]:
        items = await self._boundaries.list_archived_owned(current_user)
        return [PersonalBoundaryView(**item.model_dump(), is_mine=True) for item in items]

    async def update_boundary(
        self, boundary_id: MongoId, payload: PersonalBoundaryUpdate, current_user: UserType
    ) -> PersonalBoundaryView:
        existing = await self._boundaries.get_by_id(boundary_id)
        self._assert_owned(existing, current_user, "Boundary", boundary_id)
        updated = await self._boundaries.update_owned(
            boundary_id, current_user, payload.model_dump(exclude_unset=True)
        )
        if not updated:
            raise ConflictException("Archived boundaries cannot be edited")
        return PersonalBoundaryView(**updated.model_dump(), is_mine=True)

    async def archive_boundary(
        self, boundary_id: MongoId, current_user: UserType
    ) -> PersonalBoundaryView:
        existing = await self._boundaries.get_by_id(boundary_id)
        self._assert_owned(existing, current_user, "Boundary", boundary_id)
        archived = await self._boundaries.archive_owned(boundary_id, current_user)
        if not archived:
            raise ConflictException("Boundary is already archived")
        return PersonalBoundaryView(**archived.model_dump(), is_mine=True)

    async def restore_boundary(
        self, boundary_id: MongoId, current_user: UserType
    ) -> PersonalBoundaryView:
        existing = await self._boundaries.get_by_id(boundary_id)
        self._assert_owned(existing, current_user, "Boundary", boundary_id)
        restored = await self._boundaries.restore_owned(boundary_id, current_user)
        if not restored:
            raise ConflictException("Boundary is not archived")
        return PersonalBoundaryView(**restored.model_dump(), is_mine=True)

    async def list_requests(self, current_user: UserType) -> list[RelationshipRequestView]:
        items = await self._requests.list_active()
        return [
            RelationshipRequestView(
                **item.model_dump(), is_mine=item.owner_user_type == current_user
            )
            for item in items
        ]

    async def get_request(
        self, request_id: MongoId, current_user: UserType
    ) -> RelationshipRequestView:
        item = await self._requests.get_by_id(request_id)
        if not item or (item.archived_at and item.owner_user_type != current_user):
            raise NotFoundException("Request", request_id)
        return RelationshipRequestView(
            **item.model_dump(), is_mine=item.owner_user_type == current_user
        )

    async def create_request(
        self, payload: RelationshipRequestCreate, current_user: UserType
    ) -> RelationshipRequestView:
        now = utc_now()
        item = await self._requests.create(
            RelationshipRequest(
                **payload.model_dump(),
                owner_user_type=current_user,
                created_at=now,
                updated_at=now,
            )
        )
        return RelationshipRequestView(**item.model_dump(), is_mine=True)

    async def list_archived_requests(self, current_user: UserType) -> list[RelationshipRequestView]:
        items = await self._requests.list_archived_owned(current_user)
        return [RelationshipRequestView(**item.model_dump(), is_mine=True) for item in items]

    async def update_request(
        self, request_id: MongoId, payload: RelationshipRequestUpdate, current_user: UserType
    ) -> RelationshipRequestView:
        existing = await self._requests.get_by_id(request_id)
        self._assert_owned(existing, current_user, "Request", request_id)
        updated = await self._requests.update_owned(
            request_id, current_user, payload.model_dump(exclude_unset=True)
        )
        if not updated:
            raise ConflictException("Archived requests cannot be edited")
        return RelationshipRequestView(**updated.model_dump(), is_mine=True)

    async def archive_request(
        self, request_id: MongoId, current_user: UserType
    ) -> RelationshipRequestView:
        existing = await self._requests.get_by_id(request_id)
        self._assert_owned(existing, current_user, "Request", request_id)
        archived = await self._requests.archive_owned(request_id, current_user)
        if not archived:
            raise ConflictException("Request is already archived")
        return RelationshipRequestView(**archived.model_dump(), is_mine=True)

    async def restore_request(
        self, request_id: MongoId, current_user: UserType
    ) -> RelationshipRequestView:
        existing = await self._requests.get_by_id(request_id)
        self._assert_owned(existing, current_user, "Request", request_id)
        restored = await self._requests.restore_owned(request_id, current_user)
        if not restored:
            raise ConflictException("Request is not archived")
        return RelationshipRequestView(**restored.model_dump(), is_mine=True)

    async def list_goals(self, current_user: UserType) -> list[PersonalGoalView]:
        items = await self._goals.list_visible(current_user)
        return [
            PersonalGoalView(**item.model_dump(), is_mine=item.owner_user_type == current_user)
            for item in items
        ]

    async def list_archived_goals(self, current_user: UserType) -> list[PersonalGoalView]:
        items = await self._goals.list_archived_owned(current_user)
        return [PersonalGoalView(**item.model_dump(), is_mine=True) for item in items]

    async def get_goal(self, goal_id: MongoId, current_user: UserType) -> PersonalGoalView:
        item = await self._goals.get_by_id(goal_id)
        if not item or (
            item.owner_user_type != current_user
            and (
                item.archived_at is not None
                or item.visibility != GoalVisibility.SHARED_WITH_PARTNER
            )
        ):
            raise NotFoundException("Personal goal", goal_id)
        return PersonalGoalView(**item.model_dump(), is_mine=item.owner_user_type == current_user)

    async def create_goal(
        self, payload: PersonalGoalCreate, current_user: UserType
    ) -> PersonalGoalView:
        now = utc_now()
        item = await self._goals.create(
            PersonalGoal(
                **payload.model_dump(),
                owner_user_type=current_user,
                created_at=now,
                updated_at=now,
            )
        )
        return PersonalGoalView(**item.model_dump(), is_mine=True)

    async def update_goal(
        self, goal_id: MongoId, payload: PersonalGoalUpdate, current_user: UserType
    ) -> PersonalGoalView:
        existing = await self._goals.get_by_id(goal_id)
        self._assert_goal_owned(existing, current_user, goal_id)
        updated = await self._goals.update_owned(
            goal_id, current_user, payload.model_dump(exclude_unset=True)
        )
        if not updated:
            raise ConflictException("Archived personal goals cannot be edited")
        return PersonalGoalView(**updated.model_dump(), is_mine=True)

    async def archive_goal(self, goal_id: MongoId, current_user: UserType) -> PersonalGoalView:
        existing = await self._goals.get_by_id(goal_id)
        self._assert_goal_owned(existing, current_user, goal_id)
        archived = await self._goals.archive_owned(goal_id, current_user)
        if not archived:
            raise ConflictException("Personal goal is already archived")
        return PersonalGoalView(**archived.model_dump(), is_mine=True)

    async def restore_goal(self, goal_id: MongoId, current_user: UserType) -> PersonalGoalView:
        existing = await self._goals.get_by_id(goal_id)
        self._assert_goal_owned(existing, current_user, goal_id)
        restored = await self._goals.restore_owned(goal_id, current_user)
        if not restored:
            raise ConflictException("Personal goal is not archived")
        return PersonalGoalView(**restored.model_dump(), is_mine=True)

    def _assert_goal_owned(
        self, item: PersonalGoal | None, current_user: UserType, goal_id: MongoId
    ) -> None:
        if not item:
            raise NotFoundException("Personal goal", goal_id)
        if item.owner_user_type == current_user:
            return
        if item.archived_at is None and item.visibility == GoalVisibility.SHARED_WITH_PARTNER:
            raise ForbiddenException("Only the owner may change this personal goal")
        raise NotFoundException("Personal goal", goal_id)

    def _assert_owned(
        self,
        item: PersonalBoundary | RelationshipRequest | None,
        current_user: UserType,
        type_name: str,
        item_id: MongoId,
    ) -> None:
        if not item:
            raise NotFoundException(type_name, item_id)
        if item.owner_user_type != current_user:
            raise ForbiddenException(f"Only the owner may change this {type_name.lower()}")

    async def _get_visible_agreement(
        self, agreement_id: MongoId, current_user: UserType
    ) -> RelationshipAgreement:
        agreement = await self._agreements.get_by_id(agreement_id)
        if not agreement:
            raise NotFoundException("Agreement", agreement_id)
        if agreement.proposed_at is None and agreement.created_by_user_type != current_user:
            raise NotFoundException("Agreement", agreement_id)
        return agreement

    async def _revision_view(self, revision: AgreementRevision) -> AgreementRevisionView:
        acceptances = await self._acceptances.list_for_revision(str(revision.id))
        responses = await self._responses.list_for_revision(str(revision.id))
        return AgreementRevisionView(
            revision=revision, acceptances=acceptances, responses=responses
        )

    async def get_agreement_detail(
        self, agreement_id: MongoId, current_user: UserType
    ) -> AgreementDetail:
        agreement = await self._get_visible_agreement(agreement_id, current_user)
        if not agreement.current_revision_id:
            raise ConflictException("Agreement has no current revision")
        revisions = await self._revisions.list_for_agreement(agreement_id)
        current = next(
            (item for item in revisions if str(item.id) == agreement.current_revision_id), None
        )
        if not current:
            raise ConflictException("Agreement current revision is unavailable")
        current_view = await self._revision_view(current)
        history = [await self._revision_view(item) for item in revisions]
        active_users = {
            item.user_type for item in current_view.acceptances if item.revoked_at is None
        }
        can_accept = (
            agreement.status
            in {AgreementStatus.PROPOSED, AgreementStatus.DISCUSSING, AgreementStatus.REVISIT}
            and current_user not in active_users
        )
        return AgreementDetail(
            agreement=agreement,
            current_revision=current_view,
            history=history,
            current_user_type=current_user,
            partner_user_type=get_other_user_type(current_user),
            can_edit=agreement.status != AgreementStatus.ARCHIVED,
            can_propose=(
                agreement.status == AgreementStatus.DRAFT
                and agreement.created_by_user_type == current_user
            ),
            can_accept=can_accept,
        )

    async def _summary(
        self, agreement: RelationshipAgreement, current_user: UserType
    ) -> AgreementSummary:
        if not agreement.current_revision_id:
            raise ConflictException("Agreement has no current revision")
        revision = await self._revisions.get_by_id(agreement.current_revision_id)
        if not revision:
            raise ConflictException("Agreement current revision is unavailable")
        acceptances = await self._acceptances.list_active_for_revision(
            agreement.current_revision_id
        )
        responses = await self._responses.list_for_revision(agreement.current_revision_id)
        accepted = {item.user_type for item in acceptances}
        responded = {item.user_type for item in responses}
        partner = get_other_user_type(current_user)
        return AgreementSummary(
            id=str(agreement.id),
            status=agreement.status,
            title=revision.title,
            agreement_text=revision.agreement_text,
            fairness_type=revision.fairness_type,
            revision_number=revision.revision_number,
            updated_at=agreement.updated_at,
            is_creator=agreement.created_by_user_type == current_user,
            has_my_acceptance=current_user in accepted,
            has_partner_acceptance=partner in accepted,
            needs_my_response=(
                agreement.status
                in {AgreementStatus.PROPOSED, AgreementStatus.DISCUSSING, AgreementStatus.REVISIT}
                and current_user not in accepted
                and current_user not in responded
            ),
        )

    async def list_agreements(
        self, current_user: UserType, *, include_archived: bool = False
    ) -> list[AgreementSummary]:
        agreements = await self._agreements.list_visible(
            current_user, include_archived=include_archived
        )
        return [await self._summary(item, current_user) for item in agreements]

    async def overview(self, current_user: UserType) -> RelationshipCareOverview:
        agreements = await self.list_agreements(current_user)
        counts = {status.value: 0 for status in AgreementStatus}
        for item in agreements:
            counts[item.status.value] += 1
        return RelationshipCareOverview(
            current_user_type=current_user,
            partner_user_type=get_other_user_type(current_user),
            agreement_counts=counts,
            agreements=agreements,
            boundaries=await self.list_boundaries(current_user),
            requests=await self.list_requests(current_user),
            archived_boundaries=await self.list_archived_boundaries(current_user),
            archived_requests=await self.list_archived_requests(current_user),
            goals=await self.list_goals(current_user),
            archived_goals=await self.list_archived_goals(current_user),
        )

    def _perspectives_for_revision(
        self,
        current_user: UserType,
        my_perspective: MyAgreementPerspective | None,
        previous: AgreementRevision | None = None,
    ) -> list[AgreementPerspective]:
        by_user = {item.user_type: item for item in (previous.perspectives if previous else [])}
        if my_perspective is not None:
            by_user[current_user] = AgreementPerspective(
                user_type=current_user,
                **my_perspective.model_dump(),
            )
        return list(by_user.values())

    async def create_agreement(
        self, payload: AgreementCreate, current_user: UserType
    ) -> AgreementDetail:
        now = utc_now()
        agreement = await self._agreements.create(
            RelationshipAgreement(
                created_by_user_type=current_user,
                status=AgreementStatus.DRAFT,
                created_at=now,
                updated_at=now,
            )
        )
        if not agreement.id:
            raise ConflictException("Agreement could not be created")
        revision = await self._revisions.create(
            AgreementRevision(
                agreement_id=str(agreement.id),
                revision_number=1,
                title=payload.title,
                why_it_matters=payload.why_it_matters,
                agreement_text=payload.agreement_text,
                fairness_type=payload.fairness_type,
                fairness_explanation=payload.fairness_explanation,
                perspectives=self._perspectives_for_revision(current_user, payload.my_perspective),
                created_by_user_type=current_user,
                created_at=now,
            )
        )
        if not revision.id:
            raise ConflictException("Agreement revision could not be created")
        initialized = await self._agreements.set_initial_revision(
            str(agreement.id), str(revision.id)
        )
        if not initialized:
            raise ConflictException("Agreement could not be initialized")
        return await self.get_agreement_detail(str(agreement.id), current_user)

    async def propose_agreement(
        self, agreement_id: MongoId, current_user: UserType
    ) -> AgreementDetail:
        agreement = await self._get_visible_agreement(agreement_id, current_user)
        if agreement.status != AgreementStatus.DRAFT:
            raise ConflictException("Only a draft agreement can be proposed")
        if agreement.created_by_user_type != current_user:
            raise ForbiddenException("Only the draft author can propose it")
        updated = await self._agreements.set_status(
            agreement_id,
            AgreementStatus.PROPOSED,
            expected_revision_id=agreement.current_revision_id,
            extra={"proposed_at": utc_now()},
        )
        if not updated:
            raise ConflictException("Agreement changed before it could be proposed")
        return await self.get_agreement_detail(agreement_id, current_user)

    async def create_revision(
        self,
        agreement_id: MongoId,
        payload: AgreementRevisionCreate,
        current_user: UserType,
    ) -> AgreementDetail:
        agreement = await self._get_visible_agreement(agreement_id, current_user)
        if agreement.status == AgreementStatus.ARCHIVED:
            raise ConflictException("Archived agreements cannot be revised")
        if (
            agreement.status == AgreementStatus.DRAFT
            and agreement.created_by_user_type != current_user
        ):
            raise ForbiddenException("Only the draft author can revise it")
        if agreement.current_revision_id != payload.expected_current_revision_id:
            raise ConflictException("A newer revision already exists")
        previous = await self._revisions.get_by_id(payload.expected_current_revision_id)
        if not previous or previous.agreement_id != agreement_id:
            raise ConflictException("Current revision does not belong to this agreement")

        now = utc_now()
        try:
            revision = await self._revisions.create(
                AgreementRevision(
                    agreement_id=agreement_id,
                    revision_number=agreement.current_revision_number + 1,
                    title=payload.title,
                    why_it_matters=payload.why_it_matters,
                    agreement_text=payload.agreement_text,
                    fairness_type=payload.fairness_type,
                    fairness_explanation=payload.fairness_explanation,
                    perspectives=self._perspectives_for_revision(
                        current_user, payload.my_perspective, previous
                    ),
                    created_by_user_type=current_user,
                    created_at=now,
                )
            )
        except DuplicateKeyError as exc:
            raise ConflictException(
                "A newer revision was saved first; review it and try again"
            ) from exc
        if not revision.id:
            raise ConflictException("Revision could not be created")
        was_agreed = (
            agreement.status in {AgreementStatus.AGREED, AgreementStatus.REVISIT}
            or agreement.last_agreed_revision_id is not None
        )
        next_status = (
            AgreementStatus.DRAFT
            if agreement.status == AgreementStatus.DRAFT
            else AgreementStatus.REVISIT
            if was_agreed
            else AgreementStatus.DISCUSSING
        )
        updated = await self._agreements.replace_current_revision(
            agreement_id,
            payload.expected_current_revision_id,
            str(revision.id),
            revision.revision_number,
            next_status,
            revisited_at=now if was_agreed else None,
        )
        if not updated:
            await self._revisions.delete_candidate(str(revision.id))
            raise ConflictException("A newer revision was saved first; review it and try again")
        return await self.get_agreement_detail(agreement_id, current_user)

    async def accept_revision(
        self, revision_id: MongoId, current_user: UserType
    ) -> AgreementDetail:
        revision = await self._revisions.get_by_id(revision_id)
        if not revision:
            raise NotFoundException("Agreement revision", revision_id)
        agreement = await self._get_visible_agreement(revision.agreement_id, current_user)
        if agreement.current_revision_id != revision_id:
            raise ConflictException("Only the current revision can be accepted")
        if agreement.status not in {
            AgreementStatus.PROPOSED,
            AgreementStatus.DISCUSSING,
            AgreementStatus.REVISIT,
        }:
            raise ConflictException("This agreement is not awaiting acceptance")
        active = await self._acceptances.list_active_for_revision(revision_id)
        if current_user in {item.user_type for item in active}:
            raise ConflictException("You already agreed to this revision")
        await self._acceptances.accept(revision.agreement_id, revision_id, current_user)

        latest = await self._agreements.get_by_id(revision.agreement_id)
        if not latest or latest.current_revision_id != revision_id:
            await self._acceptances.revoke(revision_id, current_user)
            raise ConflictException("A newer revision exists; your acceptance was not applied")
        active = await self._acceptances.list_active_for_revision(revision_id)
        if {item.user_type for item in active} == ALL_USERS:
            agreed = await self._agreements.set_status(
                revision.agreement_id,
                AgreementStatus.AGREED,
                expected_revision_id=revision_id,
                extra={"last_agreed_revision_id": revision_id},
            )
            if not agreed:
                await self._acceptances.revoke(revision_id, current_user)
                raise ConflictException("The agreement changed before acceptance completed")
            await self._revisions.mark_agreed(revision_id)
        return await self.get_agreement_detail(revision.agreement_id, current_user)

    async def revoke_acceptance(
        self, revision_id: MongoId, current_user: UserType
    ) -> AgreementDetail:
        revision = await self._revisions.get_by_id(revision_id)
        if not revision:
            raise NotFoundException("Agreement revision", revision_id)
        agreement = await self._get_visible_agreement(revision.agreement_id, current_user)
        if agreement.current_revision_id != revision_id:
            raise ConflictException("Only current-revision acceptance can be changed")
        revoked = await self._acceptances.revoke(revision_id, current_user)
        if not revoked:
            raise ConflictException("You have not accepted this revision")
        if agreement.status == AgreementStatus.AGREED:
            await self._agreements.set_status(
                revision.agreement_id,
                AgreementStatus.REVISIT,
                expected_revision_id=revision_id,
                extra={"revisited_at": utc_now()},
            )
        return await self.get_agreement_detail(revision.agreement_id, current_user)

    async def respond_to_revision(
        self,
        revision_id: MongoId,
        payload: AgreementResponseCreate,
        current_user: UserType,
    ) -> AgreementDetail:
        revision = await self._revisions.get_by_id(revision_id)
        if not revision:
            raise NotFoundException("Agreement revision", revision_id)
        agreement = await self._get_visible_agreement(revision.agreement_id, current_user)
        if agreement.current_revision_id != revision_id:
            raise ConflictException("Only the current revision can receive a response")
        if agreement.status in {AgreementStatus.DRAFT, AgreementStatus.ARCHIVED}:
            raise ConflictException("This agreement is not open for partner responses")
        await self._acceptances.revoke(revision_id, current_user)
        response: AgreementResponse = await self._responses.upsert(
            revision.agreement_id,
            revision_id,
            current_user,
            payload.response_type,
            payload.note,
        )
        next_status = (
            AgreementStatus.REVISIT
            if agreement.status in {AgreementStatus.AGREED, AgreementStatus.REVISIT}
            or agreement.last_agreed_revision_id
            else AgreementStatus.DISCUSSING
        )
        extra = {"revisited_at": utc_now()} if next_status == AgreementStatus.REVISIT else None
        updated = await self._agreements.set_status(
            revision.agreement_id,
            next_status,
            expected_revision_id=revision_id,
            extra=extra,
        )
        if not updated:
            raise ConflictException("The agreement changed before your response was saved")
        return await self.get_agreement_detail(response.agreement_id, current_user)

    async def request_archive(
        self, agreement_id: MongoId, current_user: UserType
    ) -> AgreementDetail:
        agreement = await self._get_visible_agreement(agreement_id, current_user)
        if agreement.status == AgreementStatus.ARCHIVED:
            raise ConflictException("Agreement is already archived")
        if agreement.status == AgreementStatus.DRAFT:
            if agreement.created_by_user_type != current_user:
                raise ForbiddenException("Only the draft author can archive it")
            await self._agreements.set_archive_requests(agreement_id, [current_user], finalize=True)
            return await self.get_agreement_detail(agreement_id, current_user)

        marked = set(agreement.archive_requested_by_user_types)
        if current_user in marked:
            raise ConflictException("You already requested archival")
        marked.add(current_user)
        if agreement.current_revision_id:
            await self._acceptances.revoke(agreement.current_revision_id, current_user)
        finalize = marked == ALL_USERS
        next_status = (
            AgreementStatus.REVISIT
            if agreement.status in {AgreementStatus.AGREED, AgreementStatus.REVISIT}
            or agreement.last_agreed_revision_id
            else AgreementStatus.DISCUSSING
        )
        await self._agreements.set_archive_requests(
            agreement_id,
            list(marked),
            status=next_status,
            finalize=finalize,
        )
        return await self.get_agreement_detail(agreement_id, current_user)

    async def withdraw_archive_request(
        self, agreement_id: MongoId, current_user: UserType
    ) -> AgreementDetail:
        agreement = await self._get_visible_agreement(agreement_id, current_user)
        if agreement.status == AgreementStatus.ARCHIVED:
            raise ConflictException("Archived agreements cannot be restored in this version")
        marked = set(agreement.archive_requested_by_user_types)
        if current_user not in marked:
            raise ConflictException("You have not requested archival")
        marked.remove(current_user)
        await self._agreements.set_archive_requests(agreement_id, list(marked))
        return await self.get_agreement_detail(agreement_id, current_user)
