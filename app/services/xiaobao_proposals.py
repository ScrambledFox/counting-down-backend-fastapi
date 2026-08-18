from typing import Annotated, Any

from fastapi import Depends, HTTPException

from app.repositories.xiaobao import XiaoBaoProposalRepository
from app.schemas.v1.exceptions import ConflictException, NotFoundException
from app.schemas.v1.mediation import (
    MediationCommentCreate,
    MediationPerspectiveDraftUpdate,
    MediationSessionCreate,
)
from app.schemas.v1.relationship_care import (
    AgreementCreate,
    PersonalBoundaryCreate,
    PersonalGoalCreate,
)
from app.schemas.v1.todo import TodoCreate
from app.schemas.v1.user import UserType
from app.schemas.v1.xiaobao import (
    XiaoBaoMediationCommentPayload,
    XiaoBaoMediationPerspectiveDraftPayload,
    XiaoBaoProposal,
    XiaoBaoProposalType,
    XiaoBaoTogetherListPayload,
    validate_xiaobao_proposal_payload,
)
from app.services.mediation import MediationService
from app.services.relationship_care import RelationshipCareService
from app.services.todo import TodoService


class XiaoBaoProposalService:
    def __init__(
        self,
        proposals: Annotated[XiaoBaoProposalRepository, Depends()],
        relationship_care: Annotated[RelationshipCareService, Depends()],
        todos: Annotated[TodoService, Depends()],
        mediation: Annotated[MediationService, Depends()],
    ) -> None:
        self._proposals = proposals
        self._relationship_care = relationship_care
        self._todos = todos
        self._mediation = mediation

    async def update(
        self, proposal_id: str, owner: UserType, payload: dict[str, Any]
    ) -> XiaoBaoProposal:
        proposal = await self._proposals.get_owned(proposal_id, owner)
        if not proposal:
            raise NotFoundException("Xiao Bao proposal", proposal_id)
        validated = validate_xiaobao_proposal_payload(proposal.type, payload)
        updated = await self._proposals.update_pending(
            proposal_id, owner, validated.model_dump(mode="json", exclude_none=True)
        )
        if not updated:
            raise ConflictException("Only pending Xiao Bao proposals can be edited")
        return updated

    async def reject(self, proposal_id: str, owner: UserType) -> XiaoBaoProposal:
        proposal = await self._proposals.get_owned(proposal_id, owner)
        if not proposal:
            raise NotFoundException("Xiao Bao proposal", proposal_id)
        rejected = await self._proposals.reject_pending(proposal_id, owner)
        if not rejected:
            raise ConflictException("Only pending Xiao Bao proposals can be rejected")
        return rejected

    async def accept(self, proposal_id: str, owner: UserType) -> XiaoBaoProposal:
        existing = await self._proposals.get_owned(proposal_id, owner)
        if not existing:
            raise NotFoundException("Xiao Bao proposal", proposal_id)
        proposal = await self._proposals.claim_acceptance(proposal_id, owner)
        if not proposal:
            raise ConflictException("This Xiao Bao proposal has already been decided")

        entity_id: str | None = None
        try:
            if proposal.type == XiaoBaoProposalType.PERSONAL_BOUNDARY:
                boundary = await self._relationship_care.create_boundary(
                    PersonalBoundaryCreate.model_validate(proposal.payload), owner
                )
                entity_id = str(boundary.id) if boundary.id else None
            elif proposal.type == XiaoBaoProposalType.PERSONAL_GOAL:
                goal = await self._relationship_care.create_goal(
                    PersonalGoalCreate.model_validate(proposal.payload), owner
                )
                entity_id = str(goal.id) if goal.id else None
            elif proposal.type == XiaoBaoProposalType.SHARED_AGREEMENT:
                agreement = await self._relationship_care.create_agreement(
                    AgreementCreate.model_validate(proposal.payload), owner
                )
                entity_id = str(agreement.agreement.id) if agreement.agreement.id else None
            elif proposal.type == XiaoBaoProposalType.TOGETHER_LIST_ITEM:
                todo_payload = XiaoBaoTogetherListPayload.model_validate(proposal.payload)
                todo = await self._todos.create(
                    TodoCreate(title=todo_payload.title, category=todo_payload.category)
                )
                entity_id = str(todo.id) if todo.id else None
            elif proposal.type == XiaoBaoProposalType.MEDIATION_SESSION:
                session = await self._mediation.create_session(
                    owner, MediationSessionCreate.model_validate(proposal.payload)
                )
                entity_id = str(session.id) if session.id else None
            elif proposal.type == XiaoBaoProposalType.MEDIATION_COMMENT:
                if not proposal.target:
                    raise ConflictException("Mediation target is unavailable")
                comment_payload = XiaoBaoMediationCommentPayload.model_validate(proposal.payload)
                comment = await self._mediation.create_xiaobao_comment(
                    proposal.target.id,
                    MediationCommentCreate(content=comment_payload.content),
                )
                entity_id = str(comment.id) if comment.id else None
            elif proposal.type == XiaoBaoProposalType.MEDIATION_PERSPECTIVE_DRAFT:
                if not proposal.target:
                    raise ConflictException("Mediation target is unavailable")
                perspective_payload = XiaoBaoMediationPerspectiveDraftPayload.model_validate(
                    proposal.payload
                )
                perspective = await self._mediation.upsert_my_perspective_draft(
                    proposal.target.id,
                    owner,
                    MediationPerspectiveDraftUpdate.model_validate(
                        perspective_payload.model_dump(mode="python")
                    ),
                )
                entity_id = str(perspective.id) if perspective.id else None
        except HTTPException:
            await self._proposals.release_acceptance(proposal_id)
            raise

        if not entity_id:
            raise ConflictException("The proposed item could not be created")
        accepted = await self._proposals.mark_accepted(proposal_id, entity_id)
        if not accepted:
            raise ConflictException(
                "The item was created but proposal finalization needs attention"
            )
        return accepted
