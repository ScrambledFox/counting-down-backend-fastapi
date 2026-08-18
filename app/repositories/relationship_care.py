from collections.abc import Mapping
from typing import Annotated, Any

from bson import ObjectId
from fastapi import Depends
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.core.config import get_settings
from app.db.mongo_client import AsyncDB, get_db
from app.schemas.v1.base import MongoId
from app.schemas.v1.relationship_care import (
    AgreementAcceptance,
    AgreementResponse,
    AgreementResponseType,
    AgreementRevision,
    AgreementStatus,
    GoalVisibility,
    PersonalBoundary,
    PersonalGoal,
    RelationshipAgreement,
    RelationshipRequest,
)
from app.schemas.v1.user import UserType
from app.util.time import utc_now

settings = get_settings()


def _oid(value: MongoId | str) -> ObjectId:
    return ObjectId(value)


class _OwnedItemRepository[CareItem: (PersonalBoundary, RelationshipRequest, PersonalGoal)]:
    model: type[CareItem]

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    async def ensure_indexes(self) -> None:
        await self._collection.create_index(
            [("owner_user_type", ASCENDING), ("archived_at", ASCENDING), ("updated_at", DESCENDING)]
        )

    async def list_active(self) -> list[CareItem]:
        docs = (
            await self._collection.find({"archived_at": None})
            .sort("updated_at", DESCENDING)
            .to_list(length=None)
        )
        return [self.model.model_validate(doc) for doc in docs]

    async def list_archived_owned(self, owner: UserType) -> list[CareItem]:
        docs = (
            await self._collection.find(
                {
                    "owner_user_type": owner,
                    "archived_at": {"$exists": True, "$ne": None},
                }
            )
            .sort("archived_at", DESCENDING)
            .to_list(length=None)
        )
        return [self.model.model_validate(doc) for doc in docs]

    async def get_by_id(self, item_id: MongoId) -> CareItem | None:
        doc = await self._collection.find_one({"_id": _oid(item_id)})
        return self.model.model_validate(doc) if doc else None

    async def create(self, item: CareItem) -> CareItem:
        result = await self._collection.insert_one(item.serialize())
        doc = await self._collection.find_one({"_id": result.inserted_id})
        return self.model.model_validate(doc)

    async def update_owned(
        self, item_id: MongoId, owner: UserType, data: Mapping[str, Any]
    ) -> CareItem | None:
        doc = await self._collection.find_one_and_update(
            {"_id": _oid(item_id), "owner_user_type": owner, "archived_at": None},
            {"$set": {**dict(data), "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return self.model.model_validate(doc) if doc else None

    async def archive_owned(self, item_id: MongoId, owner: UserType) -> CareItem | None:
        now = utc_now()
        doc = await self._collection.find_one_and_update(
            {"_id": _oid(item_id), "owner_user_type": owner, "archived_at": None},
            {"$set": {"archived_at": now, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        return self.model.model_validate(doc) if doc else None

    async def restore_owned(self, item_id: MongoId, owner: UserType) -> CareItem | None:
        doc = await self._collection.find_one_and_update(
            {
                "_id": _oid(item_id),
                "owner_user_type": owner,
                "archived_at": {"$exists": True, "$ne": None},
            },
            {"$unset": {"archived_at": ""}, "$set": {"updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return self.model.model_validate(doc) if doc else None


class PersonalBoundaryRepository(_OwnedItemRepository[PersonalBoundary]):
    model = PersonalBoundary

    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        super().__init__(db[settings.relationship_boundaries_collection_name])


class RelationshipRequestRepository(_OwnedItemRepository[RelationshipRequest]):
    model = RelationshipRequest

    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        super().__init__(db[settings.relationship_requests_collection_name])


class PersonalGoalRepository(_OwnedItemRepository[PersonalGoal]):
    model = PersonalGoal

    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        super().__init__(db[settings.personal_goals_collection_name])

    async def ensure_indexes(self) -> None:
        await self._collection.create_index(
            [
                ("owner_user_type", ASCENDING),
                ("archived_at", ASCENDING),
                ("updated_at", DESCENDING),
            ]
        )
        await self._collection.create_index(
            [
                ("visibility", ASCENDING),
                ("archived_at", ASCENDING),
                ("updated_at", DESCENDING),
            ]
        )

    async def list_visible(self, current_user: UserType) -> list[PersonalGoal]:
        docs = (
            await self._collection.find(
                {
                    "archived_at": None,
                    "$or": [
                        {"owner_user_type": current_user},
                        {"visibility": GoalVisibility.SHARED_WITH_PARTNER},
                    ],
                }
            )
            .sort("updated_at", DESCENDING)
            .to_list(length=None)
        )
        return [PersonalGoal.model_validate(doc) for doc in docs]


class RelationshipAgreementRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.relationship_agreements_collection_name]

    async def ensure_indexes(self) -> None:
        await self._collection.create_index([("status", ASCENDING), ("updated_at", DESCENDING)])
        await self._collection.create_index(
            [("created_by_user_type", ASCENDING), ("status", ASCENDING)]
        )

    async def create(self, agreement: RelationshipAgreement) -> RelationshipAgreement:
        result = await self._collection.insert_one(agreement.serialize())
        doc = await self._collection.find_one({"_id": result.inserted_id})
        return RelationshipAgreement.model_validate(doc)

    async def get_by_id(self, agreement_id: MongoId) -> RelationshipAgreement | None:
        doc = await self._collection.find_one({"_id": _oid(agreement_id)})
        return RelationshipAgreement.model_validate(doc) if doc else None

    async def list_visible(
        self, user_type: UserType, *, include_archived: bool = False
    ) -> list[RelationshipAgreement]:
        visibility: list[dict[str, Any]] = [
            {"proposed_at": {"$exists": True, "$ne": None}},
            {"created_by_user_type": user_type},
        ]
        query: dict[str, Any] = {"$or": visibility}
        if not include_archived:
            query["status"] = {"$ne": AgreementStatus.ARCHIVED}
        docs = (
            await self._collection.find(query).sort("updated_at", DESCENDING).to_list(length=None)
        )
        return [RelationshipAgreement.model_validate(doc) for doc in docs]

    async def set_initial_revision(
        self, agreement_id: MongoId, revision_id: MongoId
    ) -> RelationshipAgreement | None:
        doc = await self._collection.find_one_and_update(
            {"_id": _oid(agreement_id), "current_revision_id": None},
            {
                "$set": {
                    "current_revision_id": revision_id,
                    "current_revision_number": 1,
                    "updated_at": utc_now(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return RelationshipAgreement.model_validate(doc) if doc else None

    async def set_status(
        self,
        agreement_id: MongoId,
        status: AgreementStatus,
        *,
        expected_revision_id: MongoId | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> RelationshipAgreement | None:
        query: dict[str, Any] = {"_id": _oid(agreement_id)}
        if expected_revision_id:
            query["current_revision_id"] = expected_revision_id
        data = {"status": status, "updated_at": utc_now(), **dict(extra or {})}
        doc = await self._collection.find_one_and_update(
            query, {"$set": data}, return_document=ReturnDocument.AFTER
        )
        return RelationshipAgreement.model_validate(doc) if doc else None

    async def replace_current_revision(
        self,
        agreement_id: MongoId,
        expected_revision_id: MongoId,
        revision_id: MongoId,
        revision_number: int,
        status: AgreementStatus,
        *,
        revisited_at: Any | None = None,
    ) -> RelationshipAgreement | None:
        data: dict[str, Any] = {
            "current_revision_id": revision_id,
            "current_revision_number": revision_number,
            "status": status,
            "updated_at": utc_now(),
            "archive_requested_by_user_types": [],
        }
        if revisited_at is not None:
            data["revisited_at"] = revisited_at
        doc = await self._collection.find_one_and_update(
            {"_id": _oid(agreement_id), "current_revision_id": expected_revision_id},
            {"$set": data},
            return_document=ReturnDocument.AFTER,
        )
        return RelationshipAgreement.model_validate(doc) if doc else None

    async def set_archive_requests(
        self,
        agreement_id: MongoId,
        users: list[UserType],
        *,
        status: AgreementStatus | None = None,
        finalize: bool = False,
    ) -> RelationshipAgreement | None:
        now = utc_now()
        data: dict[str, Any] = {
            "archive_requested_by_user_types": users,
            "updated_at": now,
        }
        if status is not None:
            data["status"] = status
        if finalize:
            data["status"] = AgreementStatus.ARCHIVED
            data["archived_at"] = now
        doc = await self._collection.find_one_and_update(
            {"_id": _oid(agreement_id)},
            {"$set": data},
            return_document=ReturnDocument.AFTER,
        )
        return RelationshipAgreement.model_validate(doc) if doc else None


class AgreementRevisionRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.agreement_revisions_collection_name]

    async def ensure_indexes(self) -> None:
        await self._collection.create_index(
            [("agreement_id", ASCENDING), ("revision_number", ASCENDING)], unique=True
        )
        await self._collection.create_index(
            [("agreement_id", ASCENDING), ("created_at", DESCENDING)]
        )

    async def create(self, revision: AgreementRevision) -> AgreementRevision:
        result = await self._collection.insert_one(revision.serialize())
        doc = await self._collection.find_one({"_id": result.inserted_id})
        return AgreementRevision.model_validate(doc)

    async def delete_candidate(self, revision_id: MongoId) -> None:
        await self._collection.delete_one({"_id": _oid(revision_id), "agreed_at": None})

    async def get_by_id(self, revision_id: MongoId) -> AgreementRevision | None:
        doc = await self._collection.find_one({"_id": _oid(revision_id)})
        return AgreementRevision.model_validate(doc) if doc else None

    async def list_for_agreement(self, agreement_id: MongoId) -> list[AgreementRevision]:
        docs = (
            await self._collection.find({"agreement_id": agreement_id})
            .sort("revision_number", DESCENDING)
            .to_list(length=None)
        )
        return [AgreementRevision.model_validate(doc) for doc in docs]

    async def mark_agreed(self, revision_id: MongoId) -> AgreementRevision | None:
        doc = await self._collection.find_one_and_update(
            {"_id": _oid(revision_id), "agreed_at": None},
            {"$set": {"agreed_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        if not doc:
            existing = await self._collection.find_one({"_id": _oid(revision_id)})
            return AgreementRevision.model_validate(existing) if existing else None
        return AgreementRevision.model_validate(doc) if doc else None


class AgreementAcceptanceRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.agreement_acceptances_collection_name]

    async def ensure_indexes(self) -> None:
        await self._collection.create_index(
            [("revision_id", ASCENDING), ("user_type", ASCENDING)], unique=True
        )
        await self._collection.create_index([("agreement_id", ASCENDING)])

    async def accept(
        self, agreement_id: MongoId, revision_id: MongoId, user_type: UserType
    ) -> AgreementAcceptance:
        now = utc_now()
        doc = await self._collection.find_one_and_update(
            {"revision_id": revision_id, "user_type": user_type},
            {
                "$set": {"agreement_id": agreement_id, "accepted_at": now, "revoked_at": None},
                "$setOnInsert": {"revision_id": revision_id, "user_type": user_type},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return AgreementAcceptance.model_validate(doc)

    async def revoke(self, revision_id: MongoId, user_type: UserType) -> AgreementAcceptance | None:
        doc = await self._collection.find_one_and_update(
            {"revision_id": revision_id, "user_type": user_type, "revoked_at": None},
            {"$set": {"revoked_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return AgreementAcceptance.model_validate(doc) if doc else None

    async def list_for_revision(self, revision_id: MongoId) -> list[AgreementAcceptance]:
        docs = (
            await self._collection.find({"revision_id": revision_id})
            .sort("accepted_at", ASCENDING)
            .to_list(length=None)
        )
        return [AgreementAcceptance.model_validate(doc) for doc in docs]

    async def list_active_for_revision(self, revision_id: MongoId) -> list[AgreementAcceptance]:
        docs = await self._collection.find(
            {"revision_id": revision_id, "revoked_at": None}
        ).to_list(length=None)
        return [AgreementAcceptance.model_validate(doc) for doc in docs]


class AgreementResponseRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.agreement_responses_collection_name]

    async def ensure_indexes(self) -> None:
        await self._collection.create_index(
            [("revision_id", ASCENDING), ("user_type", ASCENDING)], unique=True
        )

    async def upsert(
        self,
        agreement_id: MongoId,
        revision_id: MongoId,
        user_type: UserType,
        response_type: AgreementResponseType,
        note: str | None,
    ) -> AgreementResponse:
        now = utc_now()
        doc = await self._collection.find_one_and_update(
            {"revision_id": revision_id, "user_type": user_type},
            {
                "$set": {
                    "agreement_id": agreement_id,
                    "response_type": response_type,
                    "note": note,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "revision_id": revision_id,
                    "user_type": user_type,
                    "created_at": now,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return AgreementResponse.model_validate(doc)

    async def list_for_revision(self, revision_id: MongoId) -> list[AgreementResponse]:
        docs = (
            await self._collection.find({"revision_id": revision_id})
            .sort("updated_at", ASCENDING)
            .to_list(length=None)
        )
        return [AgreementResponse.model_validate(doc) for doc in docs]


async def ensure_relationship_care_indexes(db: AsyncDB) -> None:
    await PersonalBoundaryRepository(db).ensure_indexes()
    await RelationshipRequestRepository(db).ensure_indexes()
    await PersonalGoalRepository(db).ensure_indexes()
    await RelationshipAgreementRepository(db).ensure_indexes()
    await AgreementRevisionRepository(db).ensure_indexes()
    await AgreementAcceptanceRepository(db).ensure_indexes()
    await AgreementResponseRepository(db).ensure_indexes()
