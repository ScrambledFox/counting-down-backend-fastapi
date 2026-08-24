import asyncio

from app.core import logging
from app.core.config import get_settings
from app.db.mongo_client import get_db
from app.repositories.xiaobao import XiaoBaoConversationRepository, XiaoBaoMessageRepository
from app.repositories.xiaobao_push import (
    XiaoBaoPushDeliveryRepository,
    XiaoBaoPushSubscriptionRepository,
    ensure_xiaobao_push_indexes,
)
from app.services.xiaobao_push import (
    PyWebPushTransport,
    XiaoBaoPushDeliveryService,
    XiaoBaoPushDispatchService,
)

settings = get_settings()
logger = logging.get_logger(__name__)


async def process_one_xiaobao_push_work_item(
    dispatch: XiaoBaoPushDispatchService,
    delivery: XiaoBaoPushDeliveryService,
    deliveries: XiaoBaoPushDeliveryRepository,
) -> bool:
    try:
        dispatched = await dispatch.dispatch_pending(
            limit=settings.xiaobao_routine_materialize_batch_size
        )
        await deliveries.fail_exhausted_stale()
        item = await deliveries.claim_next(lease_seconds=settings.xiaobao_web_push_lease_seconds)
    except Exception as exc:
        logger.exception(
            "Xiao Bao push dispatch iteration failed",
            extra={"error_type": type(exc).__name__},
        )
        return False
    if not item:
        return bool(dispatched)
    try:
        await delivery.process(item)
    except Exception as exc:
        logger.exception(
            "Xiao Bao push delivery failed",
            extra={
                "delivery_id": str(item.id) if item.id else None,
                "error_type": type(exc).__name__,
            },
        )
        await deliveries.mark_terminal(item, "unknown")
    return True


async def run_xiaobao_push_worker(stop_event: asyncio.Event | None = None) -> None:
    db = get_db()
    await ensure_xiaobao_push_indexes(db)
    subscriptions = XiaoBaoPushSubscriptionRepository(db)
    deliveries = XiaoBaoPushDeliveryRepository(db)
    dispatch = XiaoBaoPushDispatchService(
        deliveries, subscriptions, XiaoBaoConversationRepository(db)
    )
    delivery = XiaoBaoPushDeliveryService(
        subscriptions, deliveries, XiaoBaoMessageRepository(db), PyWebPushTransport()
    )
    while stop_event is None or not stop_event.is_set():
        processed = await process_one_xiaobao_push_work_item(dispatch, delivery, deliveries)
        if not processed:
            await asyncio.sleep(settings.xiaobao_web_push_worker_poll_interval_seconds)


if __name__ == "__main__":
    asyncio.run(run_xiaobao_push_worker())
