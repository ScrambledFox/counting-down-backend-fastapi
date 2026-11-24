from datetime import datetime, timedelta
from hashlib import sha256
from typing import Annotated, Any
from uuid import uuid4

from bson import ObjectId
from cryptography.fernet import Fernet
from fastapi import Depends
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.db.mongo_client import get_db
from app.models.mongo import AsyncDB
from app.schemas.v1.base import MongoId
from app.schemas.v1.user import UserType
from app.schemas.v1.xiaobao import XiaoBaoMessage, XiaoBaoMessageSource, XiaoBaoMessageStatus
from app.schemas.v1.xiaobao_push import (
    XiaoBaoPushDelivery,
    XiaoBaoPushDeliveryKind,
    XiaoBaoPushDeliveryStatus,
    XiaoBaoPushSubscription,
)
from app.util.time import utc_now

settings = get_settings()


def _oid(value: MongoId | str) -> ObjectId:
    return ObjectId(str(value))


class XiaoBaoPushSubscriptionRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.xiaobao_push_subscriptions_collection_name]

    async def get_owned(self, device_id: str, owner: UserType) -> XiaoBaoPushSubscription | None:
        doc = await self._collection.find_one({"owner_user_type": owner, "device_id": device_id})
        return XiaoBaoPushSubscription.model_validate(doc) if doc else None

    async def get_by_id(self, subscription_id: MongoId) -> XiaoBaoPushSubscription | None:
        doc = await self._collection.find_one({"_id": _oid(subscription_id)})
        return XiaoBaoPushSubscription.model_validate(doc) if doc else None

    async def list_owned(self, owner: UserType) -> list[XiaoBaoPushSubscription]:
        docs = (
            await self._collection.find({"owner_user_type": owner})
            .sort("updated_at", DESCENDING)
            .to_list(length=None)
        )
        return [XiaoBaoPushSubscription.model_validate(doc) for doc in docs]

    async def list_owned_created_at_or_before(
        self, owner: UserType, before: datetime
    ) -> list[XiaoBaoPushSubscription]:
        docs = (
            await self._collection.find({"owner_user_type": owner, "created_at": {"$lte": before}})
            .sort("updated_at", DESCENDING)
            .to_list(length=None)
        )
        return [XiaoBaoPushSubscription.model_validate(doc) for doc in docs]

    async def endpoint_owned_by_other(self, endpoint_hash: str, owner: UserType) -> bool:
        doc = await self._collection.find_one(
            {"endpoint_hash": endpoint_hash, "owner_user_type": {"$ne": owner}}, {"_id": 1}
        )
        return doc is not None

    async def endpoint_used_by_other_device(
        self, endpoint_hash: str, owner: UserType, device_id: str
    ) -> bool:
        doc = await self._collection.find_one(
            {
                "endpoint_hash": endpoint_hash,
                "owner_user_type": owner,
                "device_id": {"$ne": device_id},
            },
            {"_id": 1},
        )
        return doc is not None

    async def upsert(self, value: XiaoBaoPushSubscription) -> XiaoBaoPushSubscription:
        data = value.model_dump(mode="python", by_alias=True, exclude_none=True)
        # `_id` is immutable and `created_at` belongs solely to the insert path. Keeping either in
        # `$set` would make a registration refresh fail after the device's initial upsert.
        data.pop("_id", None)
        created_at = data.pop("created_at")
        doc = await self._collection.find_one_and_update(
            {"owner_user_type": value.owner_user_type, "device_id": value.device_id},
            {
                "$set": data,
                "$setOnInsert": {"created_at": created_at},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if not doc:
            raise RuntimeError("Xiao Bao push subscription could not be saved")
        return XiaoBaoPushSubscription.model_validate(doc)

    async def delete_owned(self, device_id: str, owner: UserType) -> XiaoBaoPushSubscription | None:
        doc = await self._collection.find_one_and_delete(
            {"owner_user_type": owner, "device_id": device_id}
        )
        return XiaoBaoPushSubscription.model_validate(doc) if doc else None

    async def record_success(self, subscription_id: MongoId) -> None:
        now = utc_now()
        await self._collection.update_one(
            {"_id": _oid(subscription_id)},
            {
                "$set": {"last_success_at": now, "updated_at": now},
                "$unset": {"last_failure_code": ""},
            },
        )

    async def record_failure(self, subscription_id: MongoId, code: str) -> None:
        now = utc_now()
        await self._collection.update_one(
            {"_id": _oid(subscription_id)},
            {"$set": {"last_failure_at": now, "last_failure_code": code[:80], "updated_at": now}},
        )


class XiaoBaoPushDeliveryRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.xiaobao_push_deliveries_collection_name]
        self._messages = db[settings.xiaobao_messages_collection_name]

    async def _upsert_once(self, key: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
        """Insert ``document`` unless a delivery with ``key`` exists; return the stored one.

        Concurrent upserts with the same unique key can race; the loser reads the winner.
        """
        doc: dict[str, Any] | None
        try:
            doc = await self._collection.find_one_and_update(
                key,
                {"$setOnInsert": document},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            doc = await self._collection.find_one(key)
        if not doc:
            raise RuntimeError("Xiao Bao push delivery could not be enqueued")
        return doc

    async def enqueue_message(
        self, *, message_id: MongoId, owner: UserType, subscription_id: MongoId
    ) -> XiaoBaoPushDelivery:
        now = utc_now()
        doc = await self._upsert_once(
            {
                "kind": XiaoBaoPushDeliveryKind.INBOX_MESSAGE,
                "message_id": str(message_id),
                "subscription_id": str(subscription_id),
            },
            XiaoBaoPushDelivery(
                kind=XiaoBaoPushDeliveryKind.INBOX_MESSAGE,
                owner_user_type=owner,
                message_id=str(message_id),
                subscription_id=str(subscription_id),
                available_at=now,
                created_at=now,
                updated_at=now,
            ).model_dump(mode="python", by_alias=True, exclude_none=True),
        )
        return XiaoBaoPushDelivery.model_validate(doc)

    async def enqueue_test(
        self, *, owner: UserType, subscription_id: MongoId, client_test_id: str
    ) -> XiaoBaoPushDelivery:
        now = utc_now()
        doc = await self._upsert_once(
            {
                "kind": XiaoBaoPushDeliveryKind.TEST,
                "subscription_id": str(subscription_id),
                "client_test_id": client_test_id,
            },
            XiaoBaoPushDelivery(
                kind=XiaoBaoPushDeliveryKind.TEST,
                owner_user_type=owner,
                subscription_id=str(subscription_id),
                client_test_id=client_test_id,
                available_at=now,
                created_at=now,
                updated_at=now,
            ).model_dump(mode="python", by_alias=True, exclude_none=True),
        )
        return XiaoBaoPushDelivery.model_validate(doc)

    async def claim_next(self, *, lease_seconds: float) -> XiaoBaoPushDelivery | None:
        now = utc_now()
        lease_token = uuid4().hex
        doc = await self._collection.find_one_and_update(
            {
                "$or": [
                    {"status": XiaoBaoPushDeliveryStatus.PENDING, "available_at": {"$lte": now}},
                    {
                        "status": XiaoBaoPushDeliveryStatus.PROCESSING,
                        "lease_expires_at": {"$lte": now},
                    },
                ],
                "attempt_count": {"$lt": settings.xiaobao_web_push_max_attempts},
            },
            {
                "$set": {
                    "status": XiaoBaoPushDeliveryStatus.PROCESSING,
                    "lease_token": lease_token,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                    "updated_at": now,
                    "error_code": None,
                },
                "$inc": {"attempt_count": 1},
            },
            sort=[("available_at", ASCENDING), ("created_at", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoPushDelivery.model_validate(doc) if doc else None

    async def fail_exhausted_stale(self) -> int:
        """Terminalize a final claimed attempt after its worker lease expires."""
        now = utc_now()
        result = await self._collection.update_many(
            {
                "status": XiaoBaoPushDeliveryStatus.PROCESSING,
                "lease_expires_at": {"$lte": now},
                "attempt_count": {"$gte": settings.xiaobao_web_push_max_attempts},
            },
            {
                "$set": {
                    "status": XiaoBaoPushDeliveryStatus.FAILED,
                    "error_code": "unknown",
                    "completed_at": now,
                    "updated_at": now,
                },
                "$unset": {"lease_token": "", "lease_expires_at": ""},
            },
        )
        return int(result.modified_count)

    async def mark_delivered(self, item: XiaoBaoPushDelivery) -> bool:
        if not item.id or not item.lease_token:
            return False
        now = utc_now()
        result = await self._collection.update_one(
            {
                "_id": _oid(item.id),
                "status": XiaoBaoPushDeliveryStatus.PROCESSING,
                "lease_token": item.lease_token,
            },
            {
                "$set": {
                    "status": XiaoBaoPushDeliveryStatus.DELIVERED,
                    "completed_at": now,
                    "updated_at": now,
                },
                "$unset": {"lease_token": "", "lease_expires_at": ""},
            },
        )
        return bool(result.modified_count)

    async def mark_terminal(self, item: XiaoBaoPushDelivery, code: str) -> bool:
        if not item.id or not item.lease_token:
            return False
        now = utc_now()
        result = await self._collection.update_one(
            {
                "_id": _oid(item.id),
                "status": XiaoBaoPushDeliveryStatus.PROCESSING,
                "lease_token": item.lease_token,
            },
            {
                "$set": {
                    "status": XiaoBaoPushDeliveryStatus.FAILED,
                    "error_code": code[:80],
                    "completed_at": now,
                    "updated_at": now,
                },
                "$unset": {"lease_token": "", "lease_expires_at": ""},
            },
        )
        return bool(result.modified_count)

    async def retry(self, item: XiaoBaoPushDelivery, code: str) -> bool:
        if not item.id or not item.lease_token:
            return False
        now = utc_now()
        exhausted = item.attempt_count >= settings.xiaobao_web_push_max_attempts
        delay = min(
            settings.xiaobao_web_push_retry_max_seconds,
            settings.xiaobao_web_push_retry_base_seconds * (2 ** max(item.attempt_count - 1, 0)),
        )
        fields: dict[str, Any] = {
            "status": XiaoBaoPushDeliveryStatus.FAILED
            if exhausted
            else XiaoBaoPushDeliveryStatus.PENDING,
            "error_code": code[:80],
            "updated_at": now,
            "available_at": now + timedelta(seconds=delay),
        }
        if exhausted:
            fields["completed_at"] = now
        result = await self._collection.update_one(
            {
                "_id": _oid(item.id),
                "status": XiaoBaoPushDeliveryStatus.PROCESSING,
                "lease_token": item.lease_token,
            },
            {"$set": fields, "$unset": {"lease_token": "", "lease_expires_at": ""}},
        )
        return bool(result.modified_count)

    async def cancel_for_subscription(self, subscription_id: MongoId) -> None:
        now = utc_now()
        await self._collection.update_many(
            {"subscription_id": str(subscription_id), "status": XiaoBaoPushDeliveryStatus.PENDING},
            {
                "$set": {
                    "status": XiaoBaoPushDeliveryStatus.CANCELLED,
                    "completed_at": now,
                    "updated_at": now,
                    "error_code": "subscription_revoked",
                }
            },
        )

    async def list_push_dispatch_pending(self, *, limit: int) -> list[XiaoBaoMessage]:
        docs = (
            await self._messages.find(
                {
                    "source": XiaoBaoMessageSource.ROUTINE,
                    "status": XiaoBaoMessageStatus.COMPLETE,
                    "push_dispatch_pending": True,
                }
            )
            .sort("delivered_at", ASCENDING)
            .limit(limit)
            .to_list(length=limit)
        )
        return [XiaoBaoMessage.model_validate(doc) for doc in docs]

    async def mark_message_dispatched(self, message_id: MongoId) -> bool:
        result = await self._messages.update_one(
            {
                "_id": _oid(message_id),
                "status": XiaoBaoMessageStatus.COMPLETE,
                "push_dispatch_pending": True,
            },
            {"$set": {"push_dispatch_pending": False, "push_enqueued_at": utc_now()}},
        )
        return bool(result.modified_count)


async def ensure_xiaobao_push_indexes(db: AsyncDB) -> None:
    subscriptions = db[settings.xiaobao_push_subscriptions_collection_name]
    deliveries = db[settings.xiaobao_push_deliveries_collection_name]
    messages = db[settings.xiaobao_messages_collection_name]
    await subscriptions.create_index(
        [("owner_user_type", ASCENDING), ("device_id", ASCENDING)], unique=True
    )
    await subscriptions.create_index("endpoint_hash", unique=True)
    await subscriptions.create_index([("owner_user_type", ASCENDING), ("updated_at", DESCENDING)])
    await deliveries.create_index(
        [("message_id", ASCENDING), ("subscription_id", ASCENDING)],
        unique=True,
        partialFilterExpression={"kind": XiaoBaoPushDeliveryKind.INBOX_MESSAGE.value},
    )
    await deliveries.create_index(
        [("subscription_id", ASCENDING), ("client_test_id", ASCENDING)],
        unique=True,
        partialFilterExpression={"kind": XiaoBaoPushDeliveryKind.TEST.value},
    )
    await deliveries.create_index(
        [("status", ASCENDING), ("available_at", ASCENDING), ("lease_expires_at", ASCENDING)]
    )
    await deliveries.create_index([("subscription_id", ASCENDING), ("status", ASCENDING)])
    await messages.create_index(
        [("push_dispatch_pending", ASCENDING), ("delivered_at", ASCENDING)],
        partialFilterExpression={
            "push_dispatch_pending": True,
            "source": XiaoBaoMessageSource.ROUTINE.value,
            "status": XiaoBaoMessageStatus.COMPLETE.value,
        },
        name="xiaobao_push_dispatch_pending",
    )


def endpoint_hash(endpoint: str) -> str:
    return sha256(endpoint.encode("utf-8")).hexdigest()


class XiaoBaoPushCipher:
    def __init__(self) -> None:
        key = settings.xiaobao_web_push_subscription_encryption_key
        if not key:
            raise RuntimeError("Xiao Bao push subscription encryption is not configured")
        self._fernet = Fernet(key.encode("ascii"))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
