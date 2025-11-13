from datetime import datetime as dt

from pydantic import Field

from app.schemas.v1.base import CustomModel, MongoId


class Message(CustomModel):
    id: MongoId | None = Field(default=None, alias="_id")
    sender: str | None = None
    message: str
    created_at: dt
    deleted_at: dt | None = None


class MessageCreate(CustomModel):
    sender: str | None = None
    message: str
