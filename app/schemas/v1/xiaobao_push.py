from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.v1.base import CustomModel, DefaultMongoIdField, MongoId
from app.schemas.v1.user import UserType


class XiaoBaoPushSubscriptionKeys(CustomModel):
    p256dh: str = Field(min_length=16, max_length=512)
    auth: str = Field(min_length=8, max_length=512)


class XiaoBaoPushSubscriptionPayload(CustomModel):
    endpoint: str = Field(min_length=8, max_length=2048)
    keys: XiaoBaoPushSubscriptionKeys

    @field_validator("endpoint")
    @classmethod
    def require_https_endpoint(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("push subscription endpoint must use HTTPS")
        return value


class XiaoBaoPushSubscriptionUpsert(CustomModel):
    subscription: XiaoBaoPushSubscriptionPayload
    device_name: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("device_name", mode="before")
    @classmethod
    def trim_device_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class XiaoBaoPushDeliveryKind(str, Enum):
    INBOX_MESSAGE = "INBOX_MESSAGE"
    TEST = "TEST"


class XiaoBaoPushDeliveryStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class XiaoBaoPushSubscription(CustomModel):
    id: DefaultMongoIdField = None
    owner_user_type: UserType
    device_id: str
    device_name: str | None = None
    endpoint_ciphertext: str
    p256dh_ciphertext: str
    auth_ciphertext: str
    endpoint_hash: str
    created_at: datetime
    updated_at: datetime
    last_seen_at: datetime
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_failure_code: str | None = None


class XiaoBaoPushSubscriptionResponse(CustomModel):
    device_id: str
    device_name: str | None = None
    created_at: datetime
    updated_at: datetime
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_failure_code: str | None = None

    @classmethod
    def from_record(cls, value: XiaoBaoPushSubscription) -> XiaoBaoPushSubscriptionResponse:
        return cls.model_validate(value.model_dump(mode="python"))


class XiaoBaoPushConfigResponse(CustomModel):
    enabled: bool
    vapid_public_key: str | None = None


class XiaoBaoPushTestRequest(CustomModel):
    client_test_id: UUID


class XiaoBaoPushTestResponse(CustomModel):
    id: MongoId
    status: XiaoBaoPushDeliveryStatus


class XiaoBaoPushDelivery(CustomModel):
    id: DefaultMongoIdField = None
    kind: XiaoBaoPushDeliveryKind
    owner_user_type: UserType
    subscription_id: MongoId
    message_id: MongoId | None = None
    client_test_id: str | None = None
    status: XiaoBaoPushDeliveryStatus = XiaoBaoPushDeliveryStatus.PENDING
    attempt_count: int = 0
    available_at: datetime
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
