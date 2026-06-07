from typing import Annotated, Literal

from fastapi import Depends

from app.repositories.mediation import (
    MediationAIRepository,
    MediationCommentRepository,
    MediationJobRepository,
    MediationModerationRepository,
    MediationPerspectiveRepository,
    MediationSessionRepository,
)
from app.schemas.v1.base import MongoId
from app.schemas.v1.exceptions import ConflictException, NotFoundException
from app.schemas.v1.mediation import (
    AdviceEndpointResponse,
    AIJobStatus,
    CommentCreateResponse,
    MediationAIJob,
    MediationAIJobType,
    MediationCommentCreate,
    MediationCommentResponse,
    MediationEntityType,
    MediationModerationResult,
    MediationPerspective,
    MediationPerspectiveDraftUpdate,
    MediationProvider,
    MediationSession,
    MediationSessionCreate,
    MediationSessionDetailResponse,
    MediationSessionListItem,
    MediationSessionStatus,
    PerspectiveResponse,
    PerspectiveStatus,
    ReflectionEndpointResponse,
    SafetyStatus,
    SubmitPerspectiveResponse,
)
from app.schemas.v1.user import UserType
from app.services.mediation_safety import MediationSafetyService, ModerationDecision
from app.util.time import utc_now
from app.util.user import get_other_user_type

ALL_MEDIATION_USER_TYPES = {UserType.JORIS, UserType.DANFENG}


class MediationService:
    def __init__(
        self,
        session_repo: Annotated[MediationSessionRepository, Depends()],
        perspective_repo: Annotated[MediationPerspectiveRepository, Depends()],
        ai_repo: Annotated[MediationAIRepository, Depends()],
        comment_repo: Annotated[MediationCommentRepository, Depends()],
        moderation_repo: Annotated[MediationModerationRepository, Depends()],
        job_repo: Annotated[MediationJobRepository, Depends()],
        safety_service: Annotated[MediationSafetyService, Depends()],
    ) -> None:
        self._sessions = session_repo
        self._perspectives = perspective_repo
        self._ai = ai_repo
        self._comments = comment_repo
        self._moderation = moderation_repo
        self._jobs = job_repo
        self._safety = safety_service

    async def _get_session_or_404(self, session_id: MongoId) -> MediationSession:
        session = await self._sessions.get_by_id(session_id)
        if not session:
            raise NotFoundException("Mediation session", session_id)
        return session

    def _assert_session_writable(self, session: MediationSession) -> None:
        if session.status == MediationSessionStatus.ARCHIVED:
            raise ConflictException("Session is archived")
        if session.status == MediationSessionStatus.RESOLVED:
            raise ConflictException("Session is resolved")
        if session.safety_status == SafetyStatus.BLOCKED:
            raise ConflictException("Session is blocked for safety review")

    def _agreement_set(self, values: list[UserType]) -> set[UserType]:
        return {UserType(value) for value in values}

    def _agreement_flags(
        self, values: list[UserType], current_user_type: UserType
    ) -> tuple[bool, bool]:
        marked = self._agreement_set(values)
        other_user_type = get_other_user_type(current_user_type)
        return current_user_type in marked, other_user_type in marked

    async def _persist_moderation(
        self,
        *,
        decision: ModerationDecision,
        entity_type: MediationEntityType,
        entity_id: MongoId | str,
        provider: MediationProvider | None = None,
    ) -> MediationModerationResult:
        result = MediationModerationResult(
            entity_type=entity_type,
            entity_id=entity_id,
            provider=provider
            or (
                MediationProvider.INTERNAL
                if decision.raw_result is None
                else MediationProvider.OPENAI
            ),
            flagged=decision.flagged,
            safety_status=decision.safety_status,
            categories=decision.categories,
            category_scores=decision.category_scores,
            raw_result=decision.raw_result,
            created_at=utc_now(),
        )
        return await self._moderation.insert(result)

    async def _create_job(
        self,
        *,
        job_type: MediationAIJobType,
        session_id: MongoId,
        source_entity_id: MongoId | None,
        source_entity_type: str | None,
        idempotency_key: str,
    ) -> MediationAIJob:
        now = utc_now()
        return await self._jobs.create_job_if_not_exists(
            MediationAIJob(
                job_type=job_type,
                status=AIJobStatus.PENDING,
                session_id=session_id,
                source_entity_id=source_entity_id,
                source_entity_type=source_entity_type,
                idempotency_key=idempotency_key,
                created_at=now,
                updated_at=now,
            )
        )

    async def _create_private_reflection_job(
        self, session_id: MongoId, perspective_id: MongoId
    ) -> MediationAIJob:
        return await self._create_job(
            job_type=MediationAIJobType.PRIVATE_REFLECTION,
            session_id=session_id,
            source_entity_id=perspective_id,
            source_entity_type=MediationEntityType.PERSPECTIVE.value,
            idempotency_key=f"private_reflection:{session_id}:{perspective_id}",
        )

    async def _create_perspective_moderation_job(
        self, session_id: MongoId, perspective_id: MongoId
    ) -> MediationAIJob:
        return await self._create_job(
            job_type=MediationAIJobType.PERSPECTIVE_MODERATION,
            session_id=session_id,
            source_entity_id=perspective_id,
            source_entity_type=MediationEntityType.PERSPECTIVE.value,
            idempotency_key=f"perspective_moderation:{session_id}:{perspective_id}",
        )

    async def _create_shared_advice_job(self, session_id: MongoId) -> MediationAIJob:
        return await self._create_job(
            job_type=MediationAIJobType.SHARED_MEDIATION_ADVICE,
            session_id=session_id,
            source_entity_id=None,
            source_entity_type=None,
            idempotency_key=f"shared_advice:{session_id}",
        )

    async def _create_comment_response_job(
        self, session_id: MongoId, comment_id: MongoId
    ) -> MediationAIJob:
        return await self._create_job(
            job_type=MediationAIJobType.COMMENT_RESPONSE,
            session_id=session_id,
            source_entity_id=comment_id,
            source_entity_type=MediationEntityType.COMMENT.value,
            idempotency_key=f"comment_response:{session_id}:{comment_id}",
        )

    def _other_status(
        self, perspectives: list[MediationPerspective], other_user_type: UserType
    ) -> Literal["NOT_STARTED", "DRAFT", "SUBMITTED"]:
        other = next((item for item in perspectives if item.user_type == other_user_type), None)
        if not other:
            return "NOT_STARTED"
        if other.status in {
            PerspectiveStatus.LOCKED,
            PerspectiveStatus.SUBMITTED_PENDING_REVIEW,
        }:
            return "SUBMITTED"
        return "DRAFT" if other.status == PerspectiveStatus.DRAFT else "NOT_STARTED"

    async def _reflection_status(
        self, session_id: MongoId, current_user_type: UserType
    ) -> tuple[Literal["NONE", "PROCESSING", "AVAILABLE", "FAILED"], object | None]:
        reflection = await self._ai.get_reflection_for_user(session_id, current_user_type)
        if reflection:
            return "AVAILABLE", reflection.content
        job = await self._jobs.get_latest_by_type(session_id, MediationAIJobType.PRIVATE_REFLECTION)
        if job and job.status in {AIJobStatus.PENDING, AIJobStatus.PROCESSING}:
            return "PROCESSING", None
        if job and job.status == AIJobStatus.FAILED:
            return "FAILED", None
        return "NONE", None

    async def _advice_status(
        self, session: MediationSession
    ) -> tuple[Literal["NONE", "PROCESSING", "AVAILABLE", "FAILED", "BLOCKED"], object | None]:
        if session.safety_status == SafetyStatus.BLOCKED:
            return "BLOCKED", None
        advice = await self._ai.get_latest_advice(str(session.id))
        if advice:
            return "AVAILABLE", advice.content
        job = await self._jobs.get_latest_by_type(
            str(session.id), MediationAIJobType.SHARED_MEDIATION_ADVICE
        )
        if job and job.status in {AIJobStatus.PENDING, AIJobStatus.PROCESSING}:
            return "PROCESSING", None
        if job and job.status == AIJobStatus.FAILED:
            return "FAILED", None
        return "NONE", None

    async def create_session(
        self, current_user_type: UserType, payload: MediationSessionCreate
    ) -> MediationSession:
        now = utc_now()
        return await self._sessions.create(
            MediationSession(
                title=payload.title,
                description=payload.description,
                created_by_user_type=current_user_type,
                status=MediationSessionStatus.AWAITING_PERSPECTIVES,
                safety_status=SafetyStatus.NORMAL,
                created_at=now,
                updated_at=now,
            )
        )

    async def list_sessions(self, current_user_type: UserType) -> list[MediationSessionListItem]:
        sessions = await self._sessions.list_all()
        result: list[MediationSessionListItem] = []
        other_user_type = get_other_user_type(current_user_type)
        for session in sessions:
            session_id = str(session.id)
            perspectives = await self._perspectives.list_for_session(session_id)
            has_my_perspective = any(item.user_type == current_user_type for item in perspectives)
            has_other_perspective = any(item.user_type == other_user_type for item in perspectives)
            has_marked_resolved, other_has_marked_resolved = self._agreement_flags(
                session.resolved_by_user_types, current_user_type
            )
            has_marked_archived, other_has_marked_archived = self._agreement_flags(
                session.archived_by_user_types, current_user_type
            )
            result.append(
                MediationSessionListItem(
                    id=session_id,
                    title=session.title,
                    description=session.description,
                    created_by_user_type=session.created_by_user_type,
                    status=session.status,
                    safety_status=session.safety_status,
                    has_my_perspective=has_my_perspective,
                    has_other_perspective=has_other_perspective,
                    has_advice=session.latest_advice_id is not None,
                    has_marked_resolved=has_marked_resolved,
                    other_has_marked_resolved=other_has_marked_resolved,
                    has_marked_archived=has_marked_archived,
                    other_has_marked_archived=other_has_marked_archived,
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                    resolved_at=session.resolved_at,
                    archived_at=session.archived_at,
                )
            )
        return result

    async def get_session_detail(
        self, session_id: MongoId, current_user_type: UserType
    ) -> MediationSessionDetailResponse:
        session = await self._get_session_or_404(session_id)
        perspectives = await self._perspectives.list_for_session(session_id)
        my_perspective = next(
            (item for item in perspectives if item.user_type == current_user_type), None
        )
        other_user_type = get_other_user_type(current_user_type)
        reflection_status, reflection = await self._reflection_status(session_id, current_user_type)
        advice_status, advice = await self._advice_status(session)
        has_marked_resolved, other_has_marked_resolved = self._agreement_flags(
            session.resolved_by_user_types, current_user_type
        )
        has_marked_archived, other_has_marked_archived = self._agreement_flags(
            session.archived_by_user_types, current_user_type
        )
        comments = (
            await self._comments.list_for_session(session_id)
            if advice_status == "AVAILABLE"
            or session.status == MediationSessionStatus.DISCUSSION_OPEN
            else []
        )
        return MediationSessionDetailResponse(
            id=str(session.id),
            title=session.title,
            description=session.description,
            created_by_user_type=session.created_by_user_type,
            status=session.status,
            safety_status=session.safety_status,
            created_at=session.created_at,
            updated_at=session.updated_at,
            resolved_at=session.resolved_at,
            archived_at=session.archived_at,
            has_marked_resolved=has_marked_resolved,
            other_has_marked_resolved=other_has_marked_resolved,
            has_marked_archived=has_marked_archived,
            other_has_marked_archived=other_has_marked_archived,
            latest_advice_id=session.latest_advice_id,
            my_perspective=PerspectiveResponse(**my_perspective.model_dump())
            if my_perspective
            else None,
            my_reflection_status=reflection_status,
            my_reflection=reflection,
            other_user_type=other_user_type,
            other_perspective_status=self._other_status(perspectives, other_user_type),
            advice_status=advice_status,
            advice=advice,
            comments=[MediationCommentResponse(**comment.model_dump()) for comment in comments],
        )

    async def get_my_perspective(
        self, session_id: MongoId, current_user_type: UserType
    ) -> MediationPerspective | None:
        await self._get_session_or_404(session_id)
        return await self._perspectives.get_by_session_and_user(session_id, current_user_type)

    async def upsert_my_perspective_draft(
        self,
        session_id: MongoId,
        current_user_type: UserType,
        payload: MediationPerspectiveDraftUpdate,
    ) -> MediationPerspective:
        session = await self._get_session_or_404(session_id)
        self._assert_session_writable(session)
        existing = await self._perspectives.get_by_session_and_user(session_id, current_user_type)
        if existing and existing.status in {
            PerspectiveStatus.LOCKED,
            PerspectiveStatus.SUBMITTED_PENDING_REVIEW,
        }:
            raise ConflictException("Perspective is already submitted")
        return await self._perspectives.upsert_draft(
            session_id,
            current_user_type,
            payload.model_dump(),
        )

    async def submit_my_perspective(
        self, session_id: MongoId, current_user_type: UserType
    ) -> SubmitPerspectiveResponse:
        session = await self._get_session_or_404(session_id)
        self._assert_session_writable(session)
        perspective = await self._perspectives.get_by_session_and_user(
            session_id, current_user_type
        )
        if not perspective:
            raise ConflictException("Create a draft before submitting")
        if perspective.status in {
            PerspectiveStatus.LOCKED,
            PerspectiveStatus.SUBMITTED_PENDING_REVIEW,
        }:
            raise ConflictException("Perspective is already submitted")

        perspective_text = perspective.combined_text()
        if len(perspective_text) < 50:
            raise ConflictException("Perspective must contain at least 50 characters")

        pending = await self._perspectives.mark_pending_review(str(perspective.id))
        if not pending:
            raise ConflictException("Perspective is already submitted")

        created_jobs = [await self._create_perspective_moderation_job(session_id, str(pending.id))]

        return SubmitPerspectiveResponse(
            perspective=PerspectiveResponse(**pending.model_dump()),
            session=session,
            created_jobs=created_jobs,
        )

    async def get_my_reflection(
        self, session_id: MongoId, current_user_type: UserType
    ) -> ReflectionEndpointResponse:
        await self._get_session_or_404(session_id)
        status, reflection = await self._reflection_status(session_id, current_user_type)
        return ReflectionEndpointResponse(status=status, reflection=reflection)

    async def get_advice(
        self, session_id: MongoId, current_user_type: UserType
    ) -> AdviceEndpointResponse:
        del current_user_type
        session = await self._get_session_or_404(session_id)
        status, advice = await self._advice_status(session)
        message = (
            "Normal mediation is blocked because this session may involve safety risk."
            if status == "BLOCKED"
            else None
        )
        return AdviceEndpointResponse(status=status, advice=advice, message=message)

    async def _assert_comments_available(self, session: MediationSession) -> None:
        if session.status not in {
            MediationSessionStatus.AI_ADVICE_AVAILABLE,
            MediationSessionStatus.DISCUSSION_OPEN,
            MediationSessionStatus.RESOLVED,
            MediationSessionStatus.ARCHIVED,
        }:
            raise ConflictException("Comments are available only after advice is ready")
        if session.safety_status == SafetyStatus.BLOCKED:
            raise ConflictException("Session is blocked for safety review")

    async def list_comments(
        self, session_id: MongoId, current_user_type: UserType
    ) -> list[MediationCommentResponse]:
        del current_user_type
        session = await self._get_session_or_404(session_id)
        await self._assert_comments_available(session)
        comments = await self._comments.list_for_session(session_id)
        return [MediationCommentResponse(**comment.model_dump()) for comment in comments]

    async def create_comment(
        self,
        session_id: MongoId,
        current_user_type: UserType,
        payload: MediationCommentCreate,
    ) -> CommentCreateResponse:
        return await self._create_comment_or_reply(session_id, None, current_user_type, payload)

    async def create_reply(
        self,
        session_id: MongoId,
        parent_comment_id: MongoId,
        current_user_type: UserType,
        payload: MediationCommentCreate,
    ) -> CommentCreateResponse:
        parent = await self._comments.get_by_id(parent_comment_id)
        if not parent or parent.session_id != session_id:
            raise NotFoundException("Mediation comment", parent_comment_id)
        return await self._create_comment_or_reply(
            session_id, parent_comment_id, current_user_type, payload
        )

    async def _create_comment_or_reply(
        self,
        session_id: MongoId,
        parent_comment_id: MongoId | None,
        current_user_type: UserType,
        payload: MediationCommentCreate,
    ) -> CommentCreateResponse:
        session = await self._get_session_or_404(session_id)
        await self._assert_comments_available(session)
        decision = await self._safety.moderate_comment(payload.content)
        moderation = await self._persist_moderation(
            decision=decision,
            entity_type=MediationEntityType.COMMENT,
            entity_id=f"pending_comment:{session_id}",
        )
        if decision.should_block_normal_mediation:
            await self._sessions.set_safety_status(session_id, SafetyStatus.BLOCKED)
            raise ConflictException(decision.user_message or "Comment blocked for safety")

        comment = await self._comments.create_user_comment(
            session_id,
            parent_comment_id,
            current_user_type,
            payload.content,
            str(moderation.id),
        )
        job = await self._create_comment_response_job(session_id, str(comment.id))
        if session.status == MediationSessionStatus.AI_ADVICE_AVAILABLE:
            await self._sessions.set_status(session_id, MediationSessionStatus.DISCUSSION_OPEN)
        return CommentCreateResponse(
            comment=MediationCommentResponse(**comment.model_dump()),
            job=job,
        )

    async def resolve_session(
        self, session_id: MongoId, current_user_type: UserType
    ) -> MediationSession:
        session = await self._get_session_or_404(session_id)
        if session.status == MediationSessionStatus.ARCHIVED:
            raise ConflictException("Session is archived")
        if session.status == MediationSessionStatus.RESOLVED:
            return session

        resolved_by = self._agreement_set(session.resolved_by_user_types)
        resolved_by.add(current_user_type)
        finalize = resolved_by == ALL_MEDIATION_USER_TYPES
        updated = await self._sessions.mark_resolved(session_id, list(resolved_by), finalize)
        return updated or session

    async def unresolve_session(
        self, session_id: MongoId, current_user_type: UserType
    ) -> MediationSession:
        session = await self._get_session_or_404(session_id)
        if session.status == MediationSessionStatus.ARCHIVED:
            raise ConflictException("Session is archived")
        if session.status == MediationSessionStatus.RESOLVED:
            raise ConflictException("Session is already resolved")

        resolved_by = self._agreement_set(session.resolved_by_user_types)
        resolved_by.discard(current_user_type)
        updated = await self._sessions.unmark_resolved(session_id, list(resolved_by))
        return updated or session

    async def archive_session(
        self, session_id: MongoId, current_user_type: UserType
    ) -> MediationSession:
        session = await self._get_session_or_404(session_id)
        if session.status == MediationSessionStatus.ARCHIVED:
            raise ConflictException("Session is archived")

        archived_by = self._agreement_set(session.archived_by_user_types)
        archived_by.add(current_user_type)
        finalize = (
            session.status == MediationSessionStatus.RESOLVED
            or archived_by == ALL_MEDIATION_USER_TYPES
        )
        updated = await self._sessions.mark_archived(session_id, list(archived_by), finalize)
        return updated or session

    async def unarchive_session(
        self, session_id: MongoId, current_user_type: UserType
    ) -> MediationSession:
        session = await self._get_session_or_404(session_id)
        if session.status == MediationSessionStatus.ARCHIVED:
            raise ConflictException("Session is already archived")

        archived_by = self._agreement_set(session.archived_by_user_types)
        archived_by.discard(current_user_type)
        updated = await self._sessions.unmark_archived(session_id, list(archived_by))
        return updated or session
