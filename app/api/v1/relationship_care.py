from typing import Annotated

from fastapi import Depends, Query, status

from app.api.routing import make_router
from app.core.auth import require_session
from app.schemas.v1.base import MongoId
from app.schemas.v1.relationship_care import (
    AgreementCreate,
    AgreementDetail,
    AgreementResponseCreate,
    AgreementRevisionCreate,
    AgreementSummary,
    PersonalBoundaryCreate,
    PersonalBoundaryUpdate,
    PersonalBoundaryView,
    PersonalGoalCreate,
    PersonalGoalUpdate,
    PersonalGoalView,
    RelationshipCareOverview,
    RelationshipRequestCreate,
    RelationshipRequestUpdate,
    RelationshipRequestView,
)
from app.schemas.v1.session import SessionResponse
from app.services.relationship_care import RelationshipCareService

router = make_router()
ServiceDep = Annotated[RelationshipCareService, Depends()]
SessionDep = Annotated[SessionResponse, Depends(require_session)]


@router.get("/overview", response_model=RelationshipCareOverview)
async def get_relationship_care_overview(
    service: ServiceDep, session: SessionDep
) -> RelationshipCareOverview:
    return await service.overview(session.user_type)


@router.get("/boundaries", response_model=list[PersonalBoundaryView])
async def list_boundaries(service: ServiceDep, session: SessionDep) -> list[PersonalBoundaryView]:
    return await service.list_boundaries(session.user_type)


@router.post(
    "/boundaries", response_model=PersonalBoundaryView, status_code=status.HTTP_201_CREATED
)
async def create_boundary(
    payload: PersonalBoundaryCreate, service: ServiceDep, session: SessionDep
) -> PersonalBoundaryView:
    return await service.create_boundary(payload, session.user_type)


@router.get("/boundaries/{boundary_id}", response_model=PersonalBoundaryView)
async def get_boundary(
    boundary_id: MongoId, service: ServiceDep, session: SessionDep
) -> PersonalBoundaryView:
    return await service.get_boundary(boundary_id, session.user_type)


@router.patch("/boundaries/{boundary_id}", response_model=PersonalBoundaryView)
async def update_boundary(
    boundary_id: MongoId,
    payload: PersonalBoundaryUpdate,
    service: ServiceDep,
    session: SessionDep,
) -> PersonalBoundaryView:
    return await service.update_boundary(boundary_id, payload, session.user_type)


@router.post("/boundaries/{boundary_id}/archive", response_model=PersonalBoundaryView)
async def archive_boundary(
    boundary_id: MongoId, service: ServiceDep, session: SessionDep
) -> PersonalBoundaryView:
    return await service.archive_boundary(boundary_id, session.user_type)


@router.delete("/boundaries/{boundary_id}/archive", response_model=PersonalBoundaryView)
async def restore_boundary(
    boundary_id: MongoId, service: ServiceDep, session: SessionDep
) -> PersonalBoundaryView:
    return await service.restore_boundary(boundary_id, session.user_type)


@router.get("/requests", response_model=list[RelationshipRequestView])
async def list_requests(service: ServiceDep, session: SessionDep) -> list[RelationshipRequestView]:
    return await service.list_requests(session.user_type)


@router.post(
    "/requests", response_model=RelationshipRequestView, status_code=status.HTTP_201_CREATED
)
async def create_request(
    payload: RelationshipRequestCreate, service: ServiceDep, session: SessionDep
) -> RelationshipRequestView:
    return await service.create_request(payload, session.user_type)


@router.get("/requests/{request_id}", response_model=RelationshipRequestView)
async def get_request(
    request_id: MongoId, service: ServiceDep, session: SessionDep
) -> RelationshipRequestView:
    return await service.get_request(request_id, session.user_type)


@router.patch("/requests/{request_id}", response_model=RelationshipRequestView)
async def update_request(
    request_id: MongoId,
    payload: RelationshipRequestUpdate,
    service: ServiceDep,
    session: SessionDep,
) -> RelationshipRequestView:
    return await service.update_request(request_id, payload, session.user_type)


@router.post("/requests/{request_id}/archive", response_model=RelationshipRequestView)
async def archive_request(
    request_id: MongoId, service: ServiceDep, session: SessionDep
) -> RelationshipRequestView:
    return await service.archive_request(request_id, session.user_type)


@router.delete("/requests/{request_id}/archive", response_model=RelationshipRequestView)
async def restore_request(
    request_id: MongoId, service: ServiceDep, session: SessionDep
) -> RelationshipRequestView:
    return await service.restore_request(request_id, session.user_type)


@router.get("/goals", response_model=list[PersonalGoalView])
async def list_goals(service: ServiceDep, session: SessionDep) -> list[PersonalGoalView]:
    return await service.list_goals(session.user_type)


@router.post("/goals", response_model=PersonalGoalView, status_code=status.HTTP_201_CREATED)
async def create_goal(
    payload: PersonalGoalCreate, service: ServiceDep, session: SessionDep
) -> PersonalGoalView:
    return await service.create_goal(payload, session.user_type)


@router.get("/goals/{goal_id}", response_model=PersonalGoalView)
async def get_goal(goal_id: MongoId, service: ServiceDep, session: SessionDep) -> PersonalGoalView:
    return await service.get_goal(goal_id, session.user_type)


@router.patch("/goals/{goal_id}", response_model=PersonalGoalView)
async def update_goal(
    goal_id: MongoId,
    payload: PersonalGoalUpdate,
    service: ServiceDep,
    session: SessionDep,
) -> PersonalGoalView:
    return await service.update_goal(goal_id, payload, session.user_type)


@router.post("/goals/{goal_id}/archive", response_model=PersonalGoalView)
async def archive_goal(
    goal_id: MongoId, service: ServiceDep, session: SessionDep
) -> PersonalGoalView:
    return await service.archive_goal(goal_id, session.user_type)


@router.delete("/goals/{goal_id}/archive", response_model=PersonalGoalView)
async def restore_goal(
    goal_id: MongoId, service: ServiceDep, session: SessionDep
) -> PersonalGoalView:
    return await service.restore_goal(goal_id, session.user_type)


@router.get("/agreements", response_model=list[AgreementSummary])
async def list_agreements(
    service: ServiceDep,
    session: SessionDep,
    include_archived: bool = Query(default=False),
) -> list[AgreementSummary]:
    return await service.list_agreements(session.user_type, include_archived=include_archived)


@router.post("/agreements", response_model=AgreementDetail, status_code=status.HTTP_201_CREATED)
async def create_agreement(
    payload: AgreementCreate, service: ServiceDep, session: SessionDep
) -> AgreementDetail:
    return await service.create_agreement(payload, session.user_type)


@router.get("/agreements/{agreement_id}", response_model=AgreementDetail)
async def get_agreement(
    agreement_id: MongoId, service: ServiceDep, session: SessionDep
) -> AgreementDetail:
    return await service.get_agreement_detail(agreement_id, session.user_type)


@router.post("/agreements/{agreement_id}/propose", response_model=AgreementDetail)
async def propose_agreement(
    agreement_id: MongoId, service: ServiceDep, session: SessionDep
) -> AgreementDetail:
    return await service.propose_agreement(agreement_id, session.user_type)


@router.post("/agreements/{agreement_id}/revisions", response_model=AgreementDetail)
async def create_agreement_revision(
    agreement_id: MongoId,
    payload: AgreementRevisionCreate,
    service: ServiceDep,
    session: SessionDep,
) -> AgreementDetail:
    return await service.create_revision(agreement_id, payload, session.user_type)


@router.post("/agreement-revisions/{revision_id}/acceptance", response_model=AgreementDetail)
async def accept_agreement_revision(
    revision_id: MongoId, service: ServiceDep, session: SessionDep
) -> AgreementDetail:
    return await service.accept_revision(revision_id, session.user_type)


@router.delete("/agreement-revisions/{revision_id}/acceptance", response_model=AgreementDetail)
async def revoke_agreement_revision_acceptance(
    revision_id: MongoId, service: ServiceDep, session: SessionDep
) -> AgreementDetail:
    return await service.revoke_acceptance(revision_id, session.user_type)


@router.post("/agreement-revisions/{revision_id}/response", response_model=AgreementDetail)
async def respond_to_agreement_revision(
    revision_id: MongoId,
    payload: AgreementResponseCreate,
    service: ServiceDep,
    session: SessionDep,
) -> AgreementDetail:
    return await service.respond_to_revision(revision_id, payload, session.user_type)


@router.post("/agreements/{agreement_id}/archive", response_model=AgreementDetail)
async def request_agreement_archive(
    agreement_id: MongoId, service: ServiceDep, session: SessionDep
) -> AgreementDetail:
    return await service.request_archive(agreement_id, session.user_type)


@router.delete("/agreements/{agreement_id}/archive", response_model=AgreementDetail)
async def withdraw_agreement_archive_request(
    agreement_id: MongoId, service: ServiceDep, session: SessionDep
) -> AgreementDetail:
    return await service.withdraw_archive_request(agreement_id, session.user_type)
