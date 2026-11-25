from app.core import logging
from app.core.config import get_settings
from app.core.logging import error_fields
from app.models.mongo import AsyncDB
from app.repositories.xiaobao import XiaoBaoConversationRepository, XiaoBaoMessageRepository
from app.repositories.xiaobao_push import (
    XiaoBaoPushDeliveryRepository,
    XiaoBaoPushSubscriptionRepository,
)
from app.services.xiaobao_push import (
    PyWebPushTransport,
    XiaoBaoPushDeliveryService,
    XiaoBaoPushDispatchService,
)
from app.workers.job_runner import JobResult

settings = get_settings()
logger = logging.get_logger(__name__)


async def process_one_xiaobao_push_work_item(
    dispatch: XiaoBaoPushDispatchService,
    delivery: XiaoBaoPushDeliveryService,
    deliveries: XiaoBaoPushDeliveryRepository,
) -> JobResult:
    try:
        dispatched = await dispatch.dispatch_pending(
            limit=settings.xiaobao_routine_materialize_batch_size
        )
        await deliveries.fail_exhausted_stale()
        item = await deliveries.claim_next(lease_seconds=settings.xiaobao_web_push_lease_seconds)
    except Exception as exc:
        logger.error(
            "Xiao Bao push dispatch iteration failed",
            extra={"event": "job_item_failed", "job_kind": "push", **error_fields(exc)},
        )
        return JobResult.FAILED
    if not item:
        return JobResult.PROCESSED if dispatched else JobResult.IDLE
    try:
        return await delivery.process(item)
    except Exception as exc:
        logger.error(
            "Xiao Bao push delivery failed",
            extra={
                "event": "job_item_failed",
                "job_kind": "push",
                "delivery_id": str(item.id) if item.id else None,
                **error_fields(exc),
            },
        )
        await deliveries.mark_terminal(item, "unknown")
        return JobResult.FAILED


def build_push_services(
    db: AsyncDB,
) -> tuple[XiaoBaoPushDispatchService, XiaoBaoPushDeliveryService, XiaoBaoPushDeliveryRepository]:
    subscriptions = XiaoBaoPushSubscriptionRepository(db)
    deliveries = XiaoBaoPushDeliveryRepository(db)
    dispatch = XiaoBaoPushDispatchService(
        deliveries, subscriptions, XiaoBaoConversationRepository(db)
    )
    delivery = XiaoBaoPushDeliveryService(
        subscriptions, deliveries, XiaoBaoMessageRepository(db), PyWebPushTransport()
    )
    return dispatch, delivery, deliveries
