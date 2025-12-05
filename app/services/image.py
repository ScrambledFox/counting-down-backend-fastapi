from typing import Annotated

from fastapi import Depends

from app.core.config import Settings
from app.repositories.image import ImageRepository
from app.schemas.v1.exceptions import NotFoundException
from app.util.image import create_thumbnail, get_thumbnail_name

settings = Settings()


class ImageService:
    def __init__(self, repo: Annotated[ImageRepository, Depends()]):
        self._repo = repo

    async def get_image_bytes_by_key(self, key: str) -> bytes | None:
        return await self._repo.get_advent_image(key)

    async def upload_image_bytes(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> None:
        await self._repo.upload_advent_image(key, data, content_type)

    async def request_thumbnail_generation(self, key: str) -> None:
        image = await self.get_image_bytes_by_key(key)
        if image is None:
            raise NotFoundException("Image", key)

        thumbnail = create_thumbnail(image, settings.thumbnail_size)
        await self._repo.upload_thumbnail_image(
            get_thumbnail_name(key, settings.thumbnail_size), thumbnail, "image/jpeg"
        )

    async def get_thumbnail_bytes_by_key(self, key: str) -> bytes | None:
        return await self._repo.get_thumbnail_image(
            get_thumbnail_name(key, settings.thumbnail_size)
        )
