from io import BytesIO

from PIL import Image


def create_thumbnail(image_data: bytes, size: int) -> bytes:
    with Image.open(BytesIO(image_data)) as img:
        img.thumbnail((size, size))
        output = BytesIO()
        img.save(output, format=img.format)
        return output.getvalue()


def get_thumbnail_name(original_name: str, size: int) -> str:
    size_str = f"{size}x{size}"
    return f"{original_name}_{size_str}"
