from io import BytesIO

from PIL import Image


def create_thumbnail(image_data: bytes, size: tuple[int, int]) -> bytes:
    with Image.open(BytesIO(image_data)) as img:
        img.thumbnail(size)
        output = BytesIO()
        img.save(output, format=img.format)
        return output.getvalue()
