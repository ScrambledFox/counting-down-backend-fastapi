from typing import Annotated

from fastapi import Depends, UploadFile

from app.core.config import Settings
from app.repositories.advent import AdventRepository
from app.repositories.image import ImageRepository
from app.schemas.v1.advent import Advent, AdventRefCreate
from app.schemas.v1.exceptions import BadRequestException, NotFoundException
from app.schemas.v1.user import UserType
from app.util.crypto import generate_crypto_id
from app.util.image import create_thumbnail
from app.util.time import utc_now

settings = Settings()


class AdventService:
    def __init__(
        self,
        advent_repo: Annotated[AdventRepository, Depends()],
        image_repo: Annotated[ImageRepository, Depends()],
    ) -> None:
        self._advent_repo = advent_repo
        self._image_repo = image_repo

    async def list_advents_uploaded_by(self, user: UserType) -> list[Advent]:
        return await self._advent_repo.get_advents_uploaded_by(user)

    async def get_advent_by_day(self, day: int, user: UserType) -> list[Advent]:
        return await self._advent_repo.get_advents_day_uploaded_by(day, user)

    async def get_advent_by_id(self, advent_id: str) -> Advent | None:
        return await self._advent_repo.get_advent_by_id(advent_id)

    async def create_advent(self, advent_create: AdventRefCreate, image: UploadFile) -> Advent:
        # Generate unique image key
        image_key = generate_crypto_id()

        # Read the upload once so downstream consumers see the full payload
        image_data = await image.read()
        if not image_data:
            raise BadRequestException("Uploaded image is empty")

        # Save Image to storage
        await self._image_repo.upload_advent_image(
            image_key, image_data, image.content_type
        )

        # Create and save thumbnail
        thumbnail_data = create_thumbnail(image_data, settings.thumbnail_size)
        await self._image_repo.upload_thumbnail_image(image_key, thumbnail_data, image.content_type)

        # Create Advent entry
        new_advent = Advent(
            **advent_create.model_dump(),
            uploaded_at=utc_now(),
            content_type=image.content_type,
            image_key=image_key,
        )

        created_ref = await self._advent_repo.create_advent(new_advent)
        return created_ref

    async def delete_advent_by_id(self, advent_id: str) -> None:
        advent_ref = await self._advent_repo.get_advent_by_id(advent_id)
        if advent_ref is None:
            raise NotFoundException("Advent ref not found")

        # Delete image from storage - (Don't delete images for now)
        # await self._image_repo.delete_advent_image(advent_ref.image_key)
        # await self._image_repo.delete_thumbnail_image(advent_ref.image_key)

        # Delete advent entry
        await self._advent_repo.delete_advent_by_id(advent_id)
