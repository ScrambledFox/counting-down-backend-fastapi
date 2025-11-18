from typing import Annotated

from fastapi import Depends, status

from app.api.routing import make_router
from app.schemas.v1.base import MongoId
from app.schemas.v1.exceptions import BadRequestException, NotFoundException
from app.schemas.v1.response import DeletedResponse
from app.schemas.v1.todo import Todo, TodoCreate, TodoUpdate
from app.services.todo import TodoService

router = make_router()

TodoServiceDep = Annotated[TodoService, Depends()]


@router.get("/", summary="Get Todo Items", response_model=list[Todo])
async def get_todo_items(service: TodoServiceDep) -> list[Todo]:
    return await service.get_all()


@router.get("/{item_id}", summary="Get Todo Item", response_model=Todo)
async def get_todo_item(item_id: MongoId, service: TodoServiceDep) -> Todo:
    item = await service.get_by_id(item_id)
    if not item:
        raise NotFoundException("Todo", item_id)
    return item


@router.post(
    "/",
    summary="Create Todo Item",
    response_model=Todo,
    status_code=status.HTTP_201_CREATED,
)
async def create_todo_item(item: TodoCreate, service: TodoServiceDep) -> Todo:
    return await service.create(item)


@router.put("/{item_id}", summary="Update Todo Item", response_model=Todo)
async def update_todo_item(item_id: MongoId, item: TodoUpdate, service: TodoServiceDep) -> Todo:
    try:
        updated_item = await service.update(item_id, item)
        if not updated_item:
            raise NotFoundException("Todo", item_id)
        return updated_item
    except ValueError as e:
        raise BadRequestException(detail=str(e)) from None


@router.delete("/{item_id}", summary="Delete Todo Item")
async def delete_todo_item(item_id: MongoId, service: TodoServiceDep):
    success = await service.delete(item_id)
    if not success:
        raise NotFoundException("Todo", item_id)
    return DeletedResponse()


@router.post(
    "/{item_id}/toggle-completion",
    summary="Toggle Todo Item Completion",
    response_model=Todo,
)
async def toggle_todo_item_completion(item_id: MongoId, service: TodoServiceDep) -> Todo:
    updated_item = await service.toggle_completion(item_id)
    if not updated_item:
        raise NotFoundException("Todo", item_id)
    return updated_item
