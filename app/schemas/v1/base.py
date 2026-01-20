from datetime import UTC, datetime
from typing import Annotated, Any, cast
from zoneinfo import ZoneInfo

from bson import ObjectId
from pydantic import (
    AliasChoices,
    BaseModel,
    BeforeValidator,
    Field,
    WithJsonSchema,
    model_validator,
)

from app.models.mongo import Document


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


def _to_object_id(v: Any) -> ObjectId | None:
    if v is None:
        return None
    if isinstance(v, ObjectId):
        return v
    if isinstance(v, str):
        if len(v) != 24:
            raise ValueError("MongoId string must be 24 characters long")
        return ObjectId(v)
    raise TypeError("MongoId must be a string or ObjectId")


def to_mongo_object_id(v: Any) -> ObjectId | None:
    return _to_object_id(v)


MongoId = Annotated[
    str,
    BeforeValidator(validate_mongo_id),
    WithJsonSchema({"type": "string", "pattern": "^[a-fA-F0-9]{24}$"}),
]

DefaultMongoIdField = Annotated[
    MongoId | None, Field(validation_alias=AliasChoices("_id", "id"), default=None)
]


class CustomModel(BaseModel):
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
    }

    def serialize(self) -> Document:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)
    
    @model_validator(mode="before")
    @classmethod
    def normalize_datetimes(cls, data: Any) -> Any:
        def fix(v: Any) -> Any:
            if isinstance(v, datetime):
                if v.tzinfo is None:
                    return v.replace(tzinfo=UTC)
                return v.astimezone(UTC)

            if isinstance(v, list):
                items = cast(list[Any], v)
                return [fix(x) for x in items]

            if isinstance(v, dict):
                d = cast(dict[str, Any], v)  # Pydantic input dicts are typically str-keyed
                return {k: fix(x) for k, x in d.items()}

            return v

        return fix(data)
