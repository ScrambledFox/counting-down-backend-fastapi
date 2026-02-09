import asyncio
from typing import Annotated

from fastapi import Depends, UploadFile

from app.core.config import get_settings
from app.repositories.image import ImageRepository
from app.repositories.image_metadata import ImageMetadataRepository
from app.schemas.v1.exceptions import BadRequestException, NotFoundException
from app.schemas.v1.image import ImageMetadata, ImageMetadataCreate
from app.schemas.v1.user import UserType
from app.util.crypto import generate_crypto_id
from app.util.image import (
    create_thumbnail,
    decode_image_cursor,
    encode_image_cursor,
    get_thumbnail_name,
)
from app.util.time import utc_now

settings = get_settings()


class ImageService:
    def __init__(
        self,
        image_repository: Annotated[ImageRepository, Depends()],
        metadata_repository: Annotated[ImageMetadataRepository, Depends()],
    ) -> None:
        self._images = image_repository
        self._metadata = metadata_repository

    def _get_configured_thumbnail_sizes(self) -> list[int]:
        sizes = settings.thumbnail_sizes or [settings.thumbnail_size, settings.thumbnail_xl_size]
        normalized = sorted({int(size) for size in sizes if int(size) > 0})
        return normalized

    def _validate_thumbnail_size(self, size: int) -> None:
        if size <= 0:
            raise BadRequestException("Thumbnail size must be greater than 0")

        allowed = self._get_configured_thumbnail_sizes()
        if size in allowed:
            return

        if not settings.thumbnail_allow_custom_sizes:
            raise BadRequestException("Thumbnail size is not supported")

        if size < settings.thumbnail_min_size or size > settings.thumbnail_max_size:
            raise BadRequestException(
                f"Thumbnail size must be between {settings.thumbnail_min_size} and "
                f"{settings.thumbnail_max_size}"
            )

    def _resolve_thumbnail_sizes(self, sizes: list[int] | None) -> list[int]:
        if sizes is None:
            return self._get_configured_thumbnail_sizes()

        normalized = sorted({int(size) for size in sizes})
        for size in normalized:
            self._validate_thumbnail_size(size)
        return normalized

    def _resolve_thumbnail_size(self, size: int | None) -> int:
        if size is None:
            configured = self._get_configured_thumbnail_sizes()
            resolved = configured[0] if configured else settings.thumbnail_size
        else:
            resolved = int(size)
        self._validate_thumbnail_size(resolved)
        return resolved

    async def _ensure_thumbnails_for_image_key(
        self, key: str, sizes: list[int] | None = None
    ) -> None:
        resolved_sizes = self._resolve_thumbnail_sizes(sizes)
        if not resolved_sizes:
            return

        missing_sizes: list[int] = []
        for size in resolved_sizes:
            thumbnail_key = get_thumbnail_name(key, size)
            if not await self._images.get_thumbnail_exists(thumbnail_key):
                missing_sizes.append(size)

        if not missing_sizes:
            return

        image = await self.get_image_bytes_by_key(key)
        if image is None:
            raise NotFoundException("Image", key)

        for size in missing_sizes:
            thumbnail, img_format = create_thumbnail(image, size)
            await self._images.upload_thumbnail_image(
                get_thumbnail_name(key, size),
                thumbnail,
                f"image/{img_format.lower()}",
            )

    async def _create_custom_thumbnail_for_image_key(self, key: str, thumbnail_size: int) -> None:
        await self._ensure_thumbnails_for_image_key(key, [thumbnail_size])

    async def _create_standard_thumbnail_for_image_key(self, key: str) -> None:
        await self._create_custom_thumbnail_for_image_key(key, settings.thumbnail_size)

    async def _create_xl_thumbnail_for_image_key(self, key: str) -> None:
        await self._create_custom_thumbnail_for_image_key(key, settings.thumbnail_xl_size)

    async def _get_or_create_thumbnail(self, key: str, size: int) -> bytes | None:
        self._validate_thumbnail_size(size)
        thumbnail_key = get_thumbnail_name(key, size)
        existing = await self._images.get_thumbnail_image(thumbnail_key)
        if existing is not None:
            return existing

        image = await self.get_image_bytes_by_key(key)
        if image is None:
            return None

        thumbnail, img_format = create_thumbnail(image, size)
        await self._images.upload_thumbnail_image(
            thumbnail_key, thumbnail, f"image/{img_format.lower()}"
        )
        return thumbnail

    async def get_image_bytes_by_key(self, key: str) -> bytes | None:
        return await self._images.get_image(key)

    async def get_metadata_by_image_key(self, key: str) -> ImageMetadata | None:
        return await self._metadata.get_image_metadata_by_key(key)

    async def list_images_by_uploader(self, uploader: UserType) -> list[ImageMetadata]:
        return await self._metadata.get_by_user_type(uploader)

    async def list_image_metadata_page(
        self, limit: int, cursor: str | None, user_filter: UserType | None = None
    ) -> tuple[list[ImageMetadata], str | None]:
        decoded_cursor = decode_image_cursor(cursor) if cursor else None
        docs = await self._metadata.list_image_metadata_page(limit + 1, decoded_cursor, user_filter)

        has_more = len(docs) > limit
        items = docs[:limit]
        next_cursor = None
        if has_more and items:
            last_item = items[-1]
            next_cursor = encode_image_cursor(last_item.uploaded_at, str(last_item.id))

        return items, next_cursor

    async def get_image_by_id(self, image_id: str) -> ImageMetadata | None:
        return await self._metadata.get_image_metadata_by_id(image_id)

    async def get_image_exists_by_key(self, key: str) -> bool:
        return await self._images.get_image_exists(key)

    async def create_image(self, metadata: ImageMetadataCreate, image: UploadFile) -> ImageMetadata:
        # Generate unique image key - Constant to ensure both thumbnail and original image
        # are created for the same key
        IMAGE_KEY = generate_crypto_id()

        # Read the upload once so downstream consumers see the full payload
        image_data = await image.read()
        if not image_data:
            raise BadRequestException("Uploaded image is empty")

        # Save Image to storage
        await self._images.upload_image(IMAGE_KEY, image_data, image.content_type)

        #  Create thumbnails
        asyncio.create_task(self._ensure_thumbnails_for_image_key(IMAGE_KEY))

        # Save metadata to DB
        new_metadata = ImageMetadata(
            image_key=IMAGE_KEY,
            title=metadata.title,
            description=metadata.description,
            image_tags=metadata.image_tags,
            uploaded_by=metadata.uploaded_by,
            media_type=image.content_type,
            uploaded_at=utc_now(),
        )
        created_ref = await self._metadata.create_image_metadata(new_metadata)
        return created_ref

    async def upload_image_bytes(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> None:
        await self._images.upload_image(key, data, content_type)

    async def request_thumbnail_generation(
        self, key: str, thumbnail_sizes: list[int] | None = None
    ) -> None:
        if not await self.get_image_exists_by_key(key):
            raise NotFoundException("Image", key)

        resolved_sizes = self._resolve_thumbnail_sizes(thumbnail_sizes)
        asyncio.create_task(self._ensure_thumbnails_for_image_key(key, resolved_sizes))

    async def delete_image_by_id(self, image_id: str) -> bool:
        metadata = await self.get_image_by_id(image_id)
        if metadata is None:
            raise NotFoundException("Image metadata", image_id)

        # Soft delete metadata
        deleted = await self._metadata.soft_delete_image_metadata(image_id)
        if not deleted:
            return False

        # Delete image from storage - (Don't delete images for now)
        # await self._images.delete_image(metadata.image_key)
        # await self._images.delete_thumbnail_image(metadata.image_key)

        return True

    async def get_thumbnail_bytes_by_key(
        self, key: str, thumbnail_size: int | None = None
    ) -> bytes | None:
        resolved_size = self._resolve_thumbnail_size(thumbnail_size)
        return await self._get_or_create_thumbnail(key, resolved_size)

    async def get_image_presigned_url(self, key: str, expires_in: int | None = None) -> str:
        ttl = expires_in or settings.aws_s3_presign_expires
        return await self._images.generate_image_presigned_url(key, ttl)

    async def get_thumbnail_presigned_url(
        self, key: str, thumbnail_size: int | None = None, expires_in: int | None = None
    ) -> str | None:
        ttl = expires_in or settings.aws_s3_presign_expires
        resolved_size = self._resolve_thumbnail_size(thumbnail_size)
        thumbnail_key = get_thumbnail_name(key, resolved_size)

        await self._ensure_thumbnails_for_image_key(key, [resolved_size])

        return await self._images.generate_thumbnail_presigned_url(thumbnail_key, ttl)
