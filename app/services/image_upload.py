"""Direct-to-S3 image uploads.

Lambda accepts request bodies of at most 6 MB (about 4.5 MB of binary data after base64), and
phone photos can be larger. So the browser uploads the original file straight to S3 with a
presigned POST form, and the API only records it:

1. ``create_ticket``: validate the declared type and size, record a pending upload for the
   session user and return a form valid for a few minutes, bound to one key, the content type
   and the maximum size.
2. The browser POSTs the file to S3.
3. ``claim``: confirm the object exists, matches the recorded type and stays within the limit,
   then consume the pending record so the upload becomes exactly one item.
"""

from datetime import timedelta
from typing import Annotated

from fastapi import Depends

from app.core.config import get_settings
from app.models.s3 import S3ObjectInfo
from app.repositories.image import ImageRepository
from app.repositories.image_upload import ImageUploadRepository
from app.schemas.v1.exceptions import BadRequestException, ConflictException, NotFoundException
from app.schemas.v1.image import (
    ImageUploadPurpose,
    ImageUploadRequest,
    ImageUploadTicket,
    UploadFormField,
)
from app.schemas.v1.user import UserType
from app.util.crypto import generate_crypto_id
from app.util.time import utc_now

settings = get_settings()


class ImageUploadService:
    def __init__(
        self,
        images: Annotated[ImageRepository, Depends()],
        uploads: Annotated[ImageUploadRepository, Depends()],
    ) -> None:
        self._images = images
        self._uploads = uploads

    async def create_ticket(
        self, owner: UserType, request: ImageUploadRequest
    ) -> ImageUploadTicket:
        max_bytes = settings.image_upload_max_bytes
        if request.size_bytes > max_bytes:
            raise BadRequestException(f"Images can be at most {max_bytes // (1024 * 1024)} MB")
        key = generate_crypto_id()
        now = utc_now()
        expires_in = settings.image_upload_url_expires_seconds
        expires_at = now + timedelta(seconds=expires_in)
        await self._uploads.create(
            key=key,
            owner=owner,
            purpose=request.purpose.value,
            content_type=request.content_type,
            created_at=now,
            expires_at=expires_at,
        )
        form = await self._images.create_image_upload_form(
            key, request.content_type, max_bytes, expires_in
        )
        return ImageUploadTicket(
            upload_key=key,
            url=form["url"],
            fields=[
                UploadFormField(name=name, value=str(value))
                for name, value in form["fields"].items()
            ],
            expires_at=expires_at,
            max_bytes=max_bytes,
        )

    async def claim(
        self, owner: UserType, purpose: ImageUploadPurpose, upload_key: str
    ) -> S3ObjectInfo:
        pending = await self._uploads.get(upload_key, owner, purpose.value)
        if pending is None:
            raise NotFoundException("Upload", upload_key)
        info = await self._images.get_image_info(upload_key)
        if info is None:
            raise ConflictException("The upload has not finished yet. Please upload again.")
        if info.size > settings.image_upload_max_bytes:
            raise BadRequestException("The uploaded image is too large")
        if info.content_type != pending["content_type"]:
            raise BadRequestException("The uploaded file does not match the requested type")
        if not await self._uploads.consume(upload_key, owner, purpose.value):
            raise ConflictException("This upload has already been used")
        return S3ObjectInfo(size=info.size, content_type=pending["content_type"])
