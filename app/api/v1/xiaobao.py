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
    XiaoBaoMessageCreate,
    XiaoBaoProposal,
    XiaoBaoProposalUpdate,
)
from app.services.xiaobao import XiaoBaoConversationService
from app.services.xiaobao_proposals import XiaoBaoProposalService

router = make_router()
SessionDep = Annotated[SessionResponse, Security(require_session)]
ConversationServiceDep = Annotated[XiaoBaoConversationService, Depends()]
ProposalServiceDep = Annotated[XiaoBaoProposalService, Depends()]


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
