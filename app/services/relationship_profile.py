from datetime import date
from typing import Annotated

from fastapi import Depends

from app.repositories.relationship_profile import RelationshipProfileRepository
from app.schemas.v1.relationship_profile import (
    RelationshipProfile,
    RelationshipProfileAIContext,
    RelationshipProfileUpdate,
    default_relationship_profile,
)
from app.schemas.v1.user import UserType


class RelationshipProfileService:
    def __init__(self, repository: Annotated[RelationshipProfileRepository, Depends()]) -> None:
        self._repository = repository

    async def get(self) -> RelationshipProfile:
        return await self._repository.get() or default_relationship_profile()

    async def update(
        self, profile: RelationshipProfileUpdate, current_user: UserType
    ) -> RelationshipProfile:
        return await self._repository.save(profile, current_user)

    async def get_ai_context(self) -> RelationshipProfileAIContext:
        profile = await self.get()
        effectively_together = profile.currently_together and (
            profile.together_through is None or profile.together_through >= date.today()
        )
        return RelationshipProfileAIContext(
            relationship_mode=profile.relationship_mode,
            currently_together=effectively_together,
            together_through=profile.together_through if effectively_together else None,
            relationship_notes=profile.relationship_notes,
            practical_notes=profile.practical_notes,
            people=profile.people,
        )
