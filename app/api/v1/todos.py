from fastapi import APIRouter, Depends, HTTPException

from app.services.deps import get_todo_service
from app.services.todos import TodoService

from .schemas import TodoItem, TodoItemCreate

router = APIRouter(tags=["todos"], prefix="/todos")


@router.get("/", summary="Get Todo Items", response_model=list[TodoItem])
async def get_todo_items(
    service: TodoService = Depends(get_todo_service),
):
    return await service.get_all_items()

@router.post("/", summary="Create Todo Item", response_model=TodoItem)
async def create_todo_item(
    item: TodoItemCreate,
    service: TodoService = Depends(get_todo_service),
):
    try:
        return await service.create_item(item.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

@router.get("/{item_id}", summary="Get Todo Item", response_model=TodoItem)
async def get_todo_item(
    item_id: str,
    service: TodoService = Depends(get_todo_service),
):
    item = await service.get_item_by_id(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@router.put("/{item_id}", summary="Update Todo Item", response_model=TodoItem)
async def update_todo_item(
    item_id: str,
    item: TodoItemCreate,
    service: TodoService = Depends(get_todo_service),
):
    try:
        updated_item = await service.update_item(item_id, item.model_dump())
        if not updated_item:
            raise HTTPException(status_code=404, detail="Item not found")
        return updated_item
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

@router.delete(
    "/{item_id}",
    summary="Delete Todo Item",
)
async def delete_todo_item(
    item_id: str,
    service: TodoService = Depends(get_todo_service),
):
    success = await service.delete_item(item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"detail": "Item deleted"}

@router.post( 
    "/{item_id}/toggle-completion",
    summary="Toggle Todo Item Completion",
    response_model=TodoItem,
)
async def toggle_todo_item_completion(
    item_id: str,
    service: TodoService = Depends(get_todo_service),
):
    updated_item = await service.toggle_item_completion(item_id)
    if not updated_item:
        raise HTTPException(status_code=404, detail="Item not found")
    return updated_item
