from datetime import datetime

from pydantic import BaseModel

from app.core.time import utc_now
from app.schemas.v1.todo import TodoCreate


class TodoModel(BaseModel):
    title: str
    category: str
    completed: bool
    created_at: datetime
    updated_at: datetime | None

    @classmethod
    def from_dict(cls, data: TodoCreate):
        now = utc_now()
        return cls(
            title=data.title.strip(),
            category=data.category.strip(),
            completed=data.completed,
            created_at=now,
            updated_at=None,
        )
