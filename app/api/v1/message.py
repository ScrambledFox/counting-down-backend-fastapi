from fastapi import APIRouter, Depends

from app.core.exceptions import BadRequestException, NotFoundException
from app.dependencies import get_message_service
from app.schemas.v1.message import Message, MessageCreate
from app.services.message import MessageService

router = APIRouter(tags=["messages"], prefix="/messages")


@router.get("/", summary="Get Message Items")
async def get_message_items(
    service: MessageService = Depends(get_message_service),
) -> list[Message]:
    return await service.get_all_messages()


@router.get("/{message_id}", summary="Get Message Item")
async def get_message_item(
    message_id: str, service: MessageService = Depends(get_message_service)
) -> Message:
    message = await service.get_message_by_id(message_id)
    if not message:
        raise NotFoundException("Message", message_id)
    return message


@router.post("/", summary="Create Message Item")
async def create_message_item(
    message: MessageCreate, service: MessageService = Depends(get_message_service)
) -> Message:
    try:
        return await service.create_message(message)
    except ValueError as e:
        raise BadRequestException(detail=str(e)) from None


@router.delete("/{message_id}", summary="Delete Message Item")
async def delete_message_item(
    message_id: str, service: MessageService = Depends(get_message_service)
) -> dict[str, str]:
    success = await service.delete_message(message_id)
    if not success:
        raise NotFoundException("Message", message_id)
    return {"detail": "Item deleted"}
