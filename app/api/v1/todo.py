from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_todo_service
from app.schemas.v1.todo import Todo, TodoCreate, TodoUpdate
from app.services.todo import TodoService

router = APIRouter(tags=["todos"], prefix="/todos")


@router.get("/", summary="Get Todo Items", response_model=list[Todo])
async def get_todo_items(
    service: TodoService = Depends(get_todo_service),
) -> list[Todo]:
    return await service.get_all()


@router.get("/{item_id}", summary="Get Todo Item", response_model=Todo)
async def get_todo_item(item_id: str, service: TodoService = Depends(get_todo_service)) -> Todo:
    item = await service.get_by_id(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.post(
    "/", summary="Create Todo Item", response_model=Todo, status_code=status.HTTP_201_CREATED
)
async def create_todo_item(
    item: TodoCreate, service: TodoService = Depends(get_todo_service)
) -> Todo:
    try:
        return await service.create(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.put("/{item_id}", summary="Update Todo Item", response_model=Todo)
async def update_todo_item(
    item_id: str, item: TodoUpdate, service: TodoService = Depends(get_todo_service)
) -> Todo:
    try:
        updated_item = await service.update(item_id, item)
        if not updated_item:
            raise HTTPException(status_code=404, detail="Item not found")
        return updated_item
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.delete("/{item_id}", summary="Delete Todo Item")
async def delete_todo_item(
    item_id: str, service: TodoService = Depends(get_todo_service)
) -> dict[str, str]:
    success = await service.delete(item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"detail": "Item deleted"}


@router.post(
    "/{item_id}/toggle-completion",
    summary="Toggle Todo Item Completion",
    response_model=Todo,
)
async def toggle_todo_item_completion(
    item_id: str, service: TodoService = Depends(get_todo_service)
) -> Todo:
    updated_item = await service.toggle_completion(item_id)
    if not updated_item:
        raise HTTPException(status_code=404, detail="Item not found")
    return updated_item
