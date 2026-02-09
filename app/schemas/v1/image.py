from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.v1.base import DefaultMongoIdField, MongoId
from app.schemas.v1.user import UserType
from app.util.time import utc_now


class ImageThumbnailSizes(int, Enum):
    MEDIUM = 128
    XL = 1200


class ImageMetadataBase(BaseModel):
    """Base model for image metadata."""

    uploaded_by: UserType
    title: str = Field("New Image", max_length=100)
    description: str = Field("", max_length=500)
    image_tags: list[str] = Field(default_factory=list)


class ImageMetadata(ImageMetadataBase):
    """Image metadata model."""

    id: DefaultMongoIdField = None
    image_key: str
    media_type: str | None
    uploaded_at: datetime = Field(default_factory=utc_now)
    deleted_at: datetime | None = None


class ImageMetadataUpdate(BaseModel):
    """Model for updating image metadata."""

    title: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=500)
    image_tags: list[str] | None = None
    deleted_at: datetime | None = None


class ImageMetadataCreate(ImageMetadataBase):
    """Model for creating image metadata."""

    pass


class ImageCursorPayload(BaseModel):
    """Cursor payload for keyset pagination."""

    created_at: datetime
    id: MongoId


class ImageMetadataResponse(ImageMetadata):
    """Response model for image metadata."""

    url: str
    thumbnail_url: str | None = None
    thumbnail_xl_url: str | None = None


class ImagePageResponse(BaseModel):
    """Response model for keyset pagination."""

    items: list[ImageMetadataResponse]
    next_cursor: str | None = None


class ImagePresignedUrlResponse(BaseModel):
    """Response model for S3 presigned image URLs."""

    image_key: str
    url: str | None = None
    thumbnail_url: str | None = None
    thumbnail_xl_url: str | None = None
    expires_in: int
