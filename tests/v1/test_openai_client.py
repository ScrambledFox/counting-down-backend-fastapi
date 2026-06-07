from app.integrations.openai_client import _to_openai_strict_json_schema
from app.schemas.v1.mediation import PrivateReflectionOutput, SharedMediationAdviceOutput


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
