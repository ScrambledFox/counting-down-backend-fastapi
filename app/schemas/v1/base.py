from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from app.models.db import Document


def datetime_to_utc_str(dt: datetime) -> str:
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))

    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


class CustomModel(BaseModel):
    model_config = {
        "json_encoders": {datetime: datetime_to_utc_str},
        "populate_by_name": True,
    }

    def serialize(self) -> Document:
        default_dict = self.model_dump()
        return jsonable_encoder(default_dict)
