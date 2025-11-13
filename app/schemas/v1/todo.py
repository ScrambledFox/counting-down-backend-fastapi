from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.v1.base import CustomModel, MongoId


class Todo(CustomModel):
    id: MongoId | None = Field(default=None, alias="_id")
    title: str
    category: str
    completed: bool
    created_at: datetime
    updated_at: datetime | None = None


class TodoUpdate(CustomModel):
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
