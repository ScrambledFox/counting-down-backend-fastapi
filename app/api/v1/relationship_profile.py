from typing import Annotated

from fastapi import Depends

from app.api.routing import make_router
from app.core.auth import require_session
from app.schemas.v1.relationship_profile import RelationshipProfile, RelationshipProfileUpdate
from app.schemas.v1.session import SessionResponse
from app.services.relationship_profile import RelationshipProfileService

router = make_router()
ServiceDep = Annotated[RelationshipProfileService, Depends()]
SessionDep = Annotated[SessionResponse, Depends(require_session)]


@router.get("", response_model=RelationshipProfile)
async def get_relationship_profile(service: ServiceDep, _: SessionDep) -> RelationshipProfile:
    return await service.get()


@router.put("", response_model=RelationshipProfile)
async def update_relationship_profile(
    payload: RelationshipProfileUpdate,
    service: ServiceDep,
    session: SessionDep,
) -> RelationshipProfile:
    return await service.update(payload, session.user_type)
