from datetime import datetime

from pydantic import BaseModel, Field


class TodoItem(BaseModel):
    id: str | None = Field(None, description="MongoDB document id as string")
    title: str
    category: str
    completed: bool = False
    created_at: datetime | None = Field(None, alias="createdAt")
    updated_at: datetime | None = Field(None, alias="updatedAt")

class TodoItemCreate(TodoItem):
    id: None = None
    created_at: None = None
    updated_at: None = None
