from typing import Annotated

from fastapi import Depends, File, Form, UploadFile

from app.api.routing import make_router
from app.schemas.v1.advent import AdventRef, AdventRefCreate, ImageActor
from app.services.advent import AdventService

router = make_router()

AdventServiceDep = Annotated[AdventService, Depends()]


@router.post("/", summary="Create Advent Item")
async def create_advent_item(
    advent_service: AdventServiceDep,
    advent_day: int = Form(...),
    actor: ImageActor = Form(...),
    sensitive: bool = Form(...),
    image: UploadFile = File(...),
) -> AdventRef:
    advent = AdventRefCreate(advent_day=advent_day, actor=actor, sensitive=sensitive)
    return await advent_service.create_advent_ref(advent, image)


@router.get("/", summary="List Advent Items", response_model=list[AdventRef])
async def list_advent_items(advent_service: AdventServiceDep) -> list[AdventRef]:
    return await advent_service.list_advent_refs()


@router.get("/day/{advent_day}", summary="Get Advent Item by Day", response_model=list[AdventRef])
async def get_advent_items_by_day(
    advent_service: AdventServiceDep, advent_day: int, actor: ImageActor | None = None
) -> list[AdventRef]:
    return await advent_service.get_advent_ref_by_day(advent_day, actor)


@router.get("/{id}", summary="Get Advent Item by ID", response_model=AdventRef | None)
async def get_advent_item_by_id(id: str, advent_service: AdventServiceDep) -> AdventRef | None:
    return await advent_service.get_advent_ref_by_id(id)
