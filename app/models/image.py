from typing import Any

from pydantic import BaseModel, HttpUrl


class Image(BaseModel):
    key: str
    url: HttpUrl
    width: int
    height: int
    format: str
    size: int  # size in bytes

    class Config:
        schema_extra: dict[str, Any] = {
            "example": {
                "key": "images/sample.jpg",
                "url": "https://cdn.example.com/images/sample.jpg",
                "width": 1920,
                "height": 1080,
                "format": "jpeg",
                "size": 204800,
            }
        }
