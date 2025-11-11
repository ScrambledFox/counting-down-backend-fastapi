from datetime import datetime as dt

from pydantic import BaseModel


class Message(BaseModel):
    id: str | None = None
    sender: str | None = None
    message: str
    created_at: dt
    deleted_at: dt | None = None

class MessageCreate(BaseModel):
    sender: str | None = None
    message: str