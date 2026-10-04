"""Runtime-boundary tests for safe OpenRouter admission and committed failures."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from typing import AsyncIterator, Optional

from pydantic import PrivateAttr

from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from src.agents.base import LLMFactory
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.providers.credit_exhaustion_policy import ProviderErrorKind
from src.agents.providers.faux import FauxChatModel
from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
from src.agents.providers.openrouter import OpenRouterChatOpenAI
from src.agents.slo_agent.recovery.dao import RecoveryClass
from src.agents.slo_agent.recovery.service import RecoveryPolicy
from src.agents.slo_agent.sessions.service import (
    PromptAttemptPlanDAO,
    PromptAttemptResultDAO,
    SloAgentSession,
)
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.integrations.openrouter.exceptions import OpenRouterAPIError


class _FallbackCountingModel(BaseChatModel):
    """Record an unexpected fallback invocation in the committed-output test."""

    _calls: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        """Return the LangChain type label for this deterministic test model."""
        return "fallback-counter"

    @property
    def calls(self) -> int:
        """Return the recorded number of fallback stream invocations."""
        return self._calls

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: object = None,
        **kwargs: object,
    ) -> ChatResult:
        """Reject unsupported non-streaming use in this stream-boundary fixture.

        Args:
            messages (list[BaseMessage]): Request messages.
            stop (Optional[list[str]]): Stop sequences.
            run_manager (object): LangChain callback manager.
            **kwargs (object): Additional request arguments.

        Raises:
            AssertionError: Always, because this fixture proves the stream path.
        """
        raise AssertionError("fallback fixture does not support _generate")

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: object = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Record fallback use before producing an impossible test response.

        Args:
            messages (list[BaseMessage]): Request messages.
            stop (Optional[list[str]]): Stop sequences.
            run_manager (object): LangChain callback manager.
            **kwargs (object): Additional request arguments.

        Yields:
            ChatGenerationChunk: An impossible fallback response when called.
        """
        self._calls += 1
        yield ChatGenerationChunk(message=AIMessageChunk(content="fallback"))


class _CommittedFailureModel(BaseChatModel):
    """Stream one visible chunk before raising the configured provider exception."""

    def __init__(self, *, error: Exception) -> None:
        """Store the safe provider error used after the commit boundary.

        Args:
            error (Exception): Error raised after the first stream chunk.
        """
        super().__init__()
        self._error: Exception = error

    @property
    def _llm_type(self) -> str:
        """Return the LangChain type label for this deterministic test model."""
        return "committed-failure"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: object = None,
        **kwargs: object,
    ) -> ChatResult:
        """Reject unsupported non-streaming use in this stream-boundary fixture.

        Args:
            messages (list[BaseMessage]): Request messages.
            stop (Optional[list[str]]): Stop sequences.
            run_manager (object): LangChain callback manager.
            **kwargs (object): Additional request arguments.

        Raises:
            AssertionError: Always, because this fixture proves the stream path.
        """
        raise AssertionError("streaming fixture does not support _generate")

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: object = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Cross the output boundary before surfacing the configured error.

        Args:
            messages (list[BaseMessage]): Request messages.
            stop (Optional[list[str]]): Stop sequences.
            run_manager (object): LangChain callback manager.
            **kwargs (object): Additional request arguments.

        Yields:
            ChatGenerationChunk: One committed visible assistant chunk.
        """
        yield ChatGenerationChunk(message=AIMessageChunk(content="committed"))
        raise self._error


def test_factory_when_openrouter_route_is_absent_from_snapshot_rejects_before_credentials() -> None:
    """Require prepared exact-route catalog evidence rather than a structural fallback."""
    snapshot = SeedModelCatalog.load()

    with patch(
        "src.agents.base.CredentialResolver.require",
        side_effect=AssertionError("credential resolution must not run"),
    ):
        with pytest.raises(ValueError, match="Unsupported model_name"):
            LLMFactory.create(
                model_name="openrouter:vendor/unprepared",
                snapshot=snapshot,
            )


def test_factory_when_openrouter_route_is_prepared_uses_entry_api_model_and_capabilities() -> None:
    """Build from the exact prepared entry rather than direct-family defaults."""
    seed = SeedModelCatalog.load()
    template = seed.entries["gpt-5.4"]
    from src.agents.model_catalog.dao import ModelCapabilitiesDAO

    capabilities = ModelCapabilitiesDAO(
        input_modalities=("text",),
        output_modalities=("text",),
        supported_parameters=("tools",),
        reported_output_ceiling=321,
        reasoning_controls_available=True,
    )
    profile = template.runtime_profile.model_copy(update={"max_tokens": 321})
    reasoning = template.reasoning_profile.model_copy(
        update={
            "supported_levels": ("off", "low"),
            "default_level": "off",
            "provider_effort_map": {"low": "low"},
        }
    )
    entry = template.model_copy(
        update={
            "model_name": "openrouter:anthropic/not-direct",
            "api_model_name": "gateway/exact-api-model",
            "provider": ProviderName.OPENROUTER,
            "runtime_profile": profile,
            "reasoning_profile": reasoning,
            "capabilities": capabilities,
        }
    )
    snapshot = seed.model_copy(update={"entries": {**seed.entries, entry.model_name: entry}})
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="fixture",
    )

    with patch("src.agents.base.CredentialResolver.require", return_value=credential):
        result = LLMFactory.create(
            model_name=entry.model_name,
            reasoning_level="low",
            snapshot=snapshot,
        )

    assert isinstance(result.llm, OpenRouterChatOpenAI)
    payload = result.llm._get_request_payload(input_=[HumanMessage(content="hello")])
    assert payload["model"] == "gateway/exact-api-model"
    assert result.llm.max_tokens == 321
    assert payload["extra_body"] == {
        "provider": {"require_parameters": True},
        "reasoning": {"effort": "low"},
    }


async def test_pool_when_openrouter_gateway_error_follows_committed_chunk_does_not_fallback() -> None:
    """Keep a committed OpenRouter SSE failure on its original lane."""
    error = OpenRouterAPIError(status_code=503, error_type="provider_unavailable")
    primary: BaseChatModel = _CommittedFailureModel(error=error)
    fallback: _FallbackCountingModel = _FallbackCountingModel()
    pool = ModelPool(
        pool_dao=ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(
                    model_name="openrouter:vendor/committed",
                    provider=ProviderName.OPENROUTER,
                    priority=0,
                ),
                ModelPoolEntryDAO(
                    model_name="gpt-5.4",
                    provider=ProviderName.OPENAI,
                    priority=1,
                ),
            ]
        ),
        models={"openrouter:vendor/committed": primary, "gpt-5.4": fallback},
    )

    received: list[str] = []
    with pytest.raises(OpenRouterAPIError):
        async for chunk in pool._astream(messages=[HumanMessage(content="hello")]):
            received.append(str(chunk.message.content))

    assert received == ["committed"]
    assert fallback.calls == 0
    assert pool.drain_route_switch_log() == []


def test_session_when_openrouter_stream_failure_is_committed_does_not_create_continuation() -> None:
    """Reject committed OpenRouter continuation before another provider call is planned."""
    from src.agents.providers.stream_recovery.dao import (
        ProviderStreamFailure,
        StreamRecoveryAction,
        StreamRecoveryDecisionDAO,
    )

    plan = PromptAttemptPlanDAO(attempt_kind="initial", text="hello")
    failure = ProviderStreamFailure(
        decision=StreamRecoveryDecisionDAO(
            action=StreamRecoveryAction.DO_NOT_REPLAY,
            reason_code="provider_stream_interrupted",
            retry_delay_seconds=0.0,
            exception_family="httpx.ReadTimeout",
        ),
        partial_output_committed=True,
        attempt_number=1,
    )
    result = PromptAttemptResultDAO(
        turn_id="turn-openrouter",
        terminal_kind="run_failed",
        final_response="committed",
        aborted=False,
        committed_visible_output=True,
        stream_failure=failure,
        originating_provider=ProviderName.OPENROUTER,
    )

    assert SloAgentSession._is_stream_continuation_eligible(plan=plan, result=result) is False


def test_recovery_when_openrouter_policy_rejection_is_terminal_does_not_create_llm_observation() -> None:
    """Keep OpenRouter policy rejections outside generic LLM recovery."""
    from src.integrations.openrouter.exceptions import OpenRouterProtocolError

    error = OpenRouterProtocolError(status_code=403, error_type="content_policy_violation")

    decision = RecoveryPolicy.classify(exc=error, provider=ProviderName.OPENROUTER)

    assert ProviderErrorKind.POLICY_REJECTED is not ProviderErrorKind.OTHER
    assert decision.recovery_class is RecoveryClass.FATAL
    assert decision.observation_hint is None
