from typing import Annotated

from fastapi import Depends

from app.repositories.image import ImageRepository


class ImageService:
    def __init__(self, repo: Annotated[ImageRepository, Depends()]):
        self._repo = repo

    async def get_image_bytes_by_key(self, key: str) -> bytes | None:
        return await self._repo.get_bytes_by_key(key)
