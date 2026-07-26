"""Provider schema-serialisation gate for spawn_sub_agents (sub-spec 58.d)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from src.agents.slo_agent.orchestrator.dao import OrchestratorResultDAO
from src.agents.slo_agent.orchestrator.spawn_tool import SpawnSubAgentsTool


def _tool() -> BaseTool:
    """Build a spawn_sub_agents tool over a no-op pool mock.

    Returns:
        BaseTool: The bound tool whose schema is under test.
    """
    pool: MagicMock = MagicMock()
    pool.dispatch = AsyncMock(return_value=OrchestratorResultDAO(mode="single"))
    return SpawnSubAgentsTool.build(pool=pool)


class TestSpawnSubAgentsSchemaShape:
    """The generated tool schema advertises a native array plus a legacy string."""

    def test_tasks_is_a_native_array_of_objects(self) -> None:
        """``tasks`` renders as an array whose items are objects."""
        schema: dict[str, Any] = _tool().args_schema.model_json_schema()
        tasks_field: dict[str, Any] = schema["properties"]["tasks"]

        assert _array_of_objects(field=tasks_field)

    def test_tasks_json_is_a_string(self) -> None:
        """``tasks_json`` renders as a string type."""
        schema: dict[str, Any] = _tool().args_schema.model_json_schema()

        assert _permits_string(field=schema["properties"]["tasks_json"])

    def test_neither_task_input_is_required(self) -> None:
        """Only ``mode`` is required; both task inputs are optional."""
        schema: dict[str, Any] = _tool().args_schema.model_json_schema()

        assert "tasks" not in schema.get("required", [])
        assert "tasks_json" not in schema.get("required", [])


class TestSpawnSubAgentsSchemaProviderEncoding:
    """The tool serialises for the OpenAI tool encoding without raising."""

    def test_converts_to_openai_tool_with_a_nested_array(self) -> None:
        """``convert_to_openai_tool`` succeeds and preserves the ``tasks`` array."""
        encoded: dict[str, Any] = convert_to_openai_tool(_tool())
        params: dict[str, Any] = encoded["function"]["parameters"]

        assert _array_of_objects(field=params["properties"]["tasks"])


def _array_of_objects(*, field: dict[str, Any]) -> bool:
    """Return True when a JSON-schema field is an array whose items are objects.

    Tolerates the ``anyOf`` wrapping Pydantic emits for ``Optional`` fields.

    Args:
        field (dict): One JSON-schema property definition.

    Returns:
        bool: True when the field permits an array of object items.
    """
    for candidate in _schema_candidates(field=field):
        if candidate.get("type") == "array":
            items: dict[str, Any] = candidate.get("items", {})
            if items.get("type") == "object" or "type" not in items:
                return True
    return False


def _permits_string(*, field: dict[str, Any]) -> bool:
    """Return True when a JSON-schema field permits a string value.

    Args:
        field (dict): One JSON-schema property definition.

    Returns:
        bool: True when any candidate branch is typed ``string``.
    """
    return any(c.get("type") == "string" for c in _schema_candidates(field=field))


def _schema_candidates(*, field: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a field into its concrete type branches.

    Optional fields render as ``{"anyOf": [<type>, {"type": "null"}]}``; this
    returns the field itself plus any ``anyOf`` branches so callers can inspect
    the real type without special-casing nullability.

    Args:
        field (dict): One JSON-schema property definition.

    Returns:
        list[dict]: The field and its ``anyOf`` branches.
    """
    return [field, *field.get("anyOf", [])]
