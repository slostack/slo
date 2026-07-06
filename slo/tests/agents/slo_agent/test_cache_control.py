"""Tests for prompt-caching support (sub-spec 18.03).

Covers:
- ``LLMBuildResult.supports_explicit_caching`` flag for Faux vs Anthropic paths
- ``SloAgent._supports_explicit_caching`` surfaced from ``SloAgentBuildResult``
- ``SystemMessage`` cache_control annotation when flag is True / absent when False
- ``TokenUsageTotalsDAO`` cache field defaults and accumulation
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from src.agents.base import LLMBuildResult
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.graph import SloAgentBuildResult, build_slo_agent
from src.agents.slo_agent.sessions.usage import TokenUsageTotalsDAO
from src.agents.providers.faux import FauxChatModel


# ---------------------------------------------------------------------------
# LLMBuildResult flag
# ---------------------------------------------------------------------------


class TestLLMBuildResultCachingFlag:
    """``LLMBuildResult.supports_explicit_caching`` reflects the provider."""

    def test_faux_path_has_explicit_caching_false(self) -> None:
        """Pre-built LLM path (no factory) surfaces ``supports_explicit_caching=False``."""
        faux: FauxChatModel = FauxChatModel(responses=[])
        result: LLMBuildResult = LLMBuildResult(llm=faux, supports_explicit_caching=False)

        assert result.supports_explicit_caching is False

    def test_anthropic_flag_true(self) -> None:
        """Anthropic-marked ``LLMBuildResult`` carries ``supports_explicit_caching=True``."""
        faux: FauxChatModel = FauxChatModel(responses=[])
        result: LLMBuildResult = LLMBuildResult(llm=faux, supports_explicit_caching=True)

        assert result.supports_explicit_caching is True


# ---------------------------------------------------------------------------
# SloAgent flag propagation
# ---------------------------------------------------------------------------


class TestPromptCachingFlag:
    """``SloAgent._supports_explicit_caching`` and ``SystemMessage`` annotation."""

    def test_slo_agent_faux_has_explicit_caching_false(self) -> None:
        """Pre-built Faux agent has ``_supports_explicit_caching=False``."""
        agent: SloAgent = SloAgent(llm=FauxChatModel(responses=[]))

        assert agent._supports_explicit_caching is False

    def test_slo_agent_build_result_anthropic_flag_surfaced(self) -> None:
        """``SloAgentBuildResult.supports_explicit_caching=True`` flows into the agent."""
        faux: FauxChatModel = FauxChatModel(responses=[])
        faux_build_result = LLMBuildResult(llm=faux, supports_explicit_caching=True)

        with patch(
            "src.agents.slo_agent.graph.service.LLMFactory.create",
            return_value=faux_build_result,
        ):
            agent: SloAgent = SloAgent(model_name="claude-sonnet-4-6")

        assert agent._supports_explicit_caching is True

    def test_build_initial_messages_no_cache_control_when_flag_false(self) -> None:
        """``_build_initial_messages`` omits ``cache_control`` when flag is False."""
        agent: SloAgent = SloAgent(
            llm=FauxChatModel(responses=[]),
            system_prompt="System text.",
        )
        assert agent._supports_explicit_caching is False

        messages = agent._build_initial_messages(query="hello")

        system_msg: SystemMessage = messages[0]
        assert isinstance(system_msg, SystemMessage)
        assert "cache_control" not in (system_msg.additional_kwargs or {})

    def test_build_initial_messages_adds_cache_control_when_flag_true(self) -> None:
        """``_build_initial_messages`` adds ``cache_control`` when Anthropic flag is set."""
        faux: FauxChatModel = FauxChatModel(responses=[])
        faux_build_result = LLMBuildResult(llm=faux, supports_explicit_caching=True)

        with patch(
            "src.agents.slo_agent.graph.service.LLMFactory.create",
            return_value=faux_build_result,
        ):
            agent: SloAgent = SloAgent(
                model_name="claude-sonnet-4-6",
                system_prompt="System text.",
            )

        messages = agent._build_initial_messages(query="hello")

        system_msg: SystemMessage = messages[0]
        assert isinstance(system_msg, SystemMessage)
        assert system_msg.additional_kwargs.get("cache_control") == {"type": "ephemeral"}

    def test_cache_fields_captured_from_usage_metadata(self) -> None:
        """Cache token counts from usage_metadata are stored on the latest turn totals."""
        faux_response: AIMessage = AIMessage(
            content="hi",
            usage_metadata={
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "cache_creation_input_tokens": 6000,
                "cache_read_input_tokens": 0,
            },
        )
        agent: SloAgent = SloAgent(llm=FauxChatModel(responses=[faux_response]))

        agent._capture_completed_usage(message=faux_response)

        totals: TokenUsageTotalsDAO = agent._last_usage_totals
        assert totals.cache_creation_input_tokens == 6000
        assert totals.cache_read_input_tokens == 0


# ---------------------------------------------------------------------------
# TokenUsageTotalsDAO cache field accumulation
# ---------------------------------------------------------------------------


class TestTokenUsageTotalsDAOCacheAccumulation:
    """Cache fields on ``TokenUsageTotalsDAO`` default to None and accumulate correctly."""

    def test_cache_fields_default_to_none(self) -> None:
        """Fresh ``TokenUsageTotalsDAO`` has ``None`` cache fields."""
        totals: TokenUsageTotalsDAO = TokenUsageTotalsDAO()

        assert totals.cache_creation_input_tokens is None
        assert totals.cache_read_input_tokens is None

    def test_add_accumulates_cache_fields(self) -> None:
        """``add()`` sums cache fields the same way it sums other token counts."""
        first: TokenUsageTotalsDAO = TokenUsageTotalsDAO(
            input_tokens=100,
            output_tokens=10,
            total_tokens=110,
            cache_creation_input_tokens=6000,
            cache_read_input_tokens=50,
        )
        second: TokenUsageTotalsDAO = TokenUsageTotalsDAO(
            input_tokens=80,
            output_tokens=8,
            total_tokens=88,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=6000,
        )

        result: TokenUsageTotalsDAO = first.add(other=second)

        assert result.cache_creation_input_tokens == 6000
        assert result.cache_read_input_tokens == 6050

    def test_add_none_stays_none_when_both_absent(self) -> None:
        """``add()`` returns ``None`` for cache fields when both operands are ``None``."""
        first: TokenUsageTotalsDAO = TokenUsageTotalsDAO(total_tokens=10)
        second: TokenUsageTotalsDAO = TokenUsageTotalsDAO(total_tokens=5)

        result: TokenUsageTotalsDAO = first.add(other=second)

        assert result.cache_creation_input_tokens is None
        assert result.cache_read_input_tokens is None
