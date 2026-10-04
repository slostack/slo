"""Offline regression contracts for Feature 86 review defects."""

import pytest
import httpx
import openai
from pydantic import JsonValue

from src.agents.providers.openrouter import OpenRouterErrorNormalizer

from src.agents.providers.credit_exhaustion_policy import ProviderErrorClassifier, ProviderErrorKind
from langchain_core.messages import HumanMessage

from src.agents.providers.openrouter import OpenRouterChatOpenAI, OpenRouterMessageCodec
from src.agents.providers.message_extension import ProviderMessageExtensionDAO
from src.auth.credential_dao import ProviderName
from src.integrations.openrouter.exceptions import OpenRouterAPIError


@pytest.mark.parametrize(
    "error_type,status,expected",
    [
        ("authentication", 429, ProviderErrorKind.AUTHENTICATION_FAILED),
        ("permission_denied", 503, ProviderErrorKind.POLICY_REJECTED),
        ("context_length_exceeded", None, ProviderErrorKind.CONTEXT_OVERFLOW),
        ("not_found", None, ProviderErrorKind.MODEL_UNAVAILABLE),
        ("refusal", 503, ProviderErrorKind.POLICY_REJECTED),
        ("server_error", None, ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE),
        (None, None, ProviderErrorKind.INVALID_PROVIDER_REQUEST),
        ("rate_limit_exceeded", 402, ProviderErrorKind.CREDIT_EXHAUSTED),
    ],
)
def test_safe_error_precedence(
    error_type: str | None, status: int | None, expected: ProviderErrorKind
) -> None:
    """Security signals precede retry hints; unknown gateway errors are terminal."""
    signal = ProviderErrorClassifier.inspect(
        error=OpenRouterAPIError(status_code=status, error_type=error_type),
        provider=ProviderName.OPENROUTER,
    )
    assert signal.kind == expected


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, ProviderErrorKind.AUTHENTICATION_FAILED),
        (403, ProviderErrorKind.POLICY_REJECTED),
        (413, ProviderErrorKind.REQUEST_BODY_TOO_LARGE),
    ],
)
def test_status_precedes_transport_family(status: int, expected: ProviderErrorKind) -> None:
    """An attached authoritative rejection cannot become a transport retry."""

    class StatusReadError(httpx.ReadError):
        """Typed contradictory transport/status fixture for precedence tests."""

        status_code: int = status

    error = StatusReadError("private")
    assert ProviderErrorClassifier.classify(error=error, provider=ProviderName.OPENROUTER) is expected


def test_typed_sdk_timeout_normalizes_to_transient() -> None:
    """SDK timeout class, not raw exception text, supplies the retry signal."""
    error = openai.APITimeoutError(request=httpx.Request("POST", "https://local.invalid"))
    normalized = OpenRouterErrorNormalizer.normalize(error=error)
    assert (
        ProviderErrorClassifier.classify(error=normalized, provider=ProviderName.OPENROUTER)
        is ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE
    )


def test_sdk_retry_header_and_nested_budget_are_preserved_safely() -> None:
    """SDK headers and nested metadata retain policy facts but not wire secrets."""
    response = httpx.Response(
        status_code=402,
        headers={"Retry-After": "2.5", "x-private": "secret"},
        request=httpx.Request("POST", "https://local.invalid"),
    )
    error = openai.APIStatusError(
        "secret",
        response=response,
        body={"error": {"metadata": {"limit_source": "openrouter_in_flight_budget"}}},
    )
    normalized = OpenRouterErrorNormalizer.normalize(error=error)
    signal = ProviderErrorClassifier.inspect(error=normalized, provider=ProviderName.OPENROUTER)
    assert signal.kind == ProviderErrorKind.RATE_LIMITED
    assert signal.retry_after_seconds == 3
    assert "secret" not in repr(normalized.__dict__)


def test_retained_retry_advice_reaches_shared_signal() -> None:
    """Normalization must not discard retry advice before session policy sees it."""
    signal = ProviderErrorClassifier.inspect(
        error=OpenRouterAPIError(status_code=429, retry_after_seconds=7),
        provider=ProviderName.OPENROUTER,
    )
    assert signal.retry_after_seconds == 7


def test_converter_preserves_image_evidence_and_exact_batch_segments() -> None:
    """Image capabilities survive conversion; batch-like names are not batch suffixes."""
    from tests.agents.model_catalog.test_openrouter_converter_metadata import _entry

    entry = _entry(
        id="vendor/model:batching",
        architecture={"input_modalities": ["text", "image"], "output_modalities": ["text"]},
    )
    assert entry.visible_in_picker
    assert entry.capabilities is not None
    assert entry.capabilities.input_modalities == ("text", "image")
    assert not _entry(id="vendor/model:free:batch").visible_in_picker


def test_codec_preserves_mixed_first_seen_order() -> None:
    """Indexed merges must not reorder opaque blocks around whole blocks."""
    codec = OpenRouterMessageCodec(model_name="openrouter:vendor/model")
    details: list[dict[str, JsonValue]] = [
        {"index": 2, "type": "encrypted", "data": "a"},
        {"type": "encrypted", "data": "whole"},
        {"index": 0, "type": "encrypted", "data": "b"},
        {"index": 2, "type": "encrypted", "data": "c"},
    ]
    for detail in details:
        codec.append(
            extension=ProviderMessageExtensionDAO(
                provider=ProviderName.OPENROUTER,
                source_model_name="openrouter:vendor/model",
                reasoning_details=[detail],
            )
        )
    assembled = codec.build().reasoning_details
    assert all(isinstance(detail, dict) for detail in assembled)
    assert [detail["data"] for detail in assembled if isinstance(detail, dict)] == ["ac", "whole", "b"]


@pytest.mark.parametrize("stream", [True, False])
def test_stream_options_only_on_stream_requests(stream: bool) -> None:
    """Nonstream SDK payloads must omit the stream-only parameter."""
    model = OpenRouterChatOpenAI(
        slo_model_name="openrouter:vendor/model", model="vendor/model", api_key="fixture"
    )
    payload = model._get_request_payload(input_=[HumanMessage(content="hello")], stream=stream)
    assert ("stream_options" in payload) is stream


def test_nonstream_multiple_choices_fail_before_conversion() -> None:
    """Reject unsupported multiplicity rather than silently mispair signatures."""
    model = OpenRouterChatOpenAI(
        slo_model_name="openrouter:vendor/model", model="vendor/model", api_key="fixture"
    )
    with pytest.raises(OpenRouterAPIError):
        model._create_chat_result(
            response={
                "choices": [
                    {
                        "index": index,
                        "message": {"role": "assistant", "content": "answer"},
                        "finish_reason": "stop",
                    }
                    for index in [2, 0]
                ],
            }
        )
