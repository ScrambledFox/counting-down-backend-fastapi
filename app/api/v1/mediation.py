from typing import Annotated

from fastapi import Depends, status

from app.api.routing import make_router
from app.core.auth import require_session
from app.schemas.v1.base import MongoId
from app.schemas.v1.mediation import (
    AdviceEndpointResponse,
    CommentCreateResponse,
    MediationCommentCreate,
    MediationCommentResponse,
    MediationPerspective,
    MediationPerspectiveDraftUpdate,
    MediationSession,
    MediationSessionCreate,
    MediationSessionDetailResponse,
    MediationSessionListItem,
    ReflectionEndpointResponse,
    SubmitPerspectiveResponse,
)
from app.schemas.v1.session import SessionResponse
from app.services.mediation import MediationService

router = make_router()

MediationServiceDep = Annotated[MediationService, Depends()]
SessionDep = Annotated[SessionResponse, Depends(require_session)]


@router.post(
    "/",
    summary="Create mediation session",
    response_model=MediationSession,
    status_code=status.HTTP_201_CREATED,
)
async def create_mediation_session(
    payload: MediationSessionCreate,
    service: MediationServiceDep,
    session: SessionDep,
) -> MediationSession:
    return await service.create_session(session.user_type, payload)


@router.get(
    "/",
    summary="List mediation sessions",
    response_model=list[MediationSessionListItem],
)
async def list_mediation_sessions(
    service: MediationServiceDep,
    session: SessionDep,
) -> list[MediationSessionListItem]:
    return await service.list_sessions(session.user_type)


@router.get(
    "/{session_id}",
    summary="Get mediation session detail",
    response_model=MediationSessionDetailResponse,
)
async def get_mediation_session(
    session_id: MongoId,
    service: MediationServiceDep,
    session: SessionDep,
) -> MediationSessionDetailResponse:
    return await service.get_session_detail(session_id, session.user_type)


@router.post(
    "/{session_id}/resolve",
    summary="Resolve mediation session",
    response_model=MediationSession,
)
async def resolve_mediation_session(
    session_id: MongoId,
    service: MediationServiceDep,
    session: SessionDep,
) -> MediationSession:
    return await service.resolve_session(session_id, session.user_type)


@router.delete(
    "/{session_id}/resolve",
    summary="Undo mediation session resolve mark",
    response_model=MediationSession,
)
async def unresolve_mediation_session(
    session_id: MongoId,
    service: MediationServiceDep,
    session: SessionDep,
) -> MediationSession:
    return await service.unresolve_session(session_id, session.user_type)


@router.post(
    "/{session_id}/archive",
    summary="Archive mediation session",
    response_model=MediationSession,
)
async def archive_mediation_session(
    session_id: MongoId,
    service: MediationServiceDep,
    session: SessionDep,
) -> MediationSession:
    return await service.archive_session(session_id, session.user_type)


@router.delete(
    "/{session_id}/archive",
    summary="Undo mediation session archive mark",
    response_model=MediationSession,
)
async def unarchive_mediation_session(
    session_id: MongoId,
    service: MediationServiceDep,
    session: SessionDep,
) -> MediationSession:
    return await service.unarchive_session(session_id, session.user_type)


@router.get(
    "/{session_id}/perspectives/me",
    summary="Get my mediation perspective",
    response_model=MediationPerspective | None,
)
async def get_my_mediation_perspective(
    session_id: MongoId,
    service: MediationServiceDep,
    session: SessionDep,
) -> MediationPerspective | None:
    return await service.get_my_perspective(session_id, session.user_type)


@router.put(
    "/{session_id}/perspectives/me/draft",
    summary="Create or update my mediation perspective draft",
    response_model=MediationPerspective,
)
async def upsert_my_mediation_perspective_draft(
    session_id: MongoId,
    payload: MediationPerspectiveDraftUpdate,
    service: MediationServiceDep,
    session: SessionDep,
) -> MediationPerspective:
    return await service.upsert_my_perspective_draft(session_id, session.user_type, payload)


@router.post(
    "/{session_id}/perspectives/me/submit",
    summary="Submit my mediation perspective",
    response_model=SubmitPerspectiveResponse,
)
async def submit_my_mediation_perspective(
    session_id: MongoId,
    service: MediationServiceDep,
    session: SessionDep,
) -> SubmitPerspectiveResponse:
    return await service.submit_my_perspective(session_id, session.user_type)


@router.get(
    "/{session_id}/reflections/me",
    summary="Get my private mediation reflection",
    response_model=ReflectionEndpointResponse,
)
async def get_my_mediation_reflection(
    session_id: MongoId,
    service: MediationServiceDep,
    session: SessionDep,
) -> ReflectionEndpointResponse:
    return await service.get_my_reflection(session_id, session.user_type)


@router.get(
    "/{session_id}/advice",
    summary="Get shared mediation advice",
    response_model=AdviceEndpointResponse,
)
async def get_mediation_advice(
    session_id: MongoId,
    service: MediationServiceDep,
    session: SessionDep,
) -> AdviceEndpointResponse:
    return await service.get_advice(session_id, session.user_type)


@router.get(
    "/{session_id}/comments",
    summary="List mediation comments",
    response_model=list[MediationCommentResponse],
)
async def list_mediation_comments(
    session_id: MongoId,
    service: MediationServiceDep,
    session: SessionDep,
) -> list[MediationCommentResponse]:
    return await service.list_comments(session_id, session.user_type)


@router.post(
    "/{session_id}/comments",
    summary="Create mediation comment",
    response_model=CommentCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_mediation_comment(
    session_id: MongoId,
    payload: MediationCommentCreate,
    service: MediationServiceDep,
    session: SessionDep,
) -> CommentCreateResponse:
    return await service.create_comment(session_id, session.user_type, payload)


@router.post(
    "/{session_id}/comments/{comment_id}/replies",
    summary="Create mediation comment reply",
    response_model=CommentCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_mediation_reply(
    session_id: MongoId,
    comment_id: MongoId,
    payload: MediationCommentCreate,
    service: MediationServiceDep,
    session: SessionDep,
) -> CommentCreateResponse:
    return await service.create_reply(session_id, comment_id, session.user_type, payload)
