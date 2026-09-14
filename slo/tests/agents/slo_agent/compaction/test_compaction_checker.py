"""Unit tests for ``CompactionChecker.should_compact`` (sub-spec 01.a.6)."""

from __future__ import annotations

import pytest

from src.agents.slo_agent.compaction.compaction_checker import (
    CompactionChecker,
    _get_context_window,
)
from src.agents.slo_agent.compaction.constants import RESERVED_TOKEN_LIMIT
from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(*, token_usage: int | None = None) -> SessionHistoryEventDAO:
    """Build a minimal ``SessionHistoryEventDAO`` with the given token count."""
    return SessionHistoryEventDAO(
        session_id="test-session",
        kind="assistant_message",
        payload=SessionHistoryEventPayloadDAO(token_usage=token_usage),
    )


def _events_totalling(*, tokens: int) -> list[SessionHistoryEventDAO]:
    """Return a single-event list whose ``token_usage`` equals ``tokens``."""
    return [_event(token_usage=tokens)]


# ---------------------------------------------------------------------------
# _get_context_window
# ---------------------------------------------------------------------------


class TestGetContextWindow:
    """Context-window lookup, sourced from the canonical MODEL_DEFAULTS registry."""

    def test_matches_registry_for_default_model(self) -> None:
        """The default model (gpt-5.4) resolves to its registry context_window."""
        from config.ai_model_config import MODEL_DEFAULTS

        window: int = _get_context_window(model_name="gpt-5.4")

        assert window == MODEL_DEFAULTS["gpt-5.4"]["context_window"]
        assert window == 1_050_000

    def test_gpt5_resolves_to_400k(self) -> None:
        """gpt-5 resolves to its 400k window from the registry."""
        assert _get_context_window(model_name="gpt-5") == 400_000

    def test_gpt4o_resolves_to_128k_not_default(self) -> None:
        """gpt-4o has a SMALLER-than-default window — it must not be over-estimated."""
        assert _get_context_window(model_name="gpt-4o") == 128_000

    def test_gpt41_resolves_to_1m(self) -> None:
        """gpt-4.1 resolves to its 1M window."""
        assert _get_context_window(model_name="gpt-4.1") == 1_000_000

    def test_kimi_resolves_to_262k(self) -> None:
        """kimi-for-coding resolves to its documented 262k window, not the 200k default."""
        assert _get_context_window(model_name="kimi-for-coding") == 262_144

    def test_claude_models_resolve_to_registry_value(self) -> None:
        """Claude models resolve to whatever the registry declares (currently 1M)."""
        from config.ai_model_config import MODEL_DEFAULTS

        assert (
            _get_context_window(model_name="claude-sonnet-4-6")
            == MODEL_DEFAULTS["claude-sonnet-4-6"]["context_window"]
        )
        assert (
            _get_context_window(model_name="claude-opus-4-7")
            == MODEL_DEFAULTS["claude-opus-4-7"]["context_window"]
        )

    def test_o_series_resolve_to_200k(self) -> None:
        """o1/o3 resolve to their 200k windows."""
        assert _get_context_window(model_name="o1") == 200_000
        assert _get_context_window(model_name="o3") == 200_000

    def test_unknown_model_falls_back_to_200k(self) -> None:
        """An unrecognised model name returns the conservative 200 000 default."""
        window: int = _get_context_window(model_name="gpt-99-turbo-preview")

        assert window == 200_000


# ---------------------------------------------------------------------------
# should_compact — boundary arithmetic
# ---------------------------------------------------------------------------


class TestShouldCompactThresholdArithmetic:
    """Boundary behaviour around the compaction threshold."""

    async def test_returns_false_when_total_equals_threshold(self) -> None:
        """Exactly at the threshold is not yet over it — no compaction."""
        context_window: int = 100_000
        threshold: int = context_window - RESERVED_TOKEN_LIMIT  # 83_616

        result: bool = await CompactionChecker.should_compact(
            events=_events_totalling(tokens=threshold),
            model_name="claude-sonnet-4-6",
            context_window=context_window,
        )

        assert result is False

    async def test_returns_false_when_total_is_one_below_threshold(self) -> None:
        """One token below the threshold does not trigger compaction."""
        context_window: int = 100_000
        threshold: int = context_window - RESERVED_TOKEN_LIMIT

        result: bool = await CompactionChecker.should_compact(
            events=_events_totalling(tokens=threshold - 1),
            model_name="claude-sonnet-4-6",
            context_window=context_window,
        )

        assert result is False

    async def test_returns_true_when_total_is_one_above_threshold(self) -> None:
        """One token above the threshold triggers compaction."""
        context_window: int = 100_000
        threshold: int = context_window - RESERVED_TOKEN_LIMIT

        result: bool = await CompactionChecker.should_compact(
            events=_events_totalling(tokens=threshold + 1),
            model_name="claude-sonnet-4-6",
            context_window=context_window,
        )

        assert result is True

    async def test_returns_true_well_above_threshold(self) -> None:
        """Clearly over-threshold sessions trigger compaction."""
        result: bool = await CompactionChecker.should_compact(
            events=_events_totalling(tokens=190_000),
            model_name="claude-sonnet-4-6",
            context_window=200_000,
        )

        assert result is True

    async def test_returns_false_for_empty_event_list(self) -> None:
        """No events means zero tokens — compaction does not fire."""
        result: bool = await CompactionChecker.should_compact(
            events=[],
            model_name="claude-sonnet-4-6",
        )

        assert result is False


# ---------------------------------------------------------------------------
# should_compact — None token_usage handling
# ---------------------------------------------------------------------------


class TestShouldCompactNoneTokenUsage:
    """Events with ``token_usage=None`` are treated as zero tokens."""

    @pytest.mark.asyncio
    async def test_none_token_usage_counts_as_zero(self) -> None:
        """A single event with ``None`` token_usage contributes 0 to the sum."""
        result: bool = await CompactionChecker.should_compact(
            events=[_event(token_usage=None)],
            model_name="claude-sonnet-4-6",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_mixed_none_and_int_token_usage_sums_correctly(self) -> None:
        """``None`` events are skipped; integer events are summed correctly."""
        context_window: int = 50_000
        threshold: int = context_window - RESERVED_TOKEN_LIMIT  # 33_616

        events: list[SessionHistoryEventDAO] = [
            _event(token_usage=None),
            _event(token_usage=20_000),
            _event(token_usage=None),
            _event(token_usage=14_000),  # total: 34_000 > 33_616
        ]

        result: bool = await CompactionChecker.should_compact(
            events=events,
            model_name="claude-sonnet-4-6",
            context_window=context_window,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_all_none_token_usage_returns_false(self) -> None:
        """When every event has ``None`` token_usage the total is 0."""
        events: list[SessionHistoryEventDAO] = [
            _event(token_usage=None),
            _event(token_usage=None),
            _event(token_usage=None),
        ]

        result: bool = await CompactionChecker.should_compact(
            events=events,
            model_name="claude-sonnet-4-6",
        )

        assert result is False


# ---------------------------------------------------------------------------
# should_compact — context_window override
# ---------------------------------------------------------------------------


class TestShouldCompactContextWindowOverride:
    """Caller-supplied ``context_window`` takes precedence over the model table."""

    @pytest.mark.asyncio
    async def test_explicit_context_window_overrides_model_table(self) -> None:
        """A small override window causes compaction at a lower token count."""
        result: bool = await CompactionChecker.should_compact(
            events=_events_totalling(tokens=10_000),
            model_name="claude-sonnet-4-6",
            context_window=20_000,  # threshold = 3_616
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_explicit_context_window_uses_reserved_limit_correctly(self) -> None:
        """Threshold is override minus ``RESERVED_TOKEN_LIMIT``, not a magic constant."""
        override: int = 32_768
        threshold: int = override - RESERVED_TOKEN_LIMIT  # 16_384

        below: bool = await CompactionChecker.should_compact(
            events=_events_totalling(tokens=threshold),
            model_name="unknown-model",
            context_window=override,
        )
        above: bool = await CompactionChecker.should_compact(
            events=_events_totalling(tokens=threshold + 1),
            model_name="unknown-model",
            context_window=override,
        )

        assert below is False
        assert above is True

    @pytest.mark.asyncio
    async def test_unknown_model_with_no_override_uses_200k_default(self) -> None:
        """Unknown model falls back to 200 000; compaction fires near that limit."""
        threshold: int = 200_000 - RESERVED_TOKEN_LIMIT  # 183_616

        result: bool = await CompactionChecker.should_compact(
            events=_events_totalling(tokens=threshold + 1),
            model_name="gpt-99-turbo-preview",
        )

        assert result is True


# ---------------------------------------------------------------------------
# should_compact — multi-event summation
# ---------------------------------------------------------------------------


class TestShouldCompactMultiEventSum:
    """Token counts are summed correctly across many events."""

    @pytest.mark.asyncio
    async def test_sum_across_multiple_events(self) -> None:
        """Token usage from several events is summed before threshold comparison."""
        context_window: int = 200_000
        threshold: int = context_window - RESERVED_TOKEN_LIMIT  # 183_616

        events: list[SessionHistoryEventDAO] = [
            _event(token_usage=60_000),
            _event(token_usage=60_000),
            _event(token_usage=63_617),  # total: 183_617 > 183_616
        ]

        result: bool = await CompactionChecker.should_compact(
            events=events,
            model_name="claude-sonnet-4-6",
            context_window=context_window,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_multiple_events_below_threshold_return_false(self) -> None:
        """Many small events that sum below threshold do not trigger compaction."""
        events: list[SessionHistoryEventDAO] = [
            _event(token_usage=1_000),
            _event(token_usage=1_000),
            _event(token_usage=1_000),
        ]

        result: bool = await CompactionChecker.should_compact(
            events=events,
            model_name="claude-sonnet-4-6",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_events_of_mixed_kinds_are_all_counted(self) -> None:
        """``token_usage`` is summed regardless of event kind."""
        context_window: int = 50_000

        events: list[SessionHistoryEventDAO] = [
            SessionHistoryEventDAO(
                session_id="s1",
                kind="user_message",
                payload=SessionHistoryEventPayloadDAO(token_usage=10_000),
            ),
            SessionHistoryEventDAO(
                session_id="s1",
                kind="tool_result",
                payload=SessionHistoryEventPayloadDAO(token_usage=10_000),
            ),
            SessionHistoryEventDAO(
                session_id="s1",
                kind="assistant_message",
                payload=SessionHistoryEventPayloadDAO(token_usage=14_000),
            ),
            # total: 34_000 > 33_616
        ]

        result: bool = await CompactionChecker.should_compact(
            events=events,
            model_name="claude-haiku-4-5-20251001",
            context_window=context_window,
        )

        assert result is True
