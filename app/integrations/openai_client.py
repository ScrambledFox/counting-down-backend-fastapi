import json
import re
from collections.abc import Awaitable, Callable
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


@dataclass(frozen=True)
class OpenAIToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class OpenAIStreamedResult:
    text: str
    parsed_output: dict[str, Any] | None
    tool_calls: list[OpenAIToolCall]
    output_items: list[dict[str, Any]]
    response_id: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int


class _JSONStringFieldDecoder:
    """Incrementally decode one JSON string field without exposing its envelope."""

    def __init__(self, field_name: str) -> None:
        self._field_name = field_name
        self._buffer = ""
        self._position = 0
        self._started = False
        self._finished = False

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        if self._finished:
            return ""
        if not self._started:
            match = re.search(rf'"{re.escape(self._field_name)}"\s*:\s*"', self._buffer)
            if not match:
                return ""
            self._started = True
            self._position = match.end()

        decoded: list[str] = []
        simple_escapes = {
            '"': '"',
            "\\": "\\",
            "/": "/",
            "b": "\b",
            "f": "\f",
            "n": "\n",
            "r": "\r",
            "t": "\t",
        }
        while self._position < len(self._buffer):
            char = self._buffer[self._position]
            if char == '"':
                self._finished = True
                self._position += 1
                break
            if char != "\\":
                decoded.append(char)
                self._position += 1
                continue
            if self._position + 1 >= len(self._buffer):
                break
            escape = self._buffer[self._position + 1]
            if escape in simple_escapes:
                decoded.append(simple_escapes[escape])
                self._position += 2
                continue
            if escape != "u":
                raise RuntimeError("Structured response contained an invalid JSON escape")
            if self._position + 6 > len(self._buffer):
                break
            first = int(self._buffer[self._position + 2 : self._position + 6], 16)
            consumed = 6
            if 0xD800 <= first <= 0xDBFF:
                if self._position + 12 > len(self._buffer):
                    break
                if self._buffer[self._position + 6 : self._position + 8] != "\\u":
                    raise RuntimeError("Structured response contained an invalid surrogate pair")
                second = int(self._buffer[self._position + 8 : self._position + 12], 16)
                if not 0xDC00 <= second <= 0xDFFF:
                    raise RuntimeError("Structured response contained an invalid surrogate pair")
                decoded.append(chr(0x10000 + ((first - 0xD800) << 10) + (second - 0xDC00)))
                consumed = 12
            elif 0xDC00 <= first <= 0xDFFF:
                raise RuntimeError("Structured response contained an invalid surrogate pair")
            else:
                decoded.append(chr(first))
            self._position += consumed
        return "".join(decoded)


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


def _prepare_responses_input_item(item: dict[str, Any]) -> dict[str, Any]:
    """Convert a stored Responses output item into a valid stateless input item."""

    def remove_nulls(value: Any) -> Any:
        if isinstance(value, list):
            return [remove_nulls(child) for child in value]
        if isinstance(value, dict):
            return {key: remove_nulls(child) for key, child in value.items() if child is not None}
        return value

    prepared = remove_nulls(item)
    if prepared.get("type") == "reasoning":
        # `status` is present on output reasoning items but is not accepted when the item is
        # replayed through `input` with store=False.
        prepared.pop("status", None)
    return prepared


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

    async def stream_tool_response(
        self,
        *,
        model: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_text_delta: Callable[[str], Awaitable[None]],
        safety_identifier: str | None = None,
        allow_tools: bool = True,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str | None = None,
        stream_content_field: str | None = None,
    ) -> OpenAIStreamedResult:
        client = self._get_client()
        request: dict[str, Any] = {
            "model": model,
            "input": [_prepare_responses_input_item(item) for item in input_items],
            "store": False,
            "stream": True,
            "reasoning": {"effort": settings.xiaobao_reasoning_effort},
            "text": {"verbosity": "low"},
            "max_output_tokens": settings.xiaobao_max_output_tokens,
            "parallel_tool_calls": False,
            "include": ["reasoning.encrypted_content"],
        }
        if safety_identifier:
            request["safety_identifier"] = safety_identifier
        if allow_tools:
            request["tools"] = tools
            request["tool_choice"] = "auto"
        if response_schema is not None:
            if not response_schema_name or not stream_content_field:
                raise ValueError("Structured streaming requires a schema name and content field")
            request["text"]["format"] = {
                "type": "json_schema",
                "name": response_schema_name,
                "schema": _to_openai_strict_json_schema(response_schema),
                "strict": True,
            }

        stream = await client.responses.create(**request)
        raw_chunks: list[str] = []
        text_chunks: list[str] = []
        decoder = _JSONStringFieldDecoder(stream_content_field) if stream_content_field else None
        completed_response: Any | None = None
        async for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                delta = str(getattr(event, "delta", ""))
                if delta:
                    raw_chunks.append(delta)
                    decoded = decoder.feed(delta) if decoder else delta
                    if decoded:
                        text_chunks.append(decoded)
                        await on_text_delta(decoded)
            elif event_type == "response.completed":
                completed_response = getattr(event, "response", None)

        if completed_response is None:
            raise RuntimeError("OpenAI stream ended without a completed response")
        output = list(getattr(completed_response, "output", []) or [])
        output_items = [
            item.model_dump(mode="json", exclude_none=True)
            if hasattr(item, "model_dump")
            else _prepare_responses_input_item(dict(item))
            for item in output
        ]
        tool_calls = [
            OpenAIToolCall(
                call_id=str(item.call_id),
                name=str(item.name),
                arguments=str(item.arguments),
            )
            for item in output
            if getattr(item, "type", None) == "function_call"
        ]
        usage = getattr(completed_response, "usage", None)
        raw_text = "".join(raw_chunks) or str(getattr(completed_response, "output_text", ""))
        parsed_output: dict[str, Any] | None = None
        final_text = raw_text
        if response_schema is not None and not tool_calls:
            try:
                parsed = json.loads(raw_text)
            except (TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError("OpenAI returned malformed structured output") from exc
            if not isinstance(parsed, dict):
                raise RuntimeError("OpenAI structured output was not an object")
            parsed_output = parsed
            value = parsed.get(stream_content_field)
            if not isinstance(value, str):
                raise RuntimeError("OpenAI structured output omitted response content")
            final_text = value
            if text_chunks and "".join(text_chunks) != final_text:
                raise RuntimeError("Streamed content did not match the completed response")
        return OpenAIStreamedResult(
            text=final_text if not text_chunks else "".join(text_chunks),
            parsed_output=parsed_output,
            tool_calls=tool_calls,
            output_items=output_items,
            response_id=getattr(completed_response, "id", None),
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
        )
