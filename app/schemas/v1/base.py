from datetime import datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, BeforeValidator, Field

from app.models.db import Document


def datetime_to_utc_str(dt: datetime) -> str:
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))

    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def validate_mongo_id(v: Any) -> str:
    if isinstance(v, ObjectId):
        v = str(v)

    if v is None:
        return v

    if not isinstance(v, str):
        raise TypeError("MongoId must be a string or ObjectId")
    if len(v) != 24:
        raise ValueError("MongoId must be 24 characters long")
    return v


MongoId = Annotated[str, BeforeValidator(validate_mongo_id)]
DefaultMongoIdField = Annotated[MongoId | None, Field(alias="_id", default=None)]


class CustomModel(BaseModel):
    model_config = {
        "populate_by_name": True,
    }

    def serialize(self) -> Document:
        default_dict = self.model_dump()
        return jsonable_encoder(default_dict)
