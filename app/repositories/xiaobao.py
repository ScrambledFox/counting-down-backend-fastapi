from datetime import datetime, timedelta
from typing import Annotated, Any

from bson import ObjectId
from fastapi import Depends
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.db.mongo_client import get_db
from app.models.mongo import AsyncDB
from app.schemas.v1.base import MongoId
from app.schemas.v1.user import UserType
from app.schemas.v1.xiaobao import (
    XiaoBaoCompletedAction,
    XiaoBaoContextReference,
    XiaoBaoConversation,
    XiaoBaoConversationPurpose,
    XiaoBaoMascotMood,
    XiaoBaoMessage,
    XiaoBaoMessageRole,
    XiaoBaoMessageSource,
    XiaoBaoMessageStatus,
    XiaoBaoProposal,
    XiaoBaoProposalStatus,
    XiaoBaoTokenUsage,
)
from app.util.time import utc_now

settings = get_settings()


def _oid(value: MongoId | str) -> ObjectId:
    return ObjectId(str(value))


def _conversation_purpose_query(
    purpose: XiaoBaoConversationPurpose,
) -> XiaoBaoConversationPurpose | dict[str, list[XiaoBaoConversationPurpose | None]]:
    if purpose == XiaoBaoConversationPurpose.CHAT:
        # Conversations created before purposes were introduced are ordinary chats.
        return {"$in": [XiaoBaoConversationPurpose.CHAT, None]}
    return purpose


class XiaoBaoConversationRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._conversations = db[settings.xiaobao_conversations_collection_name]
        self._messages = db[settings.xiaobao_messages_collection_name]
        self._proposals = db[settings.xiaobao_proposals_collection_name]

    async def create(self, conversation: XiaoBaoConversation) -> XiaoBaoConversation:
        result = await self._conversations.insert_one(
            conversation.model_dump(mode="python", by_alias=True, exclude_none=True)
        )
        doc = await self._conversations.find_one({"_id": result.inserted_id})
        return XiaoBaoConversation.model_validate(doc)

    async def get_owned(
        self,
        conversation_id: MongoId,
        owner: UserType,
        purpose: XiaoBaoConversationPurpose | None = None,
    ) -> XiaoBaoConversation | None:
        query: dict[str, Any] = {"_id": _oid(conversation_id), "owner_user_type": owner}
        if purpose is not None:
            query["purpose"] = _conversation_purpose_query(purpose)
        doc = await self._conversations.find_one(query)
        return XiaoBaoConversation.model_validate(doc) if doc else None

    async def get_or_create_inbox(self, owner: UserType) -> XiaoBaoConversation:
        now = utc_now()
        query = {"owner_user_type": owner, "purpose": XiaoBaoConversationPurpose.ROUTINE_INBOX}
        doc: dict[str, Any] | None
        try:
            doc = await self._conversations.find_one_and_update(
                query,
                {
                    "$setOnInsert": {
                        "owner_user_type": owner,
                        "purpose": XiaoBaoConversationPurpose.ROUTINE_INBOX,
                        "title": "Routines inbox",
                        "created_at": now,
                        "updated_at": now,
                    }
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            doc = await self._conversations.find_one(query)
        if not doc:
            raise RuntimeError("Xiao Bao routines inbox could not be created")
        return XiaoBaoConversation.model_validate(doc)

    async def get_inbox(self, owner: UserType) -> XiaoBaoConversation | None:
        doc = await self._conversations.find_one(
            {"owner_user_type": owner, "purpose": XiaoBaoConversationPurpose.ROUTINE_INBOX}
        )
        return XiaoBaoConversation.model_validate(doc) if doc else None

    async def list_owned(
        self, owner: UserType, *, limit: int, before: datetime | None = None
    ) -> list[XiaoBaoConversation]:
        query: dict[str, Any] = {
            "owner_user_type": owner,
            "purpose": {"$in": [XiaoBaoConversationPurpose.CHAT, None]},
        }
        if before:
            query["updated_at"] = {"$lt": before}
        docs = (
            await self._conversations.find(query)
            .sort("updated_at", DESCENDING)
            .limit(limit)
            .to_list(length=limit)
        )
        return [XiaoBaoConversation.model_validate(doc) for doc in docs]

    async def touch(self, conversation_id: MongoId, *, title: str | None = None) -> None:
        data: dict[str, Any] = {"updated_at": utc_now()}
        if title:
            data["title"] = title
        await self._conversations.update_one({"_id": _oid(conversation_id)}, {"$set": data})

    async def delete_owned(
        self,
        conversation_id: MongoId,
        owner: UserType,
        purpose: XiaoBaoConversationPurpose = XiaoBaoConversationPurpose.CHAT,
    ) -> bool:
        result = await self._conversations.delete_one(
            {
                "_id": _oid(conversation_id),
                "owner_user_type": owner,
                "purpose": _conversation_purpose_query(purpose),
            }
        )
        if not result.deleted_count:
            return False
        await self._messages.delete_many({"conversation_id": str(conversation_id)})
        await self._proposals.delete_many({"conversation_id": str(conversation_id)})
        return True


class XiaoBaoMessageRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.xiaobao_messages_collection_name]

    async def create_user(self, message: XiaoBaoMessage) -> tuple[XiaoBaoMessage, bool]:
        try:
            result = await self._collection.insert_one(
                message.model_dump(mode="python", by_alias=True, exclude_none=True)
            )
            doc = await self._collection.find_one({"_id": result.inserted_id})
            return XiaoBaoMessage.model_validate(doc), True
        except DuplicateKeyError:
            doc = await self._collection.find_one(
                {
                    "conversation_id": message.conversation_id,
                    "client_message_id": message.client_message_id,
                    "role": XiaoBaoMessageRole.USER,
                }
            )
            if not doc:
                raise
            return XiaoBaoMessage.model_validate(doc), False

    async def create_assistant(self, message: XiaoBaoMessage) -> XiaoBaoMessage:
        result = await self._collection.insert_one(
            message.model_dump(mode="python", by_alias=True, exclude_none=True)
        )
        doc = await self._collection.find_one({"_id": result.inserted_id})
        return XiaoBaoMessage.model_validate(doc)

    async def stage_routine_output(self, message: XiaoBaoMessage) -> XiaoBaoMessage:
        try:
            return await self.create_assistant(message)
        except DuplicateKeyError:
            doc = await self._collection.find_one(
                {
                    "routine_run_id": message.routine_run_id,
                    "source": XiaoBaoMessageSource.ROUTINE,
                }
            )
            if not doc:
                raise
            return XiaoBaoMessage.model_validate(doc)

    async def get(self, message_id: MongoId) -> XiaoBaoMessage | None:
        doc = await self._collection.find_one({"_id": _oid(message_id)})
        return XiaoBaoMessage.model_validate(doc) if doc else None

    async def get_assistant_for_user_message(
        self, conversation_id: MongoId, user_message_id: MongoId
    ) -> XiaoBaoMessage | None:
        doc = await self._collection.find_one(
            {
                "conversation_id": str(conversation_id),
                "parent_user_message_id": str(user_message_id),
                "role": XiaoBaoMessageRole.ASSISTANT,
            },
            sort=[("created_at", DESCENDING)],
        )
        return XiaoBaoMessage.model_validate(doc) if doc else None

    async def list_for_conversation(
        self, conversation_id: MongoId, *, limit: int
    ) -> tuple[list[XiaoBaoMessage], bool]:
        docs = (
            await self._collection.find({"conversation_id": str(conversation_id)})
            .sort("created_at", DESCENDING)
            .limit(limit + 1)
            .to_list(length=limit + 1)
        )
        has_more = len(docs) > limit
        return [XiaoBaoMessage.model_validate(doc) for doc in reversed(docs[:limit])], has_more

    async def list_completed_history(
        self, conversation_id: MongoId, *, limit: int
    ) -> list[XiaoBaoMessage]:
        docs = (
            await self._collection.find(
                {
                    "conversation_id": str(conversation_id),
                    "status": XiaoBaoMessageStatus.COMPLETE,
                }
            )
            .sort("created_at", DESCENDING)
            .limit(limit)
            .to_list(length=limit)
        )
        return [XiaoBaoMessage.model_validate(doc) for doc in reversed(docs)]

    async def count_unread_for_conversation(self, conversation_id: MongoId) -> int:
        return await self._collection.count_documents(
            {
                "conversation_id": str(conversation_id),
                "source": XiaoBaoMessageSource.ROUTINE,
                "status": XiaoBaoMessageStatus.COMPLETE,
                "read_at": None,
            }
        )

    async def has_unread_routine_output_at_or_before(
        self,
        routine_id: MongoId,
        conversation_id: MongoId,
        *,
        threshold: datetime,
    ) -> bool:
        doc = await self._collection.find_one(
            {
                "routine_id": str(routine_id),
                "conversation_id": str(conversation_id),
                "source": XiaoBaoMessageSource.ROUTINE,
                "status": XiaoBaoMessageStatus.COMPLETE,
                "read_at": None,
                "$or": [
                    {"delivered_at": {"$lte": threshold}},
                    {
                        "delivered_at": None,
                        "created_at": {"$lte": threshold},
                    },
                ],
            },
            {"_id": 1},
        )
        return doc is not None

    async def list_routine_inbox(
        self,
        conversation_id: MongoId,
        *,
        limit: int,
        routine_id: MongoId | None = None,
        before_created_at: datetime | None = None,
        before_id: MongoId | None = None,
    ) -> tuple[list[XiaoBaoMessage], bool]:
        query: dict[str, Any] = {
            "conversation_id": str(conversation_id),
            "source": XiaoBaoMessageSource.ROUTINE,
            "status": XiaoBaoMessageStatus.COMPLETE,
        }
        if routine_id is not None:
            query["routine_id"] = str(routine_id)
        if before_created_at is not None and before_id is not None:
            query["$or"] = [
                {"created_at": {"$lt": before_created_at}},
                {"created_at": before_created_at, "_id": {"$lt": _oid(before_id)}},
            ]
        docs = (
            await self._collection.find(query)
            .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit + 1)
            .to_list(length=limit + 1)
        )
        has_more = len(docs) > limit
        return [XiaoBaoMessage.model_validate(doc) for doc in docs[:limit]], has_more

    async def list_recent_routine_outputs(
        self, routine_id: MongoId, *, limit: int
    ) -> list[XiaoBaoMessage]:
        docs = (
            await self._collection.find(
                {
                    "routine_id": str(routine_id),
                    "source": XiaoBaoMessageSource.ROUTINE,
                    "status": XiaoBaoMessageStatus.COMPLETE,
                }
            )
            .sort("created_at", DESCENDING)
            .limit(limit)
            .to_list(length=limit)
        )
        return [XiaoBaoMessage.model_validate(doc) for doc in reversed(docs)]

    async def get_by_routine_run(self, routine_run_id: MongoId) -> XiaoBaoMessage | None:
        doc = await self._collection.find_one(
            {
                "routine_run_id": str(routine_run_id),
                "source": XiaoBaoMessageSource.ROUTINE,
            }
        )
        return XiaoBaoMessage.model_validate(doc) if doc else None

    async def finalize_staged_routine_output(self, message_id: MongoId) -> XiaoBaoMessage | None:
        now = utc_now()
        doc: dict[str, Any] | None = await self._collection.find_one_and_update(
            {
                "_id": _oid(message_id),
                "source": XiaoBaoMessageSource.ROUTINE,
                "status": XiaoBaoMessageStatus.PENDING_DELIVERY,
            },
            {
                "$set": {
                    "status": XiaoBaoMessageStatus.COMPLETE,
                    "delivered_at": now,
                    "updated_at": now,
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if not doc:
            doc = await self._collection.find_one(
                {
                    "_id": _oid(message_id),
                    "source": XiaoBaoMessageSource.ROUTINE,
                    "status": XiaoBaoMessageStatus.COMPLETE,
                }
            )
        return XiaoBaoMessage.model_validate(doc) if doc else None

    async def delete_staged_routine_output(self, message_id: MongoId) -> None:
        await self._collection.delete_one(
            {
                "_id": _oid(message_id),
                "source": XiaoBaoMessageSource.ROUTINE,
                "status": XiaoBaoMessageStatus.PENDING_DELIVERY,
            }
        )

    async def mark_routine_message_read(
        self, message_id: MongoId, conversation_id: MongoId
    ) -> XiaoBaoMessage | None:
        doc = await self._collection.find_one_and_update(
            {
                "_id": _oid(message_id),
                "conversation_id": str(conversation_id),
                "source": XiaoBaoMessageSource.ROUTINE,
                "status": XiaoBaoMessageStatus.COMPLETE,
            },
            {"$set": {"read_at": utc_now(), "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoMessage.model_validate(doc) if doc else None

    async def complete(
        self,
        message_id: MongoId,
        *,
        content: str,
        references: list[XiaoBaoContextReference],
        proposal_ids: list[MongoId],
        completed_actions: list[XiaoBaoCompletedAction],
        mascot_mood: XiaoBaoMascotMood,
        model: str,
        provider_response_id: str | None,
        token_usage: XiaoBaoTokenUsage | None,
    ) -> XiaoBaoMessage | None:
        doc = await self._collection.find_one_and_update(
            {"_id": _oid(message_id), "status": XiaoBaoMessageStatus.GENERATING},
            {
                "$set": {
                    "status": XiaoBaoMessageStatus.COMPLETE,
                    "content": content,
                    "context_references": [item.model_dump(mode="json") for item in references],
                    "proposal_ids": proposal_ids,
                    "completed_actions": [
                        item.model_dump(mode="json") for item in completed_actions
                    ],
                    "mascot_mood": mascot_mood.value,
                    "model": model,
                    "provider_response_id": provider_response_id,
                    "token_usage": token_usage.model_dump(mode="json") if token_usage else None,
                    "updated_at": utc_now(),
                    "error_code": None,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoMessage.model_validate(doc) if doc else None

    async def mark_terminal(
        self, message_id: MongoId, status: XiaoBaoMessageStatus, error_code: str
    ) -> XiaoBaoMessage | None:
        doc = await self._collection.find_one_and_update(
            {"_id": _oid(message_id), "status": XiaoBaoMessageStatus.GENERATING},
            {"$set": {"status": status, "error_code": error_code, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoMessage.model_validate(doc) if doc else None

    async def restart(self, message_id: MongoId) -> XiaoBaoMessage | None:
        doc = await self._collection.find_one_and_update(
            {
                "_id": _oid(message_id),
                "status": {"$in": [XiaoBaoMessageStatus.FAILED, XiaoBaoMessageStatus.CANCELLED]},
            },
            {
                "$set": {
                    "status": XiaoBaoMessageStatus.GENERATING,
                    "content": "",
                    "context_references": [],
                    "proposal_ids": [],
                    "completed_actions": [],
                    "mascot_mood": None,
                    "error_code": None,
                    "updated_at": utc_now(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoMessage.model_validate(doc) if doc else None


class XiaoBaoProposalRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.xiaobao_proposals_collection_name]

    async def create(self, proposal: XiaoBaoProposal) -> XiaoBaoProposal:
        result = await self._collection.insert_one(
            proposal.model_dump(mode="python", by_alias=True, exclude_none=True)
        )
        doc = await self._collection.find_one({"_id": result.inserted_id})
        return XiaoBaoProposal.model_validate(doc)

    async def get_owned(self, proposal_id: MongoId, owner: UserType) -> XiaoBaoProposal | None:
        doc = await self._collection.find_one({"_id": _oid(proposal_id), "owner_user_type": owner})
        return XiaoBaoProposal.model_validate(doc) if doc else None

    async def list_for_conversation(self, conversation_id: MongoId) -> list[XiaoBaoProposal]:
        docs = (
            await self._collection.find({"conversation_id": str(conversation_id)})
            .sort("created_at", ASCENDING)
            .to_list(length=None)
        )
        return [XiaoBaoProposal.model_validate(doc) for doc in docs]

    async def update_pending(
        self, proposal_id: MongoId, owner: UserType, payload: dict[str, Any]
    ) -> XiaoBaoProposal | None:
        doc = await self._collection.find_one_and_update(
            {
                "_id": _oid(proposal_id),
                "owner_user_type": owner,
                "status": XiaoBaoProposalStatus.PENDING,
            },
            {"$set": {"payload": payload, "updated_at": utc_now()}, "$inc": {"revision": 1}},
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoProposal.model_validate(doc) if doc else None

    async def claim_acceptance(
        self, proposal_id: MongoId, owner: UserType
    ) -> XiaoBaoProposal | None:
        doc = await self._collection.find_one_and_update(
            {
                "_id": _oid(proposal_id),
                "owner_user_type": owner,
                "status": XiaoBaoProposalStatus.PENDING,
            },
            {"$set": {"status": XiaoBaoProposalStatus.ACCEPTING, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoProposal.model_validate(doc) if doc else None

    async def mark_accepted(
        self, proposal_id: MongoId, created_entity_id: MongoId
    ) -> XiaoBaoProposal | None:
        now = utc_now()
        doc = await self._collection.find_one_and_update(
            {"_id": _oid(proposal_id), "status": XiaoBaoProposalStatus.ACCEPTING},
            {
                "$set": {
                    "status": XiaoBaoProposalStatus.ACCEPTED,
                    "created_entity_id": str(created_entity_id),
                    "decided_at": now,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoProposal.model_validate(doc) if doc else None

    async def release_acceptance(self, proposal_id: MongoId) -> None:
        await self._collection.update_one(
            {"_id": _oid(proposal_id), "status": XiaoBaoProposalStatus.ACCEPTING},
            {"$set": {"status": XiaoBaoProposalStatus.PENDING, "updated_at": utc_now()}},
        )

    async def reject_pending(self, proposal_id: MongoId, owner: UserType) -> XiaoBaoProposal | None:
        now = utc_now()
        doc = await self._collection.find_one_and_update(
            {
                "_id": _oid(proposal_id),
                "owner_user_type": owner,
                "status": XiaoBaoProposalStatus.PENDING,
            },
            {
                "$set": {
                    "status": XiaoBaoProposalStatus.REJECTED,
                    "decided_at": now,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return XiaoBaoProposal.model_validate(doc) if doc else None


class XiaoBaoRateLimitRepository:
    def __init__(self, db: Annotated[AsyncDB, Depends(get_db)]) -> None:
        self._collection = db[settings.xiaobao_rate_limits_collection_name]

    async def consume(self, owner: UserType) -> bool:
        now = utc_now()
        window_seconds = settings.xiaobao_rate_limit_window_seconds
        timestamp = int(now.timestamp())
        window_start = datetime.fromtimestamp(timestamp - timestamp % window_seconds, tz=now.tzinfo)
        expires_at = window_start + timedelta(seconds=window_seconds * 2)
        doc = await self._collection.find_one_and_update(
            {"owner_user_type": owner, "window_start": window_start},
            {
                "$inc": {"count": 1},
                "$setOnInsert": {"window_start": window_start, "expires_at": expires_at},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return bool(doc and int(doc["count"]) <= settings.xiaobao_rate_limit_requests)


async def ensure_xiaobao_indexes(db: AsyncDB) -> None:
    conversations = db[settings.xiaobao_conversations_collection_name]
    messages = db[settings.xiaobao_messages_collection_name]
    proposals = db[settings.xiaobao_proposals_collection_name]
    rate_limits = db[settings.xiaobao_rate_limits_collection_name]
    await conversations.create_index([("owner_user_type", ASCENDING), ("updated_at", DESCENDING)])
    await conversations.create_index(
        [("owner_user_type", ASCENDING), ("purpose", ASCENDING)],
        unique=True,
        partialFilterExpression={"purpose": XiaoBaoConversationPurpose.ROUTINE_INBOX.value},
        name="one_xiaobao_routine_inbox_per_owner",
    )
    await messages.create_index([("conversation_id", ASCENDING), ("created_at", ASCENDING)])
    await messages.create_index(
        [("conversation_id", ASCENDING), ("client_message_id", ASCENDING)],
        unique=True,
        partialFilterExpression={"client_message_id": {"$type": "string"}},
    )
    await messages.create_index(
        [("conversation_id", ASCENDING)],
        unique=True,
        partialFilterExpression={
            "role": XiaoBaoMessageRole.ASSISTANT.value,
            "status": XiaoBaoMessageStatus.GENERATING.value,
        },
        name="one_active_xiaobao_generation",
    )
    await messages.create_index(
        [("routine_run_id", ASCENDING)],
        unique=True,
        partialFilterExpression={"routine_run_id": {"$type": "string"}},
        name="one_xiaobao_message_per_routine_run",
    )
    await messages.create_index(
        [("conversation_id", ASCENDING), ("read_at", ASCENDING), ("created_at", DESCENDING)],
        partialFilterExpression={"source": XiaoBaoMessageSource.ROUTINE.value},
        name="xiaobao_routine_inbox_unread",
    )
    await messages.create_index(
        [
            ("routine_id", ASCENDING),
            ("conversation_id", ASCENDING),
            ("status", ASCENDING),
            ("read_at", ASCENDING),
            ("delivered_at", ASCENDING),
            ("created_at", ASCENDING),
        ],
        partialFilterExpression={"source": XiaoBaoMessageSource.ROUTINE.value},
        name="xiaobao_routine_unread_inactivity",
    )
    await messages.create_index(
        [("conversation_id", ASCENDING), ("created_at", DESCENDING), ("_id", DESCENDING)],
        partialFilterExpression={
            "source": XiaoBaoMessageSource.ROUTINE.value,
            "status": XiaoBaoMessageStatus.COMPLETE.value,
        },
        name="xiaobao_routine_inbox_pages",
    )
    await messages.create_index(
        [
            ("conversation_id", ASCENDING),
            ("routine_id", ASCENDING),
            ("created_at", DESCENDING),
            ("_id", DESCENDING),
        ],
        partialFilterExpression={
            "source": XiaoBaoMessageSource.ROUTINE.value,
            "status": XiaoBaoMessageStatus.COMPLETE.value,
        },
        name="xiaobao_filtered_routine_inbox_pages",
    )
    await proposals.create_index(
        [("owner_user_type", ASCENDING), ("conversation_id", ASCENDING), ("status", ASCENDING)]
    )
    await proposals.create_index([("message_id", ASCENDING), ("created_at", ASCENDING)])
    await rate_limits.create_index(
        [("owner_user_type", ASCENDING), ("window_start", ASCENDING)], unique=True
    )
    await rate_limits.create_index("expires_at", expireAfterSeconds=0)
