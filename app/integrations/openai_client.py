import json
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings

settings = get_settings()


@dataclass(frozen=True)
class OpenAIStructuredResult:
    parsed: dict[str, Any]
    response_id: str | None


@dataclass(frozen=True)
class OpenAIModerationResult:
    flagged: bool
    categories: dict[str, bool]
    category_scores: dict[str, float] | None
    raw_result: dict[str, Any] | None


def _to_openai_strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize Pydantic JSON Schema for OpenAI strict structured outputs."""
    normalized = dict(schema)

    def visit(value: Any) -> Any:
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value

        current = {key: visit(item) for key, item in value.items() if key != "default"}
        if current.get("type") == "object" or "properties" in current:
            current["additionalProperties"] = False
            properties = current.get("properties")
            if isinstance(properties, dict):
                current["required"] = list(properties.keys())
        return current

    return visit(normalized)


class OpenAIClient:
    def __init__(self) -> None:
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise RuntimeError("The openai package is not installed") from exc
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._client

    async def create_structured_response(
        self,
        *,
        model: str,
        system_prompt: str,
        user_input: str,
        json_schema: dict[str, Any],
        schema_name: str,
        safety_identifier: str | None = None,
    ) -> OpenAIStructuredResult:
        client = self._get_client()
        strict_schema = _to_openai_strict_json_schema(json_schema)
        response = await client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": strict_schema,
                    "strict": True,
                }
            },
            user=safety_identifier,
        )
        output_text = getattr(response, "output_text", None)
        if not output_text:
            raise RuntimeError("OpenAI response did not contain output_text")
        return OpenAIStructuredResult(
            parsed=json.loads(output_text),
            response_id=getattr(response, "id", None),
        )

    async def moderate_text(self, *, text: str) -> OpenAIModerationResult:
        client = self._get_client()
        response = await client.moderations.create(
            model=settings.openai_model_moderation,
            input=text,
        )
        result = response.results[0]
        categories = result.categories.model_dump()
        category_scores = result.category_scores.model_dump()
        raw = response.model_dump(mode="json")
        return OpenAIModerationResult(
            flagged=bool(result.flagged),
            categories={key: bool(value) for key, value in categories.items()},
            category_scores={key: float(value) for key, value in category_scores.items()},
            raw_result=raw,
        )
