from typing import Annotated

from fastapi import Depends
from fastapi.responses import StreamingResponse

from app.api.routing import make_router
from app.schemas.v1.exceptions import NotFoundException
from app.services.image import ImageService

router = make_router()

ImageServiceDep = Annotated[ImageService, Depends()]


@router.get("/{key:path}", summary="Get Image Item")
async def get_image_item(key: str, service: ImageServiceDep) -> StreamingResponse:
    data = await service.get_image_bytes_by_key(key)
    if data is None:
        raise NotFoundException("Image", key)

    return StreamingResponse(content=iter([data]), media_type="image/jpeg")
