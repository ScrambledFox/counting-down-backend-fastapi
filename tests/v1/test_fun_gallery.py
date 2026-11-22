import re
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

from app.api.v1.image import get_images_by_me, get_images_for_me, list_images
from app.core.config import get_settings
from app.repositories.image import ImageRepository
from app.repositories.image_metadata import ImageMetadataRepository
from app.schemas.v1.image import ImageCursorPayload, ImageMetadata
from app.schemas.v1.session import SessionResponse
from app.services.image import ImageService


@pytest.mark.parametrize(
    "endpoint,uploader",
    [(list_images, None), (get_images_by_me, "Joris"), (get_images_for_me, "Danfeng")],
)
async def test_sensitive_filter_reaches_repository_through_each_endpoint(endpoint, uploader):
    metadata = AsyncMock(spec=ImageMetadataRepository)
    metadata.list_image_metadata_page.return_value = []
    service = ImageService(Mock(spec=ImageRepository), metadata)
    session = SessionResponse(
        session_id="test",
        user_type="Joris",
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
    )
    kwargs = {} if endpoint is list_images else {"user_info": session}
    page = await endpoint(service, limit=12, cursor=None, sensitive_only=True, **kwargs)
    assert page.items == []
    metadata.list_image_metadata_page.assert_awaited_once_with(
        13, None, uploader, sensitive_only=True
    )


@pytest.mark.parametrize("uploader", [None, "Joris", "Danfeng"])
@pytest.mark.parametrize("paginated", [False, True])
async def test_sensitive_query_combines_exact_tags_uploader_and_cursor(uploader, paginated):
    collection = Mock()
    collection.find.return_value.sort.return_value.limit.return_value.to_list = AsyncMock(
        return_value=[]
    )
    repo = ImageMetadataRepository.__new__(ImageMetadataRepository)
    repo._collection = collection
    cursor = (
        ImageCursorPayload(created_at=datetime.now(UTC), id=str(ObjectId())) if paginated else None
    )
    assert await repo.list_image_metadata_page(13, cursor, uploader, True) == []
    query = collection.find.call_args.args[0]
    filters = query["$and"][0] if paginated else query
    assert filters["deleted_at"] is None
    assert filters.get("uploaded_by") == uploader
    tag_filter = filters["image_tags"]
    flags = re.IGNORECASE if "i" in tag_filter.get("$options", "") else 0
    for tag in ["sensitive", " Sensitive ", "SPICY", " nude\t"]:
        assert re.search(tag_filter["$regex"], tag, flags)
    for tag in ["holiday", "not-sensitive", "sensitive-ish", "nudest", ""]:
        assert not re.search(tag_filter["$regex"], tag, flags)
    if paginated:
        assert query["$and"][1]["$or"] == [
            {"uploaded_at": {"$lt": cursor.created_at}},
            {"uploaded_at": cursor.created_at, "_id": {"$lt": ObjectId(cursor.id)}},
        ]
    collection.find.return_value.sort.assert_called_once_with([("uploaded_at", -1), ("_id", -1)])
    collection.find.return_value.sort.return_value.limit.assert_called_once_with(13)


@pytest.mark.parametrize("uploader", [None, "Joris", "Danfeng"])
async def test_sensitive_pagination_filters_before_limit_and_keeps_uploader(uploader):
    client = AsyncIOMotorClient(get_settings().mongo_url, serverSelectionTimeoutMS=2000)
    collection = client["test"][f"fun_gallery_{ObjectId()}"]
    connected = False
    try:
        try:
            await client.admin.command("ping")
            connected = True
        except ServerSelectionTimeoutError:
            pytest.skip("MongoDB unavailable for gallery integration test")
        repo = ImageMetadataRepository.__new__(ImageMetadataRepository)
        repo._collection = collection
        now = datetime(2026, 11, 22, tzinfo=UTC)
        documents = []
        for index, tag in enumerate(
            [
                "holiday",
                "Sensitive",
                "spicy",
                " NUDE ",
                "not-sensitive",
                "sensitive-ish",
                "sensitive",
            ]
        ):
            for user in ["Joris", "Danfeng"]:
                photo = ImageMetadata(
                    id=str(ObjectId()),
                    image_key=f"{index}-{user}",
                    uploaded_by=user,
                    media_type="image/jpeg",
                    image_tags=[tag],
                    uploaded_at=now - timedelta(days=index),
                    deleted_at=now if index == 6 else None,
                )
                documents.append({"_id": ObjectId(photo.id), **photo.model_dump(exclude={"id"})})
        await collection.insert_many(documents)
        service = ImageService(Mock(spec=ImageRepository), repo)
        found = []
        cursor = None
        while True:
            items, cursor = await service.list_image_metadata_page(2, cursor, uploader, True)
            found.extend(items)
            if not cursor:
                break
            assert len(items) == 2
        expected = [
            doc
            for doc in documents
            if doc["image_key"].split("-")[0] in ["1", "2", "3"]
            and (uploader is None or doc["uploaded_by"] == uploader)
        ]
        expected.sort(key=lambda doc: (doc["uploaded_at"], doc["_id"]), reverse=True)
        assert [photo.image_key for photo in found] == [doc["image_key"] for doc in expected]
        normal, _ = await service.list_image_metadata_page(20, None, uploader)
        assert any("holiday" in photo.image_tags for photo in normal)
    finally:
        # Drop only this test's unique collection, never a shared collection.
        if connected:
            await collection.drop()
        client.close()
