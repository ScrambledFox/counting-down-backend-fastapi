import base64
import binascii
import json
from datetime import UTC, datetime
from io import BytesIO

from bson import ObjectId
from PIL import Image, ImageOps

from app.schemas.v1.exceptions import BadRequestException
from app.schemas.v1.image import ImageCursorPayload


def create_thumbnail(image_data: bytes, size: int) -> tuple[bytes, str]:
    """
    Create a thumbnail from the given image data while preserving aspect ratio.

    Args:
        image_data: The original image data as bytes
        size: The maximum size of the thumbnail's width and height.

    Returns:
        A tuple containing the thumbnail image data as bytes and the image format
        (e.g., "JPEG", "PNG").
    """
    with Image.open(BytesIO(image_data)) as img:
        img_format = img.format or "JPEG"
        # Normalize orientation using EXIF data if present to avoid unexpected rotations
        normalized = ImageOps.exif_transpose(img)
        normalized.thumbnail((size, size))
        output = BytesIO()
        normalized.save(output, format=img_format)
        return output.getvalue(), img_format


def get_thumbnail_name(original_name: str, size: int) -> str:
    size_str = f"{size}x{size}"
    return f"{original_name}_{size_str}"


def encode_image_cursor(created_at: datetime, image_id: str) -> str:
    created_at_utc = (
        created_at.astimezone(UTC) if created_at.tzinfo else created_at.replace(tzinfo=UTC)
    )
    payload = {"created_at": created_at_utc.isoformat(), "id": image_id}
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_image_cursor(cursor: str) -> ImageCursorPayload:
    try:
        padding = "=" * (-len(cursor) % 4)
        decoded = base64.urlsafe_b64decode(cursor + padding)
        payload: dict[str, object] = json.loads(decoded.decode("utf-8"))

        created_at_value = payload.get("created_at")
        image_id = payload.get("id")

        if not isinstance(created_at_value, str) or not isinstance(image_id, str):
            raise ValueError("Cursor payload is missing required fields")

        created_at = datetime.fromisoformat(created_at_value)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        else:
            created_at = created_at.astimezone(UTC)

        if not ObjectId.is_valid(image_id):
            raise ValueError("Invalid image id")

        return ImageCursorPayload(created_at=created_at, id=image_id)
    except (ValueError, TypeError, json.JSONDecodeError, binascii.Error) as exc:
        raise BadRequestException("Invalid cursor") from exc
