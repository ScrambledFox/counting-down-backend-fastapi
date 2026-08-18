import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.integrations.openai_client import _to_openai_strict_json_schema
from app.repositories.xiaobao import XiaoBaoProposalRepository
from app.schemas.v1.mediation import MediationSessionCreate
from app.schemas.v1.relationship_care import (
    AgreementCreate,
    PersonalBoundaryCreate,
    PersonalGoalCreate,
)
from app.schemas.v1.todo import TodoCreate
from app.schemas.v1.user import UserType
from app.schemas.v1.xiaobao import (
    XiaoBaoCompletedAction,
    XiaoBaoContextReference,
    XiaoBaoContextReferenceType,
    XiaoBaoMediationCommentPayload,
    XiaoBaoMediationPerspectiveDraftPayload,
    XiaoBaoPrivateMediationContext,
    XiaoBaoProposal,
    XiaoBaoProposalTarget,
    XiaoBaoProposalTargetType,
    XiaoBaoProposalType,
    XiaoBaoRelationshipContext,
    XiaoBaoTogetherListPayload,
)
from app.services.todo import TodoService
from app.util.time import utc_now


class _ReferenceArgs(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=10)


class _BoundaryProposalArgs(BaseModel):
    payload: PersonalBoundaryCreate
    rationale: str | None = Field(default=None, max_length=2000)


class _GoalProposalArgs(BaseModel):
    payload: PersonalGoalCreate
    rationale: str | None = Field(default=None, max_length=2000)


class _AgreementProposalArgs(BaseModel):
    payload: AgreementCreate
    rationale: str | None = Field(default=None, max_length=2000)


class _TogetherProposalArgs(BaseModel):
    payload: XiaoBaoTogetherListPayload
    rationale: str | None = Field(default=None, max_length=2000)


class _TogetherAddArgs(BaseModel):
    payload: XiaoBaoTogetherListPayload


class _PrivateMediationArgs(BaseModel):
    session_reference_key: str = Field(min_length=1, max_length=100)


class _MediationSessionProposalArgs(BaseModel):
    payload: MediationSessionCreate
    rationale: str | None = Field(default=None, max_length=2000)


class _MediationCommentProposalArgs(BaseModel):
    session_reference_key: str = Field(min_length=1, max_length=100)
    payload: XiaoBaoMediationCommentPayload
    rationale: str | None = Field(default=None, max_length=2000)


class _MediationPerspectiveDraftProposalArgs(BaseModel):
    session_reference_key: str = Field(min_length=1, max_length=100)
    payload: XiaoBaoMediationPerspectiveDraftPayload
    rationale: str | None = Field(default=None, max_length=2000)


@dataclass
class XiaoBaoToolContext:
    owner: UserType
    conversation_id: str
    assistant_message_id: str
    relationship_context: XiaoBaoRelationshipContext
    private_mediation_by_key: dict[str, XiaoBaoPrivateMediationContext]
    loaded_private_mediation_keys: set[str]
    proposal_repo: XiaoBaoProposalRepository
    todo_service: TodoService


@dataclass
class XiaoBaoToolResult:
    output: dict[str, Any]
    references: list[XiaoBaoContextReference]
    proposal_ids: list[str]
    completed_actions: list[XiaoBaoCompletedAction]
    loaded_private_mediation_keys: list[str] = field(default_factory=list)


_TOOLS: list[tuple[str, str, type[BaseModel]]] = [
    (
        "record_context_references",
        "Record authorized relationship records materially used in the answer.",
        _ReferenceArgs,
    ),
    (
        "propose_personal_boundary",
        "Create a reviewable personal-boundary proposal.",
        _BoundaryProposalArgs,
    ),
    (
        "propose_personal_goal",
        "Create a reviewable personal-growth-goal proposal.",
        _GoalProposalArgs,
    ),
    (
        "propose_shared_agreement",
        "Create a reviewable shared-agreement proposal.",
        _AgreementProposalArgs,
    ),
    (
        "propose_together_list_item",
        "Create a reviewable Together List proposal.",
        _TogetherProposalArgs,
    ),
    (
        "add_together_list_item",
        "Add a specific item after an explicit user instruction.",
        _TogetherAddArgs,
    ),
    (
        "load_my_mediation_details",
        "Load the current user's private perspective and reflection for one authorized mediation.",
        _PrivateMediationArgs,
    ),
    (
        "propose_mediation_session",
        "Create a reviewable proposal to start a mediation session.",
        _MediationSessionProposalArgs,
    ),
    (
        "propose_mediation_comment",
        "Create a reviewable Xiao Bao comment using shared mediation data only.",
        _MediationCommentProposalArgs,
    ),
    (
        "propose_mediation_perspective_draft",
        "Create a reviewable private perspective draft after loading the user's details.",
        _MediationPerspectiveDraftProposalArgs,
    ),
]


def xiaobao_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": name,
            "description": description,
            "parameters": _to_openai_strict_json_schema(model.model_json_schema()),
            "strict": True,
        }
        for name, description, model in _TOOLS
    ]


async def execute_xiaobao_tool(
    name: str, arguments: str, context: XiaoBaoToolContext
) -> XiaoBaoToolResult:
    models = {name: model for name, _, model in _TOOLS}
    if name not in models:
        return XiaoBaoToolResult(
            output={"ok": False, "error": "unknown_tool"},
            references=[],
            proposal_ids=[],
            completed_actions=[],
        )
    parsed = models[name].model_validate(json.loads(arguments))
    if name == "load_my_mediation_details":
        if not isinstance(parsed, _PrivateMediationArgs):
            raise ValueError("Invalid private mediation tool arguments")
        private_item = context.private_mediation_by_key.get(parsed.session_reference_key)
        if not private_item:
            return XiaoBaoToolResult(
                output={"ok": False, "error": "invalid_mediation_reference"},
                references=[],
                proposal_ids=[],
                completed_actions=[],
            )
        return XiaoBaoToolResult(
            output={"ok": True, "loaded_reference_key": parsed.session_reference_key},
            references=[private_item.session_reference],
            proposal_ids=[],
            completed_actions=[],
            loaded_private_mediation_keys=[parsed.session_reference_key],
        )

    if name == "record_context_references":
        if not isinstance(parsed, _ReferenceArgs):
            raise ValueError("Invalid reference tool arguments")
        registry = context.relationship_context.reference_registry()
        references = [registry[key] for key in parsed.keys if key in registry]
        return XiaoBaoToolResult(
            output={"ok": True, "accepted_reference_keys": [item.key for item in references]},
            references=references,
            proposal_ids=[],
            completed_actions=[],
        )

    if name == "add_together_list_item":
        if not isinstance(parsed, _TogetherAddArgs):
            raise ValueError("Invalid Together List tool arguments")
        payload = XiaoBaoTogetherListPayload.model_validate(parsed.payload)
        normalized_title = " ".join(payload.title.casefold().split())
        existing = next(
            (
                item
                for item in context.relationship_context.together_list
                if " ".join(str(item.data.get("title", "")).casefold().split()) == normalized_title
                and item.data.get("category") == payload.category
            ),
            None,
        )
        if existing:
            action = XiaoBaoCompletedAction(
                type="TOGETHER_LIST_ITEM_ALREADY_PRESENT",
                entity_id=existing.reference.id,
                title=existing.reference.title,
            )
            return XiaoBaoToolResult(
                output={
                    "ok": True,
                    "already_present": True,
                    "entity_id": existing.reference.id,
                    "title": existing.reference.title,
                },
                references=[existing.reference],
                proposal_ids=[],
                completed_actions=[action],
            )
        todo = await context.todo_service.create(
            TodoCreate(title=payload.title, category=payload.category)
        )
        if not todo.id:
            raise RuntimeError("Together List item was created without an identifier")
        action = XiaoBaoCompletedAction(
            type="TOGETHER_LIST_ITEM_ADDED", entity_id=str(todo.id), title=todo.title
        )
        return XiaoBaoToolResult(
            output={"ok": True, "entity_id": str(todo.id), "title": todo.title},
            references=[],
            proposal_ids=[],
            completed_actions=[action],
        )

    type_map = {
        "propose_personal_boundary": XiaoBaoProposalType.PERSONAL_BOUNDARY,
        "propose_personal_goal": XiaoBaoProposalType.PERSONAL_GOAL,
        "propose_shared_agreement": XiaoBaoProposalType.SHARED_AGREEMENT,
        "propose_together_list_item": XiaoBaoProposalType.TOGETHER_LIST_ITEM,
        "propose_mediation_session": XiaoBaoProposalType.MEDIATION_SESSION,
        "propose_mediation_comment": XiaoBaoProposalType.MEDIATION_COMMENT,
        "propose_mediation_perspective_draft": (XiaoBaoProposalType.MEDIATION_PERSPECTIVE_DRAFT),
    }
    if not isinstance(
        parsed,
        (
            _BoundaryProposalArgs,
            _GoalProposalArgs,
            _AgreementProposalArgs,
            _TogetherProposalArgs,
            _MediationSessionProposalArgs,
            _MediationCommentProposalArgs,
            _MediationPerspectiveDraftProposalArgs,
        ),
    ):
        raise ValueError("Invalid proposal tool arguments")
    target: XiaoBaoProposalTarget | None = None
    if isinstance(parsed, (_MediationCommentProposalArgs, _MediationPerspectiveDraftProposalArgs)):
        reference = context.relationship_context.reference_registry().get(
            parsed.session_reference_key
        )
        if not reference or reference.type != XiaoBaoContextReferenceType.MEDIATION_SESSION:
            return XiaoBaoToolResult(
                output={"ok": False, "error": "invalid_mediation_reference"},
                references=[],
                proposal_ids=[],
                completed_actions=[],
            )
        if isinstance(parsed, _MediationCommentProposalArgs) and (
            context.loaded_private_mediation_keys
        ):
            return XiaoBaoToolResult(
                output={"ok": False, "error": "private_context_cannot_be_shared"},
                references=[],
                proposal_ids=[],
                completed_actions=[],
            )
        if isinstance(parsed, _MediationPerspectiveDraftProposalArgs) and (
            parsed.session_reference_key not in context.loaded_private_mediation_keys
        ):
            return XiaoBaoToolResult(
                output={"ok": False, "error": "private_context_must_be_loaded_first"},
                references=[],
                proposal_ids=[],
                completed_actions=[],
            )
        target = XiaoBaoProposalTarget(
            type=XiaoBaoProposalTargetType.MEDIATION_SESSION,
            id=reference.id,
            title=reference.title,
        )

    now = utc_now()
    proposal = await context.proposal_repo.create(
        XiaoBaoProposal(
            conversation_id=context.conversation_id,
            message_id=context.assistant_message_id,
            owner_user_type=context.owner,
            type=type_map[name],
            payload=parsed.payload,
            target=target,
            rationale=parsed.rationale,
            created_at=now,
            updated_at=now,
        )
    )
    if not proposal.id:
        raise RuntimeError("Xiao Bao proposal was created without an identifier")
    return XiaoBaoToolResult(
        output={"ok": True, "proposal_id": str(proposal.id), "status": proposal.status.value},
        references=[],
        proposal_ids=[str(proposal.id)],
        completed_actions=[],
    )
