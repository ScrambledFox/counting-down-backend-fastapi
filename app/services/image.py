from typing import Annotated

from fastapi import Depends

from app.repositories.image import ImageRepository


class ImageService:
    def __init__(self, repo: Annotated[ImageRepository, Depends()]):
        self._repo = repo

    async def get_image_bytes_by_key(self, key: str) -> bytes | None:
        return await self._repo.get_advent_image(key)

    async def upload_image_bytes(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> None:
        await self._repo.upload_advent_image(key, data, content_type)
