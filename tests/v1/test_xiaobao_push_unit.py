from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.repositories.xiaobao_push import (
    XiaoBaoPushDeliveryRepository,
    XiaoBaoPushSubscriptionRepository,
)
from app.schemas.v1.user import UserType
from app.schemas.v1.xiaobao import (
    XiaoBaoConversation,
    XiaoBaoConversationPurpose,
    XiaoBaoMessage,
    XiaoBaoMessageRole,
    XiaoBaoMessageSource,
    XiaoBaoMessageStatus,
)
from app.schemas.v1.xiaobao_push import (
    XiaoBaoPushDelivery,
    XiaoBaoPushDeliveryKind,
    XiaoBaoPushDeliveryStatus,
    XiaoBaoPushSubscription,
)
from app.services import xiaobao_push
from app.services.xiaobao_push import (
    PushTransportError,
    PyWebPushTransport,
    XiaoBaoPushDeliveryService,
)
from app.util.time import utc_now
from app.workers.xiaobao_push_worker import process_one_xiaobao_push_work_item

OID_1 = "64b64c000000000000000001"
OID_2 = "64b64c000000000000000002"


def _configure_push(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xiaobao_push.settings, "xiaobao_web_push_enabled", True)
    monkeypatch.setattr(xiaobao_push.settings, "xiaobao_web_push_vapid_public_key", "public")
    monkeypatch.setattr(xiaobao_push.settings, "xiaobao_web_push_vapid_private_key", "private")
    monkeypatch.setattr(
        xiaobao_push.settings, "xiaobao_web_push_vapid_subject", "mailto:test@example.com"
    )
    monkeypatch.setattr(
        xiaobao_push.settings,
        "xiaobao_web_push_subscription_encryption_key",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )


@pytest.mark.asyncio
async def test_transport_sends_only_fixed_inbox_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_push(monkeypatch)
    sent: dict[str, object] = {}

    def fake_webpush(**kwargs: object) -> None:
        sent.update(kwargs)

    monkeypatch.setattr(xiaobao_push, "webpush", fake_webpush)
    await PyWebPushTransport().send(
        {"endpoint": "https://push.example/device", "keys": {"p256dh": "a", "auth": "b"}},
        {"v": 1, "kind": "INBOX", "message_id": OID_1},
    )

    assert sent["data"] == '{"v":1,"kind":"INBOX","message_id":"64b64c000000000000000001"}'
    assert "title" not in sent and "body" not in sent


@pytest.mark.asyncio
async def test_timeout_is_terminal_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_push(monkeypatch)

    def timeout_webpush(**_kwargs: object) -> None:
        raise TimeoutError

    monkeypatch.setattr(xiaobao_push, "webpush", timeout_webpush)
    with pytest.raises(PushTransportError, match="unknown") as exc_info:
        await PyWebPushTransport().send({}, {"v": 1, "kind": "TEST", "message_id": OID_1})
    assert not exc_info.value.retryable


@pytest.mark.asyncio
async def test_requests_timeout_is_terminal_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    from requests.exceptions import Timeout

    _configure_push(monkeypatch)

    def timeout_webpush(**_kwargs: object) -> None:
        raise Timeout

    monkeypatch.setattr(xiaobao_push, "webpush", timeout_webpush)
    with pytest.raises(PushTransportError, match="unknown"):
        await PyWebPushTransport().send({}, {"v": 1, "kind": "TEST", "message_id": OID_1})


@pytest.mark.asyncio
async def test_expired_subscription_never_touches_inbox_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_push(monkeypatch)
    now = utc_now()
    delivery = XiaoBaoPushDelivery(
        id=OID_1,
        kind=XiaoBaoPushDeliveryKind.INBOX_MESSAGE,
        owner_user_type=UserType.JORIS,
        subscription_id=OID_2,
        message_id=OID_1,
        status=XiaoBaoPushDeliveryStatus.PROCESSING,
        attempt_count=1,
        lease_token="lease",
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    subscription = XiaoBaoPushSubscription(
        id=OID_2,
        owner_user_type=UserType.JORIS,
        device_id="device",
        endpoint_ciphertext="gAAAAABpT2vCg0kz0lZlwji6b8iLPRhzeahRANfw4LcyH_MhNc9sqn7ba_MxO1WiX5-nxziiqLh-FJi4BN-F-rvD4O8PQ6Q0Ww==",
        p256dh_ciphertext="gAAAAABpT2vCg0kz0lZlwji6b8iLPRhzeahRANfw4LcyH_MhNc9sqn7ba_MxO1WiX5-nxziiqLh-FJi4BN-F-rvD4O8PQ6Q0Ww==",
        auth_ciphertext="gAAAAABpT2vCg0kz0lZlwji6b8iLPRhzeahRANfw4LcyH_MhNc9sqn7ba_MxO1WiX5-nxziiqLh-FJi4BN-F-rvD4O8PQ6Q0Ww==",
        endpoint_hash="hash",
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )
    subscriptions = SimpleNamespace(
        get_by_id=AsyncMock(return_value=subscription),
        record_failure=AsyncMock(),
        delete_owned=AsyncMock(),
    )
    deliveries = SimpleNamespace(mark_terminal=AsyncMock(), cancel_for_subscription=AsyncMock())
    messages = SimpleNamespace(get_completed_routine_message=AsyncMock(return_value=object()))
    transport = SimpleNamespace(send=AsyncMock(side_effect=PushTransportError("expired")))
    service = XiaoBaoPushDeliveryService(subscriptions, deliveries, messages, transport)

    # The cipher is not relevant to expiry; bypass it with synthetic subscription data.
    monkeypatch.setattr(
        xiaobao_push.XiaoBaoPushCipher,
        "decrypt",
        lambda _self, _value: "https://push.example/device",
    )
    await service.process(delivery)

    messages.get_completed_routine_message.assert_awaited_once_with(OID_1)
    deliveries.mark_terminal.assert_awaited_once_with(delivery, "expired")
    deliveries.cancel_for_subscription.assert_awaited_once_with(OID_2)


@pytest.mark.asyncio
async def test_dispatch_only_uses_devices_registered_when_message_became_visible() -> None:
    now = utc_now()
    message = XiaoBaoMessage(
        id=OID_1,
        conversation_id=OID_2,
        role=XiaoBaoMessageRole.ASSISTANT,
        status=XiaoBaoMessageStatus.COMPLETE,
        source=XiaoBaoMessageSource.ROUTINE,
        content="Private message",
        routine_id=OID_1,
        routine_run_id=OID_2,
        created_at=now,
        updated_at=now,
        delivered_at=now,
        push_dispatch_pending=True,
    )
    conversation = XiaoBaoConversation(
        id=OID_2,
        owner_user_type=UserType.JORIS,
        title="Routines inbox",
        purpose=XiaoBaoConversationPurpose.ROUTINE_INBOX,
        created_at=now,
        updated_at=now,
    )
    deliveries = SimpleNamespace(
        list_push_dispatch_pending=AsyncMock(return_value=[message]),
        mark_message_dispatched=AsyncMock(return_value=True),
        enqueue_message=AsyncMock(),
    )
    subscriptions = SimpleNamespace(list_owned_created_at_or_before=AsyncMock(return_value=[]))
    conversations = SimpleNamespace(get=AsyncMock(return_value=conversation))
    dispatch = xiaobao_push.XiaoBaoPushDispatchService(deliveries, subscriptions, conversations)

    assert await dispatch.dispatch_pending(limit=10) == 1
    subscriptions.list_owned_created_at_or_before.assert_awaited_once_with(UserType.JORIS, now)
    deliveries.enqueue_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_failure_keeps_worker_loop_alive() -> None:
    dispatch = SimpleNamespace(
        dispatch_pending=AsyncMock(side_effect=RuntimeError("db unavailable"))
    )
    delivery = SimpleNamespace(process=AsyncMock())
    deliveries = SimpleNamespace(fail_exhausted_stale=AsyncMock(), claim_next=AsyncMock())

    assert not await process_one_xiaobao_push_work_item(dispatch, delivery, deliveries)
    deliveries.claim_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscription_refresh_does_not_set_immutable_fields() -> None:
    now = utc_now()
    subscription = XiaoBaoPushSubscription(
        id=OID_2,
        owner_user_type=UserType.JORIS,
        device_id="11111111-1111-1111-1111-111111111111",
        endpoint_ciphertext="endpoint",
        p256dh_ciphertext="p256dh",
        auth_ciphertext="auth",
        endpoint_hash="hash",
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )
    collection = SimpleNamespace(
        find_one_and_update=AsyncMock(
            return_value=subscription.model_dump(mode="python", by_alias=True)
        )
    )
    repository = XiaoBaoPushSubscriptionRepository.__new__(XiaoBaoPushSubscriptionRepository)
    repository._collection = collection

    await repository.upsert(subscription)

    update = collection.find_one_and_update.await_args.args[1]
    assert "_id" not in update["$set"]
    assert "created_at" not in update["$set"]
    assert update["$setOnInsert"]["created_at"] == now


def test_enabled_production_push_rejects_malformed_fernet_key() -> None:
    with pytest.raises(ValueError, match="Fernet key"):
        Settings(
            app_env="prod",
            access_key_danfeng="d",
            access_key_joris="j",
            xiaobao_web_push_enabled=True,
            xiaobao_web_push_vapid_public_key="public",
            xiaobao_web_push_vapid_private_key="private",
            xiaobao_web_push_vapid_subject="mailto:test@example.com",
            xiaobao_web_push_subscription_encryption_key="not-a-fernet-key",
        )


@pytest.mark.asyncio
async def test_stale_final_claim_is_terminalized_without_resend() -> None:
    collection = SimpleNamespace(
        update_many=AsyncMock(return_value=SimpleNamespace(modified_count=1))
    )
    repository = XiaoBaoPushDeliveryRepository.__new__(XiaoBaoPushDeliveryRepository)
    repository._collection = collection

    assert await repository.fail_exhausted_stale() == 1
    query = collection.update_many.await_args.args[0]
    update = collection.update_many.await_args.args[1]
    assert query["attempt_count"] == {"$gte": xiaobao_push.settings.xiaobao_web_push_max_attempts}
    assert update["$set"]["status"] == XiaoBaoPushDeliveryStatus.FAILED
    assert update["$set"]["error_code"] == "unknown"
