from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from app.integrations.openai_client import OpenAIClient, OpenAIModerationResult
from app.schemas.v1.mediation import SafetyStatus


@dataclass(frozen=True)
class ModerationDecision:
    flagged: bool
    safety_status: SafetyStatus
    categories: dict[str, bool]
    category_scores: dict[str, float] | None
    raw_result: dict | None
    should_block_normal_mediation: bool
    user_message: str | None = None


class MediationSafetyService:
    def __init__(self, openai_client: Annotated[OpenAIClient, Depends()]) -> None:
        self._openai = openai_client

    def _decision_from_result(self, result: OpenAIModerationResult) -> ModerationDecision:
        blocking_categories = {
            "self-harm",
            "self_harm",
            "self-harm/intent",
            "self_harm_intent",
            "violence",
            "violence/graphic",
            "harassment/threatening",
            "harassment_threatening",
            "sexual/minors",
            "sexual_minors",
        }
        blocked = result.flagged and any(
            result.categories.get(category, False) for category in blocking_categories
        )
        if blocked:
            status = SafetyStatus.BLOCKED
        elif result.flagged:
            status = SafetyStatus.FLAGGED
        else:
            status = SafetyStatus.NORMAL
        return ModerationDecision(
            flagged=result.flagged,
            safety_status=status,
            categories=result.categories,
            category_scores=result.category_scores,
            raw_result=result.raw_result,
            should_block_normal_mediation=blocked,
            user_message=(
                "This mediation needs to pause because the content may involve safety risk."
                if blocked
                else None
            ),
        )

    def _internal_keyword_decision(self, text: str) -> ModerationDecision | None:
        lowered = text.lower()
        high_risk_terms = [
            "suicide",
            "kill myself",
            "kill you",
            "hurt you",
            "hit me",
            "hit you",
            "threat",
            "coercion",
            "stalking",
            "retaliation",
        ]
        if any(term in lowered for term in high_risk_terms):
            return ModerationDecision(
                flagged=True,
                safety_status=SafetyStatus.BLOCKED,
                categories={"internal_high_risk_keyword": True},
                category_scores=None,
                raw_result=None,
                should_block_normal_mediation=True,
                user_message=(
                    "This mediation needs to pause because the content may involve safety risk."
                ),
            )
        return None

    async def moderate_text(self, text: str) -> ModerationDecision:
        internal = self._internal_keyword_decision(text)
        if internal:
            return internal
        try:
            result = await self._openai.moderate_text(text=text)
        except RuntimeError:
            return ModerationDecision(
                flagged=False,
                safety_status=SafetyStatus.NORMAL,
                categories={"moderation_unavailable": True},
                category_scores=None,
                raw_result=None,
                should_block_normal_mediation=False,
            )
        return self._decision_from_result(result)

    def _bypassed_decision(self) -> ModerationDecision:
        return ModerationDecision(
            flagged=False,
            safety_status=SafetyStatus.NORMAL,
            categories={},
            category_scores=None,
            raw_result=None,
            should_block_normal_mediation=False,
        )

    async def moderate_perspective(self, perspective_text: str) -> ModerationDecision:
        return self._bypassed_decision()

    async def moderate_comment(self, comment_text: str) -> ModerationDecision:
        return self._bypassed_decision()

    async def moderate_ai_output(self, output_text: str) -> ModerationDecision:
        return await self.moderate_text(output_text)
