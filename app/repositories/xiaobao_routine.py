from datetime import datetime, timedelta
from typing import Annotated, Any
from uuid import uuid4

from bson import ObjectId
from fastapi import Depends
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.core.config import get_settings
from app.db.mongo_client import get_db
from app.models.mongo import AsyncDB
from app.schemas.v1.base import MongoId
from app.schemas.v1.user import UserType
from app.schemas.v1.xiaobao_routine import (
    XiaoBaoRoutine,
    XiaoBaoRoutineFinishReason,
    XiaoBaoRoutineFrequency,
    XiaoBaoRoutinePauseReason,
    XiaoBaoRoutineRun,
    XiaoBaoRoutineRunStatus,
)
from app.util.time import utc_now

settings = get_settings()


def _oid(value: MongoId | str) -> ObjectId:
    return ObjectId(str(value))


class XiaoBaoRoutineRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.xiaobao_routines_collection_name]

    async def create(self, routine: XiaoBaoRoutine) -> XiaoBaoRoutine:
        result = await self._collection.insert_one(
            routine.model_dump(mode="python", by_alias=True, exclude_none=True)
        )
        doc = await self._collection.find_one({"_id": result.inserted_id})
        return XiaoBaoRoutine.model_validate(doc)

    async def get_owned(self, routine_id: MongoId, owner: UserType) -> XiaoBaoRoutine | None:
        doc = await self._collection.find_one(
            {"_id": _oid(routine_id), "owner_user_type": owner, "deleted_at": None}
        )
        return XiaoBaoRoutine.model_validate(doc) if doc else None

    async def get_active(self, routine_id: MongoId) -> XiaoBaoRoutine | None:
        doc = await self._collection.find_one(
            {"_id": _oid(routine_id), "enabled": True, "deleted_at": None}
        )
        return XiaoBaoRoutine.model_validate(doc) if doc else None

    async def get_for_execution(self, routine_id: MongoId) -> XiaoBaoRoutine | None:
        doc = await self._collection.find_one({"_id": _oid(routine_id)})
        return XiaoBaoRoutine.model_validate(doc) if doc else None

    async def list_owned(self, owner: UserType) -> list[XiaoBaoRoutine]:
        docs = (
            await self._collection.find({"owner_user_type": owner, "deleted_at": None})
            .sort("created_at", DESCENDING)
            .to_list(length=None)
        )
        return [XiaoBaoRoutine.model_validate(doc) for doc in docs]

    async def list_active(self) -> list[XiaoBaoRoutine]:
        docs = await self._collection.find({"enabled": True, "deleted_at": None}).to_list(
            length=None
        )
        return [XiaoBaoRoutine.model_validate(doc) for doc in docs]

    async def list_committed_delivery_repairs(self, *, limit: int) -> list[XiaoBaoRoutine]:
        docs = (
            await self._collection.find({"committed_delivery_pending_run_id": {"$type": "string"}})
            .sort("updated_at", ASCENDING)
            .limit(limit)
            .to_list(length=limit)
        )
        return [XiaoBaoRoutine.model_validate(doc) for doc in docs]

    async def list_committed_delivery_guarded_routine_ids(self) -> list[MongoId]:
        docs = await self._collection.find(
            {"committed_delivery_pending_run_id": {"$type": "string"}},
            {"_id": 1},
        ).to_list(length=None)
        return [str(doc["_id"]) for doc in docs]

    async def update_owned(
        self, routine_id: MongoId, owner: UserType, fields: dict[str, Any]
    ) -> XiaoBaoRoutine | None:
        fields["updated_at"] = utc_now()
        doc = await self._collection.find_one_and_update(
            {"_id": _oid(routine_id), "owner_user_type": owner, "deleted_at": None},
            {
                "$set": fields,
                "$inc": {"revision": 1},
                "$unset": {
                    "pending_delivery_run_id": "",
                    "pending_delivery_expires_at": "",
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoRoutine.model_validate(doc) if doc else None

    async def pause_owned(self, routine_id: MongoId, owner: UserType) -> XiaoBaoRoutine | None:
        now = utc_now()
        doc = await self._collection.find_one_and_update(
            {
                "_id": _oid(routine_id),
                "owner_user_type": owner,
                "enabled": True,
                "deleted_at": None,
            },
            {
                "$set": {
                    "enabled": False,
                    "paused_at": now,
                    "pause_reason": XiaoBaoRoutinePauseReason.MANUAL,
                    "updated_at": now,
                },
                "$inc": {"revision": 1},
                "$unset": {
                    "pending_delivery_run_id": "",
                    "pending_delivery_expires_at": "",
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoRoutine.model_validate(doc) if doc else None

    async def auto_pause_for_unread_inactivity(
        self, routine_id: MongoId, owner: UserType, *, revision: int
    ) -> XiaoBaoRoutine | None:
        now = utc_now()
        doc = await self._collection.find_one_and_update(
            {
                "_id": _oid(routine_id),
                "owner_user_type": owner,
                "enabled": True,
                "deleted_at": None,
                "revision": revision,
            },
            {
                "$set": {
                    "enabled": False,
                    "paused_at": now,
                    "pause_reason": XiaoBaoRoutinePauseReason.UNREAD_INACTIVITY,
                    "updated_at": now,
                },
                "$inc": {"revision": 1},
                "$unset": {
                    "pending_delivery_run_id": "",
                    "pending_delivery_expires_at": "",
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoRoutine.model_validate(doc) if doc else None

    async def resume_owned(
        self, routine_id: MongoId, owner: UserType, next_run_at: datetime
    ) -> XiaoBaoRoutine | None:
        now = utc_now()
        doc = await self._collection.find_one_and_update(
            {"_id": _oid(routine_id), "owner_user_type": owner, "deleted_at": None},
            {
                "$set": {"enabled": True, "next_run_at": next_run_at, "updated_at": now},
                "$inc": {"revision": 1},
                "$unset": {
                    "paused_at": "",
                    "pause_reason": "",
                    "pending_delivery_run_id": "",
                    "pending_delivery_expires_at": "",
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoRoutine.model_validate(doc) if doc else None

    async def soft_delete_owned(self, routine_id: MongoId, owner: UserType) -> bool:
        now = utc_now()
        result = await self._collection.update_one(
            {"_id": _oid(routine_id), "owner_user_type": owner, "deleted_at": None},
            {
                "$set": {"enabled": False, "deleted_at": now, "updated_at": now},
                "$inc": {"revision": 1},
                "$unset": {
                    "pending_delivery_run_id": "",
                    "pending_delivery_expires_at": "",
                },
            },
        )
        return bool(result.modified_count)

    async def reserve_delivery(
        self,
        routine_id: MongoId,
        owner: UserType,
        *,
        revision: int,
        run_id: MongoId,
        expires_at: datetime,
    ) -> bool:
        now = utc_now()
        result = await self._collection.update_one(
            {
                "_id": _oid(routine_id),
                "owner_user_type": owner,
                "enabled": True,
                "deleted_at": None,
                "revision": revision,
                "$or": [
                    {"pending_delivery_run_id": {"$exists": False}},
                    {"pending_delivery_run_id": None},
                    {"pending_delivery_run_id": str(run_id)},
                    {"pending_delivery_expires_at": {"$lte": now}},
                ],
                "$and": [
                    {
                        "$or": [
                            {"committed_delivery_pending_run_id": {"$exists": False}},
                            {"committed_delivery_pending_run_id": None},
                            {"committed_delivery_pending_run_id": str(run_id)},
                        ]
                    }
                ],
            },
            {
                "$set": {
                    "pending_delivery_run_id": str(run_id),
                    "pending_delivery_expires_at": expires_at,
                    "updated_at": now,
                }
            },
        )
        return bool(result.matched_count)

    async def commit_delivery(
        self,
        routine_id: MongoId,
        owner: UserType,
        *,
        revision: int,
        run_id: MongoId,
    ) -> bool:
        committed = await self._collection.find_one(
            {
                "_id": _oid(routine_id),
                "owner_user_type": owner,
                "last_committed_delivery_run_id": str(run_id),
            }
        )
        if committed:
            return True
        doc = await self._collection.find_one_and_update(
            {
                "_id": _oid(routine_id),
                "owner_user_type": owner,
                "enabled": True,
                "deleted_at": None,
                "revision": revision,
                "pending_delivery_run_id": str(run_id),
            },
            {
                "$set": {
                    "last_committed_delivery_run_id": str(run_id),
                    "committed_delivery_pending_run_id": str(run_id),
                    "updated_at": utc_now(),
                },
                "$unset": {
                    "pending_delivery_run_id": "",
                    "pending_delivery_expires_at": "",
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if doc and doc.get("last_committed_delivery_run_id") == str(run_id):
            return True
        # Another worker may have committed between the initial read and this update.
        committed = await self._collection.find_one(
            {
                "_id": _oid(routine_id),
                "owner_user_type": owner,
                "last_committed_delivery_run_id": str(run_id),
            }
        )
        return bool(committed)

    async def release_committed_delivery(
        self, routine_id: MongoId, owner: UserType, *, run_id: MongoId
    ) -> bool:
        result = await self._collection.update_one(
            {
                "_id": _oid(routine_id),
                "owner_user_type": owner,
                "committed_delivery_pending_run_id": str(run_id),
            },
            {"$unset": {"committed_delivery_pending_run_id": ""}},
        )
        return bool(result.matched_count)

    async def list_due(self, now: datetime, *, limit: int) -> list[XiaoBaoRoutine]:
        docs = (
            await self._collection.find(
                {
                    "enabled": True,
                    "deleted_at": None,
                    "next_run_at": {"$type": "date", "$lte": now},
                }
            )
            .sort("next_run_at", ASCENDING)
            .limit(limit)
            .to_list(length=limit)
        )
        return [XiaoBaoRoutine.model_validate(doc) for doc in docs]

    async def advance_if_due(
        self, routine_id: MongoId, scheduled_for: datetime, next_run_at: datetime | None
    ) -> bool:
        result = await self._collection.update_one(
            {
                "_id": _oid(routine_id),
                "enabled": True,
                "deleted_at": None,
                "next_run_at": scheduled_for,
            },
            {
                "$set": {
                    "last_scheduled_for": scheduled_for,
                    "next_run_at": next_run_at,
                    "updated_at": utc_now(),
                }
            },
        )
        return bool(result.modified_count)

    async def finish_one_time_delivery(
        self, routine_id: MongoId, owner: UserType, *, run_id: MongoId
    ) -> bool:
        """Terminalize a one-time schedule only after its committed output is visible."""
        now = utc_now()
        result = await self._collection.update_one(
            {
                "_id": _oid(routine_id),
                "owner_user_type": owner,
                "schedule.frequency": XiaoBaoRoutineFrequency.ONCE,
                "last_committed_delivery_run_id": str(run_id),
                "finished_at": None,
            },
            {
                "$set": {
                    "enabled": False,
                    "finished_at": now,
                    "finish_reason": XiaoBaoRoutineFinishReason.DELIVERED,
                    "updated_at": now,
                }
            },
        )
        return bool(result.modified_count)

    async def finish_one_time_failure(
        self, routine_id: MongoId, owner: UserType, *, revision: int
    ) -> bool:
        """Do not leave an exhausted one-time run looking like an enabled routine."""
        now = utc_now()
        result = await self._collection.update_one(
            {
                "_id": _oid(routine_id),
                "owner_user_type": owner,
                "enabled": True,
                "deleted_at": None,
                "revision": revision,
                "schedule.frequency": XiaoBaoRoutineFrequency.ONCE,
                "next_run_at": None,
                "finished_at": None,
            },
            {
                "$set": {
                    "enabled": False,
                    "finished_at": now,
                    "finish_reason": XiaoBaoRoutineFinishReason.FAILED,
                    "updated_at": now,
                }
            },
        )
        return bool(result.modified_count)


class XiaoBaoRoutineRunRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.xiaobao_routine_runs_collection_name]

    async def materialize(self, run: XiaoBaoRoutineRun) -> XiaoBaoRoutineRun:
        await self._collection.update_one(
            {"routine_id": run.routine_id, "scheduled_for": run.scheduled_for},
            {"$setOnInsert": run.model_dump(mode="python", by_alias=True, exclude_none=True)},
            upsert=True,
        )
        doc = await self._collection.find_one(
            {"routine_id": run.routine_id, "scheduled_for": run.scheduled_for}
        )
        return XiaoBaoRoutineRun.model_validate(doc)

    async def list_owned(
        self, routine_id: MongoId, owner: UserType, *, limit: int
    ) -> tuple[list[XiaoBaoRoutineRun], bool]:
        docs = (
            await self._collection.find({"routine_id": str(routine_id), "owner_user_type": owner})
            .sort("scheduled_for", DESCENDING)
            .limit(limit + 1)
            .to_list(length=limit + 1)
        )
        return [XiaoBaoRoutineRun.model_validate(doc) for doc in docs[:limit]], len(docs) > limit

    async def claim_next(
        self,
        *,
        lease_seconds: float,
        excluded_routine_ids: list[MongoId] | None = None,
    ) -> XiaoBaoRoutineRun | None:
        now = utc_now()
        lease_token = uuid4().hex
        query: dict[str, Any] = {
            "$or": [
                {
                    "status": XiaoBaoRoutineRunStatus.PENDING,
                    "available_at": {"$lte": now},
                },
                {
                    "status": XiaoBaoRoutineRunStatus.PROCESSING,
                    "lease_expires_at": {"$lte": now},
                },
            ],
            "attempt_count": {"$lt": settings.xiaobao_routine_max_attempts},
        }
        if excluded_routine_ids:
            query["routine_id"] = {"$nin": [str(item) for item in excluded_routine_ids]}
        doc = await self._collection.find_one_and_update(
            query,
            {
                "$set": {
                    "status": XiaoBaoRoutineRunStatus.PROCESSING,
                    "lease_token": lease_token,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                    "started_at": now,
                    "updated_at": now,
                    "error_code": None,
                },
                "$inc": {"attempt_count": 1},
            },
            sort=[("available_at", ASCENDING), ("scheduled_for", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoRoutineRun.model_validate(doc) if doc else None

    async def claim_delivery_repair(
        self, run_id: MongoId, *, lease_seconds: float
    ) -> XiaoBaoRoutineRun | None:
        existing = await self._collection.find_one({"_id": _oid(run_id)})
        if not existing:
            return None
        run = XiaoBaoRoutineRun.model_validate(existing)
        if run.status == XiaoBaoRoutineRunStatus.COMPLETED:
            return run
        now = utc_now()
        lease_token = uuid4().hex
        doc = await self._collection.find_one_and_update(
            {
                "_id": _oid(run_id),
                "$or": [
                    {
                        "status": {
                            "$nin": [
                                XiaoBaoRoutineRunStatus.PROCESSING,
                                XiaoBaoRoutineRunStatus.COMPLETED,
                            ]
                        },
                        "available_at": {"$lte": now},
                    },
                    {
                        "status": XiaoBaoRoutineRunStatus.PROCESSING,
                        "lease_expires_at": {"$lte": now},
                    },
                ],
            },
            {
                "$set": {
                    "status": XiaoBaoRoutineRunStatus.PROCESSING,
                    "lease_token": lease_token,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                    "started_at": now,
                    "updated_at": now,
                    "error_code": None,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoRoutineRun.model_validate(doc) if doc else None

    async def fail_exhausted_stale(
        self, *, excluded_routine_ids: list[MongoId] | None = None
    ) -> int:
        now = utc_now()
        query: dict[str, Any] = {
            "status": XiaoBaoRoutineRunStatus.PROCESSING,
            "lease_expires_at": {"$lte": now},
            "attempt_count": {"$gte": settings.xiaobao_routine_max_attempts},
        }
        if excluded_routine_ids:
            query["routine_id"] = {"$nin": [str(item) for item in excluded_routine_ids]}
        result = await self._collection.update_many(
            query,
            {
                "$set": {
                    "status": XiaoBaoRoutineRunStatus.FAILED,
                    "error_code": "lease_expired",
                    "completed_at": now,
                    "updated_at": now,
                },
                "$unset": {"lease_token": "", "lease_expires_at": ""},
            },
        )
        return int(result.modified_count)

    async def list_terminal_failures(self, *, limit: int) -> list[XiaoBaoRoutineRun]:
        docs = (
            await self._collection.find({"status": XiaoBaoRoutineRunStatus.FAILED})
            .sort("completed_at", DESCENDING)
            .limit(limit)
            .to_list(length=limit)
        )
        return [XiaoBaoRoutineRun.model_validate(doc) for doc in docs]

    async def mark_completed(
        self,
        run_id: MongoId,
        lease_token: str,
        *,
        output_message_id: MongoId,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
    ) -> XiaoBaoRoutineRun | None:
        now = utc_now()
        doc = await self._collection.find_one_and_update(
            {
                "_id": _oid(run_id),
                "status": XiaoBaoRoutineRunStatus.PROCESSING,
                "lease_token": lease_token,
            },
            {
                "$set": {
                    "status": XiaoBaoRoutineRunStatus.COMPLETED,
                    "output_message_id": str(output_message_id),
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "completed_at": now,
                    "updated_at": now,
                },
                "$unset": {"lease_token": "", "lease_expires_at": ""},
            },
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoRoutineRun.model_validate(doc) if doc else None

    async def mark_failed_or_retry(
        self, run: XiaoBaoRoutineRun, error_code: str
    ) -> XiaoBaoRoutineRun | None:
        if not run.id or not run.lease_token:
            return None
        now = utc_now()
        exhausted = run.attempt_count >= settings.xiaobao_routine_max_attempts
        delay = min(
            settings.xiaobao_routine_retry_max_seconds,
            settings.xiaobao_routine_retry_base_seconds * (2 ** max(run.attempt_count - 1, 0)),
        )
        status = XiaoBaoRoutineRunStatus.FAILED if exhausted else XiaoBaoRoutineRunStatus.PENDING
        fields: dict[str, Any] = {
            "status": status,
            "error_code": error_code[:80],
            "updated_at": now,
            "available_at": now + timedelta(seconds=delay),
        }
        if exhausted:
            fields["completed_at"] = now
        doc = await self._collection.find_one_and_update(
            {
                "_id": _oid(run.id),
                "status": XiaoBaoRoutineRunStatus.PROCESSING,
                "lease_token": run.lease_token,
            },
            {"$set": fields, "$unset": {"lease_token": "", "lease_expires_at": ""}},
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoRoutineRun.model_validate(doc) if doc else None

    async def cancel_pending_for_routine(self, routine_id: MongoId) -> None:
        now = utc_now()
        await self._collection.update_many(
            {
                "routine_id": str(routine_id),
                "status": XiaoBaoRoutineRunStatus.PENDING,
            },
            {
                "$set": {
                    "status": XiaoBaoRoutineRunStatus.CANCELLED,
                    "completed_at": now,
                    "updated_at": now,
                    "error_code": "routine_inactive",
                }
            },
        )

    async def cancel_claim(
        self, run: XiaoBaoRoutineRun, error_code: str = "routine_inactive"
    ) -> None:
        if not run.id or not run.lease_token:
            return
        now = utc_now()
        await self._collection.update_one(
            {"_id": _oid(run.id), "lease_token": run.lease_token},
            {
                "$set": {
                    "status": XiaoBaoRoutineRunStatus.CANCELLED,
                    "completed_at": now,
                    "updated_at": now,
                    "error_code": error_code[:80],
                },
                "$unset": {"lease_token": "", "lease_expires_at": ""},
            },
        )


async def ensure_xiaobao_routine_indexes(db: AsyncDB) -> None:
    routines = db[settings.xiaobao_routines_collection_name]
    runs = db[settings.xiaobao_routine_runs_collection_name]
    await routines.create_index(
        [("enabled", ASCENDING), ("next_run_at", ASCENDING)],
        partialFilterExpression={"deleted_at": None},
        name="xiaobao_due_routines",
    )
    await routines.create_index(
        [("owner_user_type", ASCENDING), ("created_at", DESCENDING)],
        partialFilterExpression={"deleted_at": None},
        name="xiaobao_owned_routines",
    )
    await routines.create_index(
        [("committed_delivery_pending_run_id", ASCENDING), ("updated_at", ASCENDING)],
        partialFilterExpression={"committed_delivery_pending_run_id": {"$type": "string"}},
        name="xiaobao_committed_delivery_repairs",
    )
    await runs.create_index([("routine_id", ASCENDING), ("scheduled_for", ASCENDING)], unique=True)
    await runs.create_index(
        [("status", ASCENDING), ("available_at", ASCENDING), ("lease_expires_at", ASCENDING)],
        name="xiaobao_claimable_routine_runs",
    )
    await runs.create_index(
        [("owner_user_type", ASCENDING), ("routine_id", ASCENDING), ("scheduled_for", DESCENDING)]
    )
