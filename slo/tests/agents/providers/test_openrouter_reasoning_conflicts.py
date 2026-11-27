"""Offline SDK evidence for safe reasoning merge conflict diagnostics."""

import json
import logging

import httpx
import pytest
from langchain_core.messages import HumanMessage

from src.agents.providers.openrouter import OpenRouterChatOpenAI
from src.integrations.openrouter.exceptions import OpenRouterAPIError, OpenRouterReasoningConflictDAO
from tests.agents.providers.test_openrouter_fragments import _sse


@pytest.mark.parametrize("field", ["id", "format", "signature", "private-field-name"])
async def test_conflict_logs_structure_without_values(field: str, caplog: pytest.LogCaptureFixture) -> None:
    """SDK streaming failures expose only bounded schema names and JSON shapes."""

    def respond(request: httpx.Request) -> httpx.Response:
        """Supply conflicting metadata without contacting a provider."""
        return _sse(
            [
                {"reasoning_details": [{"index": 0, "type": "reasoning.text", field: "PRIVATE_OLD"}]},
                {"reasoning_details": [{"index": 0, "type": "reasoning.text", field: "PRIVATE_NEW"}]},
            ]
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = OpenRouterChatOpenAI(
            slo_model_name="openrouter:vendor/model",
            model="vendor/model",
            api_key="SYNTHETIC_SECRET",
            http_async_client=client,
            max_retries=0,
        )
        with caplog.at_level(logging.ERROR), pytest.raises(OpenRouterAPIError):
            _ = [chunk async for chunk in model.astream([HumanMessage(content="test")])]
    record = next(r for r in caplog.records if r.getMessage().startswith("OpenRouter failure "))
    diagnostic = json.loads(record.getMessage().removeprefix("OpenRouter failure "))
    assert diagnostic["reasoning_conflict"] == {
        "field": field if field != "private-field-name" else "other",
        "existing_value_type": "string",
        "incoming_value_type": "string",
        "existing_index": 0,
        "incoming_index": 0,
        "existing_detail_type": "reasoning.text",
        "incoming_detail_type": "reasoning.text",
    }
    for secret in ("PRIVATE_OLD", "PRIVATE_NEW", "private-field-name", "SYNTHETIC_SECRET"):
        assert secret not in caplog.text


@pytest.mark.parametrize(
    ("value", "expected_type"),
    [
        (None, "null"),
        (True, "boolean"),
        (1, "integer"),
        (1.5, "number"),
        (["PRIVATE"], "array"),
        ({"PRIVATE": "PRIVATE"}, "object"),
    ],
)
def test_conflict_projection_limits_untrusted_shapes(value: object, expected_type: str) -> None:
    """Unknown detail types, nested values and invalid indexes cannot leak into logs."""
    diagnostic = OpenRouterReasoningConflictDAO.build(
        field="PRIVATE_FIELD",
        existing={"PRIVATE_FIELD": value, "type": ["PRIVATE_TYPE"], "index": True},
        incoming={"PRIVATE_FIELD": value, "type": "PRIVATE_TYPE", "index": 2**100},
    )
    assert diagnostic.existing_value_type == expected_type
    assert diagnostic.incoming_value_type == expected_type
    assert diagnostic.existing_index is None
    assert diagnostic.incoming_index is None
    assert diagnostic.field == "other"
    assert diagnostic.existing_detail_type == "other"
    assert diagnostic.incoming_detail_type == "other"
    assert "PRIVATE" not in diagnostic.model_dump_json()
