from typing import Annotated

from fastapi import Depends

from app.api.routing import make_router
from app.schemas.v1.base import MongoId
from app.schemas.v1.exceptions import BadRequestException, NotFoundException
from app.schemas.v1.message import Message, MessageCreate
from app.schemas.v1.response import DeletedResponse
from app.services.message import MessageService

router = make_router()

MessageServiceDep = Annotated[MessageService, Depends()]


@router.get("/", summary="Get Message Items", response_model=list[Message])
async def get_message_items(service: MessageServiceDep) -> list[Message]:
    return await service.get_all_messages()


@router.get("/{message_id}", summary="Get Message Item", response_model=Message)
async def get_message_item(message_id: MongoId, service: MessageServiceDep) -> Message:
    message = await service.get_message_by_id(message_id)
    if not message:
        raise NotFoundException("Message", message_id)
    return message


@router.post("/", summary="Create Message Item", response_model=Message)
async def create_message_item(message: MessageCreate, service: MessageServiceDep) -> Message:
    try:
        return await service.create_message(message)
    except ValueError as e:
        raise BadRequestException(detail=str(e)) from None


@router.delete("/{message_id}", summary="Delete Message Item")
async def delete_message_item(message_id: MongoId, service: MessageServiceDep):
    success = await service.delete_message(message_id)
    if not success:
        raise NotFoundException("Message", message_id)
    return DeletedResponse()
