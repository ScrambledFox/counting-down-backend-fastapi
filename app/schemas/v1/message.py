from datetime import datetime as dt

from app.schemas.v1.base import CustomModel, DefaultMongoIdField


class Message(CustomModel):
    id: DefaultMongoIdField = None
    sender: str | None = None
    message: str
    created_at: dt
    deleted_at: dt | None = None


class MessageCreate(CustomModel):
    sender: str | None = None
    message: str
