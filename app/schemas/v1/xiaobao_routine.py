from datetime import UTC, date, datetime, time
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_serializer, field_validator, model_validator

from app.schemas.v1.base import CustomModel, DefaultMongoIdField, MongoId
from app.schemas.v1.user import UserType


class XiaoBaoRoutineFrequency(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    ONCE = "ONCE"


class XiaoBaoRoutineKind(str, Enum):
    REMINDER = "REMINDER"
    ROUTINE = "ROUTINE"


class XiaoBaoRoutineContextProfile(str, Enum):
    RELATIONSHIP_CARE = "RELATIONSHIP_CARE"


class XiaoBaoRoutineDeliveryChannel(str, Enum):
    IN_APP = "IN_APP"


class XiaoBaoRoutinePauseReason(str, Enum):
    MANUAL = "MANUAL"
    UNREAD_INACTIVITY = "UNREAD_INACTIVITY"


class XiaoBaoRoutineFinishReason(str, Enum):
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class XiaoBaoRoutineRunStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class XiaoBaoRoutineSchedule(CustomModel):
    frequency: XiaoBaoRoutineFrequency
    local_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(min_length=1, max_length=100)
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    local_date: date | None = None

    @field_serializer("local_date")
    def serialize_local_date(self, value: date | None) -> str | None:
        """Keep local calendar dates BSON-safe without converting them to UTC instants."""
        return value.isoformat() if value is not None else None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @field_validator("weekdays")
    @classmethod
    def normalize_weekdays(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("weekdays must use 0 (Monday) through 6 (Sunday)")
        if len(set(value)) != len(value):
            raise ValueError("weekdays must not contain duplicates")
        return sorted(value)

    @model_validator(mode="after")
    def validate_frequency(self) -> XiaoBaoRoutineSchedule:
        if self.frequency == XiaoBaoRoutineFrequency.DAILY and self.weekdays:
            raise ValueError("daily schedules must not specify weekdays")
        if self.frequency == XiaoBaoRoutineFrequency.WEEKLY and not self.weekdays:
            raise ValueError("weekly schedules require at least one weekday")
        if self.frequency == XiaoBaoRoutineFrequency.ONCE:
            if self.weekdays:
                raise ValueError("one-time schedules must not specify weekdays")
            if self.local_date is None:
                raise ValueError("one-time schedules require local_date")
            local_naive = datetime.combine(
                self.local_date,
                time(*(int(part) for part in self.local_time.split(":"))),
            )
            timezone = ZoneInfo(self.timezone)
            valid = any(
                candidate.astimezone(UTC).astimezone(timezone).replace(tzinfo=None) == local_naive
                for candidate in (
                    local_naive.replace(tzinfo=timezone, fold=0),
                    local_naive.replace(tzinfo=timezone, fold=1),
                )
            )
            if not valid:
                raise ValueError("one-time reminder local time does not exist in its timezone")
        elif self.local_date is not None:
            raise ValueError("only one-time schedules may specify local_date")
        return self


class XiaoBaoRoutineCreate(CustomModel):
    kind: XiaoBaoRoutineKind = XiaoBaoRoutineKind.ROUTINE
    name: str = Field(min_length=1, max_length=100)
    instruction: str | None = Field(default=None, min_length=1, max_length=3000)
    message: str | None = Field(default=None, min_length=1, max_length=3000)
    schedule: XiaoBaoRoutineSchedule
    context_profile: XiaoBaoRoutineContextProfile = XiaoBaoRoutineContextProfile.RELATIONSHIP_CARE

    @field_validator("name", "instruction", "message", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_kind(self) -> XiaoBaoRoutineCreate:
        if self.kind == XiaoBaoRoutineKind.REMINDER:
            if self.schedule.frequency != XiaoBaoRoutineFrequency.ONCE:
                raise ValueError("reminders must use a one-time schedule")
            if not self.message:
                raise ValueError("reminders require a message")
            if self.instruction is not None:
                raise ValueError("reminders cannot include a routine instruction")
        else:
            if self.schedule.frequency == XiaoBaoRoutineFrequency.ONCE:
                raise ValueError("routines must use a daily or weekly schedule")
            if not self.instruction:
                raise ValueError("routines require an instruction")
            if self.message is not None:
                raise ValueError("routines cannot include a static reminder message")
        return self


class XiaoBaoRoutineUpdate(CustomModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    instruction: str | None = Field(default=None, min_length=1, max_length=3000)
    message: str | None = Field(default=None, min_length=1, max_length=3000)
    schedule: XiaoBaoRoutineSchedule | None = None
    context_profile: XiaoBaoRoutineContextProfile | None = None

    @field_validator("name", "instruction", "message", mode="before")
    @classmethod
    def trim_optional_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class XiaoBaoRoutine(CustomModel):
    id: DefaultMongoIdField = None
    owner_user_type: UserType
    kind: XiaoBaoRoutineKind = XiaoBaoRoutineKind.ROUTINE
    name: str
    instruction: str | None = None
    message: str | None = None
    schedule: XiaoBaoRoutineSchedule
    context_profile: XiaoBaoRoutineContextProfile
    delivery_channel: XiaoBaoRoutineDeliveryChannel = XiaoBaoRoutineDeliveryChannel.IN_APP
    enabled: bool = True
    next_run_at: datetime | None
    last_scheduled_for: datetime | None = None
    revision: int = Field(default=1, ge=1)
    policy_version: int = Field(default=1, ge=1)
    pending_delivery_run_id: MongoId | None = None
    pending_delivery_expires_at: datetime | None = None
    committed_delivery_pending_run_id: MongoId | None = None
    last_committed_delivery_run_id: MongoId | None = None
    created_at: datetime
    updated_at: datetime
    paused_at: datetime | None = None
    pause_reason: XiaoBaoRoutinePauseReason | None = None
    finished_at: datetime | None = None
    finish_reason: XiaoBaoRoutineFinishReason | None = None
    deleted_at: datetime | None = None


class XiaoBaoRoutineResponse(CustomModel):
    id: MongoId
    kind: XiaoBaoRoutineKind
    name: str
    instruction: str | None = None
    message: str | None = None
    schedule: XiaoBaoRoutineSchedule
    context_profile: XiaoBaoRoutineContextProfile
    delivery_channel: XiaoBaoRoutineDeliveryChannel
    enabled: bool
    next_run_at: datetime | None
    last_scheduled_for: datetime | None = None
    created_at: datetime
    updated_at: datetime
    paused_at: datetime | None = None
    pause_reason: XiaoBaoRoutinePauseReason | None = None
    finished_at: datetime | None = None
    finish_reason: XiaoBaoRoutineFinishReason | None = None
    deleted_at: datetime | None = None

    @classmethod
    def from_record(cls, routine: XiaoBaoRoutine) -> XiaoBaoRoutineResponse:
        return cls.model_validate(routine.model_dump(mode="python"))


class XiaoBaoRoutineRun(CustomModel):
    id: DefaultMongoIdField = None
    routine_id: MongoId
    owner_user_type: UserType
    status: XiaoBaoRoutineRunStatus
    scheduled_for: datetime
    local_scheduled_at: str = Field(min_length=1, max_length=40)
    timezone_snapshot: str = Field(min_length=1, max_length=100)
    available_at: datetime
    attempt_count: int = Field(default=0, ge=0)
    routine_revision: int = Field(default=1, ge=1)
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    output_message_id: MongoId | None = None
    error_code: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=100)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class XiaoBaoRoutineRunResponse(CustomModel):
    id: MongoId
    routine_id: MongoId
    status: XiaoBaoRoutineRunStatus
    scheduled_for: datetime
    local_scheduled_at: str
    timezone_snapshot: str
    attempt_count: int
    output_message_id: MongoId | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @classmethod
    def from_record(cls, run: XiaoBaoRoutineRun) -> XiaoBaoRoutineRunResponse:
        return cls.model_validate(run.model_dump(mode="python"))


class XiaoBaoRoutineRunList(CustomModel):
    items: list[XiaoBaoRoutineRunResponse]
    has_more: bool = False


class XiaoBaoInboxUnreadCount(CustomModel):
    unread_count: int = Field(ge=0)
