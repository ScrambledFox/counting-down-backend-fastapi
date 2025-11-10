from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.dependencies import get_db
from app.repositories.todos import TodoRepository


async def get_todo_repo(
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> TodoRepository:
    return TodoRepository(db)
