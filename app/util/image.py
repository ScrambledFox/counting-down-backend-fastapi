from io import BytesIO

from PIL import Image, ImageOps


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
