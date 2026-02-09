from typing import Annotated

from fastapi import Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.api.routing import make_router
from app.core.auth import require_session
from app.core.config import get_settings
from app.schemas.v1.base import MongoId
from app.schemas.v1.exceptions import NotFoundException
from app.schemas.v1.image_metadata import (
    ImageMetadataCreate,
    ImageMetadataResponse,
    ImagePageResponse,
    ImagePresignedUrlResponse,
)
from app.schemas.v1.session import SessionResponse
from app.schemas.v1.user import UserType
from app.services.image import ImageService

router = make_router(prefix="/images")

settings = get_settings()

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


@router.get("", summary="List Images", dependencies=[Depends(require_session)])
async def list_images(
    img_service: ImageServiceDependency,
    limit: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
    cursor: str | None = Query(None),
) -> ImagePageResponse:
    items, next_cursor = await img_service.list_image_metadata_page(limit=limit, cursor=cursor)

    items_with_urls = [
        ImageMetadataResponse(
            **item.model_dump(),
            url=await img_service.get_image_presigned_url(item.image_key),
            thumbnail_url=await img_service.get_thumbnail_presigned_url(item.image_key),
        )
        for item in items
    ]

    return ImagePageResponse(items=items_with_urls, next_cursor=next_cursor)


@router.get("/for_me", summary="List Images for Me", dependencies=[Depends(require_session)])
async def get_images_for_me(
    img_service: ImageServiceDependency,
    user_info: Annotated[SessionResponse, Depends(require_session)],
    limit: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
    cursor: str | None = Query(None),
) -> ImagePageResponse:
    items, next_cursor = await img_service.list_image_metadata_page(
        limit=limit, cursor=cursor, user_filter=user_info.get_other_user()
    )
    items_with_urls = [
        ImageMetadataResponse(
            **item.model_dump(),
            url=await img_service.get_image_presigned_url(item.image_key),
            thumbnail_url=await img_service.get_thumbnail_presigned_url(item.image_key),
        )
        for item in items
    ]
    return ImagePageResponse(items=items_with_urls, next_cursor=next_cursor)


@router.get("/by_me", summary="List Images by Me", dependencies=[Depends(require_session)])
async def get_images_by_me(
    img_service: ImageServiceDependency,
    user_info: Annotated[SessionResponse, Depends(require_session)],
    limit: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
    cursor: str | None = Query(None),
) -> ImagePageResponse:
    items, next_cursor = await img_service.list_image_metadata_page(
        limit=limit, cursor=cursor, user_filter=user_info.user_type
    )
    items_with_urls = [
        ImageMetadataResponse(
            **item.model_dump(),
            url=await img_service.get_image_presigned_url(item.image_key),
            thumbnail_url=await img_service.get_thumbnail_presigned_url(item.image_key),
        )
        for item in items
    ]
    return ImagePageResponse(items=items_with_urls, next_cursor=next_cursor)


@router.get("/{id}/meta", summary="Get Image Metadata", dependencies=[Depends(require_session)])
async def get_image_metadata(
    id: MongoId,
    img_service: ImageServiceDependency,
) -> ImageMetadataResponse:
    metadata = await img_service.get_image_by_id(id)
    if metadata is None:
        raise NotFoundException("Image Metadata", id)

    url = await img_service.get_image_presigned_url(metadata.image_key)
    thumbnail_url = await img_service.get_thumbnail_presigned_url(metadata.image_key)

    return ImageMetadataResponse(**metadata.model_dump(), url=url, thumbnail_url=thumbnail_url)


@router.post("/", summary="Create Image")
async def create_image_metadata(
    image_meta: Annotated[ImageMetadataCreate, Depends(_parse_image_metadata_form)],
    img_service: ImageServiceDependency,
    image: UploadFile = File(...),
) -> ImageMetadataResponse:
    item = await img_service.create_image(image_meta, image)

    url = await img_service.get_image_presigned_url(item.image_key)
    thumbnail_url = await img_service.get_thumbnail_presigned_url(item.image_key)

    return ImageMetadataResponse(**item.model_dump(), url=url, thumbnail_url=thumbnail_url)


# ------------------------------------
# Image Data Endpoints
# ------------------------------------


@router.get("/{image_key}", summary="Get Image Data Bytes", dependencies=[Depends(require_session)])
async def get_image_item(
    image_key: str,
    image_service: ImageServiceDependency,
) -> StreamingResponse:
    data = await image_service.get_image_bytes_by_key(image_key)
    if data is None:
        raise NotFoundException("Image", image_key)

    meta = await image_service.get_metadata_by_image_key(image_key)
    media_type = meta.media_type if meta and meta.media_type else "image/jpeg"

    return StreamingResponse(content=iter([data]), media_type=media_type)


@router.get(
    "/{image_key}/url",
    summary="Get Image Presigned URL",
    dependencies=[Depends(require_session)],
)
async def get_image_presigned_url(
    image_key: str,
    service: ImageServiceDependency,
    expires_in: int | None = Query(None, ge=1, le=settings.aws_s3_max_presign_expires),
) -> ImagePresignedUrlResponse:
    # Check if image exists before generating presigned URL to avoid generating URLs for
    # non-existent images
    if not await service.get_image_exists_by_key(image_key):
        raise NotFoundException("Image", image_key)

    url = await service.get_image_presigned_url(image_key, expires_in)

    return ImagePresignedUrlResponse(
        image_key=image_key,
        url=url,
        expires_in=expires_in or settings.aws_s3_presign_expires,
    )


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

    # Thumbnails are always JPEGs, so we can hardcode the media type here
    return StreamingResponse(content=iter([data]), media_type="image/jpeg")


@router.get(
    "/{image_key}/thumbnail/url",
    summary="Get Thumbnail Presigned URL",
    dependencies=[Depends(require_session)],
)
async def get_thumbnail_presigned_url(
    image_key: str,
    service: ImageServiceDependency,
    expires_in: int = Query(
        settings.aws_s3_presign_expires, ge=1, le=settings.aws_s3_max_presign_expires
    ),
) -> ImagePresignedUrlResponse:
    if not await service.get_image_exists_by_key(image_key):
        raise NotFoundException("Image", image_key)

    url = await service.get_thumbnail_presigned_url(image_key, expires_in)

    return ImagePresignedUrlResponse(
        image_key=image_key,
        url=url,
        expires_in=expires_in,
    )
