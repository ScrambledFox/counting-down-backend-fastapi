from fastapi import Depends

from app.core.config import settings
from app.db.s3_client import get_s3_storage
from app.models.s3 import S3Storage


class ImageRepository:
    def __init__(self, s3_storage: S3Storage = Depends(get_s3_storage)) -> None:
        self._s3_storage = s3_storage

    async def get_bytes_by_key(self, key: str) -> bytes | None:
        try:
            data = await self._s3_storage.get_bytes(bucket=settings.aws_s3_bucket, key=key)
            return data
        except Exception:
            return None
