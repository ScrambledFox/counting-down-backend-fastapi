from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.schemas import TogetherListItemCreate
from app.models.together_list_item import TogetherListItem
from app.services.deps import get_together_list_service
from app.services.together_list import TogetherListService

router = APIRouter(tags=["together_list"], prefix="/todos")


@router.get("/", summary="Get Together List Items", response_model=list[TogetherListItem])
async def get_together_list_items(
    service: TogetherListService = Depends(get_together_list_service),
):
    return await service.get_all_items()

@router.post("/", summary="Create Together List Item", response_model=TogetherListItem)
async def create_together_list_item(
    item: TogetherListItemCreate,
    service: TogetherListService = Depends(get_together_list_service),
):
    try:
        return await service.create_item(item.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

@router.get("/{item_id}", summary="Get Together List Item", response_model=TogetherListItem)
async def get_together_list_item(
    item_id: str,
    service: TogetherListService = Depends(get_together_list_service),
):
    item = await service.get_item_by_id(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@router.put("/{item_id}", summary="Update Together List Item", response_model=TogetherListItem)
async def update_together_list_item(
    item_id: str,
    item: TogetherListItemCreate,
    service: TogetherListService = Depends(get_together_list_service),
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
    summary="Delete Together List Item",
    response_model=dict,
)
async def delete_together_list_item(
    item_id: str,
    service: TogetherListService = Depends(get_together_list_service),
):
    success = await service.delete_item(item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"detail": "Item deleted"}

@router.post( 
    "/{item_id}/toggle-completion",
    summary="Toggle Together List Item Completion",
    response_model=TogetherListItem,
)
async def toggle_together_list_item_completion(
    item_id: str,
    service: TogetherListService = Depends(get_together_list_service),
):
    updated_item = await service.toggle_item_completion(item_id)
    if not updated_item:
        raise HTTPException(status_code=404, detail="Item not found")
    return updated_item
