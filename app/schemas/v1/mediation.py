from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from app.schemas.v1.base import CustomModel, DefaultMongoIdField, MongoId
from app.schemas.v1.user import UserType


class MediationSessionStatus(str, Enum):
    AWAITING_PERSPECTIVES = "AWAITING_PERSPECTIVES"
    PARTIAL_PERSPECTIVE_SUBMITTED = "PARTIAL_PERSPECTIVE_SUBMITTED"
    BOTH_PERSPECTIVES_SUBMITTED = "BOTH_PERSPECTIVES_SUBMITTED"
    AI_MEDIATION_PROCESSING = "AI_MEDIATION_PROCESSING"
    AI_ADVICE_AVAILABLE = "AI_ADVICE_AVAILABLE"
    DISCUSSION_OPEN = "DISCUSSION_OPEN"
    RESOLVED = "RESOLVED"
    ARCHIVED = "ARCHIVED"


class PerspectiveStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED_PENDING_REVIEW = "SUBMITTED_PENDING_REVIEW"
    LOCKED = "LOCKED"
    FLAGGED = "FLAGGED"


class SafetyStatus(str, Enum):
    NORMAL = "NORMAL"
    FLAGGED = "FLAGGED"
    BLOCKED = "BLOCKED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class MediationAIJobType(str, Enum):
    PERSPECTIVE_MODERATION = "PERSPECTIVE_MODERATION"
    PRIVATE_REFLECTION = "PRIVATE_REFLECTION"
    SHARED_MEDIATION_ADVICE = "SHARED_MEDIATION_ADVICE"
    COMMENT_RESPONSE = "COMMENT_RESPONSE"


class AIJobStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MediationAuthorType(str, Enum):
    USER = "USER"
    AI = "AI"


class MediationEntityType(str, Enum):
    PERSPECTIVE = "PERSPECTIVE"
    COMMENT = "COMMENT"
    AI_REFLECTION = "AI_REFLECTION"
    AI_ADVICE = "AI_ADVICE"
    AI_COMMENT = "AI_COMMENT"


class MediationProvider(str, Enum):
    OPENAI = "OPENAI"
    INTERNAL = "INTERNAL"


class Task(CustomModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        extra="forbid",
    )

    title: str
    description: str


class PrivateReflectionOutput(CustomModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        extra="forbid",
    )

    emotional_reflection: str
    calming_exercise: str
    possible_underlying_needs: list[str]
    things_to_avoid_right_now: list[str]
    next_best_action: str
    neutral_reminder: str
    safety_note: str | None = None


class SharedMediationAdviceOutput(CustomModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        extra="forbid",
    )

    neutral_summary: str
    joris_likely_feelings_and_needs: list[str]
    danfeng_likely_feelings_and_needs: list[str]
    shared_conflict_pattern: str
    points_of_agreement: list[str]
    points_of_misunderstanding: list[str]
    suggested_conversation_script: list[str]
    tasks_for_joris: list[Task]
    tasks_for_danfeng: list[Task]
    joint_task: Task
    what_to_avoid: list[str]
    safety_note: str | None = None


class CommentAIResponseOutput(CustomModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        extra="forbid",
    )

    response: str
    updated_suggestions: list[str]
    should_pause_discussion: bool
    safety_note: str | None = None


class MediationSession(CustomModel):
    id: DefaultMongoIdField = None
    title: str
    description: str | None = None
    created_by_user_type: UserType
    status: MediationSessionStatus
    safety_status: SafetyStatus
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    archived_at: datetime | None = None
    resolved_by_user_types: list[UserType] = Field(default_factory=list)
    archived_by_user_types: list[UserType] = Field(default_factory=list)
    latest_advice_id: MongoId | None = None


class MediationPerspective(CustomModel):
    id: DefaultMongoIdField = None
    session_id: MongoId
    user_type: UserType
    what_happened: str | None = None
    what_i_felt: str | None = None
    what_i_needed: str | None = None
    what_hurt_me: str | None = None
    my_part: str | None = None
    what_i_want_now: str | None = None
    free_text: str | None = None
    status: PerspectiveStatus
    submitted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    moderation_result_id: MongoId | None = None

    def combined_text(self) -> str:
        parts = [
            self.what_happened,
            self.what_i_felt,
            self.what_i_needed,
            self.what_hurt_me,
            self.my_part,
            self.what_i_want_now,
            self.free_text,
        ]
        return "\n\n".join(part.strip() for part in parts if part and part.strip())


class MediationAIReflection(CustomModel):
    id: DefaultMongoIdField = None
    session_id: MongoId
    perspective_id: MongoId
    recipient_user_type: UserType
    content: PrivateReflectionOutput
    model: str
    prompt_version: str
    openai_response_id: str | None = None
    created_at: datetime
    moderation_result_id: MongoId | None = None


class MediationAdvice(CustomModel):
    id: DefaultMongoIdField = None
    session_id: MongoId
    content: SharedMediationAdviceOutput
    model: str
    prompt_version: str
    openai_response_id: str | None = None
    created_at: datetime
    superseded_by_id: MongoId | None = None
    moderation_result_id: MongoId | None = None


class MediationComment(CustomModel):
    id: DefaultMongoIdField = None
    session_id: MongoId
    parent_comment_id: MongoId | None = None
    author_type: MediationAuthorType
    author_user_type: UserType | None = None
    content: str
    created_at: datetime
    updated_at: datetime | None = None
    moderation_result_id: MongoId | None = None
    ai_job_id: MongoId | None = None


class MediationModerationResult(CustomModel):
    id: DefaultMongoIdField = None
    entity_type: MediationEntityType
    entity_id: MongoId | str
    provider: MediationProvider
    flagged: bool
    safety_status: SafetyStatus
    categories: dict[str, bool]
    category_scores: dict[str, float] | None = None
    raw_result: dict | None = None
    created_at: datetime


class MediationAIJob(CustomModel):
    id: DefaultMongoIdField = None
    job_type: MediationAIJobType
    status: AIJobStatus
    session_id: MongoId
    source_entity_id: MongoId | None = None
    source_entity_type: str | None = None
    idempotency_key: str
    attempts: int = 0
    max_attempts: int = 3
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class MediationSessionCreate(CustomModel):
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Title must not be empty")
        return stripped

    @field_validator("description")
    @classmethod
    def description_strip(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


class MediationPerspectiveDraftUpdate(CustomModel):
    what_happened: str | None = Field(default=None, max_length=3000)
    what_i_felt: str | None = Field(default=None, max_length=1500)
    what_i_needed: str | None = Field(default=None, max_length=1500)
    what_hurt_me: str | None = Field(default=None, max_length=1500)
    my_part: str | None = Field(default=None, max_length=1500)
    what_i_want_now: str | None = Field(default=None, max_length=1500)
    free_text: str | None = Field(default=None, max_length=3000)

    @field_validator("*")
    @classmethod
    def strip_blank_strings(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    def combined_text(self) -> str:
        values = self.model_dump().values()
        return "\n\n".join(value.strip() for value in values if isinstance(value, str) and value)


class MediationCommentCreate(CustomModel):
    content: str = Field(min_length=1, max_length=3000)

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Content must not be empty")
        return stripped


class MediationSessionListItem(CustomModel):
    id: MongoId
    title: str
    description: str | None = None
    created_by_user_type: UserType
    status: MediationSessionStatus
    safety_status: SafetyStatus
    has_my_perspective: bool
    has_other_perspective: bool
    has_advice: bool
    has_marked_resolved: bool
    other_has_marked_resolved: bool
    has_marked_archived: bool
    other_has_marked_archived: bool
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    archived_at: datetime | None = None


class PerspectiveResponse(MediationPerspective):
    pass


class OtherPerspectiveStatus(CustomModel):
    user_type: UserType
    status: Literal["NOT_STARTED", "DRAFT", "SUBMITTED"]


class MediationCommentResponse(MediationComment):
    pass


class MediationSessionDetailResponse(CustomModel):
    id: MongoId
    title: str
    description: str | None = None
    created_by_user_type: UserType
    status: MediationSessionStatus
    safety_status: SafetyStatus
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    archived_at: datetime | None = None
    has_marked_resolved: bool
    other_has_marked_resolved: bool
    has_marked_archived: bool
    other_has_marked_archived: bool
    latest_advice_id: MongoId | None = None
    my_perspective: PerspectiveResponse | None = None
    my_reflection_status: Literal["NONE", "PROCESSING", "AVAILABLE", "FAILED"]
    my_reflection: PrivateReflectionOutput | None = None
    other_user_type: UserType
    other_perspective_status: Literal["NOT_STARTED", "DRAFT", "SUBMITTED"]
    advice_status: Literal["NONE", "PROCESSING", "AVAILABLE", "FAILED", "BLOCKED"]
    advice: SharedMediationAdviceOutput | None = None
    comments: list[MediationCommentResponse]


class SubmitPerspectiveResponse(CustomModel):
    perspective: PerspectiveResponse
    session: MediationSession
    created_jobs: list[MediationAIJob]
    safety_message: str | None = None


class ReflectionEndpointResponse(CustomModel):
    status: Literal["NONE", "PROCESSING", "AVAILABLE", "FAILED"]
    reflection: PrivateReflectionOutput | None = None


class AdviceEndpointResponse(CustomModel):
    status: Literal["NONE", "PROCESSING", "AVAILABLE", "FAILED", "BLOCKED"]
    advice: SharedMediationAdviceOutput | None = None
    message: str | None = None


class CommentCreateResponse(CustomModel):
    comment: MediationCommentResponse
    job: MediationAIJob | None
