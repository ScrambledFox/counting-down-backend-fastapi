

from app.core.time import utc_now
from app.repositories.message import MessageRepository
from app.schemas.v1.message import Message, MessageCreate


class MessageService:
    def __init__(self, repo: MessageRepository) -> None:
        self._repo = repo

    async def get_all_messages(self) -> list[Message]:
        return await self._repo.list_not_deleted()
    
    async def get_message_by_id(self, message_id: str) -> Message | None:
        return await self._repo.get(message_id)

    async def create_message(self, message: MessageCreate) -> Message:
        new_message: Message = Message(
            sender=message.sender.strip() if message.sender else "Anonymous",
            message=message.message.strip(),
            created_at=utc_now(),
        )

        created_id = await self._repo.create(new_message)

        created = await self._repo.get(created_id)
        if created is None:
            raise RuntimeError(f"Failed to fetch newly created message with id {created_id}")
        return created

    async def delete_message(self, message_id: str) -> bool:
        updated = await self._repo.update(
            message_id,
            {
                "deleted_at": utc_now(),
            },
        )
        return updated is not None