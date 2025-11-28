from typing import Annotated

from fastapi import Depends

from app.repositories.message import MessageRepository
from app.schemas.v1.base import MongoId
from app.schemas.v1.message import Message, MessageCreate
from app.util.time import utc_now


class MessageService:
    def __init__(self, repo: Annotated[MessageRepository, Depends()]):
        self._repo = repo

    async def get_all_messages(self) -> list[Message]:
        return await self._repo.list_not_deleted()

    async def get_message_by_id(self, message_id: MongoId) -> Message | None:
        return await self._repo.get(message_id)

    async def create_message(self, message: MessageCreate) -> Message:
        new_message: Message = Message(
            sender=message.sender.strip() if message.sender else "Anonymous",
            message=message.message.strip(),
            created_at=utc_now(),
        )
        return await self._repo.create(new_message)

    async def delete_message(self, message_id: MongoId) -> bool:
        updated = await self._repo.update(
            message_id,
            {
                "deleted_at": utc_now(),
            },
        )
        return updated is not None
