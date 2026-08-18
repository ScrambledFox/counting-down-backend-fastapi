from datetime import datetime
from enum import Enum

from pydantic import Field, field_validator, model_validator

from app.schemas.v1.base import CustomModel, DefaultMongoIdField, MongoId
from app.schemas.v1.user import UserType


class RelationshipCareCategory(str, Enum):
    CONFLICT = "CONFLICT"
    PRIVACY = "PRIVACY"
    TRUST = "TRUST"
    AUTONOMY = "AUTONOMY"
    COMMUNICATION = "COMMUNICATION"
    INTIMACY = "INTIMACY"
    FAMILY = "FAMILY"
    TIME = "TIME"
    SOCIAL_LIFE = "SOCIAL_LIFE"
    OTHER = "OTHER"


class RequestImportance(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    DISCUSSING = "DISCUSSING"
    AGREED = "AGREED"
    REVISIT = "REVISIT"
    ARCHIVED = "ARCHIVED"


class FairnessType(str, Enum):
    SYMMETRIC = "SYMMETRIC"
    ASYMMETRIC = "ASYMMETRIC"


class AgreementResponseType(str, Enum):
    DISCUSS = "DISCUSS"
    NOT_COMFORTABLE = "NOT_COMFORTABLE"


class PersonalGoalCategory(str, Enum):
    EMOTIONAL_REGULATION = "EMOTIONAL_REGULATION"
    CONFLICT = "CONFLICT"
    COMMUNICATION = "COMMUNICATION"
    TRUST = "TRUST"
    AUTONOMY = "AUTONOMY"
    INTIMACY = "INTIMACY"
    ATTACHMENT = "ATTACHMENT"
    SELF_RESPECT = "SELF_RESPECT"
    OTHER = "OTHER"


class GoalVisibility(str, Enum):
    PRIVATE = "PRIVATE"
    SHARED_WITH_PARTNER = "SHARED_WITH_PARTNER"


class _TrimmedModel(CustomModel):
    @field_validator("*", mode="before")
    @classmethod
    def trim_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class PersonalBoundaryFields(_TrimmedModel):
    title: str = Field(min_length=1, max_length=120)
    what_i_need: str = Field(min_length=1, max_length=1500)
    what_i_will_do: str = Field(min_length=1, max_length=1500)
    why_this_matters: str | None = Field(default=None, max_length=1500)
    category: RelationshipCareCategory = RelationshipCareCategory.OTHER


class PersonalBoundaryCreate(PersonalBoundaryFields):
    pass


class PersonalBoundaryUpdate(_TrimmedModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    what_i_need: str | None = Field(default=None, min_length=1, max_length=1500)
    what_i_will_do: str | None = Field(default=None, min_length=1, max_length=1500)
    why_this_matters: str | None = Field(default=None, max_length=1500)
    category: RelationshipCareCategory | None = None

    @model_validator(mode="after")
    def reject_blank_required_fields(self) -> PersonalBoundaryUpdate:
        for name in {"title", "what_i_need", "what_i_will_do"} & self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} must not be blank")
        return self


class PersonalBoundary(PersonalBoundaryFields):
    id: DefaultMongoIdField = None
    owner_user_type: UserType
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class PersonalBoundaryView(PersonalBoundary):
    is_mine: bool


class RelationshipRequestFields(_TrimmedModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    why_it_matters: str = Field(min_length=1, max_length=1500)
    ideas: str | None = Field(default=None, max_length=2000)
    importance: RequestImportance = RequestImportance.MEDIUM
    category: RelationshipCareCategory = RelationshipCareCategory.OTHER


class RelationshipRequestCreate(RelationshipRequestFields):
    pass


class RelationshipRequestUpdate(_TrimmedModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    why_it_matters: str | None = Field(default=None, min_length=1, max_length=1500)
    ideas: str | None = Field(default=None, max_length=2000)
    importance: RequestImportance | None = None
    category: RelationshipCareCategory | None = None

    @model_validator(mode="after")
    def reject_blank_required_fields(self) -> RelationshipRequestUpdate:
        for name in {"title", "description", "why_it_matters"} & self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} must not be blank")
        return self


class RelationshipRequest(RelationshipRequestFields):
    id: DefaultMongoIdField = None
    owner_user_type: UserType
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class RelationshipRequestView(RelationshipRequest):
    is_mine: bool


class PersonalGoalFields(_TrimmedModel):
    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=3000)
    why_it_matters: str | None = Field(default=None, max_length=2000)
    trigger: str | None = Field(default=None, max_length=2000)
    practice: str | None = Field(default=None, max_length=2000)
    reminder: str | None = Field(default=None, max_length=500)
    category: PersonalGoalCategory = PersonalGoalCategory.OTHER
    visibility: GoalVisibility = GoalVisibility.PRIVATE


class PersonalGoalCreate(PersonalGoalFields):
    pass


class PersonalGoalUpdate(_TrimmedModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    goal: str | None = Field(default=None, min_length=1, max_length=3000)
    why_it_matters: str | None = Field(default=None, max_length=2000)
    trigger: str | None = Field(default=None, max_length=2000)
    practice: str | None = Field(default=None, max_length=2000)
    reminder: str | None = Field(default=None, max_length=500)
    category: PersonalGoalCategory | None = None
    visibility: GoalVisibility | None = None

    @model_validator(mode="after")
    def reject_blank_required_fields(self) -> PersonalGoalUpdate:
        for name in {"title", "goal"} & self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} must not be blank")
        for name in {"category", "visibility"} & self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} must not be null")
        return self


class PersonalGoal(PersonalGoalFields):
    id: DefaultMongoIdField = None
    owner_user_type: UserType
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class PersonalGoalView(PersonalGoal):
    is_mine: bool


class AgreementPerspective(_TrimmedModel):
    user_type: UserType
    what_i_need: str | None = Field(default=None, max_length=1500)
    what_i_commit_to: str | None = Field(default=None, max_length=1500)
    why_this_matters_to_me: str | None = Field(default=None, max_length=1500)


class MyAgreementPerspective(_TrimmedModel):
    what_i_need: str | None = Field(default=None, max_length=1500)
    what_i_commit_to: str | None = Field(default=None, max_length=1500)
    why_this_matters_to_me: str | None = Field(default=None, max_length=1500)


class AgreementRevisionFields(_TrimmedModel):
    title: str = Field(min_length=1, max_length=120)
    why_it_matters: str = Field(min_length=1, max_length=2000)
    agreement_text: str = Field(min_length=1, max_length=4000)
    fairness_type: FairnessType
    fairness_explanation: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_fairness(self) -> AgreementRevisionFields:
        if self.fairness_type == FairnessType.ASYMMETRIC and not self.fairness_explanation:
            raise ValueError("An asymmetric agreement needs a fairness explanation")
        if self.fairness_type == FairnessType.SYMMETRIC:
            self.fairness_explanation = None
        return self


class AgreementCreate(AgreementRevisionFields):
    my_perspective: MyAgreementPerspective | None = None


class AgreementRevisionCreate(AgreementRevisionFields):
    expected_current_revision_id: MongoId
    my_perspective: MyAgreementPerspective | None = None


class RelationshipAgreement(CustomModel):
    id: DefaultMongoIdField = None
    created_by_user_type: UserType
    status: AgreementStatus
    current_revision_id: MongoId | None = None
    current_revision_number: int = 0
    last_agreed_revision_id: MongoId | None = None
    created_at: datetime
    updated_at: datetime
    proposed_at: datetime | None = None
    revisited_at: datetime | None = None
    archive_requested_by_user_types: list[UserType] = Field(default_factory=list)
    archived_at: datetime | None = None


class AgreementRevision(AgreementRevisionFields):
    id: DefaultMongoIdField = None
    agreement_id: MongoId
    revision_number: int
    perspectives: list[AgreementPerspective] = Field(default_factory=list)
    created_by_user_type: UserType
    created_at: datetime
    agreed_at: datetime | None = None


class AgreementAcceptance(CustomModel):
    id: DefaultMongoIdField = None
    agreement_id: MongoId
    revision_id: MongoId
    user_type: UserType
    accepted_at: datetime
    revoked_at: datetime | None = None


class AgreementResponseCreate(_TrimmedModel):
    response_type: AgreementResponseType
    note: str | None = Field(default=None, max_length=2000)


class AgreementResponse(AgreementResponseCreate):
    id: DefaultMongoIdField = None
    agreement_id: MongoId
    revision_id: MongoId
    user_type: UserType
    created_at: datetime
    updated_at: datetime


class AgreementSummary(CustomModel):
    id: MongoId
    status: AgreementStatus
    title: str
    agreement_text: str
    fairness_type: FairnessType
    revision_number: int
    updated_at: datetime
    is_creator: bool
    has_my_acceptance: bool
    has_partner_acceptance: bool
    needs_my_response: bool


class AgreementRevisionView(CustomModel):
    revision: AgreementRevision
    acceptances: list[AgreementAcceptance]
    responses: list[AgreementResponse]


class AgreementDetail(CustomModel):
    agreement: RelationshipAgreement
    current_revision: AgreementRevisionView
    history: list[AgreementRevisionView]
    current_user_type: UserType
    partner_user_type: UserType
    can_edit: bool
    can_propose: bool
    can_accept: bool


class RelationshipCareOverview(CustomModel):
    current_user_type: UserType
    partner_user_type: UserType
    agreement_counts: dict[str, int]
    agreements: list[AgreementSummary]
    boundaries: list[PersonalBoundaryView]
    requests: list[RelationshipRequestView]
    archived_boundaries: list[PersonalBoundaryView]
    archived_requests: list[RelationshipRequestView]
    goals: list[PersonalGoalView]
    archived_goals: list[PersonalGoalView]
