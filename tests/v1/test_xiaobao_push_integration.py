from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from app.core.config import get_settings
from app.db.mongo_client import get_test_db
from app.models.mongo import AsyncDB
from app.repositories.xiaobao_push import (
    XiaoBaoPushDeliveryRepository,
    ensure_xiaobao_push_indexes,
)
from app.schemas.v1.user import UserType

settings = get_settings()
MESSAGE_ID = "64b64c000000000000000001"
SUBSCRIPTION_ID = "64b64c000000000000000002"


@pytest_asyncio.fixture
async def push_test_db() -> AsyncGenerator[AsyncDB]:
    db = get_test_db()
    await db[settings.xiaobao_push_deliveries_collection_name].delete_many({})
    await db[settings.xiaobao_push_subscriptions_collection_name].delete_many({})
    await ensure_xiaobao_push_indexes(db)
    yield db
    await db[settings.xiaobao_push_deliveries_collection_name].delete_many({})
    await db[settings.xiaobao_push_subscriptions_collection_name].delete_many({})


@pytest.mark.asyncio
async def test_message_delivery_enqueue_is_unique_per_device(push_test_db: AsyncDB) -> None:
    deliveries = XiaoBaoPushDeliveryRepository(push_test_db)

    first = await deliveries.enqueue_message(
        message_id=MESSAGE_ID,
        owner=UserType.JORIS,
        subscription_id=SUBSCRIPTION_ID,
    )
    replay = await deliveries.enqueue_message(
        message_id=MESSAGE_ID,
        owner=UserType.JORIS,
        subscription_id=SUBSCRIPTION_ID,
    )

    assert first.id == replay.id
    assert (
        await push_test_db[settings.xiaobao_push_deliveries_collection_name].count_documents({})
    ) == 1
