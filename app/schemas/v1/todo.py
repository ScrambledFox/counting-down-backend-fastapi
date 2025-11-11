from datetime import datetime

from pydantic import BaseModel, field_validator


class Todo(BaseModel):
    id: str | None = None
    title: str
    category: str
    completed: bool
    created_at: datetime
    updated_at: datetime | None = None


class TodoUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    completed: bool | None = None

    @field_validator("title", "category")
    def not_empty(cls, v: str | None) -> str | None:
        if v is not None:
            v2 = v.strip()
            if not v2:
                raise ValueError("Must not be empty or whitespace")
            return v2
        return v


class TodoCreate(BaseModel):
    title: str
    category: str
    completed: bool = False

    @field_validator("title", "category")
    def not_empty(cls, v: str) -> str:
        v2 = v.strip()
        if not v2:
            raise ValueError("Must not be empty or whitespace")
        return v2
