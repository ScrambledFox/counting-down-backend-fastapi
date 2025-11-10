from datetime import datetime

from pydantic import BaseModel, Field


class Todo(BaseModel):
    id: str | None = Field(None, description="MongoDB document id as string")
    title: str
    category: str
    completed: bool = False
    created_at: datetime | None = Field(None, alias="createdAt")
    updated_at: datetime | None = Field(None, alias="updatedAt")
