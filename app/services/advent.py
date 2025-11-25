from typing import Annotated

from fastapi import Depends, UploadFile

from app.core.time import utc_now
from app.repositories.advent import AdventRepository
from app.repositories.image import ImageRepository
from app.schemas.v1.advent import AdventRef, AdventRefCreate, ImageActor
from app.util.crypto import generate_crypto_id


class AdventService:
    def __init__(
        self,
        advent_repo: Annotated[AdventRepository, Depends()],
        image_repo: Annotated[ImageRepository, Depends()],
    ) -> None:
        self._advent_repo = advent_repo
        self._image_repo = image_repo

    async def list_advent_refs(self) -> list[AdventRef]:
        return await self._advent_repo.list_advent_refs()

    async def get_advent_ref_by_id(self, advent_ref_id: str) -> AdventRef | None:
        return await self._advent_repo.get_advent_ref_by_id(advent_ref_id)

    async def get_advent_ref_by_key(self, key: str) -> AdventRef | None:
        return await self._advent_repo.get_advent_ref_by_key(key)

    async def get_advent_ref_by_day(
        self, advent_day: int, actor: ImageActor | None = None
    ) -> list[AdventRef]:
        if actor is not None:
            return await self._advent_repo.get_advent_ref_by_day_and_actor(advent_day, actor)

        return await self._advent_repo.get_advent_ref_by_day(advent_day)

    async def create_advent_ref(
        self, advent_create: AdventRefCreate, image: UploadFile
    ) -> AdventRef:
        # Generate unique image key
        image_key = generate_crypto_id()

        # Save Image to storage
        await self._image_repo.upload_bytes(image_key, await image.read())

        # Create AdventRef entry
        new_advent_ref = AdventRef(
            **advent_create.model_dump(),
            uploaded_at=utc_now(),
            content_type=image.content_type,
            image_key=image_key,
        )

        created_ref = await self._advent_repo.create_advent_ref(new_advent_ref)
        return created_ref
