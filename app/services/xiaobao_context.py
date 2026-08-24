import json
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends

from app.core.config import get_settings
from app.schemas.v1.mediation import MediationSessionStatus
from app.schemas.v1.user import UserType
from app.schemas.v1.xiaobao import (
    XiaoBaoContextItem,
    XiaoBaoContextReference,
    XiaoBaoContextReferenceType,
    XiaoBaoPrivateMediationContext,
    XiaoBaoRelationshipContext,
)
from app.services.mediation import MediationService
from app.services.relationship_care import RelationshipCareService
from app.services.relationship_profile import RelationshipProfileService
from app.services.todo import TodoService
from app.util.user import get_other_user_type

settings = get_settings()


@dataclass(frozen=True)
class AuthorizedXiaoBaoContext:
    public: XiaoBaoRelationshipContext
    private_mediation_by_key: dict[str, XiaoBaoPrivateMediationContext]


class RelationshipContextService:
    def __init__(
        self,
        relationship_care: Annotated[RelationshipCareService, Depends()],
        todos: Annotated[TodoService, Depends()],
        mediation: Annotated[MediationService, Depends()],
        relationship_profile: Annotated[RelationshipProfileService, Depends()],
    ) -> None:
        self._relationship_care = relationship_care
        self._todos = todos
        self._mediation = mediation
        self._relationship_profile = relationship_profile

    def _item(
        self,
        item_type: XiaoBaoContextReferenceType,
        item_id: str,
        title: str,
        data: dict[str, Any],
    ) -> XiaoBaoContextItem:
        return XiaoBaoContextItem(
            reference=XiaoBaoContextReference(
                key=f"{item_type.value.lower()}:{item_id}",
                type=item_type,
                id=item_id,
                title=title,
            ),
            data=data,
        )

    async def _mediation_context(
        self, current_user: UserType
    ) -> tuple[list[XiaoBaoContextItem], dict[str, XiaoBaoPrivateMediationContext]]:
        sessions = await self._mediation.list_sessions(current_user)
        active_statuses = {
            MediationSessionStatus.AWAITING_PERSPECTIVES,
            MediationSessionStatus.PARTIAL_PERSPECTIVE_SUBMITTED,
            MediationSessionStatus.BOTH_PERSPECTIVES_SUBMITTED,
            MediationSessionStatus.AI_MEDIATION_PROCESSING,
            MediationSessionStatus.AI_ADVICE_AVAILABLE,
            MediationSessionStatus.DISCUSSION_OPEN,
        }
        sessions.sort(
            key=lambda item: (
                0 if item.status in active_statuses else 1,
                -item.updated_at.timestamp(),
            )
        )
        selected = sessions[: settings.xiaobao_mediation_session_limit]
        public_items: list[XiaoBaoContextItem] = []
        private_items: dict[str, XiaoBaoPrivateMediationContext] = {}
        remaining = settings.xiaobao_mediation_context_character_limit

        for session in selected:
            detail = await self._mediation.get_session_detail(str(session.id), current_user)
            reference = XiaoBaoContextReference(
                key=f"mediation_session:{session.id}",
                type=XiaoBaoContextReferenceType.MEDIATION_SESSION,
                id=str(session.id),
                title=session.title,
            )
            data: dict[str, Any] = {
                "title": session.title,
                "description": session.description,
                "created_by": session.created_by_user_type.value,
                "status": session.status.value,
                "safety_status": session.safety_status.value,
                "has_my_perspective": session.has_my_perspective,
                "my_perspective_status": (
                    detail.my_perspective.status.value if detail.my_perspective else "NOT_STARTED"
                ),
                "other_perspective_status": detail.other_perspective_status,
                "my_reflection_status": detail.my_reflection_status,
                "advice_status": detail.advice_status,
                "has_marked_resolved": session.has_marked_resolved,
                "other_has_marked_resolved": session.other_has_marked_resolved,
                "has_marked_archived": session.has_marked_archived,
                "other_has_marked_archived": session.other_has_marked_archived,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "resolved_at": session.resolved_at.isoformat() if session.resolved_at else None,
                "archived_at": session.archived_at.isoformat() if session.archived_at else None,
            }
            metadata_size = len(json.dumps(data, ensure_ascii=True))
            remaining -= metadata_size

            if detail.advice is not None:
                advice = detail.advice.model_dump(mode="json", exclude_none=True)
                advice_size = len(json.dumps(advice, ensure_ascii=True))
                if advice_size <= remaining:
                    data["shared_advice"] = advice
                    remaining -= advice_size
                else:
                    data["shared_advice_truncated"] = True

            comments: list[dict[str, Any]] = []
            for comment in reversed(detail.comments[-settings.xiaobao_mediation_comment_limit :]):
                reduced_comment = {
                    "author_type": comment.author_type.value,
                    "author_user_type": (
                        comment.author_user_type.value if comment.author_user_type else None
                    ),
                    "ai_author_type": (
                        comment.ai_author_type.value if comment.ai_author_type else None
                    ),
                    "content": comment.content,
                    "created_at": comment.created_at.isoformat(),
                }
                comment_size = len(json.dumps(reduced_comment, ensure_ascii=True))
                if comment_size > remaining:
                    data["shared_comments_truncated"] = True
                    break
                comments.append(reduced_comment)
                remaining -= comment_size
            if comments:
                data["shared_comments"] = list(reversed(comments))

            public_items.append(XiaoBaoContextItem(reference=reference, data=data))
            private_data = XiaoBaoPrivateMediationContext(
                session_reference=reference,
                perspective=(
                    {
                        "status": detail.my_perspective.status.value,
                        "what_happened": detail.my_perspective.what_happened,
                        "what_i_felt": detail.my_perspective.what_i_felt,
                        "what_i_needed": detail.my_perspective.what_i_needed,
                        "what_hurt_me": detail.my_perspective.what_hurt_me,
                        "my_part": detail.my_perspective.my_part,
                        "what_i_want_now": detail.my_perspective.what_i_want_now,
                        "free_text": detail.my_perspective.free_text,
                    }
                    if detail.my_perspective
                    else None
                ),
                reflection_status=detail.my_reflection_status,
                reflection=(
                    detail.my_reflection.model_dump(mode="json", exclude_none=True)
                    if detail.my_reflection
                    else None
                ),
            )
            if len(private_data.model_dump_json(exclude_none=True)) <= (
                settings.xiaobao_mediation_private_context_character_limit
            ):
                private_items[reference.key] = private_data

        return public_items, private_items

    def _assemble(
        self,
        current_user: UserType,
        *,
        overview: Any,
        todos: list[Any],
        relationship_profile: Any,
        mediation_sessions: list[XiaoBaoContextItem],
        private_mediation: dict[str, XiaoBaoPrivateMediationContext],
    ) -> AuthorizedXiaoBaoContext:
        boundaries = [
            self._item(
                XiaoBaoContextReferenceType.PERSONAL_BOUNDARY,
                str(item.id),
                item.title,
                {
                    "owner": item.owner_user_type.value,
                    "is_mine": item.is_mine,
                    "title": item.title,
                    "what_i_need": item.what_i_need,
                    "what_i_will_do": item.what_i_will_do,
                    "why_this_matters": item.why_this_matters,
                    "category": item.category.value,
                },
            )
            for item in overview.boundaries
            if item.id and item.archived_at is None
        ]
        wishes = [
            self._item(
                XiaoBaoContextReferenceType.WISH,
                str(item.id),
                item.title,
                {
                    "owner": item.owner_user_type.value,
                    "is_mine": item.is_mine,
                    "title": item.title,
                    "description": item.description,
                    "why_it_matters": item.why_it_matters,
                    "ideas": item.ideas,
                    "importance": item.importance.value,
                    "category": item.category.value,
                },
            )
            for item in overview.requests
            if item.id and item.archived_at is None
        ]
        goals = [
            self._item(
                XiaoBaoContextReferenceType.PERSONAL_GOAL,
                str(item.id),
                item.title,
                {
                    "owner": item.owner_user_type.value,
                    "is_mine": item.is_mine,
                    "title": item.title,
                    "goal": item.goal,
                    "why_it_matters": item.why_it_matters,
                    "trigger": item.trigger,
                    "practice": item.practice,
                    "reminder": item.reminder,
                    "category": item.category.value,
                    "visibility": item.visibility.value,
                },
            )
            for item in overview.goals
            if item.id and item.archived_at is None
        ]
        agreements = [
            self._item(
                XiaoBaoContextReferenceType.SHARED_AGREEMENT,
                item.id,
                item.title,
                {
                    "title": item.title,
                    "agreement_text": item.agreement_text,
                    "status": item.status.value,
                    "fairness_type": item.fairness_type.value,
                    "is_creator": item.is_creator,
                },
            )
            for item in overview.agreements
            if item.status.value != "ARCHIVED"
        ]
        together_list = [
            self._item(
                XiaoBaoContextReferenceType.TOGETHER_LIST_ITEM,
                str(item.id),
                item.title,
                {"title": item.title, "category": item.category},
            )
            for item in todos
            if item.id and not item.completed and item.deleted_at is None
        ]
        return AuthorizedXiaoBaoContext(
            public=XiaoBaoRelationshipContext(
                current_user_type=current_user,
                partner_user_type=get_other_user_type(current_user),
                relationship_profile=relationship_profile,
                boundaries=boundaries,
                wishes=wishes,
                personal_goals=goals,
                agreements=agreements,
                together_list=together_list,
                mediation_sessions=mediation_sessions,
            ),
            private_mediation_by_key=private_mediation,
        )

    async def build(self, current_user: UserType) -> AuthorizedXiaoBaoContext:
        overview = await self._relationship_care.overview(current_user)
        todos = await self._todos.get_all()
        mediation_sessions, private_mediation = await self._mediation_context(current_user)
        relationship_profile = await self._relationship_profile.get_ai_context()
        return self._assemble(
            current_user,
            overview=overview,
            todos=todos,
            relationship_profile=relationship_profile,
            mediation_sessions=mediation_sessions,
            private_mediation=private_mediation,
        )

    async def build_for_routine(self, current_user: UserType) -> AuthorizedXiaoBaoContext:
        """Build fresh allowlisted context without querying mediation at all."""
        overview = await self._relationship_care.overview(current_user)
        todos = await self._todos.get_all()
        relationship_profile = await self._relationship_profile.get_ai_context()
        return self._assemble(
            current_user,
            overview=overview,
            todos=todos,
            relationship_profile=relationship_profile,
            mediation_sessions=[],
            private_mediation={},
        )
