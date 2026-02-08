from typing import Annotated

from fastapi import Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from app.api.routing import make_router
from app.core.auth import require_session
from app.schemas.v1.exceptions import NotFoundException
from app.schemas.v1.image_metadata import ImageMetadata, ImageMetadataCreate
from app.schemas.v1.session import SessionResponse
from app.schemas.v1.user import UserType
from app.services.image import ImageService

router = make_router(prefix="/images")

ImageServiceDependency = Annotated[ImageService, Depends()]


def _parse_image_metadata_form(
    uploaded_by: Annotated[UserType, Form(...)],
    title: Annotated[str, Form()] = "New Image",
    description: Annotated[str, Form()] = "",
    image_tags: Annotated[list[str] | None, Form()] = None,
) -> ImageMetadataCreate:
    return ImageMetadataCreate(
        uploaded_by=uploaded_by,
        title=title,
        description=description,
        image_tags=image_tags or [],
    )


# ------------------------------------
# General Image Endpoints
# ------------------------------------


@router.get("/for_me", summary="Get Images for Me", dependencies=[Depends(require_session)])
async def get_images_for_me(
    img_service: ImageServiceDependency,
    user_info: Annotated[SessionResponse, Depends(require_session)],
) -> list[ImageMetadata]:
    return await img_service.list_images_by_uploader(user_info.get_other_user())


@router.get("/by_me", summary="Get Images by Me", dependencies=[Depends(require_session)])
async def get_images_by_me(
    img_service: ImageServiceDependency,
    user_info: Annotated[SessionResponse, Depends(require_session)],
):
    return await img_service.list_images_by_uploader(user_info.user_type)


@router.get("/{id}/meta", summary="Get Image Metadata", dependencies=[Depends(require_session)])
async def get_image_metadata(
    id: str,
    img_service: ImageServiceDependency,
):
    metadata = await img_service.get_image_by_id(id)
    if metadata is None:
        raise NotFoundException("Image Metadata", id)
    return metadata


@router.post("/", summary="Create Image")
async def create_image_metadata(
    image_meta: Annotated[ImageMetadataCreate, Depends(_parse_image_metadata_form)],
    img_service: ImageServiceDependency,
    image: UploadFile = File(...),
):
    return await img_service.create_image(image_meta, image)


# ------------------------------------
# Image Data Endpoints
# ------------------------------------


@router.get("/{image_key}", summary="Get Image Item", dependencies=[Depends(require_session)])
async def get_image_item(
    image_key: str,
    service: ImageServiceDependency,
) -> StreamingResponse:
    data = await service.get_image_bytes_by_key(image_key)
    if data is None:
        raise NotFoundException("Image", image_key)

    return StreamingResponse(content=iter([data]), media_type="image/jpeg")


# ------------------------------------
# Thumbnail Endpoints
# ------------------------------------


@router.post(
    "/{image_key}/thumbnail",
    summary="Request Thumbnail Generation",
    dependencies=[Depends(require_session)],
)
async def request_thumbnail_generation(
    image_key: str,
    service: ImageServiceDependency,
):
    if await service.get_thumbnail_bytes_by_key(image_key) is not None:
        return {"message": "Thumbnail already exists"}
    await service.request_thumbnail_generation(image_key)
    return {"message": "Thumbnail generation requested successfully"}


@router.get(
    "/{image_key}/thumbnail",
    summary="Get Thumbnail Image",
    dependencies=[Depends(require_session)],
)
async def get_thumbnail_image(
    image_key: str,
    service: ImageServiceDependency,
) -> StreamingResponse:
    data = await service.get_thumbnail_bytes_by_key(image_key)
    if data is None:
        raise NotFoundException("Thumbnail Image", image_key)

    return StreamingResponse(content=iter([data]), media_type="image/jpeg")
