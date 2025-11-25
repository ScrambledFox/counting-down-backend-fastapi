from datetime import datetime
from enum import Enum

from app.schemas.v1.base import CustomModel, DefaultMongoIdField


class ImageActor(str, Enum):
    JORIS = "Joris"
    DANFENG = "Danfeng"
    BOTH = "Both"
    UNDEFINED = "Undefined"


class AdventBase(CustomModel):
    advent_day: int
    actor: ImageActor
    sensitive: bool


class AdventRef(AdventBase):
    id: DefaultMongoIdField = None
    image_key: str
    content_type: str | None
    uploaded_at: datetime


class AdventRefCreate(AdventBase):
    pass
