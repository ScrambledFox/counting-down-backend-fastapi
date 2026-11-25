import asyncio
import json
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends
from pywebpush import WebPushException, webpush  # type: ignore[import-untyped]
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout

from app.core.config import get_settings
from app.repositories.xiaobao import XiaoBaoConversationRepository, XiaoBaoMessageRepository
from app.repositories.xiaobao_push import (
    XiaoBaoPushCipher,
    XiaoBaoPushDeliveryRepository,
    XiaoBaoPushSubscriptionRepository,
    endpoint_hash,
)
from app.schemas.v1.exceptions import ConflictException, NotFoundException
from app.schemas.v1.user import UserType
from app.schemas.v1.xiaobao_push import (
    XiaoBaoPushConfigResponse,
    XiaoBaoPushDelivery,
    XiaoBaoPushDeliveryKind,
    XiaoBaoPushSubscription,
    XiaoBaoPushSubscriptionResponse,
    XiaoBaoPushSubscriptionUpsert,
    XiaoBaoPushTestResponse,
)
from app.util.time import utc_now
from app.workers.job_runner import JobResult

settings = get_settings()


class PushTransportError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class WebPushTransport(Protocol):
    async def send(self, subscription: dict[str, object], payload: dict[str, object]) -> None: ...


class PyWebPushTransport:
    async def send(self, subscription: dict[str, object], payload: dict[str, object]) -> None:
        if not settings.xiaobao_web_push_ready:
            raise PushTransportError("not_configured")
        try:
            await asyncio.to_thread(
                webpush,
                subscription_info=subscription,
                data=json.dumps(payload, separators=(",", ":")),
                vapid_private_key=settings.xiaobao_web_push_vapid_private_key,
                vapid_claims={"sub": settings.xiaobao_web_push_vapid_subject},
                ttl=settings.xiaobao_web_push_ttl_seconds,
                timeout=10,
            )
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in {404, 410}:
                raise PushTransportError("expired") from exc
            if status == 429 or (status is not None and 500 <= status <= 599):
                raise PushTransportError(f"http_{status}", retryable=True) from exc
            raise PushTransportError(f"http_{status}" if status else "unknown") from exc
        except (TimeoutError, RequestsTimeout, RequestsConnectionError) as exc:
            # A timed-out request may have reached a provider. Do not risk a duplicate alert.
            raise PushTransportError("unknown") from exc


def get_web_push_transport() -> WebPushTransport:
    return PyWebPushTransport()


class XiaoBaoPushService:
    def __init__(
        self,
        subscriptions: Annotated[XiaoBaoPushSubscriptionRepository, Depends()],
        deliveries: Annotated[XiaoBaoPushDeliveryRepository, Depends()],
    ) -> None:
        self._subscriptions = subscriptions
        self._deliveries = deliveries

    @staticmethod
    def _require_configured() -> None:
        if not settings.xiaobao_web_push_ready:
            raise ConflictException("Xiao Bao push notifications are not configured")

    async def config(self) -> XiaoBaoPushConfigResponse:
        return XiaoBaoPushConfigResponse(
            enabled=settings.xiaobao_web_push_ready,
            vapid_public_key=(
                settings.xiaobao_web_push_vapid_public_key
                if settings.xiaobao_web_push_ready
                else None
            ),
        )

    async def list(self, owner: UserType) -> list[XiaoBaoPushSubscriptionResponse]:
        return [
            XiaoBaoPushSubscriptionResponse.from_record(item)
            for item in await self._subscriptions.list_owned(owner)
        ]

    async def upsert(
        self, device_id: UUID, owner: UserType, payload: XiaoBaoPushSubscriptionUpsert
    ) -> XiaoBaoPushSubscriptionResponse:
        self._require_configured()
        device_id_str = str(device_id)
        fingerprint = endpoint_hash(payload.subscription.endpoint)
        if await self._subscriptions.endpoint_owned_by_other(fingerprint, owner):
            raise ConflictException("This push subscription belongs to another user")
        if await self._subscriptions.endpoint_used_by_other_device(
            fingerprint, owner, device_id_str
        ):
            raise ConflictException(
                "This push subscription is already registered to another device"
            )
        cipher = XiaoBaoPushCipher()
        now = utc_now()
        existing = await self._subscriptions.get_owned(device_id_str, owner)
        stored = await self._subscriptions.upsert(
            XiaoBaoPushSubscription(
                id=existing.id if existing else None,
                owner_user_type=owner,
                device_id=device_id_str,
                device_name=payload.device_name,
                endpoint_ciphertext=cipher.encrypt(payload.subscription.endpoint),
                p256dh_ciphertext=cipher.encrypt(payload.subscription.keys.p256dh),
                auth_ciphertext=cipher.encrypt(payload.subscription.keys.auth),
                endpoint_hash=fingerprint,
                created_at=existing.created_at if existing else now,
                updated_at=now,
                last_seen_at=now,
                last_success_at=existing.last_success_at if existing else None,
                last_failure_at=existing.last_failure_at if existing else None,
                last_failure_code=existing.last_failure_code if existing else None,
            )
        )
        return XiaoBaoPushSubscriptionResponse.from_record(stored)

    async def revoke(self, device_id: UUID, owner: UserType) -> None:
        device_id_str = str(device_id)
        item = await self._subscriptions.delete_owned(device_id_str, owner)
        if not item or not item.id:
            raise NotFoundException("Xiao Bao push subscription", device_id_str)
        await self._deliveries.cancel_for_subscription(str(item.id))

    async def test(
        self, device_id: UUID, owner: UserType, client_test_id: str
    ) -> XiaoBaoPushTestResponse:
        self._require_configured()
        device_id_str = str(device_id)
        item = await self._subscriptions.get_owned(device_id_str, owner)
        if not item or not item.id:
            raise NotFoundException("Xiao Bao push subscription", device_id_str)
        delivery = await self._deliveries.enqueue_test(
            owner=owner, subscription_id=str(item.id), client_test_id=client_test_id
        )
        if not delivery.id:
            raise RuntimeError("Xiao Bao push test has no identifier")
        return XiaoBaoPushTestResponse(id=str(delivery.id), status=delivery.status)


class XiaoBaoPushDispatchService:
    def __init__(
        self,
        deliveries: XiaoBaoPushDeliveryRepository,
        subscriptions: XiaoBaoPushSubscriptionRepository,
        conversations: XiaoBaoConversationRepository,
    ) -> None:
        self._deliveries = deliveries
        self._subscriptions = subscriptions
        self._conversations = conversations

    async def dispatch_pending(self, *, limit: int) -> int:
        dispatched = 0
        for message in await self._deliveries.list_push_dispatch_pending(limit=limit):
            if not message.id:
                continue
            conversation = await self._conversations.get(str(message.conversation_id))
            if not conversation:
                continue
            for subscription in await self._subscriptions.list_owned_created_at_or_before(
                conversation.owner_user_type,
                message.delivered_at or message.created_at,
            ):
                if subscription.id:
                    await self._deliveries.enqueue_message(
                        message_id=str(message.id),
                        owner=conversation.owner_user_type,
                        subscription_id=str(subscription.id),
                    )
            if await self._deliveries.mark_message_dispatched(str(message.id)):
                dispatched += 1
        return dispatched


class XiaoBaoPushDeliveryService:
    def __init__(
        self,
        subscriptions: XiaoBaoPushSubscriptionRepository,
        deliveries: XiaoBaoPushDeliveryRepository,
        messages: XiaoBaoMessageRepository,
        transport: WebPushTransport,
    ) -> None:
        self._subscriptions = subscriptions
        self._deliveries = deliveries
        self._messages = messages
        self._transport = transport

    async def process(self, item: XiaoBaoPushDelivery) -> JobResult:
        """Deliver one claimed push and report the outcome.

        Expected final outcomes (revoked subscription, missing message, expired endpoint) are
        ``TERMINAL``; retryable or unexpected transport errors are ``FAILED``.
        """
        if not item.id or not item.subscription_id:
            return JobResult.TERMINAL
        subscription = await self._subscriptions.get_by_id(item.subscription_id)
        if not subscription or subscription.owner_user_type != item.owner_user_type:
            await self._deliveries.mark_terminal(item, "subscription_revoked")
            return JobResult.TERMINAL
        cipher = XiaoBaoPushCipher()
        data: dict[str, object]
        if item.kind == XiaoBaoPushDeliveryKind.INBOX_MESSAGE:
            if not item.message_id:
                await self._deliveries.mark_terminal(item, "missing_message")
                return JobResult.TERMINAL
            message = await self._messages.get_completed_routine_message(item.message_id)
            if not message:
                await self._deliveries.mark_terminal(item, "missing_message")
                return JobResult.TERMINAL
            data = {"v": 1, "kind": "INBOX", "message_id": str(item.message_id)}
        else:
            data = {"v": 1, "kind": "TEST", "message_id": str(item.id)}
        raw_subscription: dict[str, object] = {
            "endpoint": cipher.decrypt(subscription.endpoint_ciphertext),
            "keys": {
                "p256dh": cipher.decrypt(subscription.p256dh_ciphertext),
                "auth": cipher.decrypt(subscription.auth_ciphertext),
            },
        }
        try:
            await self._transport.send(raw_subscription, data)
        except PushTransportError as exc:
            await self._subscriptions.record_failure(str(subscription.id), exc.code)
            if exc.code == "expired":
                await self._deliveries.mark_terminal(item, exc.code)
                await self._subscriptions.delete_owned(
                    subscription.device_id, subscription.owner_user_type
                )
                await self._deliveries.cancel_for_subscription(str(subscription.id))
                return JobResult.TERMINAL
            if exc.retryable:
                await self._deliveries.retry(item, exc.code)
            else:
                await self._deliveries.mark_terminal(item, exc.code)
            return JobResult.FAILED
        await self._subscriptions.record_success(str(subscription.id))
        await self._deliveries.mark_delivered(item)
        return JobResult.PROCESSED
