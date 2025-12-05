from fastapi import Depends

from app.core.config import settings
from app.db.s3_client import get_s3_storage
from app.models.s3 import S3Storage


class ImageRepository:
    def __init__(self, s3_storage: S3Storage = Depends(get_s3_storage)) -> None:
        self._s3_storage = s3_storage
        self._bucket = settings.aws_s3_bucket

    def _advent_prefix(self) -> str:
        prefix = settings.aws_s3_advent_image_folder
        if not prefix:
            return ""
        if not prefix.endswith("/"):
            return prefix + "/"
        return prefix

    def _thumbnail_prefix(self) -> str:
        prefix = settings.aws_s3_thumbnail_folder
        if not prefix:
            return ""
        if not prefix.endswith("/"):
            return prefix + "/"
        return prefix

    def _advent_key(self, name: str) -> str:
        prefix = self._advent_prefix()
        return prefix + name.lstrip("/")

    def _thumbnail_key(self, name: str) -> str:
        prefix = self._thumbnail_prefix()
        return prefix + name.lstrip("/")

    async def get_advent_image(self, name: str) -> bytes | None:
        key = self._advent_key(name)
        return await self._s3_storage.get_object(bucket=self._bucket, key=key)

    async def upload_advent_image(
        self, name: str, data: bytes, content_type: str | None = None
    ) -> None:
        key = self._advent_key(name)
        await self._s3_storage.upload_object(
            bucket=self._bucket, key=key, data=data, content_type=content_type
        )

    async def delete_advent_image(self, name: str) -> None:
        key = self._advent_key(name)
        await self._s3_storage.delete_object(bucket=self._bucket, key=key)

    async def generate_advent_presigned_url(self, name: str, expires_in: int = 3600) -> str:
        key = self._advent_key(name)
        return await self._s3_storage.generate_presigned_url(
            bucket=self._bucket, key=key, expires_in=expires_in
        )

    async def upload_thumbnail_image(
        self, name: str, data: bytes, content_type: str | None = None
    ) -> None:
        key = self._thumbnail_key(name)
        await self._s3_storage.upload_object(
            bucket=self._bucket, key=key, data=data, content_type=content_type
        )

    async def get_thumbnail_image(self, name: str) -> bytes | None:
        key = self._thumbnail_key(name)
        return await self._s3_storage.get_object(bucket=self._bucket, key=key)
