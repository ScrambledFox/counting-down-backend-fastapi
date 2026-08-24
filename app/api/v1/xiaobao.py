from datetime import datetime
from typing import Annotated

from fastapi import Depends, Query, Response, Security, status
from fastapi.responses import StreamingResponse

from app.api.routing import make_router
from app.core.auth import require_session
from app.schemas.v1.base import MongoId
from app.schemas.v1.session import SessionResponse
from app.schemas.v1.xiaobao import (
    XiaoBaoConversation,
    XiaoBaoConversationDetail,
    XiaoBaoInbox,
    XiaoBaoInboxMessageResponse,
    XiaoBaoMessageCreate,
    XiaoBaoProposal,
    XiaoBaoProposalUpdate,
)
from app.schemas.v1.xiaobao_routine import (
    XiaoBaoInboxUnreadCount,
    XiaoBaoRoutineCreate,
    XiaoBaoRoutineResponse,
    XiaoBaoRoutineRunList,
    XiaoBaoRoutineUpdate,
)
from app.services.xiaobao import XiaoBaoConversationService
from app.services.xiaobao_proposals import XiaoBaoProposalService
from app.services.xiaobao_routine import XiaoBaoRoutineService

router = make_router()
SessionDep = Annotated[SessionResponse, Security(require_session)]
ConversationServiceDep = Annotated[XiaoBaoConversationService, Depends()]
ProposalServiceDep = Annotated[XiaoBaoProposalService, Depends()]
RoutineServiceDep = Annotated[XiaoBaoRoutineService, Depends()]


@router.post(
    "/conversations", response_model=XiaoBaoConversation, status_code=status.HTTP_201_CREATED
)
async def create_conversation(
    service: ConversationServiceDep, session: SessionDep
) -> XiaoBaoConversation:
    return await service.create_conversation(session.user_type)


@router.get("/conversations", response_model=list[XiaoBaoConversation])
async def list_conversations(
    service: ConversationServiceDep,
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=50),
    before: datetime | None = Query(default=None),
) -> list[XiaoBaoConversation]:
    return await service.list_conversations(session.user_type, limit=limit, before=before)


@router.get("/conversations/{conversation_id}", response_model=XiaoBaoConversationDetail)
async def get_conversation(
    conversation_id: MongoId, service: ConversationServiceDep, session: SessionDep
) -> XiaoBaoConversationDetail:
    return await service.get_conversation(conversation_id, session.user_type)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: MongoId, service: ConversationServiceDep, session: SessionDep
) -> Response:
    await service.delete_conversation(conversation_id, session.user_type)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: MongoId,
    payload: XiaoBaoMessageCreate,
    service: ConversationServiceDep,
    session: SessionDep,
) -> StreamingResponse:
    user_message, assistant, should_generate = await service.prepare_message(
        conversation_id, session.user_type, payload
    )
    return StreamingResponse(
        service.stream_answer(
            conversation_id,
            session.user_type,
            user_message,
            assistant,
            run_generation=should_generate,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/conversations/{conversation_id}/messages/{assistant_message_id}/retry")
async def retry_message(
    conversation_id: MongoId,
    assistant_message_id: MongoId,
    service: ConversationServiceDep,
    session: SessionDep,
) -> StreamingResponse:
    user_message, assistant = await service.prepare_retry(
        conversation_id, assistant_message_id, session.user_type
    )
    return StreamingResponse(
        service.stream_answer(
            conversation_id,
            session.user_type,
            user_message,
            assistant,
            run_generation=True,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.patch("/proposals/{proposal_id}", response_model=XiaoBaoProposal)
async def update_proposal(
    proposal_id: MongoId,
    payload: XiaoBaoProposalUpdate,
    service: ProposalServiceDep,
    session: SessionDep,
) -> XiaoBaoProposal:
    return await service.update(proposal_id, session.user_type, payload.payload)


@router.post("/proposals/{proposal_id}/accept", response_model=XiaoBaoProposal)
async def accept_proposal(
    proposal_id: MongoId, service: ProposalServiceDep, session: SessionDep
) -> XiaoBaoProposal:
    return await service.accept(proposal_id, session.user_type)


@router.post("/proposals/{proposal_id}/reject", response_model=XiaoBaoProposal)
async def reject_proposal(
    proposal_id: MongoId, service: ProposalServiceDep, session: SessionDep
) -> XiaoBaoProposal:
    return await service.reject(proposal_id, session.user_type)


@router.get("/routines", response_model=list[XiaoBaoRoutineResponse])
async def list_routines(
    service: RoutineServiceDep, session: SessionDep
) -> list[XiaoBaoRoutineResponse]:
    return await service.list(session.user_type)


@router.post(
    "/routines", response_model=XiaoBaoRoutineResponse, status_code=status.HTTP_201_CREATED
)
async def create_routine(
    payload: XiaoBaoRoutineCreate, service: RoutineServiceDep, session: SessionDep
) -> XiaoBaoRoutineResponse:
    return await service.create(payload, session.user_type)


@router.get("/routines/{routine_id}", response_model=XiaoBaoRoutineResponse)
async def get_routine(
    routine_id: MongoId, service: RoutineServiceDep, session: SessionDep
) -> XiaoBaoRoutineResponse:
    return await service.get(routine_id, session.user_type)


@router.patch("/routines/{routine_id}", response_model=XiaoBaoRoutineResponse)
async def update_routine(
    routine_id: MongoId,
    payload: XiaoBaoRoutineUpdate,
    service: RoutineServiceDep,
    session: SessionDep,
) -> XiaoBaoRoutineResponse:
    return await service.update(routine_id, payload, session.user_type)


@router.delete("/routines/{routine_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_routine(
    routine_id: MongoId, service: RoutineServiceDep, session: SessionDep
) -> Response:
    await service.delete(routine_id, session.user_type)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/routines/{routine_id}/pause", response_model=XiaoBaoRoutineResponse)
async def pause_routine(
    routine_id: MongoId, service: RoutineServiceDep, session: SessionDep
) -> XiaoBaoRoutineResponse:
    return await service.pause(routine_id, session.user_type)


@router.post(
    "/routines/{routine_id}/resume",
    response_model=XiaoBaoRoutineResponse,
    responses={
        status.HTTP_409_CONFLICT: {"description": "Unread inactivity threshold still blocks resume"}
    },
)
async def resume_routine(
    routine_id: MongoId, service: RoutineServiceDep, session: SessionDep
) -> XiaoBaoRoutineResponse:
    return await service.resume(routine_id, session.user_type)


@router.get("/routines/{routine_id}/runs", response_model=XiaoBaoRoutineRunList)
async def list_routine_runs(
    routine_id: MongoId,
    service: RoutineServiceDep,
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100),
) -> XiaoBaoRoutineRunList:
    return await service.list_runs(routine_id, session.user_type, limit=limit)


@router.get("/inbox", response_model=XiaoBaoInbox)
async def get_routine_inbox(
    service: RoutineServiceDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
    routine_id: MongoId | None = Query(default=None),
    cursor: str | None = Query(default=None, min_length=1, max_length=500),
) -> XiaoBaoInbox:
    return await service.inbox(
        session.user_type,
        limit=limit,
        routine_id=routine_id,
        cursor=cursor,
    )


@router.get("/inbox/unread-count", response_model=XiaoBaoInboxUnreadCount)
async def get_routine_inbox_unread_count(
    service: RoutineServiceDep, session: SessionDep
) -> XiaoBaoInboxUnreadCount:
    return await service.unread_count(session.user_type)


@router.post("/inbox/{message_id}/read", response_model=XiaoBaoInboxMessageResponse)
async def mark_routine_inbox_message_read(
    message_id: MongoId, service: RoutineServiceDep, session: SessionDep
) -> XiaoBaoInboxMessageResponse:
    return await service.mark_read(message_id, session.user_type)
