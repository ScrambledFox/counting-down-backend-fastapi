from typing import Annotated

from fastapi import Depends, File, Form, UploadFile

from app.api.routing import make_router
from app.core.auth import require_session
from app.schemas.v1.advent import Advent, AdventCreate, AdventType
from app.schemas.v1.session import SessionResponse
from app.services.advent import AdventService
from app.util.time import utc_now
from app.util.user import get_other_user_type

router = make_router()

AdventServiceDep = Annotated[AdventService, Depends()]


@router.get(
    "/by_me", summary="List Advent Items Uploaded By My User Type", response_model=list[Advent]
)
async def list_advent_items_by_me(
    advent_service: AdventServiceDep, session: SessionResponse = Depends(require_session)
) -> list[Advent]:
    return await advent_service.list_advents_uploaded_by(session.user_type)


@router.get("/for_me", summary="List Advent Items For My User Type", response_model=list[Advent])
async def list_advent_items_for_me(
    advent_service: AdventServiceDep, session: SessionResponse = Depends(require_session)
) -> list[Advent]:
    other_user = get_other_user_type(session.user_type)
    return await advent_service.list_advents_uploaded_by(other_user)


@router.get("/today", summary="Get Today's Advent Items", response_model=list[Advent])
async def get_today_advent_items(
    advent_service: AdventServiceDep,
    session: SessionResponse = Depends(require_session),
) -> list[Advent]:
    today_day = utc_now().day
    other_user = get_other_user_type(session.user_type)
    return await advent_service.get_advent_by_day(today_day, other_user)


@router.get("/day/{advent_day}", summary="Get Advent Item by Day", response_model=list[Advent])
async def get_advent_items_by_day(
    advent_service: AdventServiceDep,
    advent_day: int,
    session: SessionResponse = Depends(require_session),
) -> list[Advent]:
    return await advent_service.get_advent_by_day(advent_day, session.user_type)


@router.get("/{id}", summary="Get Advent Item by ID", response_model=Advent | None)
async def get_advent_item_by_id(id: str, advent_service: AdventServiceDep) -> Advent | None:
    return await advent_service.get_advent_by_id(id)


@router.post("/", summary="Create Advent Item")
async def create_advent_item(
    advent_service: AdventServiceDep,
    day: int = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    type: AdventType = Form(...),
    image: UploadFile = File(...),
    session: SessionResponse = Depends(require_session),
) -> Advent:
    advent = AdventCreate(
        day=day, uploaded_by=session.user_type, title=title, description=description, type=type
    )
    return await advent_service.create_advent(advent, image)


@router.delete("/{id}", summary="Delete Advent Item by ID")
async def delete_advent_item_by_id(id: str, advent_service: AdventServiceDep) -> dict[str, str]:
    await advent_service.delete_advent_by_id(id)
    return {"detail": f"Advent item with ID {id} has been deleted"}
