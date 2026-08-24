import base64
import binascii
import json
from datetime import datetime
from typing import Annotated, Any

from bson import ObjectId
from fastapi import Depends

from app.repositories.xiaobao import XiaoBaoConversationRepository, XiaoBaoMessageRepository
from app.repositories.xiaobao_routine import (
    XiaoBaoRoutineRepository,
    XiaoBaoRoutineRunRepository,
)
from app.schemas.v1.base import MongoId
from app.schemas.v1.exceptions import BadRequestException, ConflictException, NotFoundException
from app.schemas.v1.user import UserType
from app.schemas.v1.xiaobao import (
    XiaoBaoInbox,
    XiaoBaoInboxMessageResponse,
)
from app.schemas.v1.xiaobao_routine import (
    XiaoBaoInboxUnreadCount,
    XiaoBaoRoutine,
    XiaoBaoRoutineCreate,
    XiaoBaoRoutineDeliveryChannel,
    XiaoBaoRoutineFrequency,
    XiaoBaoRoutineKind,
    XiaoBaoRoutinePauseReason,
    XiaoBaoRoutineResponse,
    XiaoBaoRoutineRunList,
    XiaoBaoRoutineRunResponse,
    XiaoBaoRoutineUpdate,
)
from app.services.xiaobao_routine_policy import XIAOBAO_ROUTINE_UNREAD_INACTIVITY_THRESHOLD
from app.services.xiaobao_schedule import next_scheduled_at
from app.util.time import utc_now


def _encode_inbox_cursor(created_at: datetime, message_id: MongoId) -> str:
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "id": str(message_id)},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_inbox_cursor(cursor: str) -> tuple[datetime, MongoId]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        created_at = datetime.fromisoformat(payload["created_at"])
        if created_at.tzinfo is None:
            raise ValueError
        message_id = str(ObjectId(payload["id"]))
    except (binascii.Error, KeyError, TypeError, UnicodeError, ValueError) as exc:
        raise BadRequestException("Invalid Xiao Bao inbox cursor") from exc
    return created_at, message_id


class XiaoBaoRoutineService:
    def __init__(
        self,
        routines: Annotated[XiaoBaoRoutineRepository, Depends()],
        runs: Annotated[XiaoBaoRoutineRunRepository, Depends()],
        conversations: Annotated[XiaoBaoConversationRepository, Depends()],
        messages: Annotated[XiaoBaoMessageRepository, Depends()],
    ) -> None:
        self._routines = routines
        self._runs = runs
        self._conversations = conversations
        self._messages = messages

    @staticmethod
    def _next_run_at(
        payload: XiaoBaoRoutineCreate | XiaoBaoRoutineUpdate, now: datetime
    ) -> datetime:
        if payload.schedule is None:
            raise ConflictException("A routine schedule cannot be removed")
        try:
            return next_scheduled_at(payload.schedule, after=now)
        except ValueError as exc:
            raise BadRequestException(str(exc)) from exc

    async def create(
        self, payload: XiaoBaoRoutineCreate, owner: UserType
    ) -> XiaoBaoRoutineResponse:
        now = utc_now()
        routine = await self._routines.create(
            XiaoBaoRoutine(
                owner_user_type=owner,
                kind=payload.kind,
                name=payload.name,
                instruction=payload.instruction,
                message=payload.message,
                schedule=payload.schedule,
                context_profile=payload.context_profile,
                delivery_channel=XiaoBaoRoutineDeliveryChannel.IN_APP,
                enabled=True,
                next_run_at=self._next_run_at(payload, now),
                created_at=now,
                updated_at=now,
            )
        )
        return XiaoBaoRoutineResponse.from_record(routine)

    async def list(self, owner: UserType) -> list[XiaoBaoRoutineResponse]:
        return [
            XiaoBaoRoutineResponse.from_record(item)
            for item in await self._routines.list_owned(owner)
        ]

    async def _get_record(self, routine_id: MongoId, owner: UserType) -> XiaoBaoRoutine:
        routine = await self._routines.get_owned(routine_id, owner)
        if not routine:
            raise NotFoundException("Xiao Bao routine", routine_id)
        return routine

    async def get(self, routine_id: MongoId, owner: UserType) -> XiaoBaoRoutineResponse:
        return XiaoBaoRoutineResponse.from_record(await self._get_record(routine_id, owner))

    async def update(
        self, routine_id: MongoId, payload: XiaoBaoRoutineUpdate, owner: UserType
    ) -> XiaoBaoRoutineResponse:
        current = await self._get_record(routine_id, owner)
        if current.finished_at is not None:
            raise ConflictException("A completed one-time reminder cannot be edited")
        fields: dict[str, Any] = payload.model_dump(
            mode="python", exclude_unset=True, exclude_none=True
        )
        now = utc_now()
        if current.kind == XiaoBaoRoutineKind.REMINDER:
            if current.next_run_at is None:
                raise ConflictException("A consumed one-time reminder cannot be edited")
            if current.next_run_at <= now and "schedule" not in fields:
                raise ConflictException(
                    "A one-time reminder cannot be edited after its scheduled time"
                )
        if current.kind == XiaoBaoRoutineKind.REMINDER and "instruction" in fields:
            raise BadRequestException("A reminder cannot include a routine instruction")
        if current.kind == XiaoBaoRoutineKind.ROUTINE and "message" in fields:
            raise BadRequestException("A routine cannot include a static reminder message")
        if "schedule" in fields:
            schedule = payload.schedule
            if schedule is None:
                raise ConflictException("A routine schedule cannot be removed")
            fields["schedule"] = schedule.model_dump(mode="python")
            if current.kind == XiaoBaoRoutineKind.REMINDER and (
                schedule.frequency != XiaoBaoRoutineFrequency.ONCE
            ):
                raise BadRequestException("A reminder must use a one-time schedule")
            if current.kind == XiaoBaoRoutineKind.ROUTINE and (
                schedule.frequency == XiaoBaoRoutineFrequency.ONCE
            ):
                raise BadRequestException("A routine must use a daily or weekly schedule")
            if current.enabled or current.kind == XiaoBaoRoutineKind.REMINDER:
                fields["next_run_at"] = self._next_run_at(payload, now)
        if not fields:
            return XiaoBaoRoutineResponse.from_record(current)
        updated = await self._routines.update_owned(routine_id, owner, fields)
        if not updated:
            raise NotFoundException("Xiao Bao routine", routine_id)
        if "schedule" in fields:
            await self._runs.cancel_pending_for_routine(routine_id)
        return XiaoBaoRoutineResponse.from_record(updated)

    async def pause(self, routine_id: MongoId, owner: UserType) -> XiaoBaoRoutineResponse:
        current = await self._get_record(routine_id, owner)
        if not current.enabled:
            await self._runs.cancel_pending_for_routine(routine_id)
            return XiaoBaoRoutineResponse.from_record(current)
        paused = await self._routines.pause_owned(routine_id, owner)
        if not paused:
            # A concurrent pause may have won after the initial read. Preserve its reason and
            # revision instead of rewriting an inactivity pause as manual.
            latest = await self._routines.get_owned(routine_id, owner)
            if latest and not latest.enabled:
                await self._runs.cancel_pending_for_routine(routine_id)
                return XiaoBaoRoutineResponse.from_record(latest)
            raise NotFoundException("Xiao Bao routine", routine_id)
        await self._runs.cancel_pending_for_routine(routine_id)
        return XiaoBaoRoutineResponse.from_record(paused)

    async def resume(self, routine_id: MongoId, owner: UserType) -> XiaoBaoRoutineResponse:
        current = await self._get_record(routine_id, owner)
        now = utc_now()
        if current.schedule.frequency == XiaoBaoRoutineFrequency.ONCE and (
            current.finished_at is not None or current.next_run_at is None
        ):
            raise ConflictException("A completed one-time reminder cannot be resumed")
        if current.pause_reason == XiaoBaoRoutinePauseReason.UNREAD_INACTIVITY:
            inbox = await self._conversations.get_inbox(owner)
            if (
                inbox
                and inbox.id
                and await self._messages.has_unread_routine_output_at_or_before(
                    routine_id,
                    str(inbox.id),
                    threshold=now - XIAOBAO_ROUTINE_UNREAD_INACTIVITY_THRESHOLD,
                )
            ):
                raise ConflictException(
                    "Read this routine's older inbox messages before resuming it"
                )
        try:
            next_run_at = next_scheduled_at(current.schedule, after=now)
        except ValueError as exc:
            raise ConflictException(
                "A one-time reminder cannot be resumed after its scheduled time"
            ) from exc
        resumed = await self._routines.resume_owned(routine_id, owner, next_run_at)
        if not resumed:
            raise NotFoundException("Xiao Bao routine", routine_id)
        return XiaoBaoRoutineResponse.from_record(resumed)

    async def delete(self, routine_id: MongoId, owner: UserType) -> None:
        await self._get_record(routine_id, owner)
        if not await self._routines.soft_delete_owned(routine_id, owner):
            raise NotFoundException("Xiao Bao routine", routine_id)
        await self._runs.cancel_pending_for_routine(routine_id)

    async def list_runs(
        self, routine_id: MongoId, owner: UserType, *, limit: int
    ) -> XiaoBaoRoutineRunList:
        await self._get_record(routine_id, owner)
        items, has_more = await self._runs.list_owned(routine_id, owner, limit=limit)
        return XiaoBaoRoutineRunList(
            items=[XiaoBaoRoutineRunResponse.from_record(item) for item in items],
            has_more=has_more,
        )

    async def inbox(
        self,
        owner: UserType,
        *,
        limit: int,
        routine_id: MongoId | None = None,
        cursor: str | None = None,
    ) -> XiaoBaoInbox:
        if routine_id is not None:
            await self._get_record(routine_id, owner)
        before_created_at: datetime | None = None
        before_id: MongoId | None = None
        if cursor is not None:
            before_created_at, before_id = _decode_inbox_cursor(cursor)
        conversation = await self._conversations.get_or_create_inbox(owner)
        if not conversation.id:
            raise ConflictException("The routines inbox is unavailable")
        messages, has_more = await self._messages.list_routine_inbox(
            str(conversation.id),
            limit=limit,
            routine_id=routine_id,
            before_created_at=before_created_at,
            before_id=before_id,
        )
        unread = await self._messages.count_unread_for_conversation(str(conversation.id))
        return XiaoBaoInbox(
            messages=[XiaoBaoInboxMessageResponse.from_record(item) for item in messages],
            has_more_messages=has_more,
            next_cursor=(
                _encode_inbox_cursor(messages[-1].created_at, str(messages[-1].id))
                if has_more and messages and messages[-1].id
                else None
            ),
            unread_count=unread,
        )

    async def unread_count(self, owner: UserType) -> XiaoBaoInboxUnreadCount:
        conversation = await self._conversations.get_or_create_inbox(owner)
        if not conversation.id:
            raise ConflictException("The routines inbox is unavailable")
        return XiaoBaoInboxUnreadCount(
            unread_count=await self._messages.count_unread_for_conversation(str(conversation.id))
        )

    async def mark_read(self, message_id: MongoId, owner: UserType) -> XiaoBaoInboxMessageResponse:
        conversation = await self._conversations.get_or_create_inbox(owner)
        if not conversation.id:
            raise ConflictException("The routines inbox is unavailable")
        message = await self._messages.mark_routine_message_read(message_id, str(conversation.id))
        if not message:
            raise NotFoundException("Xiao Bao inbox message", message_id)
        return XiaoBaoInboxMessageResponse.from_record(message)
