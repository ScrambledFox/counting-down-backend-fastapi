from collections.abc import Mapping
from datetime import timedelta
from typing import Annotated, Any
from uuid import uuid4

from bson import ObjectId
from fastapi import Depends
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.db.mongo_client import AsyncDB, get_db
from app.schemas.v1.base import MongoId
from app.schemas.v1.mediation import (
    AIJobStatus,
    MediationAdvice,
    MediationAIAuthorType,
    MediationAIJob,
    MediationAIJobType,
    MediationAIReflection,
    MediationAuthorType,
    MediationComment,
    MediationModerationResult,
    MediationPerspective,
    MediationSession,
    MediationSessionStatus,
    PerspectiveStatus,
    SafetyStatus,
)
from app.schemas.v1.user import UserType
from app.util.time import utc_now

settings = get_settings()


def _oid(value: MongoId | str | None) -> ObjectId | None:
    return ObjectId(value) if value else None


async def _insert_once_per_job(collection: Any, document: dict[str, Any]) -> dict[str, Any] | None:
    """Insert an AI output, deduplicated per producing job on a best-effort basis.

    A retried or superseded job run that reaches persistence again receives the output already
    stored for that job instead of creating a duplicate. Without a unique index, two writers in
    the same instant could still both insert; see ADR 0001. Outputs without a job are plain
    inserts.
    """
    job_id = document.get("ai_job_id")
    if job_id is None:
        result = await collection.insert_one(document)
        return await collection.find_one({"_id": result.inserted_id})
    return await collection.find_one_and_update(
        {"ai_job_id": job_id},
        {"$setOnInsert": document},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


class MediationSessionRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.mediation_sessions_collection_name]

    async def ensure_indexes(self) -> None:
        await self._collection.create_index([("created_at", DESCENDING)])
        await self._collection.create_index([("status", ASCENDING)])
        await self._collection.create_index([("safety_status", ASCENDING)])

    async def create(self, session: MediationSession) -> MediationSession:
        result = await self._collection.insert_one(session.serialize())
        doc = await self._collection.find_one({"_id": result.inserted_id})
        return MediationSession.model_validate(doc)

    async def list_all(self) -> list[MediationSession]:
        docs = await self._collection.find({}).sort("created_at", DESCENDING).to_list(length=None)
        return [MediationSession.model_validate(doc) for doc in docs]

    async def get_by_id(self, session_id: MongoId) -> MediationSession | None:
        doc = await self._collection.find_one({"_id": _oid(session_id)})
        return MediationSession.model_validate(doc) if doc else None

    async def update_fields(
        self, session_id: MongoId, data: Mapping[str, Any]
    ) -> MediationSession | None:
        payload = dict(data)
        payload["updated_at"] = utc_now()
        doc = await self._collection.find_one_and_update(
            {"_id": _oid(session_id)},
            {"$set": payload},
            return_document=ReturnDocument.AFTER,
        )
        return MediationSession.model_validate(doc) if doc else None

    async def set_status(
        self, session_id: MongoId, status: MediationSessionStatus
    ) -> MediationSession | None:
        return await self.update_fields(session_id, {"status": status})

    async def set_safety_status(
        self, session_id: MongoId, safety_status: SafetyStatus
    ) -> MediationSession | None:
        return await self.update_fields(session_id, {"safety_status": safety_status})

    async def set_latest_advice(
        self, session_id: MongoId, advice_id: MongoId
    ) -> MediationSession | None:
        return await self.update_fields(
            session_id,
            {
                "latest_advice_id": str(advice_id),
                "status": MediationSessionStatus.AI_ADVICE_AVAILABLE,
            },
        )

    async def mark_resolved(
        self, session_id: MongoId, resolved_by_user_types: list[UserType], finalize: bool
    ) -> MediationSession | None:
        now = utc_now()
        data: dict[str, Any] = {"resolved_by_user_types": resolved_by_user_types}
        if finalize:
            data["status"] = MediationSessionStatus.RESOLVED
            data["resolved_at"] = now
        return await self.update_fields(session_id, data)

    async def unmark_resolved(
        self, session_id: MongoId, resolved_by_user_types: list[UserType]
    ) -> MediationSession | None:
        return await self.update_fields(
            session_id, {"resolved_by_user_types": resolved_by_user_types}
        )

    async def mark_archived(
        self, session_id: MongoId, archived_by_user_types: list[UserType], finalize: bool
    ) -> MediationSession | None:
        now = utc_now()
        data: dict[str, Any] = {"archived_by_user_types": archived_by_user_types}
        if finalize:
            data["status"] = MediationSessionStatus.ARCHIVED
            data["archived_at"] = now
        return await self.update_fields(session_id, data)

    async def unmark_archived(
        self, session_id: MongoId, archived_by_user_types: list[UserType]
    ) -> MediationSession | None:
        return await self.update_fields(
            session_id, {"archived_by_user_types": archived_by_user_types}
        )


class MediationPerspectiveRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.mediation_perspectives_collection_name]

    async def ensure_indexes(self) -> None:
        await self._collection.create_index(
            [("session_id", ASCENDING), ("user_type", ASCENDING)], unique=True
        )
        await self._collection.create_index([("session_id", ASCENDING), ("status", ASCENDING)])

    async def get_by_session_and_user(
        self, session_id: MongoId, user_type: UserType
    ) -> MediationPerspective | None:
        doc = await self._collection.find_one({"session_id": session_id, "user_type": user_type})
        return MediationPerspective.model_validate(doc) if doc else None

    async def get_by_id(self, perspective_id: MongoId) -> MediationPerspective | None:
        doc = await self._collection.find_one({"_id": _oid(perspective_id)})
        return MediationPerspective.model_validate(doc) if doc else None

    async def upsert_draft(
        self, session_id: MongoId, user_type: UserType, data: Mapping[str, Any]
    ) -> MediationPerspective:
        now = utc_now()
        update = {
            "$set": {**dict(data), "updated_at": now, "status": PerspectiveStatus.DRAFT},
            "$setOnInsert": {"session_id": session_id, "user_type": user_type, "created_at": now},
        }
        doc = await self._collection.find_one_and_update(
            {"session_id": session_id, "user_type": user_type},
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return MediationPerspective.model_validate(doc)

    async def mark_pending_review(self, perspective_id: MongoId) -> MediationPerspective | None:
        now = utc_now()
        doc = await self._collection.find_one_and_update(
            {"_id": _oid(perspective_id), "status": PerspectiveStatus.DRAFT},
            {
                "$set": {
                    "status": PerspectiveStatus.SUBMITTED_PENDING_REVIEW,
                    "submitted_at": now,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return MediationPerspective.model_validate(doc) if doc else None

    async def lock_perspective(
        self, perspective_id: MongoId, moderation_result_id: MongoId | None
    ) -> MediationPerspective | None:
        now = utc_now()
        doc = await self._collection.find_one_and_update(
            {
                "_id": _oid(perspective_id),
                "status": PerspectiveStatus.SUBMITTED_PENDING_REVIEW,
            },
            {
                "$set": {
                    "status": PerspectiveStatus.LOCKED,
                    "updated_at": now,
                    "moderation_result_id": moderation_result_id,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return MediationPerspective.model_validate(doc) if doc else None

    async def mark_flagged(
        self, perspective_id: MongoId, moderation_result_id: MongoId | None
    ) -> MediationPerspective | None:
        now = utc_now()
        doc = await self._collection.find_one_and_update(
            {"_id": _oid(perspective_id)},
            {
                "$set": {
                    "status": PerspectiveStatus.FLAGGED,
                    "updated_at": now,
                    "moderation_result_id": moderation_result_id,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return MediationPerspective.model_validate(doc) if doc else None

    async def count_locked_for_session(self, session_id: MongoId) -> int:
        return await self._collection.count_documents(
            {"session_id": session_id, "status": PerspectiveStatus.LOCKED}
        )

    async def list_for_session(self, session_id: MongoId) -> list[MediationPerspective]:
        docs = await self._collection.find({"session_id": session_id}).to_list(length=None)
        return [MediationPerspective.model_validate(doc) for doc in docs]

    async def list_locked_for_session(self, session_id: MongoId) -> list[MediationPerspective]:
        docs = await self._collection.find(
            {"session_id": session_id, "status": PerspectiveStatus.LOCKED}
        ).to_list(length=None)
        return [MediationPerspective.model_validate(doc) for doc in docs]


class MediationModerationRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.mediation_moderation_results_collection_name]

    async def ensure_indexes(self) -> None:
        await self._collection.create_index([("entity_type", ASCENDING), ("entity_id", ASCENDING)])

    async def insert(self, result: MediationModerationResult) -> MediationModerationResult:
        inserted = await self._collection.insert_one(result.serialize())
        doc = await self._collection.find_one({"_id": inserted.inserted_id})
        return MediationModerationResult.model_validate(doc)


class MediationAIRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._reflections = db[settings.mediation_ai_reflections_collection_name]
        self._advices = db[settings.mediation_advices_collection_name]
        self._comments = db[settings.mediation_comments_collection_name]

    async def ensure_indexes(self) -> None:
        await self._reflections.create_index(
            [("session_id", ASCENDING), ("recipient_user_type", ASCENDING)]
        )
        await self._advices.create_index([("session_id", ASCENDING), ("created_at", DESCENDING)])
        # Non-unique so legacy documents can never block startup; lookups for per-job writes.
        await self._reflections.create_index([("ai_job_id", ASCENDING)], sparse=True)
        await self._advices.create_index([("ai_job_id", ASCENDING)], sparse=True)

    async def insert_reflection(self, reflection: MediationAIReflection) -> MediationAIReflection:
        doc = await _insert_once_per_job(self._reflections, reflection.serialize())
        return MediationAIReflection.model_validate(doc)

    async def get_reflection_for_user(
        self, session_id: MongoId, user_type: UserType
    ) -> MediationAIReflection | None:
        doc = await self._reflections.find_one(
            {"session_id": session_id, "recipient_user_type": user_type},
            sort=[("created_at", DESCENDING)],
        )
        return MediationAIReflection.model_validate(doc) if doc else None

    async def insert_advice(self, advice: MediationAdvice) -> MediationAdvice:
        doc = await _insert_once_per_job(self._advices, advice.serialize())
        return MediationAdvice.model_validate(doc)

    async def get_latest_advice(self, session_id: MongoId) -> MediationAdvice | None:
        doc = await self._advices.find_one(
            {"session_id": session_id, "superseded_by_id": {"$exists": False}},
            sort=[("created_at", DESCENDING)],
        )
        return MediationAdvice.model_validate(doc) if doc else None

    async def insert_ai_comment(self, comment: MediationComment) -> MediationComment:
        result = await self._comments.insert_one(comment.serialize())
        doc = await self._comments.find_one({"_id": result.inserted_id})
        return MediationComment.model_validate(doc)


class MediationCommentRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.mediation_comments_collection_name]

    async def ensure_indexes(self) -> None:
        await self._collection.create_index(
            [("session_id", ASCENDING), ("parent_comment_id", ASCENDING), ("created_at", ASCENDING)]
        )
        await self._collection.create_index([("ai_job_id", ASCENDING)], sparse=True)

    async def create_user_comment(
        self,
        session_id: MongoId,
        parent_comment_id: MongoId | None,
        user_type: UserType,
        content: str,
        moderation_result_id: MongoId | None,
    ) -> MediationComment:
        now = utc_now()
        comment = MediationComment(
            session_id=session_id,
            parent_comment_id=parent_comment_id,
            author_type=MediationAuthorType.USER,
            author_user_type=user_type,
            content=content,
            created_at=now,
            moderation_result_id=moderation_result_id,
        )
        result = await self._collection.insert_one(comment.serialize())
        doc = await self._collection.find_one({"_id": result.inserted_id})
        return MediationComment.model_validate(doc)

    async def create_ai_comment(
        self,
        session_id: MongoId,
        parent_comment_id: MongoId | None,
        content: str,
        ai_job_id: MongoId | None,
        *,
        ai_author_type: MediationAIAuthorType = MediationAIAuthorType.MEDIATION_ASSISTANT,
        moderation_result_id: MongoId | None = None,
    ) -> MediationComment:
        now = utc_now()
        comment = MediationComment(
            session_id=session_id,
            parent_comment_id=parent_comment_id,
            author_type=MediationAuthorType.AI,
            author_user_type=None,
            ai_author_type=ai_author_type,
            content=content,
            created_at=now,
            moderation_result_id=moderation_result_id,
            ai_job_id=ai_job_id,
        )
        doc = await _insert_once_per_job(self._collection, comment.serialize())
        return MediationComment.model_validate(doc)

    async def list_for_session(self, session_id: MongoId) -> list[MediationComment]:
        docs = (
            await self._collection.find({"session_id": session_id})
            .sort("created_at", ASCENDING)
            .to_list(length=None)
        )
        return [MediationComment.model_validate(doc) for doc in docs]

    async def get_by_id(self, comment_id: MongoId) -> MediationComment | None:
        doc = await self._collection.find_one({"_id": _oid(comment_id)})
        return MediationComment.model_validate(doc) if doc else None


class MediationJobRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.mediation_ai_jobs_collection_name]

    async def ensure_indexes(self) -> None:
        await self._collection.create_index([("idempotency_key", ASCENDING)], unique=True)
        await self._collection.create_index([("status", ASCENDING), ("created_at", ASCENDING)])

    async def create_job_if_not_exists(self, job: MediationAIJob) -> MediationAIJob:
        try:
            result = await self._collection.insert_one(job.serialize())
            doc = await self._collection.find_one({"_id": result.inserted_id})
        except DuplicateKeyError:
            doc = await self._collection.find_one({"idempotency_key": job.idempotency_key})
        return MediationAIJob.model_validate(doc)

    async def get_latest_by_type(
        self, session_id: MongoId, job_type: MediationAIJobType
    ) -> MediationAIJob | None:
        doc = await self._collection.find_one(
            {"session_id": session_id, "job_type": job_type},
            sort=[("created_at", DESCENDING)],
        )
        return MediationAIJob.model_validate(doc) if doc else None

    async def fail_exhausted_stale_processing_jobs(self, stale_after_seconds: float) -> int:
        now = utc_now()
        stale_before = now - timedelta(seconds=stale_after_seconds)
        result = await self._collection.update_many(
            {
                "status": AIJobStatus.PROCESSING,
                "$expr": {"$gte": ["$attempts", "$max_attempts"]},
                "$or": [
                    {"started_at": {"$lte": stale_before}},
                    {"started_at": None},
                    {"started_at": {"$exists": False}},
                ],
            },
            {
                "$set": {
                    "status": AIJobStatus.FAILED,
                    "error_message": "Job exceeded retry attempts while processing.",
                    "updated_at": now,
                },
                "$unset": {"lease_token": ""},
            },
        )
        return int(result.modified_count)

    async def claim_next_pending_job(
        self, stale_after_seconds: float | None = None
    ) -> MediationAIJob | None:
        now = utc_now()
        retryable_status_filter: dict[str, Any] = {"status": AIJobStatus.PENDING}
        if stale_after_seconds is not None:
            stale_before = now - timedelta(seconds=stale_after_seconds)
            retryable_status_filter = {
                "$or": [
                    {"status": AIJobStatus.PENDING},
                    {
                        "status": AIJobStatus.PROCESSING,
                        "$or": [
                            {"started_at": {"$lte": stale_before}},
                            {"started_at": None},
                            {"started_at": {"$exists": False}},
                        ],
                    },
                ]
            }
        doc = await self._collection.find_one_and_update(
            {
                **retryable_status_filter,
                "$expr": {"$lt": ["$attempts", "$max_attempts"]},
            },
            {
                "$set": {
                    "status": AIJobStatus.PROCESSING,
                    "started_at": now,
                    "updated_at": now,
                    "lease_token": uuid4().hex,
                },
                "$inc": {"attempts": 1},
            },
            sort=[("created_at", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )
        return MediationAIJob.model_validate(doc) if doc else None

    @staticmethod
    def _owned_by(job: MediationAIJob) -> dict[str, Any]:
        """Match the job only while ``job``'s claim is still the current one.

        A worker whose lease went stale was superseded by a newer claim with a new token, so its
        writes match nothing. Callers reject jobs without a token before calling this.
        """
        return {
            "_id": _oid(job.id),
            "status": AIJobStatus.PROCESSING,
            "lease_token": job.lease_token,
        }

    async def is_owner(self, job: MediationAIJob) -> bool:
        if not job.id or not job.lease_token:
            return False
        return await self._collection.count_documents(self._owned_by(job), limit=1) == 1

    async def mark_completed(self, job: MediationAIJob) -> MediationAIJob | None:
        """Complete the job if ``job`` still owns it; return None for a superseded worker."""
        if not job.id or not job.lease_token:
            return None
        now = utc_now()
        doc = await self._collection.find_one_and_update(
            self._owned_by(job),
            {
                "$set": {"status": AIJobStatus.COMPLETED, "completed_at": now, "updated_at": now},
                "$unset": {"lease_token": ""},
            },
            return_document=ReturnDocument.AFTER,
        )
        return MediationAIJob.model_validate(doc) if doc else None

    async def mark_failed_or_retry(
        self, job: MediationAIJob, error_message: str
    ) -> MediationAIJob | None:
        """Retry or fail the job if ``job`` still owns it; return None for a superseded worker."""
        if not job.id or not job.lease_token:
            return None
        now = utc_now()
        exhausted = {"$gte": ["$attempts", {"$ifNull": ["$max_attempts", 3]}]}
        doc = await self._collection.find_one_and_update(
            self._owned_by(job),
            [
                {
                    "$set": {
                        "status": {"$cond": [exhausted, AIJobStatus.FAILED, AIJobStatus.PENDING]},
                        "error_message": error_message[:2000],
                        "updated_at": now,
                    }
                },
                {"$unset": "lease_token"},
            ],
            return_document=ReturnDocument.AFTER,
        )
        return MediationAIJob.model_validate(doc) if doc else None


async def ensure_mediation_indexes(db: AsyncDB) -> None:
    await MediationSessionRepository(db).ensure_indexes()
    await MediationPerspectiveRepository(db).ensure_indexes()
    await MediationModerationRepository(db).ensure_indexes()
    await MediationAIRepository(db).ensure_indexes()
    await MediationCommentRepository(db).ensure_indexes()
    await MediationJobRepository(db).ensure_indexes()
