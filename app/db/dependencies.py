from app.db.client import AsyncDB, get_db


async def get_db_dep() -> AsyncDB:
    return await get_db()
