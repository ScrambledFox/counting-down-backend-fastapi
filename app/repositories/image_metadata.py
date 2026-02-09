from typing import Annotated, Any

from bson import ObjectId
from fastapi import Depends

from app.core.config import get_settings
from app.db.mongo_client import get_db
from app.models.mongo import AsyncDB
from app.schemas.v1.base import MongoId
from app.schemas.v1.image_metadata import ImageCursorPayload, ImageMetadata, ImageMetadataUpdate
from app.schemas.v1.user import UserType
from app.util.time import utc_now

settings = get_settings()


class ImageMetadataRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.image_metadata_collection_name]

    async def create_image_metadata(self, metadata: ImageMetadata) -> ImageMetadata:
        result = await self._collection.insert_one(
            metadata.model_dump(by_alias=True, exclude_none=True)
        )
        doc = await self._collection.find_one({"_id": result.inserted_id})
        return ImageMetadata.model_validate(doc)

    async def get_by_user_type(self, user_type: UserType) -> list[ImageMetadata]:
        cursor = self._collection.find({"uploaded_by": user_type, "deleted_at": None}).sort(
            [("uploaded_at", -1)]
        )
        docs = await cursor.to_list(length=None)
        return [ImageMetadata.model_validate(doc) for doc in docs]

    async def get_image_metadata_by_id(self, metadata_id: MongoId) -> ImageMetadata | None:
        doc = await self._collection.find_one({"_id": ObjectId(metadata_id), "deleted_at": None})
        return ImageMetadata.model_validate(doc) if doc else None

    async def get_image_metadata_by_key(self, image_key: str) -> ImageMetadata | None:
        doc = await self._collection.find_one({"image_key": image_key, "deleted_at": None})
        return ImageMetadata.model_validate(doc) if doc else None

    async def list_image_metadata_page(
        self, limit: int, cursor: ImageCursorPayload | None, user_filter: UserType | None = None
    ) -> list[ImageMetadata]:
        # Index required for keyset pagination (created_at stored as uploaded_at):
        # db.images.createIndex({ uploaded_at: -1, _id: -1 })
        query: dict[str, Any] = {"deleted_at": None}

        if user_filter is not None:
            query["uploaded_by"] = user_filter

        if cursor is not None:
            query = {
                "$and": [
                    query,
                    {
                        "$or": [
                            {"uploaded_at": {"$lt": cursor.created_at}},
                            {
                                "uploaded_at": cursor.created_at,
                                "_id": {"$lt": ObjectId(cursor.id)},
                            },
                        ]
                    },
                ]
            }

        cursor_query = (
            self._collection.find(query).sort([("uploaded_at", -1), ("_id", -1)]).limit(limit)
        )
        docs = await cursor_query.to_list(length=limit)
        return [ImageMetadata.model_validate(doc) for doc in docs]

    async def update_image_metadata(
        self, metadata_id: MongoId, metadata_update: ImageMetadataUpdate
    ) -> ImageMetadata | None:
        update_data = metadata_update.model_dump(by_alias=True, exclude_none=True)
        result = await self._collection.update_one(
            {"_id": ObjectId(metadata_id), "deleted_at": None}, {"$set": update_data}
        )
        if result.matched_count == 0:
            return None
        doc = await self._collection.find_one({"_id": ObjectId(metadata_id), "deleted_at": None})
        return ImageMetadata.model_validate(doc) if doc else None

    async def soft_delete_image_metadata(self, metadata_id: MongoId) -> bool:
        # Soft delete by setting deleted_at timestamp instead of removing the document
        result = await self._collection.update_one(
            {"_id": ObjectId(metadata_id), "deleted_at": None}, {"$set": {"deleted_at": utc_now()}}
        )
        return result.matched_count > 0
