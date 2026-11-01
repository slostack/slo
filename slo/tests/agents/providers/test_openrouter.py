"""Offline OpenRouter Chat Completions construction tests."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from tests.agents.retry_options import SDKRetryOptions

from src.agents.base import LLMFactory
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.providers.message_extension import (
    PROVIDER_MESSAGE_EXTENSION_KEY,
    ProviderMessageExtensionDAO,
)
from src.agents.providers.openrouter import OpenRouterChatOpenAI
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.compaction.token_estimator import TokenEstimator
from src.agents.slo_agent.rate_limit.service import _message_char_length
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName

_OPENROUTER_MODEL_NAME = "openrouter:vendor/exact-model"


def _prepared_snapshot():
    """Build one local prepared exact-route snapshot for transport-only tests."""
    seed = SeedModelCatalog.load()
    template = seed.entries["gpt-5.4"]
    from src.agents.model_catalog.dao import ModelCapabilitiesDAO

    entry = template.model_copy(
        update={
            "model_name": _OPENROUTER_MODEL_NAME,
            "api_model_name": "vendor/exact-model",
            "provider": ProviderName.OPENROUTER,
            "capabilities": ModelCapabilitiesDAO(
                input_modalities=("text",),
                output_modalities=("text",),
                supported_parameters=("tools",),
            ),
        }
    )
    return seed.model_copy(update={"entries": {**seed.entries, entry.model_name: entry}})


@pytest.mark.parametrize("retry_options", [{}, {"max_retries": 0}, {"max_retries": 5}])
def test_factory_builds_chat_completions_for_exact_openrouter_api_model_name(
    retry_options: SDKRetryOptions,
) -> None:
    """Build the fixed gateway adapter without inheriting direct-provider defaults."""
    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="test-key",
    )
    async_client: httpx.AsyncClient = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code=200)),
    )

    with patch("src.agents.base.CredentialResolver.require", return_value=credential):
        result = LLMFactory.create(
            model_name=_OPENROUTER_MODEL_NAME,
            http_async_client=async_client,
            snapshot=_prepared_snapshot(),
            **retry_options,
        )

    assert isinstance(result.llm, OpenRouterChatOpenAI)
    assert result.llm.model_name == "vendor/exact-model"
    assert result.llm.openai_api_base == "https://openrouter.ai/api/v1"
    assert result.llm.max_retries == retry_options.get("max_retries", 3)
    assert result.llm.root_async_client.max_retries == retry_options.get("max_retries", 3)
    assert result.llm.use_responses_api is False
    assert result.llm.default_headers == {
        "X-OpenRouter-Title": "Slo",
        "X-OpenRouter-Categories": "cli-agent",
    }
    assert result.supports_explicit_caching is False


def test_factory_request_payload_contains_only_chat_completions_gateway_fields() -> None:
    """Attach required gateway fields without Responses, cache, or routing overrides."""
    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="test-key",
    )
    async_client: httpx.AsyncClient = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code=200)),
    )

    with patch("src.agents.base.CredentialResolver.require", return_value=credential):
        result = LLMFactory.create(
            model_name=_OPENROUTER_MODEL_NAME,
            http_async_client=async_client,
            snapshot=_prepared_snapshot(),
        )

    assert isinstance(result.llm, OpenRouterChatOpenAI)
    payload: dict[str, object] = result.llm._get_request_payload(input_=[])

    assert payload["model"] == "vendor/exact-model"
    assert payload["extra_body"] == {"provider": {"require_parameters": True}}
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert "reasoning" not in payload
    assert "thinking" not in payload
    assert "cache_control" not in payload
    assert "use_responses_api" not in payload


def test_request_payload_preserves_extension_only_for_the_same_openrouter_route() -> None:
    """Replay opaque reasoning details only to the exact route that produced them."""
    same_route_extension: ProviderMessageExtensionDAO = ProviderMessageExtensionDAO(
        provider=ProviderName.OPENROUTER,
        source_model_name=_OPENROUTER_MODEL_NAME,
        reasoning_details=[{"type": "encrypted", "data": "opaque"}],
    )
    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="test-key",
    )
    async_client: httpx.AsyncClient = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code=200)),
    )

    with patch("src.agents.base.CredentialResolver.require", return_value=credential):
        result = LLMFactory.create(
            model_name=_OPENROUTER_MODEL_NAME,
            http_async_client=async_client,
            snapshot=_prepared_snapshot(),
        )

    from langchain_core.messages import AIMessage

    message: AIMessage = AIMessage(
        content="answer",
        additional_kwargs={PROVIDER_MESSAGE_EXTENSION_KEY: same_route_extension.model_dump(mode="json")},
    )
    assert isinstance(result.llm, OpenRouterChatOpenAI)
    payload: dict[str, object] = result.llm._get_request_payload(input_=[message])

    assert payload["messages"] == [
        {
            "role": "assistant",
            "content": "answer",
            "reasoning_details": [{"type": "encrypted", "data": "opaque"}],
        }
    ]


def test_request_payload_strips_extension_from_a_different_openrouter_route() -> None:
    """Prevent opaque continuation signatures from crossing canonical route boundaries."""
    extension: ProviderMessageExtensionDAO = ProviderMessageExtensionDAO(
        provider=ProviderName.OPENROUTER,
        source_model_name="openrouter:vendor/first-model",
        reasoning="private reasoning",
    )
    adapter: OpenRouterChatOpenAI = OpenRouterChatOpenAI(
        slo_model_name="openrouter:vendor/second-model",
        model="vendor/second-model",
        api_key="test-key",
        max_retries=0,
        use_responses_api=False,
    )

    from langchain_core.messages import AIMessage

    payload: dict[str, object] = adapter._get_request_payload(
        input_=[
            AIMessage(
                content="answer",
                additional_kwargs={PROVIDER_MESSAGE_EXTENSION_KEY: extension.model_dump(mode="json")},
            )
        ]
    )

    assert payload["messages"] == [{"role": "assistant", "content": "answer"}]


def test_provider_extension_round_trips_through_assistant_trace_and_history_projection() -> None:
    """Persist one typed extension and restore it as private same-route replay metadata."""
    extension: ProviderMessageExtensionDAO = ProviderMessageExtensionDAO(
        provider=ProviderName.OPENROUTER,
        source_model_name=_OPENROUTER_MODEL_NAME,
        reasoning_details=[{"type": "encrypted", "data": "opaque"}],
    )

    from langchain_core.messages import AIMessage

    agent: SloAgent = object.__new__(SloAgent)
    agent._current_iteration = 1
    events = agent._trace_events_from_message(
        message=AIMessage(
            content="answer",
            additional_kwargs={PROVIDER_MESSAGE_EXTENSION_KEY: extension.model_dump(mode="json")},
        )
    )
    history_event: SessionHistoryEventDAO = SessionHistoryEventDAO(
        session_id="test-session",
        turn_id="test-turn",
        kind="assistant_message",
        payload=SessionHistoryEventPayloadDAO(
            content=events[0].payload.content,
            provider_message_extension=events[0].payload.provider_message_extension,
        ),
    )

    projected: AIMessage = SessionHistoryProjector._event_to_message(event=history_event)  # type: ignore[assignment]

    assert projected.additional_kwargs[PROVIDER_MESSAGE_EXTENSION_KEY] == extension.model_dump(mode="json")


def test_extension_counts_once_in_history_and_replayed_rate_estimates() -> None:
    """Include opaque continuation metadata in both local context-estimation owners."""
    extension: ProviderMessageExtensionDAO = ProviderMessageExtensionDAO(
        provider=ProviderName.OPENROUTER,
        source_model_name=_OPENROUTER_MODEL_NAME,
        reasoning_details=[{"data": "opaque"}],
    )
    event: SessionHistoryEventDAO = SessionHistoryEventDAO(
        session_id="test-session",
        turn_id="test-turn",
        kind="assistant_message",
        payload=SessionHistoryEventPayloadDAO(
            content="answer",
            provider_message_extension=extension,
        ),
    )

    from langchain_core.messages import AIMessage
    import json

    message: AIMessage = AIMessage(
        content="answer",
        additional_kwargs={PROVIDER_MESSAGE_EXTENSION_KEY: extension.model_dump(mode="json")},
    )
    expected_chars: int = len("answer") + len(
        json.dumps(extension.model_dump(mode="json"), ensure_ascii=False)
    )

    assert TokenEstimator._count_chars(event=event) == expected_chars
    assert _message_char_length(message=message) == expected_chars


def test_request_policy_builds_gateway_provider_and_reasoning_payload() -> None:
    """Build the gateway-only request fields without Responses or native thinking fields."""
    from src.agents.providers.openrouter import OpenRouterRequestPolicy

    payload: dict[str, object] = OpenRouterRequestPolicy.build(
        max_tokens=4096,
        reasoning_effort="low",
        controls_available=True,
    )

    assert payload["max_tokens"] == 4096
    assert payload["extra_body"] == {"provider": {"require_parameters": True}, "reasoning": {"effort": "low"}}
    assert "thinking" not in payload
    assert "use_responses_api" not in payload


def test_request_policy_when_controls_are_unavailable_omits_reasoning_payload() -> None:
    """Avoid claiming that absent catalog metadata authorizes a reasoning control."""
    from src.agents.providers.openrouter import OpenRouterRequestPolicy

    payload: dict[str, object] = OpenRouterRequestPolicy.build(
        max_tokens=1024,
        reasoning_effort=None,
        controls_available=False,
    )

    assert payload["extra_body"] == {"provider": {"require_parameters": True}}
