from typing import Annotated

from fastapi import Depends

from app.core.config import settings
from app.db.mongo_client import get_db
from app.models.mongo import AsyncDB
from app.schemas.v1.session import Session
from app.util.time import utc_now


class SessionRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._sessions = db[settings.sessions_collection_name]

    async def delete_expired_sessions(self) -> int:
        result = await self._sessions.delete_many({"expires_at": {"$lt": utc_now()}})
        return result.deleted_count

    async def invalidate_all_sessions(self) -> int:
        result = await self._sessions.delete_many({})
        return result.deleted_count

    async def invalidate_session_with_id(self, session_id: str) -> int:
        result = await self._sessions.delete_one({"session_id": session_id})
        return result.deleted_count

    async def count_active_sessions(self) -> int:
        return await self._sessions.count_documents({"expires_at": {"$gt": utc_now()}})

    async def get_session_by_id(self, session_id: str) -> Session | None:
        doc = await self._sessions.find_one(
            {"session_id": session_id, "expires_at": {"$gt": utc_now()}}
        )
        return Session.model_validate(doc) if doc else None

    async def get_session_by_access_key(self, access_key: str) -> Session | None:
        doc = await self._sessions.find_one(
            {"user_type": access_key, "expires_at": {"$gt": utc_now()}}
        )
        return Session.model_validate(doc) if doc else None

    async def create_session(self, session_data: Session) -> Session:
        result = await self._sessions.insert_one(
            session_data.model_dump(by_alias=True, exclude_none=True)
        )
        doc = await self._sessions.find_one({"_id": result.inserted_id})
        return Session.model_validate(doc)
