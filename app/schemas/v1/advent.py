from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator

from app.schemas.v1.base import CustomModel, DefaultMongoIdField
from app.schemas.v1.user import UserType


class AdventType(StrEnum):
    SPICY = "spicy"
    CUTE = "cute"
    FUNNY = "funny"
    HOT = "hot"


class AdventBase(CustomModel):
    day: int
    uploaded_by: UserType
    title: str = Field(default="New Advent", max_length=100)
    description: str = Field(default="", max_length=500)
    type: AdventType

    @field_validator("day")
    def validate_day(cls, v: int) -> int:
        if not (1 <= v <= 31):
            raise ValueError("Day must be between 1 and 31")
        return v


class Advent(AdventBase):
    id: DefaultMongoIdField = None
    image_key: str
    content_type: str | None
    uploaded_at: datetime


class AdventCreate(AdventBase):
    pass
