import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.integrations.openai_client import (
    OpenAIClient,
    _JSONStringFieldDecoder,
    _prepare_responses_input_item,
    _to_openai_strict_json_schema,
)
from app.schemas.v1.mediation import PrivateReflectionOutput, SharedMediationAdviceOutput
from app.schemas.v1.xiaobao import XiaoBaoResponseEnvelope


def _assert_object_schemas_are_strict(schema: object) -> None:
    if isinstance(schema, list):
        for item in schema:
            _assert_object_schemas_are_strict(item)
        return
    if not isinstance(schema, dict):
        return

    if schema.get("type") == "object" or "properties" in schema:
        assert schema["additionalProperties"] is False
        assert set(schema.get("required", [])) == set(schema.get("properties", {}).keys())
        assert "default" not in schema

    for value in schema.values():
        _assert_object_schemas_are_strict(value)


def test_private_reflection_schema_is_normalized_for_openai_strict_outputs() -> None:
    schema = _to_openai_strict_json_schema(PrivateReflectionOutput.model_json_schema())

    _assert_object_schemas_are_strict(schema)


def test_private_reflection_raw_schema_forbids_additional_properties() -> None:
    schema = PrivateReflectionOutput.model_json_schema()

    assert schema["additionalProperties"] is False


def test_shared_advice_nested_task_schema_is_normalized_for_openai_strict_outputs() -> None:
    schema = _to_openai_strict_json_schema(SharedMediationAdviceOutput.model_json_schema())

    _assert_object_schemas_are_strict(schema)


def test_reasoning_output_is_sanitized_before_stateless_tool_continuation() -> None:
    item = {
        "id": "rs_test",
        "type": "reasoning",
        "status": None,
        "content": None,
        "summary": [],
        "encrypted_content": "encrypted-test-content",
    }

    prepared = _prepare_responses_input_item(item)

    assert prepared == {
        "id": "rs_test",
        "type": "reasoning",
        "summary": [],
        "encrypted_content": "encrypted-test-content",
    }


def test_xiaobao_response_schema_has_only_content_and_allowed_mood() -> None:
    schema = _to_openai_strict_json_schema(XiaoBaoResponseEnvelope.model_json_schema())

    assert list(schema["properties"]) == ["content", "mood"]
    assert schema["required"] == ["content", "mood"]
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["XiaoBaoMascotMood"]["enum"] == [
        "IDLE",
        "LOVE",
        "CONCERNED",
    ]


def test_xiaobao_content_decoder_handles_every_character_as_a_separate_chunk() -> None:
    content = '**A "quoted" line**\n\nPath: `C:\\\\Us` — 小宝 💗'
    envelope = json.dumps({"content": content, "mood": "LOVE"}, ensure_ascii=True)
    decoder = _JSONStringFieldDecoder("content")

    streamed = "".join(decoder.feed(character) for character in envelope)

    assert streamed == content
    assert '"content"' not in streamed
    assert '"mood"' not in streamed


def test_xiaobao_response_envelope_rejects_an_arbitrary_mood() -> None:
    with pytest.raises(ValidationError):
        XiaoBaoResponseEnvelope.model_validate({"content": "Hello", "mood": "PARTY"})


@pytest.mark.asyncio
async def test_structured_stream_emits_only_decoded_content_and_returns_envelope() -> None:
    raw = json.dumps(
        {"content": '**Hello**\nShe said "yes" — 小宝', "mood": "LOVE"},
        ensure_ascii=True,
    )
    completed = SimpleNamespace(
        id="resp_test",
        output=[],
        output_text=raw,
        usage=SimpleNamespace(input_tokens=8, output_tokens=5, total_tokens=13),
    )

    class FakeStream:
        def __aiter__(self):
            async def events():
                for character in raw:
                    yield SimpleNamespace(type="response.output_text.delta", delta=character)
                yield SimpleNamespace(type="response.completed", response=completed)

            return events()

    create = AsyncMock(return_value=FakeStream())
    client = OpenAIClient()
    client._client = SimpleNamespace(responses=SimpleNamespace(create=create))
    deltas: list[str] = []

    async def collect(delta: str) -> None:
        deltas.append(delta)

    result = await client.stream_tool_response(
        model="test-model",
        input_items=[{"role": "user", "content": "Hello"}],
        tools=[],
        on_text_delta=collect,
        allow_tools=False,
        response_schema=XiaoBaoResponseEnvelope.model_json_schema(),
        response_schema_name="xiaobao_response",
        stream_content_field="content",
    )

    assert "".join(deltas) == '**Hello**\nShe said "yes" — 小宝'
    assert result.text == "".join(deltas)
    assert result.parsed_output == {
        "content": '**Hello**\nShe said "yes" — 小宝',
        "mood": "LOVE",
    }
    request = create.await_args.kwargs
    assert request["store"] is False
    assert request["parallel_tool_calls"] is False
    assert request["text"]["format"]["strict"] is True
    assert set(request["text"]["format"]["schema"]["properties"]) == {"content", "mood"}


@pytest.mark.asyncio
async def test_malformed_structured_stream_uses_provider_failure_path() -> None:
    raw = '{"content":"unfinished'
    completed = SimpleNamespace(
        id="resp_bad",
        output=[],
        output_text=raw,
        usage=None,
    )

    class FakeStream:
        def __aiter__(self):
            async def events():
                yield SimpleNamespace(type="response.output_text.delta", delta=raw)
                yield SimpleNamespace(type="response.completed", response=completed)

            return events()

    client = OpenAIClient()
    client._client = SimpleNamespace(
        responses=SimpleNamespace(create=AsyncMock(return_value=FakeStream()))
    )

    with pytest.raises(RuntimeError, match="malformed structured output"):
        await client.stream_tool_response(
            model="test-model",
            input_items=[],
            tools=[],
            on_text_delta=AsyncMock(),
            allow_tools=False,
            response_schema=XiaoBaoResponseEnvelope.model_json_schema(),
            response_schema_name="xiaobao_response",
            stream_content_field="content",
        )


@pytest.mark.asyncio
async def test_refusal_uses_provider_failure_path_without_streaming_wrapper_text() -> None:
    completed = SimpleNamespace(id="resp_refusal", output=[], output_text="", usage=None)

    class FakeStream:
        def __aiter__(self):
            async def events():
                yield SimpleNamespace(
                    type="response.refusal.delta",
                    delta="I cannot provide that response.",
                )
                yield SimpleNamespace(type="response.completed", response=completed)

            return events()

    client = OpenAIClient()
    client._client = SimpleNamespace(
        responses=SimpleNamespace(create=AsyncMock(return_value=FakeStream()))
    )
    on_delta = AsyncMock()

    with pytest.raises(RuntimeError, match="malformed structured output"):
        await client.stream_tool_response(
            model="test-model",
            input_items=[],
            tools=[],
            on_text_delta=on_delta,
            allow_tools=False,
            response_schema=XiaoBaoResponseEnvelope.model_json_schema(),
            response_schema_name="xiaobao_response",
            stream_content_field="content",
        )

    on_delta.assert_not_awaited()
