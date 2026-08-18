from typing import Annotated, Any

from fastapi import Depends
from pymongo import ASCENDING, ReturnDocument

from app.core.config import get_settings
from app.db.mongo_client import AsyncDB, get_db
from app.schemas.v1.relationship_profile import RelationshipProfile, RelationshipProfileUpdate
from app.schemas.v1.user import UserType
from app.util.time import utc_now

settings = get_settings()
SINGLETON_KEY = "PRIMARY"


class RelationshipProfileRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.relationship_profile_collection_name]

    async def get(self) -> RelationshipProfile | None:
        document = await self._collection.find_one({"singleton_key": SINGLETON_KEY})
        return RelationshipProfile.model_validate(document) if document else None

    async def save(
        self, profile: RelationshipProfileUpdate, updated_by: UserType
    ) -> RelationshipProfile:
        now = utc_now()
        data: dict[str, Any] = profile.model_dump(mode="json")
        data.update({"updated_by_user_type": updated_by, "updated_at": now})
        document = await self._collection.find_one_and_update(
            {"singleton_key": SINGLETON_KEY},
            {
                "$set": data,
                "$setOnInsert": {"singleton_key": SINGLETON_KEY, "created_at": now},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return RelationshipProfile.model_validate(document)

    async def ensure_indexes(self) -> None:
        await self._collection.create_index(
            [("singleton_key", ASCENDING)], unique=True, name="one_relationship_profile"
        )


async def ensure_relationship_profile_indexes(db: AsyncDB) -> None:
    await RelationshipProfileRepository(db).ensure_indexes()
