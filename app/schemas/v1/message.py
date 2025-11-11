from datetime import datetime as dt

from pydantic import BaseModel


class Message(BaseModel):
    id: str | None = None
    sender: str
    message: str
    created_at: dt
    deleted_at: dt | None = None

class MessageCreate(BaseModel):
    sender: str
    message: str