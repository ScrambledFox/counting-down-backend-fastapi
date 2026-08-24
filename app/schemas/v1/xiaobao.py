from datetime import datetime
from enum import Enum
from typing import Any, cast

from pydantic import Field, field_validator, model_validator

from app.schemas.v1.base import CustomModel, DefaultMongoIdField, MongoId
from app.schemas.v1.mediation import MediationSessionCreate
from app.schemas.v1.relationship_care import (
    AgreementCreate,
    PersonalBoundaryCreate,
    PersonalGoalCreate,
)
from app.schemas.v1.relationship_profile import RelationshipProfileAIContext
from app.schemas.v1.user import UserType
from app.schemas.v1.xiaobao_routine import XiaoBaoRoutineCreate, XiaoBaoRoutineKind


class XiaoBaoMessageRole(str, Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class XiaoBaoMessageStatus(str, Enum):
    GENERATING = "GENERATING"
    PENDING_DELIVERY = "PENDING_DELIVERY"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class XiaoBaoConversationPurpose(str, Enum):
    CHAT = "CHAT"
    ROUTINE_INBOX = "ROUTINE_INBOX"


class XiaoBaoMessageSource(str, Enum):
    INTERACTIVE = "INTERACTIVE"
    ROUTINE = "ROUTINE"


class XiaoBaoMascotMood(str, Enum):
    IDLE = "IDLE"
    LOVE = "LOVE"
    CONCERNED = "CONCERNED"


class XiaoBaoResponseEnvelope(CustomModel):
    """Strict final model output. Field order is part of the streaming contract."""

    model_config = {"extra": "forbid"}

    content: str = Field(max_length=50_000)
    mood: XiaoBaoMascotMood


class XiaoBaoProposalType(str, Enum):
    PERSONAL_BOUNDARY = "PERSONAL_BOUNDARY"
    PERSONAL_GOAL = "PERSONAL_GOAL"
    SHARED_AGREEMENT = "SHARED_AGREEMENT"
    TOGETHER_LIST_ITEM = "TOGETHER_LIST_ITEM"
    MEDIATION_SESSION = "MEDIATION_SESSION"
    MEDIATION_COMMENT = "MEDIATION_COMMENT"
    MEDIATION_PERSPECTIVE_DRAFT = "MEDIATION_PERSPECTIVE_DRAFT"
    ROUTINE = "ROUTINE"
    REMINDER = "REMINDER"


class XiaoBaoProposalStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTING = "ACCEPTING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class XiaoBaoContextReferenceType(str, Enum):
    PERSONAL_BOUNDARY = "PERSONAL_BOUNDARY"
    PERSONAL_GOAL = "PERSONAL_GOAL"
    SHARED_AGREEMENT = "SHARED_AGREEMENT"
    WISH = "WISH"
    TOGETHER_LIST_ITEM = "TOGETHER_LIST_ITEM"
    MEDIATION_SESSION = "MEDIATION_SESSION"


class XiaoBaoProposalTargetType(str, Enum):
    MEDIATION_SESSION = "MEDIATION_SESSION"


class XiaoBaoContextReference(CustomModel):
    key: str = Field(min_length=1, max_length=100)
    type: XiaoBaoContextReferenceType
    id: MongoId
    title: str = Field(min_length=1, max_length=160)


class XiaoBaoCompletedAction(CustomModel):
    type: str = Field(min_length=1, max_length=80)
    entity_id: MongoId
    title: str = Field(min_length=1, max_length=200)


class XiaoBaoTokenUsage(CustomModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class XiaoBaoConversation(CustomModel):
    id: DefaultMongoIdField = None
    owner_user_type: UserType
    title: str = Field(min_length=1, max_length=80)
    purpose: XiaoBaoConversationPurpose = XiaoBaoConversationPurpose.CHAT
    created_at: datetime
    updated_at: datetime


class XiaoBaoMessage(CustomModel):
    id: DefaultMongoIdField = None
    conversation_id: MongoId
    role: XiaoBaoMessageRole
    status: XiaoBaoMessageStatus
    source: XiaoBaoMessageSource = XiaoBaoMessageSource.INTERACTIVE
    content: str = Field(default="", max_length=50_000)
    client_message_id: str | None = Field(default=None, min_length=1, max_length=100)
    parent_user_message_id: MongoId | None = None
    context_references: list[XiaoBaoContextReference] = Field(default_factory=list)
    proposal_ids: list[MongoId] = Field(default_factory=list)
    completed_actions: list[XiaoBaoCompletedAction] = Field(default_factory=list)
    mascot_mood: XiaoBaoMascotMood | None = None
    model: str | None = Field(default=None, max_length=100)
    provider_response_id: str | None = Field(default=None, max_length=200)
    token_usage: XiaoBaoTokenUsage | None = None
    error_code: str | None = Field(default=None, max_length=80)
    routine_id: MongoId | None = None
    routine_run_id: MongoId | None = None
    read_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


TOGETHER_LIST_CATEGORIES = (
    "Date",
    "Adventure",
    "Home",
    "Food",
    "Culture",
    "Activity",
    "Movie",
)


class XiaoBaoTogetherListPayload(CustomModel):
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(default="Date")

    @field_validator("title", "category", mode="before")
    @classmethod
    def trim_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        if value not in TOGETHER_LIST_CATEGORIES:
            raise ValueError("Unsupported Together List category")
        return value


class XiaoBaoMediationCommentPayload(CustomModel):
    content: str = Field(min_length=1, max_length=3000)

    @field_validator("content", mode="before")
    @classmethod
    def trim_content(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class XiaoBaoMediationPerspectiveDraftPayload(CustomModel):
    what_happened: str | None = Field(default=None, max_length=3000)
    what_i_felt: str | None = Field(default=None, max_length=1500)
    what_i_needed: str | None = Field(default=None, max_length=1500)
    what_hurt_me: str | None = Field(default=None, max_length=1500)
    my_part: str | None = Field(default=None, max_length=1500)
    what_i_want_now: str | None = Field(default=None, max_length=1500)
    free_text: str | None = Field(default=None, max_length=3000)

    @field_validator("*", mode="before")
    @classmethod
    def trim_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class XiaoBaoProposalTarget(CustomModel):
    type: XiaoBaoProposalTargetType
    id: MongoId
    title: str = Field(min_length=1, max_length=160)


type XiaoBaoProposalPayload = (
    PersonalBoundaryCreate
    | PersonalGoalCreate
    | AgreementCreate
    | XiaoBaoTogetherListPayload
    | MediationSessionCreate
    | XiaoBaoMediationCommentPayload
    | XiaoBaoMediationPerspectiveDraftPayload
    | XiaoBaoRoutineCreate
)


_PROPOSAL_PAYLOAD_TYPES: dict[XiaoBaoProposalType, type[CustomModel]] = {
    XiaoBaoProposalType.PERSONAL_BOUNDARY: PersonalBoundaryCreate,
    XiaoBaoProposalType.PERSONAL_GOAL: PersonalGoalCreate,
    XiaoBaoProposalType.SHARED_AGREEMENT: AgreementCreate,
    XiaoBaoProposalType.TOGETHER_LIST_ITEM: XiaoBaoTogetherListPayload,
    XiaoBaoProposalType.MEDIATION_SESSION: MediationSessionCreate,
    XiaoBaoProposalType.MEDIATION_COMMENT: XiaoBaoMediationCommentPayload,
    XiaoBaoProposalType.MEDIATION_PERSPECTIVE_DRAFT: XiaoBaoMediationPerspectiveDraftPayload,
    XiaoBaoProposalType.ROUTINE: XiaoBaoRoutineCreate,
    XiaoBaoProposalType.REMINDER: XiaoBaoRoutineCreate,
}


def validate_xiaobao_proposal_payload(
    proposal_type: XiaoBaoProposalType, payload: dict[str, Any]
) -> XiaoBaoProposalPayload:
    return cast(
        XiaoBaoProposalPayload,
        _PROPOSAL_PAYLOAD_TYPES[proposal_type].model_validate(payload),
    )


class XiaoBaoProposal(CustomModel):
    id: DefaultMongoIdField = None
    conversation_id: MongoId
    message_id: MongoId
    owner_user_type: UserType
    type: XiaoBaoProposalType
    payload: XiaoBaoProposalPayload
    target: XiaoBaoProposalTarget | None = None
    rationale: str | None = Field(default=None, max_length=2000)
    status: XiaoBaoProposalStatus = XiaoBaoProposalStatus.PENDING
    revision: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None = None
    created_entity_id: MongoId | None = None

    @model_validator(mode="after")
    def payload_matches_type(self) -> XiaoBaoProposal:
        expected = _PROPOSAL_PAYLOAD_TYPES[self.type]
        if not isinstance(self.payload, expected):
            raise ValueError(f"Payload does not match proposal type {self.type.value}")
        if (
            self.type == XiaoBaoProposalType.ROUTINE
            and self.payload.kind != XiaoBaoRoutineKind.ROUTINE
        ):
            raise ValueError("Routine proposals require a recurring routine payload")
        if (
            self.type == XiaoBaoProposalType.REMINDER
            and self.payload.kind != XiaoBaoRoutineKind.REMINDER
        ):
            raise ValueError("Reminder proposals require a one-time reminder payload")
        needs_target = self.type in {
            XiaoBaoProposalType.MEDIATION_COMMENT,
            XiaoBaoProposalType.MEDIATION_PERSPECTIVE_DRAFT,
        }
        if needs_target and (
            not self.target or self.target.type != XiaoBaoProposalTargetType.MEDIATION_SESSION
        ):
            raise ValueError(f"Proposal type {self.type.value} requires a mediation target")
        if not needs_target and self.target is not None:
            raise ValueError(f"Proposal type {self.type.value} does not accept a target")
        return self


class XiaoBaoProposalUpdate(CustomModel):
    payload: dict[str, Any]


class XiaoBaoMessageCreate(CustomModel):
    content: str = Field(min_length=1, max_length=5000)
    client_message_id: str = Field(min_length=1, max_length=100)

    @field_validator("content", mode="before")
    @classmethod
    def trim_content(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class XiaoBaoConversationDetail(CustomModel):
    conversation: XiaoBaoConversation
    messages: list[XiaoBaoMessage]
    proposals: list[XiaoBaoProposal]
    has_more_messages: bool = False


class XiaoBaoInboxMessageResponse(CustomModel):
    id: MongoId
    content: str
    mascot_mood: XiaoBaoMascotMood | None = None
    routine_id: MongoId
    routine_run_id: MongoId
    read_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, message: XiaoBaoMessage) -> XiaoBaoInboxMessageResponse:
        return cls.model_validate(message.model_dump(mode="python"))


class XiaoBaoInbox(CustomModel):
    messages: list[XiaoBaoInboxMessageResponse]
    has_more_messages: bool = False
    next_cursor: str | None = None
    unread_count: int = 0


class XiaoBaoContextItem(CustomModel):
    reference: XiaoBaoContextReference
    data: dict[str, Any]


class XiaoBaoRelationshipContext(CustomModel):
    current_user_type: UserType
    partner_user_type: UserType
    relationship_profile: RelationshipProfileAIContext | None = None
    boundaries: list[XiaoBaoContextItem] = Field(default_factory=list)
    wishes: list[XiaoBaoContextItem] = Field(default_factory=list)
    personal_goals: list[XiaoBaoContextItem] = Field(default_factory=list)
    agreements: list[XiaoBaoContextItem] = Field(default_factory=list)
    together_list: list[XiaoBaoContextItem] = Field(default_factory=list)
    mediation_sessions: list[XiaoBaoContextItem] = Field(default_factory=list)

    def reference_registry(self) -> dict[str, XiaoBaoContextReference]:
        items = (
            self.boundaries
            + self.wishes
            + self.personal_goals
            + self.agreements
            + self.together_list
            + self.mediation_sessions
        )
        return {item.reference.key: item.reference for item in items}


class XiaoBaoPrivateMediationContext(CustomModel):
    session_reference: XiaoBaoContextReference
    perspective: dict[str, Any] | None = None
    reflection_status: str
    reflection: dict[str, Any] | None = None
