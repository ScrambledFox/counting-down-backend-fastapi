import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.openai_client import OpenAIClient
from app.repositories.xiaobao import (
    XiaoBaoConversationRepository,
    XiaoBaoMessageRepository,
    XiaoBaoProposalRepository,
    XiaoBaoRateLimitRepository,
)
from app.schemas.v1.base import MongoId
from app.schemas.v1.exceptions import ConflictException, NotFoundException
from app.schemas.v1.user import UserType
from app.schemas.v1.xiaobao import (
    XiaoBaoConversation,
    XiaoBaoConversationDetail,
    XiaoBaoMessage,
    XiaoBaoMessageCreate,
    XiaoBaoMessageRole,
    XiaoBaoMessageStatus,
)
from app.services.todo import TodoService
from app.services.xiaobao_context import RelationshipContextService
from app.util.time import utc_now
from app.xiaobao.graph import (
    XiaoBaoRuntimeContext,
    get_xiaobao_checkpointer,
    run_xiaobao_graph,
)

settings = get_settings()
logger = get_logger(__name__)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=True)}\n\n"


class XiaoBaoConversationService:
    def __init__(
        self,
        conversations: Annotated[XiaoBaoConversationRepository, Depends()],
        messages: Annotated[XiaoBaoMessageRepository, Depends()],
        proposals: Annotated[XiaoBaoProposalRepository, Depends()],
        rate_limits: Annotated[XiaoBaoRateLimitRepository, Depends()],
        relationship_context: Annotated[RelationshipContextService, Depends()],
        todos: Annotated[TodoService, Depends()],
        openai_client: Annotated[OpenAIClient, Depends()],
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._proposals = proposals
        self._rate_limits = rate_limits
        self._relationship_context = relationship_context
        self._todos = todos
        self._openai = openai_client

    async def create_conversation(self, owner: UserType) -> XiaoBaoConversation:
        now = utc_now()
        return await self._conversations.create(
            XiaoBaoConversation(
                owner_user_type=owner,
                title="New chat",
                created_at=now,
                updated_at=now,
            )
        )

    async def list_conversations(
        self, owner: UserType, *, limit: int, before: Any | None = None
    ) -> list[XiaoBaoConversation]:
        return await self._conversations.list_owned(owner, limit=limit, before=before)

    async def get_conversation(
        self, conversation_id: MongoId, owner: UserType
    ) -> XiaoBaoConversationDetail:
        conversation = await self._require_conversation(conversation_id, owner)
        messages, has_more = await self._messages.list_for_conversation(conversation_id, limit=100)
        proposals = await self._proposals.list_for_conversation(conversation_id)
        return XiaoBaoConversationDetail(
            conversation=conversation,
            messages=messages,
            proposals=proposals,
            has_more_messages=has_more,
        )

    async def delete_conversation(self, conversation_id: MongoId, owner: UserType) -> None:
        deleted = await self._conversations.delete_owned(conversation_id, owner)
        if not deleted:
            raise NotFoundException("Xiao Bao conversation", conversation_id)
        try:
            await get_xiaobao_checkpointer().adelete_thread(str(conversation_id))
        except Exception:
            logger.warning(
                "Xiao Bao checkpoint cleanup failed", extra={"conversation_id": conversation_id}
            )

    async def _require_conversation(
        self, conversation_id: MongoId, owner: UserType
    ) -> XiaoBaoConversation:
        conversation = await self._conversations.get_owned(conversation_id, owner)
        if not conversation:
            raise NotFoundException("Xiao Bao conversation", conversation_id)
        return conversation

    async def _consume_rate_limit(self, owner: UserType) -> None:
        if not await self._rate_limits.consume(owner):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Xiao Bao needs a short breather. Please try again in a few minutes.",
            )

    def _title_from_message(self, content: str) -> str:
        collapsed = " ".join(content.split())
        return collapsed[:60] + ("…" if len(collapsed) > 60 else "")

    async def prepare_message(
        self, conversation_id: MongoId, owner: UserType, payload: XiaoBaoMessageCreate
    ) -> tuple[XiaoBaoMessage, XiaoBaoMessage, bool]:
        conversation = await self._require_conversation(conversation_id, owner)
        await self._consume_rate_limit(owner)
        now = utc_now()
        user_message, created = await self._messages.create_user(
            XiaoBaoMessage(
                conversation_id=str(conversation_id),
                role=XiaoBaoMessageRole.USER,
                status=XiaoBaoMessageStatus.COMPLETE,
                content=payload.content,
                client_message_id=payload.client_message_id,
                created_at=now,
                updated_at=now,
            )
        )
        if not user_message.id:
            raise ConflictException("The Xiao Bao message could not be created")
        existing = await self._messages.get_assistant_for_user_message(
            conversation_id, str(user_message.id)
        )
        if existing:
            if existing.status == XiaoBaoMessageStatus.GENERATING:
                raise ConflictException("Xiao Bao is already answering this message")
            return user_message, existing, False
        try:
            assistant = await self._messages.create_assistant(
                XiaoBaoMessage(
                    conversation_id=str(conversation_id),
                    role=XiaoBaoMessageRole.ASSISTANT,
                    status=XiaoBaoMessageStatus.GENERATING,
                    parent_user_message_id=str(user_message.id),
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
        except DuplicateKeyError as exc:
            raise ConflictException("Xiao Bao is already answering this conversation") from exc
        if created and conversation.title == "New chat":
            await self._conversations.touch(
                conversation_id, title=self._title_from_message(payload.content)
            )
        else:
            await self._conversations.touch(conversation_id)
        return user_message, assistant, True

    async def prepare_retry(
        self, conversation_id: MongoId, assistant_message_id: MongoId, owner: UserType
    ) -> tuple[XiaoBaoMessage, XiaoBaoMessage]:
        await self._require_conversation(conversation_id, owner)
        await self._consume_rate_limit(owner)
        assistant = await self._messages.get(assistant_message_id)
        if (
            not assistant
            or assistant.conversation_id != str(conversation_id)
            or assistant.role != XiaoBaoMessageRole.ASSISTANT
            or not assistant.parent_user_message_id
        ):
            raise NotFoundException("Xiao Bao message", assistant_message_id)
        restarted = await self._messages.restart(assistant_message_id)
        if not restarted:
            raise ConflictException("Only failed or cancelled Xiao Bao messages can be retried")
        user_message = await self._messages.get(assistant.parent_user_message_id)
        if not user_message:
            raise NotFoundException("Xiao Bao user message", assistant.parent_user_message_id)
        return user_message, restarted

    async def _history(
        self, conversation_id: MongoId, excluded_user_message_id: MongoId
    ) -> list[dict[str, str]]:
        messages = await self._messages.list_completed_history(
            conversation_id, limit=settings.xiaobao_history_message_limit + 1
        )
        candidates = [item for item in messages if str(item.id) != str(excluded_user_message_id)]
        selected: list[XiaoBaoMessage] = []
        characters = 0
        for item in reversed(candidates):
            if characters + len(item.content) > settings.xiaobao_history_character_limit:
                break
            selected.append(item)
            characters += len(item.content)
        return [
            {
                "role": "user" if item.role == XiaoBaoMessageRole.USER else "assistant",
                "content": item.content,
            }
            for item in reversed(selected)
        ]

    async def stream_answer(
        self,
        conversation_id: MongoId,
        owner: UserType,
        user_message: XiaoBaoMessage,
        assistant: XiaoBaoMessage,
        *,
        run_generation: bool,
    ) -> AsyncIterator[str]:
        if not user_message.id or not assistant.id:
            raise ConflictException("Xiao Bao message identifiers are unavailable")
        yield _sse("message.accepted", {"message": user_message.model_dump(mode="json")})
        yield _sse("assistant.started", {"message": assistant.model_dump(mode="json")})

        if not run_generation:
            if assistant.status == XiaoBaoMessageStatus.COMPLETE:
                proposals = await self._proposals.list_for_conversation(conversation_id)
                yield _sse(
                    "assistant.completed",
                    {
                        "message": assistant.model_dump(mode="json"),
                        "proposals": [
                            item.model_dump(mode="json")
                            for item in proposals
                            if str(item.message_id) == str(assistant.id)
                        ],
                    },
                )
            else:
                yield _sse(
                    "assistant.failed",
                    {"message": assistant.model_dump(mode="json"), "retryable": True},
                )
            return

        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

        async def emit(event: str, data: dict[str, Any]) -> None:
            await queue.put((event, data))

        started_at = time.monotonic()
        task: asyncio.Task[Any] | None = None
        try:
            authorized_context = await self._relationship_context.build(owner)
            history = await self._history(conversation_id, str(user_message.id))
            runtime = XiaoBaoRuntimeContext(
                owner=owner,
                conversation_id=str(conversation_id),
                assistant_message_id=str(assistant.id),
                history=history,
                relationship_context=authorized_context.public,
                private_mediation_by_key=authorized_context.private_mediation_by_key,
                proposal_repo=self._proposals,
                todo_service=self._todos,
                openai_client=self._openai,
                emit=emit,
            )
            task = asyncio.create_task(run_xiaobao_graph(runtime, user_message.content))
            while not task.done() or not queue.empty():
                next_event = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {task, next_event},
                    timeout=10,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if next_event in done:
                    event, data = next_event.result()
                    yield _sse(event, data)
                else:
                    next_event.cancel()
                    with suppress(asyncio.CancelledError):
                        await next_event
                if not done:
                    yield ": keep-alive\n\n"
            graph_result = await task
            if not graph_result.content:
                raise RuntimeError("Xiao Bao returned an empty final response")
            completed = await self._messages.complete(
                str(assistant.id),
                content=graph_result.content,
                references=graph_result.context_references,
                proposal_ids=graph_result.proposal_ids,
                completed_actions=graph_result.completed_actions,
                mascot_mood=graph_result.mascot_mood,
                model=settings.openai_model_xiaobao,
                provider_response_id=graph_result.response_id,
                token_usage=graph_result.token_usage,
            )
            if not completed:
                raise RuntimeError("Xiao Bao assistant message could not be finalized")
            await self._conversations.touch(conversation_id)
            proposals = await self._proposals.list_for_conversation(conversation_id)
            logger.info(
                "Xiao Bao response completed",
                extra={
                    "conversation_id": str(conversation_id),
                    "user_type": owner.value,
                    "model": settings.openai_model_xiaobao,
                    "duration_ms": round((time.monotonic() - started_at) * 1000),
                    "input_tokens": graph_result.token_usage.input_tokens,
                    "output_tokens": graph_result.token_usage.output_tokens,
                    "proposal_count": len(graph_result.proposal_ids),
                },
            )
            yield _sse(
                "assistant.completed",
                {
                    "message": completed.model_dump(mode="json"),
                    "proposals": [
                        item.model_dump(mode="json")
                        for item in proposals
                        if str(item.message_id) == str(completed.id)
                    ],
                },
            )
        except asyncio.CancelledError:
            if task:
                task.cancel()
            await self._messages.mark_terminal(
                str(assistant.id), XiaoBaoMessageStatus.CANCELLED, "client_cancelled"
            )
            raise
        except Exception as exc:
            if task:
                task.cancel()
            failed = await self._messages.mark_terminal(
                str(assistant.id), XiaoBaoMessageStatus.FAILED, type(exc).__name__
            )
            logger.warning(
                "Xiao Bao response failed",
                extra={
                    "conversation_id": str(conversation_id),
                    "user_type": owner.value,
                    "error_type": type(exc).__name__,
                },
            )
            yield _sse(
                "assistant.failed",
                {
                    "message": failed.model_dump(mode="json") if failed else None,
                    "retryable": True,
                },
            )
