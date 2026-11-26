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
    thumbnail_sizes_ready: list[int] = Field(default_factory=list)


class ImageMetadataCreate(ImageMetadataBase):
    """Model for creating image metadata."""

    pass


class ImageMetadataUpdate(BaseModel):
    """Model for updating image metadata."""

    title: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=500)
    image_tags: list[str] | None = None


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


class ImageUploadPurpose(str, Enum):
    GALLERY = "gallery"
    ADVENT = "advent"


class ImageUploadRequest(BaseModel):
    """Ask for a direct-to-S3 upload form."""

    purpose: ImageUploadPurpose = ImageUploadPurpose.GALLERY
    content_type: str = Field(..., pattern=r"^image/[a-z0-9.+-]{1,50}$")
    size_bytes: int = Field(..., gt=0)


class UploadFormField(BaseModel):
    name: str
    value: str


class ImageUploadTicket(BaseModel):
    """A one-time S3 form upload: POST ``fields`` in order, then the file, to ``url``.

    Fields are name/value pairs rather than an object so that client-side key conversion (the
    frontend camel-cases response keys) can never rename S3's signed form fields.
    """

    upload_key: str
    url: str
    fields: list[UploadFormField]
    expires_at: datetime
    max_bytes: int


class ImageFromUploadCreate(ImageMetadataBase):
    """Create gallery image metadata for a finished direct upload."""

    upload_key: str = Field(..., min_length=1, max_length=100)
