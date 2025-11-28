from typing import Annotated

from fastapi import Depends, UploadFile

from app.repositories.advent import AdventRepository
from app.repositories.image import ImageRepository
from app.schemas.v1.advent import Advent, AdventRefCreate
from app.schemas.v1.exceptions import NotFoundException
from app.schemas.v1.user import UserType
from app.util.crypto import generate_crypto_id
from app.util.time import utc_now


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

        # Save Image to storage
        await self._image_repo.upload_advent_image(
            image_key, await image.read(), image.content_type
        )

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

        # Delete image from storage - (Optional, depending on whether you want to keep images)
        # await self._image_repo.delete_image(advent_ref.image_key)

        # Delete advent entry
        await self._advent_repo.delete_advent_by_id(advent_id)
