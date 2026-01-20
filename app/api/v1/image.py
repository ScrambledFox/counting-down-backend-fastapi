from typing import Annotated

from fastapi import Depends, File, UploadFile
from fastapi.responses import StreamingResponse

from app.api.routing import make_router
from app.core.auth import require_session
from app.schemas.v1.advent import Advent, AdventCreate
from app.schemas.v1.exceptions import NotFoundException
from app.schemas.v1.session import SessionResponse
from app.services.advent import AdventService
from app.services.image import ImageService
from app.util.user import get_other_user_type

router = make_router()

ImageServiceDep = Annotated[ImageService, Depends()]
AdventServiceDep = Annotated[AdventService, Depends()]


@router.get("/images/for_me", summary="Get Images for Me", dependencies=[Depends(require_session)])
async def get_images_for_me(
    advent: AdventServiceDep, user_info: Annotated[SessionResponse, Depends(require_session)]
) -> list[Advent]:
    advents = await advent.list_advents_uploaded_by(get_other_user_type(user_info.user_type))
    return advents


@router.get("/images/by_me", summary="Get Images by Me", dependencies=[Depends(require_session)])
async def get_images_by_me(
    advent: AdventServiceDep, user_info: Annotated[SessionResponse, Depends(require_session)]
):
    advents = await advent.list_advents_uploaded_by(user_info.user_type)
    return advents


@router.get(
    "/image-metadata/{id}", summary="Get Image Metadata", dependencies=[Depends(require_session)]
)
async def get_image_metadata(
    id: str,
    advent: AdventServiceDep,
):
    metadata = await advent.get_advent_by_id(id)
    if metadata is None:
        raise NotFoundException("Image Metadata", id)
    return metadata


@router.post("/image-metadata/", summary="Create Image Metadata")
async def create_image_metadata(
    advent_data: AdventCreate,
    advent: AdventServiceDep,
    image: UploadFile = File(...),
):
    created_advent = await advent.create_advent(advent_data, image)
    return created_advent


@router.get("/images/{key}", summary="Get Image Item", dependencies=[Depends(require_session)])
async def get_image_item(
    key: str,
    service: ImageServiceDep,
) -> StreamingResponse:
    data = await service.get_image_bytes_by_key(key)
    if data is None:
        raise NotFoundException("Image", key)

    return StreamingResponse(content=iter([data]), media_type="image/jpeg")


@router.post("/images/{key}", summary="Upload Image Item")
async def upload_image_item(
    key: str,
    service: ImageServiceDep,
    file: UploadFile = File(...),
):
    content_type = file.content_type
    data = await file.read()
    await service.upload_image_bytes(key, data, content_type)
    return {"message": "Image uploaded successfully"}


@router.post(
    "/image-thumbnails/{key}",
    summary="Request Thumbnail Generation",
    dependencies=[Depends(require_session)],
)
async def request_thumbnail_generation(
    key: str,
    service: ImageServiceDep,
):
    if await service.get_thumbnail_bytes_by_key(key) is not None:
        return {"message": "Thumbnail already exists"}
    await service.request_thumbnail_generation(key)
    return {"message": "Thumbnail generation requested successfully"}


@router.get(
    "/image-thumbnails/{key}",
    summary="Get Thumbnail Image",
    dependencies=[Depends(require_session)],
)
async def get_thumbnail_image(
    key: str,
    service: ImageServiceDep,
) -> StreamingResponse:
    data = await service.get_thumbnail_bytes_by_key(key)
    if data is None:
        raise NotFoundException("Thumbnail Image", key)

    return StreamingResponse(content=iter([data]), media_type="image/jpeg")
