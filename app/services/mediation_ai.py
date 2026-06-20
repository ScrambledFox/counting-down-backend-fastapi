import json
from typing import Annotated

from fastapi import Depends

from app.core.config import get_settings
from app.integrations.openai_client import OpenAIClient
from app.prompts.mediation_prompts import (
    COMMENT_RESPONSE_SYSTEM_PROMPT,
    PRIVATE_REFLECTION_PROMPT_VERSION,
    PRIVATE_REFLECTION_SYSTEM_PROMPT,
    SHARED_MEDIATION_PROMPT_VERSION,
    SHARED_MEDIATION_SYSTEM_PROMPT,
)
from app.repositories.mediation import (
    MediationAIRepository,
    MediationCommentRepository,
    MediationJobRepository,
    MediationModerationRepository,
    MediationPerspectiveRepository,
    MediationSessionRepository,
)
from app.schemas.v1.exceptions import NotFoundException
from app.schemas.v1.mediation import (
    AIJobStatus,
    CommentAIResponseOutput,
    MediationAdvice,
    MediationAIJob,
    MediationAIJobType,
    MediationAIReflection,
    MediationEntityType,
    MediationModerationResult,
    MediationProvider,
    MediationSessionStatus,
    PerspectiveStatus,
    PrivateReflectionOutput,
    SafetyStatus,
    SharedMediationAdviceOutput,
)
from app.services.mediation_safety import MediationSafetyService, ModerationDecision
from app.util.time import utc_now

settings = get_settings()


class MediationAIService:
    def __init__(
        self,
        session_repo: Annotated[MediationSessionRepository, Depends()],
        perspective_repo: Annotated[MediationPerspectiveRepository, Depends()],
        ai_repo: Annotated[MediationAIRepository, Depends()],
        comment_repo: Annotated[MediationCommentRepository, Depends()],
        moderation_repo: Annotated[MediationModerationRepository, Depends()],
        job_repo: Annotated[MediationJobRepository, Depends()],
        safety_service: Annotated[MediationSafetyService, Depends()],
        openai_client: Annotated[OpenAIClient, Depends()],
    ) -> None:
        self._sessions = session_repo
        self._perspectives = perspective_repo
        self._ai = ai_repo
        self._comments = comment_repo
        self._moderation = moderation_repo
        self._jobs = job_repo
        self._safety = safety_service
        self._openai = openai_client

    async def process_job(self, job: MediationAIJob) -> None:
        if job.job_type == MediationAIJobType.PERSPECTIVE_MODERATION:
            await self.moderate_perspective_submission(job)
        elif job.job_type == MediationAIJobType.PRIVATE_REFLECTION:
            await self.generate_private_reflection(job)
        elif job.job_type == MediationAIJobType.SHARED_MEDIATION_ADVICE:
            await self.generate_shared_advice(job)
        elif job.job_type == MediationAIJobType.COMMENT_RESPONSE:
            await self.generate_comment_response(job)
        else:
            raise RuntimeError(f"Unsupported mediation job type: {job.job_type}")

    async def _create_job(
        self,
        *,
        job_type: MediationAIJobType,
        session_id: str,
        source_entity_id: str | None,
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
        self, session_id: str, perspective_id: str
    ) -> MediationAIJob:
        return await self._create_job(
            job_type=MediationAIJobType.PRIVATE_REFLECTION,
            session_id=session_id,
            source_entity_id=perspective_id,
            source_entity_type=MediationEntityType.PERSPECTIVE.value,
            idempotency_key=f"private_reflection:{session_id}:{perspective_id}",
        )

    async def _create_shared_advice_job(self, session_id: str) -> MediationAIJob:
        return await self._create_job(
            job_type=MediationAIJobType.SHARED_MEDIATION_ADVICE,
            session_id=session_id,
            source_entity_id=None,
            source_entity_type=None,
            idempotency_key=f"shared_advice:{session_id}",
        )

    async def _persist_perspective_moderation(
        self, job: MediationAIJob, decision: ModerationDecision
    ) -> MediationModerationResult:
        result = MediationModerationResult(
            entity_type=MediationEntityType.PERSPECTIVE,
            entity_id=job.source_entity_id or f"pending_perspective:{job.id}",
            provider=MediationProvider.INTERNAL
            if decision.raw_result is None
            else MediationProvider.OPENAI,
            flagged=decision.flagged,
            safety_status=decision.safety_status,
            categories=decision.categories,
            category_scores=decision.category_scores,
            raw_result=decision.raw_result,
            created_at=utc_now(),
        )
        return await self._moderation.insert(result)

    async def moderate_perspective_submission(self, job: MediationAIJob) -> None:
        if not job.source_entity_id:
            raise RuntimeError("Perspective moderation job is missing source_entity_id")
        perspective = await self._perspectives.get_by_id(job.source_entity_id)
        if not perspective:
            raise NotFoundException("Mediation perspective", job.source_entity_id)
        if perspective.status == PerspectiveStatus.FLAGGED:
            return
        if perspective.status == PerspectiveStatus.LOCKED:
            await self._create_private_reflection_job(job.session_id, str(perspective.id))
            locked_count = await self._perspectives.count_locked_for_session(job.session_id)
            if locked_count >= 2:
                await self._sessions.set_status(
                    job.session_id, MediationSessionStatus.AI_MEDIATION_PROCESSING
                )
                await self._create_shared_advice_job(job.session_id)
            return
        if perspective.status != PerspectiveStatus.SUBMITTED_PENDING_REVIEW:
            raise RuntimeError("Perspective moderation requires a submitted perspective")

        decision = await self._safety.moderate_perspective(perspective.combined_text())
        moderation = await self._persist_perspective_moderation(job, decision)
        if decision.should_block_normal_mediation:
            await self._perspectives.mark_flagged(str(perspective.id), str(moderation.id))
            await self._sessions.set_safety_status(job.session_id, SafetyStatus.BLOCKED)
            return

        locked = await self._perspectives.lock_perspective(
            str(perspective.id), str(moderation.id)
        )
        if not locked:
            return

        await self._create_private_reflection_job(job.session_id, str(locked.id))
        locked_count = await self._perspectives.count_locked_for_session(job.session_id)
        if locked_count == 1:
            await self._sessions.set_status(
                job.session_id, MediationSessionStatus.PARTIAL_PERSPECTIVE_SUBMITTED
            )
        else:
            await self._sessions.set_status(
                job.session_id, MediationSessionStatus.AI_MEDIATION_PROCESSING
            )
            await self._create_shared_advice_job(job.session_id)

    async def _persist_output_moderation(
        self,
        *,
        output_text: str,
        entity_type: MediationEntityType,
        entity_id: str,
    ) -> MediationModerationResult:
        decision = await self._safety.moderate_ai_output(output_text)
        result = MediationModerationResult(
            entity_type=entity_type,
            entity_id=entity_id,
            provider=MediationProvider.INTERNAL
            if decision.raw_result is None
            else MediationProvider.OPENAI,
            flagged=decision.flagged,
            safety_status=decision.safety_status,
            categories=decision.categories,
            category_scores=decision.category_scores,
            raw_result=decision.raw_result,
            created_at=utc_now(),
        )
        return await self._moderation.insert(result)

    async def _block_if_output_unsafe(
        self, job: MediationAIJob, decision: ModerationDecision
    ) -> None:
        if decision.should_block_normal_mediation:
            await self._sessions.set_safety_status(job.session_id, SafetyStatus.BLOCKED)
            raise RuntimeError("AI output blocked by moderation")

    async def generate_private_reflection(self, job: MediationAIJob) -> None:
        if not job.source_entity_id:
            raise RuntimeError("Private reflection job is missing source_entity_id")
        perspective = await self._perspectives.get_by_id(job.source_entity_id)
        if not perspective:
            raise NotFoundException("Mediation perspective", job.source_entity_id)
        user_input = json.dumps(
            {
                "session_id": job.session_id,
                "user_type": perspective.user_type,
                "perspective": perspective.model_dump(mode="json"),
            },
            ensure_ascii=True,
        )
        result = await self._openai.create_structured_response(
            model=settings.openai_model_mediation,
            system_prompt=PRIVATE_REFLECTION_SYSTEM_PROMPT,
            user_input=user_input,
            json_schema=PrivateReflectionOutput.model_json_schema(),
            schema_name="private_reflection",
            safety_identifier=f"mediation:{job.session_id}:{perspective.user_type}",
        )
        content = PrivateReflectionOutput.model_validate(result.parsed)
        decision = await self._safety.moderate_ai_output(content.model_dump_json())
        await self._block_if_output_unsafe(job, decision)
        moderation = await self._persist_output_moderation(
            output_text=content.model_dump_json(),
            entity_type=MediationEntityType.AI_REFLECTION,
            entity_id=f"pending_reflection:{job.id}",
        )
        await self._ai.insert_reflection(
            MediationAIReflection(
                session_id=job.session_id,
                perspective_id=str(perspective.id),
                recipient_user_type=perspective.user_type,
                content=content,
                model=settings.openai_model_mediation,
                prompt_version=PRIVATE_REFLECTION_PROMPT_VERSION,
                openai_response_id=result.response_id,
                created_at=utc_now(),
                moderation_result_id=str(moderation.id),
            )
        )

    async def generate_shared_advice(self, job: MediationAIJob) -> None:
        session = await self._sessions.get_by_id(job.session_id)
        if not session:
            raise NotFoundException("Mediation session", job.session_id)
        perspectives = await self._perspectives.list_locked_for_session(job.session_id)
        if len(perspectives) != 2:
            raise RuntimeError("Shared advice requires both perspectives")
        user_input = json.dumps(
            {
                "session": session.model_dump(mode="json"),
                "perspectives": [item.model_dump(mode="json") for item in perspectives],
            },
            ensure_ascii=True,
        )
        result = await self._openai.create_structured_response(
            model=settings.openai_model_mediation,
            system_prompt=SHARED_MEDIATION_SYSTEM_PROMPT,
            user_input=user_input,
            json_schema=SharedMediationAdviceOutput.model_json_schema(),
            schema_name="shared_mediation_advice",
            safety_identifier=f"mediation:{job.session_id}:shared",
        )
        content = SharedMediationAdviceOutput.model_validate(result.parsed)
        moderation = await self._persist_output_moderation(
            output_text=content.model_dump_json(),
            entity_type=MediationEntityType.AI_ADVICE,
            entity_id=f"pending_advice:{job.id}",
        )
        advice = await self._ai.insert_advice(
            MediationAdvice(
                session_id=job.session_id,
                content=content,
                model=settings.openai_model_mediation,
                prompt_version=SHARED_MEDIATION_PROMPT_VERSION,
                openai_response_id=result.response_id,
                created_at=utc_now(),
                moderation_result_id=str(moderation.id),
            )
        )
        await self._sessions.set_latest_advice(job.session_id, str(advice.id))

    async def generate_comment_response(self, job: MediationAIJob) -> None:
        if not job.source_entity_id:
            raise RuntimeError("Comment response job is missing source_entity_id")
        session = await self._sessions.get_by_id(job.session_id)
        if not session:
            raise NotFoundException("Mediation session", job.session_id)
        comment = await self._comments.get_by_id(job.source_entity_id)
        if not comment:
            raise NotFoundException("Mediation comment", job.source_entity_id)
        advice = await self._ai.get_latest_advice(job.session_id)
        comments = await self._comments.list_for_session(job.session_id)
        user_input = json.dumps(
            {
                "session": session.model_dump(mode="json"),
                "advice": advice.content.model_dump(mode="json") if advice else None,
                "new_comment": comment.model_dump(mode="json"),
                "recent_comments": [item.model_dump(mode="json") for item in comments[-20:]],
            },
            ensure_ascii=True,
        )
        result = await self._openai.create_structured_response(
            model=settings.openai_model_mediation,
            system_prompt=COMMENT_RESPONSE_SYSTEM_PROMPT,
            user_input=user_input,
            json_schema=CommentAIResponseOutput.model_json_schema(),
            schema_name="comment_ai_response",
            safety_identifier=f"mediation:{job.session_id}:comment",
        )
        content = CommentAIResponseOutput.model_validate(result.parsed)
        decision = await self._safety.moderate_ai_output(content.model_dump_json())
        await self._block_if_output_unsafe(job, decision)
        await self._persist_output_moderation(
            output_text=content.model_dump_json(),
            entity_type=MediationEntityType.AI_COMMENT,
            entity_id=f"pending_ai_comment:{job.id}",
        )
        await self._comments.create_ai_comment(
            job.session_id,
            str(comment.id),
            content.response,
            str(job.id) if job.id else None,
        )
        if content.should_pause_discussion:
            await self._sessions.set_safety_status(job.session_id, SafetyStatus.NEEDS_REVIEW)
        elif session.status == MediationSessionStatus.AI_ADVICE_AVAILABLE:
            await self._sessions.set_status(job.session_id, MediationSessionStatus.DISCUSSION_OPEN)
