from typing import Annotated

from fastapi import Depends, File, UploadFile
from fastapi.responses import StreamingResponse

from app.api.routing import make_router
from app.core.auth import require_session
from app.schemas.v1.exceptions import NotFoundException
from app.services.image import ImageService

router = make_router()

ImageServiceDep = Annotated[ImageService, Depends()]


@router.get("/{key}", summary="Get Image Item", dependencies=[Depends(require_session)])
async def get_image_item(
    key: str,
    service: ImageServiceDep,
) -> StreamingResponse:
    data = await service.get_image_bytes_by_key(key)
    if data is None:
        raise NotFoundException("Image", key)

    return StreamingResponse(content=iter([data]), media_type="image/jpeg")


@router.post("/{key}", summary="Upload Image Item")
async def upload_image_item(
    key: str,
    service: ImageServiceDep,
    file: UploadFile = File(...),
):
    content_type = file.content_type
    data = await file.read()
    await service.upload_image_bytes(key, data, content_type)
    return {"message": "Image uploaded successfully"}


@router.post("/thumbnail/{key}", summary="Request Thumbnail Generation")
async def request_thumbnail_generation(
    key: str,
    service: ImageServiceDep,
):
    await service.request_thumbnail_generation(key)
    return {"message": "Thumbnail generation requested successfully"}


@router.get(
    "/thumbnail/{key}", summary="Get Thumbnail Image", dependencies=[Depends(require_session)]
)
async def get_thumbnail_image(
    key: str,
    service: ImageServiceDep,
) -> StreamingResponse:
    data = await service.get_thumbnail_bytes_by_key(key)
    if data is None:
        raise NotFoundException("Thumbnail Image", key)

    return StreamingResponse(content=iter([data]), media_type="image/jpeg")
