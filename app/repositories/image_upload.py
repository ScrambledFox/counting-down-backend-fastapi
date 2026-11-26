"""Pending direct-to-S3 uploads.

Issuing an upload form records ``{_id: <image key>, owner, purpose, content_type}``. Finishing
the upload atomically removes the record, so each upload can be turned into exactly one gallery
image or advent item, and only by the person who requested it. Unfinished records expire through
a TTL index; any orphaned object stays private in S3.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends

from app.core.config import get_settings
from app.db.mongo_client import get_db
from app.models.mongo import AsyncDB
from app.schemas.v1.user import UserType

settings = get_settings()


class ImageUploadRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.image_uploads_collection_name]

    async def create(
        self,
        *,
        key: str,
        owner: UserType,
        purpose: str,
        content_type: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        await self._collection.insert_one(
            {
                "_id": key,
                "owner": owner.value,
                "purpose": purpose,
                "content_type": content_type,
                "created_at": created_at,
                "expires_at": expires_at,
            }
        )

    async def get(self, key: str, owner: UserType, purpose: str) -> dict[str, Any] | None:
        return await self._collection.find_one(
            {"_id": key, "owner": owner.value, "purpose": purpose}
        )

    async def consume(self, key: str, owner: UserType, purpose: str) -> bool:
        removed = await self._collection.find_one_and_delete(
            {"_id": key, "owner": owner.value, "purpose": purpose}
        )
        return removed is not None


async def ensure_image_upload_indexes(db: AsyncDB) -> None:
    # Records outlive the form by a day so a slow upload can still be finished.
    await db[settings.image_uploads_collection_name].create_index(
        "expires_at", expireAfterSeconds=24 * 60 * 60
    )
