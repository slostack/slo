"""Safe, actionable diagnostics survive OpenRouter exception normalization."""

import json
import logging
from typing import Any

import pytest
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI

from src.agents.providers.openrouter import OpenRouterChatOpenAI
from src.integrations.openrouter.exceptions import OpenRouterAPIError


@pytest.mark.parametrize("operation", ["_generate", "_agenerate", "_stream", "_astream"])
async def test_boundaries_log_original_failure_without_private_data(
    operation: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """All four SDK boundaries retain stack locations and chained exception types."""

    def fail() -> None:
        try:
            raise ValueError("private-provider-body")
        except ValueError as cause:
            raise RuntimeError("private-api-key") from cause

    def generate(*args: Any, **kwargs: Any) -> Any:
        fail()

    async def agenerate(*args: Any, **kwargs: Any) -> Any:
        fail()

    def stream(*args: Any, **kwargs: Any) -> Any:
        yield ChatGenerationChunk(message=AIMessageChunk(content="private-output"))
        fail()

    async def astream(*args: Any, **kwargs: Any) -> Any:
        yield ChatGenerationChunk(message=AIMessageChunk(content="private-output"))
        fail()

    monkeypatch.setattr(
        ChatOpenAI,
        operation,
        {
            "_generate": generate,
            "_agenerate": agenerate,
            "_stream": stream,
            "_astream": astream,
        }[operation],
    )
    model = OpenRouterChatOpenAI(
        slo_model_name="openrouter:vendor/model", model="vendor/model", api_key="synthetic-only"
    )
    with caplog.at_level(logging.ERROR), pytest.raises(OpenRouterAPIError) as caught:
        if operation == "_generate":
            model._generate(messages=[])
        elif operation == "_agenerate":
            await model._agenerate(messages=[])
        elif operation == "_stream":
            list(model._stream(messages=[]))
        else:
            async for _ in model._astream(messages=[]):
                pass
    records = [r for r in caplog.records if r.getMessage().startswith("OpenRouter failure ")]
    assert len(records) == 1
    diagnostic = json.loads(records[0].getMessage().removeprefix("OpenRouter failure "))
    assert diagnostic["operation"] == operation
    assert diagnostic["partial_output_committed"] == ("stream" in operation)
    assert diagnostic["diagnostic_id"] == caught.value.diagnostic_id
    assert diagnostic["exceptions"][0]["type"] == "builtins.RuntimeError"
    assert diagnostic["exceptions"][1]["type"] == "builtins.ValueError"
    assert any(frame["function"] == "fail" for frame in diagnostic["exceptions"][0]["frames"])
    for private in ("private-provider-body", "private-api-key", "private-output"):
        assert private not in caplog.text
    assert records[0].exc_info is None


def test_metadata_conflict_has_specific_reason_and_safe_reference(caplog: pytest.LogCaptureFixture) -> None:
    """Metadata rejection explains the local failure without exposing conflicting values."""
    from src.agents.providers.openrouter import OpenRouterErrorNormalizer, OpenRouterMessageCodec

    try:
        OpenRouterMessageCodec._merge_field(target={"id": "private-old-id"}, key="id", value="private-new-id")
    except OpenRouterAPIError as error:
        with caplog.at_level(logging.ERROR):
            normalized = OpenRouterErrorNormalizer.diagnose(
                error=error, operation="_astream", model_name="openrouter:vendor/model"
            )
            assert (
                OpenRouterErrorNormalizer.diagnose(
                    error=normalized, operation="_astream", model_name="openrouter:vendor/model"
                )
                is normalized
            )
    else:
        pytest.fail("Expected conflicting metadata to be rejected")
    records = [r for r in caplog.records if r.getMessage().startswith("OpenRouter failure ")]
    assert len(records) == 1
    diagnostic = json.loads(records[0].getMessage().removeprefix("OpenRouter failure "))
    assert diagnostic["diagnostic_reason"] == "reasoning_field_conflict"
    assert normalized.diagnostic_id is not None
    assert normalized.diagnostic_id in str(normalized)
    assert "private-old-id" not in caplog.text
    assert "private-new-id" not in caplog.text


def test_http_error_logs_safe_status_and_classification(caplog: pytest.LogCaptureFixture) -> None:
    """Provider rejection facts remain available without the raw message/body."""
    import httpx
    import openai
    from src.agents.providers.openrouter import OpenRouterErrorNormalizer

    error = openai.APIStatusError(
        "private-error-message",
        response=httpx.Response(status_code=429, request=httpx.Request("POST", "https://example.invalid")),
        body={"error": {"type": "rate_limit_exceeded", "message": "private-body"}},
    )
    with caplog.at_level(logging.ERROR):
        OpenRouterErrorNormalizer.diagnose(
            error=error, operation="_generate", model_name="openrouter:vendor/model"
        )
    record = next(r for r in caplog.records if r.getMessage().startswith("OpenRouter failure "))
    diagnostic = json.loads(record.getMessage().removeprefix("OpenRouter failure "))
    assert diagnostic["status_code"] == 429
    assert diagnostic["error_type"] == "rate_limit_exceeded"
    assert "private-error-message" not in caplog.text
    assert "private-body" not in caplog.text
