"""Direct-to-S3 uploads: ticket, ownership, one-time claim and the S3 form conditions."""

import base64
import json
from collections.abc import AsyncGenerator
from io import BytesIO
from typing import Any

import boto3
import pytest
import pytest_asyncio
from botocore.config import Config
from fastapi import HTTPException
from PIL import Image

from app.core.config import get_settings
from app.db.mongo_client import get_test_db
from app.db.s3_client import Boto3S3Storage
from app.models.mongo import AsyncDB
from app.models.s3 import S3ObjectInfo
from app.repositories.image import ImageRepository
from app.repositories.image_upload import ImageUploadRepository, ensure_image_upload_indexes
from app.schemas.v1.advent import AdventCreate, AdventType
from app.schemas.v1.image import ImageUploadPurpose, ImageUploadRequest
from app.schemas.v1.user import UserType
from app.services import image_upload as image_upload_module
from app.services.image_upload import ImageUploadService

settings = get_settings()


class FakeS3:
    """In-memory stand-in for the S3 storage protocol."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str | None]] = {}
        self.forms: list[dict[str, Any]] = []

    async def upload_object(
        self, *, bucket: str, key: str, data: bytes, content_type: str | None = None
    ) -> None:
        self.objects[key] = (data, content_type)

    async def get_object(self, *, bucket: str, key: str) -> bytes | None:
        stored = self.objects.get(key)
        return stored[0] if stored else None

    async def get_object_exists(self, *, bucket: str, key: str) -> bool:
        return key in self.objects

    async def get_object_info(self, *, bucket: str, key: str) -> S3ObjectInfo | None:
        stored = self.objects.get(key)
        return S3ObjectInfo(size=len(stored[0]), content_type=stored[1]) if stored else None

    async def generate_presigned_post(self, **kwargs: Any) -> dict[str, Any]:
        self.forms.append(kwargs)
        return {"url": "https://bucket.example/", "fields": {"key": kwargs["key"], "policy": "p"}}

    async def delete_object(self, *, bucket: str, key: str) -> None:
        self.objects.pop(key, None)

    async def generate_presigned_url(self, *, bucket: str, key: str, expires_in: int = 3600) -> str:
        return f"https://bucket.example/{key}"


@pytest_asyncio.fixture
async def upload_db() -> AsyncGenerator[AsyncDB]:
    db = get_test_db()
    await db[settings.image_uploads_collection_name].delete_many({})
    await ensure_image_upload_indexes(db)
    yield db
    await db[settings.image_uploads_collection_name].delete_many({})


@pytest.fixture
def storage() -> FakeS3:
    return FakeS3()


@pytest.fixture
def service(upload_db: AsyncDB, storage: FakeS3) -> ImageUploadService:
    return ImageUploadService(ImageRepository(storage), ImageUploadRepository(upload_db))


def _jpeg(size: tuple[int, int] = (64, 48)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, (200, 120, 140)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _request(**overrides: Any) -> ImageUploadRequest:
    values: dict[str, Any] = {"content_type": "image/jpeg", "size_bytes": 1000} | overrides
    return ImageUploadRequest(**values)


def _object_key(storage: FakeS3, upload_key: str) -> str:
    return ImageRepository(storage)._image_key(upload_key)


@pytest.mark.asyncio
async def test_ticket_binds_the_form_to_one_key_type_and_size(
    service: ImageUploadService, storage: FakeS3
) -> None:
    ticket = await service.create_ticket(UserType.JORIS, _request())

    form = storage.forms[0]
    assert form["key"] == _object_key(storage, ticket.upload_key)
    assert form["content_type"] == "image/jpeg"
    assert form["max_bytes"] == settings.image_upload_max_bytes
    assert form["expires_in"] == settings.image_upload_url_expires_seconds
    assert [(field.name, field.value) for field in ticket.fields] == [
        ("key", form["key"]),
        ("policy", "p"),
    ]


@pytest.mark.asyncio
async def test_oversized_uploads_are_refused_up_front(service: ImageUploadService) -> None:
    with pytest.raises(HTTPException) as refused:
        await service.create_ticket(
            UserType.JORIS, _request(size_bytes=settings.image_upload_max_bytes + 1)
        )
    assert refused.value.status_code == 400


@pytest.mark.asyncio
async def test_an_upload_becomes_exactly_one_item_of_its_owner(
    service: ImageUploadService, storage: FakeS3
) -> None:
    ticket = await service.create_ticket(UserType.JORIS, _request())

    with pytest.raises(HTTPException) as not_finished:
        await service.claim(UserType.JORIS, ImageUploadPurpose.GALLERY, ticket.upload_key)
    assert not_finished.value.status_code == 409

    storage.objects[_object_key(storage, ticket.upload_key)] = (_jpeg(), "image/jpeg")

    with pytest.raises(HTTPException) as other_user:
        await service.claim(UserType.DANFENG, ImageUploadPurpose.GALLERY, ticket.upload_key)
    assert other_user.value.status_code == 404
    with pytest.raises(HTTPException) as other_purpose:
        await service.claim(UserType.JORIS, ImageUploadPurpose.ADVENT, ticket.upload_key)
    assert other_purpose.value.status_code == 404

    stored = await service.claim(UserType.JORIS, ImageUploadPurpose.GALLERY, ticket.upload_key)
    assert stored.content_type == "image/jpeg"

    with pytest.raises(HTTPException) as reused:
        await service.claim(UserType.JORIS, ImageUploadPurpose.GALLERY, ticket.upload_key)
    assert reused.value.status_code == 404


@pytest.mark.asyncio
async def test_uploads_that_do_not_match_the_ticket_are_refused(
    service: ImageUploadService, storage: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticket = await service.create_ticket(UserType.JORIS, _request())
    key = _object_key(storage, ticket.upload_key)

    storage.objects[key] = (b"<svg/>", "image/svg+xml")
    with pytest.raises(HTTPException) as wrong_type:
        await service.claim(UserType.JORIS, ImageUploadPurpose.GALLERY, ticket.upload_key)
    assert wrong_type.value.status_code == 400

    storage.objects[key] = (_jpeg(), "image/jpeg")
    monkeypatch.setattr(image_upload_module.settings, "image_upload_max_bytes", 10)
    with pytest.raises(HTTPException) as too_large:
        await service.claim(UserType.JORIS, ImageUploadPurpose.GALLERY, ticket.upload_key)
    assert too_large.value.status_code == 400


@pytest.mark.asyncio
async def test_advent_from_upload_creates_its_thumbnail(storage: FakeS3) -> None:
    from app.services.advent import AdventService

    class FakeAdventRepository:
        async def create_advent(self, advent: Any) -> Any:
            return advent

    images = ImageRepository(storage)
    storage.objects[images._image_key("advent-key")] = (_jpeg((800, 600)), "image/jpeg")
    service = AdventService(FakeAdventRepository(), images)  # type: ignore[arg-type]

    advent = await service.create_advent_from_upload(
        AdventCreate(day=3, uploaded_by=UserType.JORIS, title="t", type=AdventType.CUTE),
        "advent-key",
        "image/jpeg",
    )

    assert advent.image_key == "advent-key"
    assert advent.content_type == "image/jpeg"
    assert images._thumbnail_key("advent-key") in storage.objects


@pytest.mark.asyncio
async def test_s3_form_policy_enforces_key_type_and_size() -> None:
    """The real boto3 form: S3 rejects uploads that break these conditions."""
    client = boto3.client(
        "s3",
        region_name="eu-west-1",
        aws_access_key_id="AKIASYNTHETIC0000000",
        aws_secret_access_key="synthetic-secret",
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )
    form = await Boto3S3Storage(client).generate_presigned_post(
        bucket="synthetic-bucket",
        key="images/abc",
        content_type="image/png",
        max_bytes=5000,
        expires_in=600,
    )

    policy = json.loads(base64.b64decode(form["fields"]["policy"]))
    conditions = policy["conditions"]
    assert {"key": "images/abc"} in conditions
    assert {"Content-Type": "image/png"} in conditions
    assert ["content-length-range", 1, 5000] in conditions
    assert form["fields"]["Content-Type"] == "image/png"
    assert form["url"].startswith("https://synthetic-bucket.s3")
