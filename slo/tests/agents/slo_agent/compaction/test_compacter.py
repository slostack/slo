"""Tests for Compacter and CompactionResult (sub-spec 01.a.7).

Coverage targets:
  - _find_cut_point: normal cut, tool_call/tool_result pair protection (Rule 1),
    first-user_message protection (Rule 2), error paths.
  - _build_compaction_input: correct role labelling; lifecycle events skipped.
  - compact(): full happy-path with mock LLM; token accounting.
"""

from __future__ import annotations

import base64
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.agents.providers.openai_codex import build_chatgpt_backed_chat_openai
from src.agents.slo_agent.compaction.compacter import (
    CompactionResult,
    Compacter,
    _max_compaction_input_token_units,
)
from src.agents.slo_agent.compaction.constants import (
    COMPACTION_INPUT_SAFETY_DIVISOR,
    KEEP_RECENT_TOKENS,
    RESERVED_TOKEN_LIMIT,
)
from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    *,
    kind: str,
    session_id: str = "sess-1",
    token_usage: int | None = None,
    content: str | None = None,
    tool_name: str | None = None,
    tool_call_id: str | None = None,
    tool_input: dict[str, Any] | None = None,
    tool_output: str | None = None,
) -> SessionHistoryEventDAO:
    """Construct a SessionHistoryEventDAO for tests."""
    return SessionHistoryEventDAO(
        session_id=session_id,
        kind=kind,  # type: ignore[arg-type]
        recorded_at=datetime.now(timezone.utc),
        payload=SessionHistoryEventPayloadDAO(
            content=content,
            token_usage=token_usage,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_input=tool_input,
            tool_output=tool_output,
        ),
    )


def _mock_llm(*, summary: str = "The summary.") -> MagicMock:
    """Return a mock BaseChatModel whose ainvoke returns summary.

    ``spec=BaseChatModel`` keeps the double from fabricating ``.bound`` or
    ``.active_llm``, which the pool/backend unwrapping probes would otherwise
    follow forever.
    """
    llm = MagicMock(spec=BaseChatModel)
    response = MagicMock(spec=AIMessage)
    response.content = summary
    llm.ainvoke = AsyncMock(return_value=response)
    return llm


# ---------------------------------------------------------------------------
# _find_cut_point: normal cases
# ---------------------------------------------------------------------------


class TestFindCutPointNormal:
    def test_simple_cut_at_expected_index(self) -> None:
        """Cut is found when accumulation reaches KEEP_RECENT_TOKENS."""
        # 5 events.  Each has token_usage = KEEP_RECENT_TOKENS // 2.
        # Walking newest-to-oldest: after event[4] we have half the budget,
        # after event[3] the retained window reaches the full budget
        # (>= KEEP_RECENT_TOKENS).  candidate_cut = 3 - 1 = 2 → retain idx3,4.
        half: int = KEEP_RECENT_TOKENS // 2
        events = [
            _make_event(kind="user_message", token_usage=half),  # idx 0
            _make_event(kind="assistant_message", token_usage=half),  # idx 1
            _make_event(kind="assistant_message", token_usage=half),  # idx 2  ← cut
            _make_event(kind="assistant_message", token_usage=half),  # idx 3  ← retained
            _make_event(kind="assistant_message", token_usage=half),  # idx 4  ← retained
        ]
        cut = Compacter._find_cut_point(events=events)
        assert cut == 2

    def test_none_token_usage_treated_as_zero(self) -> None:
        """Events with token_usage=None contribute 0 to the accumulator."""
        big: int = KEEP_RECENT_TOKENS + 1
        events = [
            _make_event(kind="user_message", token_usage=None),  # idx 0
            _make_event(kind="assistant_message", token_usage=None),  # idx 1  ← cut
            _make_event(kind="assistant_message", token_usage=big),  # idx 2  ← retained
        ]
        # Walking newest: idx2 contributes big > threshold after first event.
        # candidate_cut = 2 - 1 = 1; kind "assistant_message" is safe; not first user_message.
        cut = Compacter._find_cut_point(events=events)
        assert cut == 1


# ---------------------------------------------------------------------------
# _find_cut_point: Rule 1 — tool_call / tool_result pair protection
# ---------------------------------------------------------------------------


class TestFindCutPointCleanCut:
    """The cut must never split a tool span (parallel batch or spawn group).

    Spans are paired by ``tool_call_id`` — the shape of real tool events.
    When the token-driven candidate would split a span, the cut retreats UP
    (an earlier index, compacting more) to before the span's first tool_call.
    """

    def test_cut_retreats_above_parallel_batch_split_by_delta(self) -> None:
        """Regression for the orphan bug: a delta between calls and results.

        The token walk lands the candidate on the interleaved ``assistant_delta``
        (idx 4), which would compact the parallel tool_calls (A@2, B@3) while
        retaining their tool_results (A@5, B@6). The cut must retreat above the
        batch (to idx 1).
        """
        big: int = KEEP_RECENT_TOKENS + 1
        events = [
            _make_event(kind="user_message", token_usage=10),  # 0
            _make_event(kind="assistant_message", token_usage=10),  # 1
            _make_event(kind="tool_call", token_usage=10, tool_call_id="A"),  # 2
            _make_event(kind="tool_call", token_usage=10, tool_call_id="B"),  # 3
            _make_event(kind="assistant_delta", token_usage=10),  # 4  ← naive cut
            _make_event(kind="tool_result", token_usage=big, tool_call_id="A"),  # 5
            _make_event(kind="tool_result", token_usage=10, tool_call_id="B"),  # 6
            _make_event(kind="assistant_message", token_usage=10),  # 7
        ]
        cut = Compacter._find_cut_point(events=events)
        assert cut == 1  # retreated above tool_call A (idx 2)
        assert Compacter._is_clean_cut(events=events, cut=cut)

    def test_cut_retreats_above_spawn_sub_agents_group(self) -> None:
        """A spawn_sub_agents tool span (with interleaved sub-agent events) is not split.

        ``spawn_sub_agents`` is a tool: tool_call(SPAWN) → sub_agent_spawned/
        sub_agent_completed (turn_id=None) → tool_result(SPAWN). The candidate
        lands inside the span (idx 6); the cut retreats above the spawn
        tool_call (idx 2).
        """
        big: int = KEEP_RECENT_TOKENS + 1
        events = [
            _make_event(kind="user_message", token_usage=10),  # 0
            _make_event(kind="assistant_message", token_usage=10),  # 1
            _make_event(kind="tool_call", token_usage=10, tool_call_id="SPAWN"),  # 2
            _make_event(kind="sub_agent_spawned", token_usage=0),  # 3
            _make_event(kind="sub_agent_spawned", token_usage=0),  # 4
            _make_event(kind="sub_agent_completed", token_usage=0),  # 5
            _make_event(kind="sub_agent_completed", token_usage=0),  # 6
            _make_event(kind="tool_result", token_usage=big, tool_call_id="SPAWN"),  # 7
            _make_event(kind="assistant_message", token_usage=10),  # 8
        ]
        cut = Compacter._find_cut_point(events=events)
        assert cut == 1  # retreated above the spawn tool_call (idx 2)
        assert Compacter._is_clean_cut(events=events, cut=cut)

    def test_fully_compacted_group_needs_no_retreat(self) -> None:
        """A group entirely on the compacted side is already clean (no retreat)."""
        big: int = KEEP_RECENT_TOKENS + 1
        events = [
            _make_event(kind="user_message", token_usage=10),  # 0
            _make_event(kind="tool_call", token_usage=10, tool_call_id="A"),  # 1
            _make_event(kind="tool_result", token_usage=10, tool_call_id="A"),  # 2
            _make_event(kind="assistant_message", token_usage=big),  # 3  ← retained
        ]
        # candidate = 3 - 1 = 2 (the tool_result); span A = (1, 2), 1 <= 2 < 2 is
        # False, so the cut is already clean — the whole group is compacted.
        cut = Compacter._find_cut_point(events=events)
        assert cut == 2
        assert Compacter._is_clean_cut(events=events, cut=cut)


class TestIsCleanCut:
    """The cut-completeness invariant (Requirement 3)."""

    def _events_with_span(self) -> list[SessionHistoryEventDAO]:
        return [
            _make_event(kind="user_message", token_usage=10),  # 0
            _make_event(kind="assistant_message", token_usage=10),  # 1
            _make_event(kind="tool_call", token_usage=10, tool_call_id="A"),  # 2
            _make_event(kind="assistant_delta", token_usage=10),  # 3
            _make_event(kind="tool_result", token_usage=10, tool_call_id="A"),  # 4
        ]

    def test_clean_when_group_fully_retained(self) -> None:
        """cut before the call → whole span retained → clean."""
        events = self._events_with_span()
        assert Compacter._is_clean_cut(events=events, cut=1) is True

    def test_clean_when_group_fully_compacted(self) -> None:
        """cut at/after the result → whole span compacted → clean."""
        events = self._events_with_span()
        assert Compacter._is_clean_cut(events=events, cut=4) is True

    def test_not_clean_when_call_compacted_result_retained(self) -> None:
        """cut between call and result (on the delta) → split → not clean."""
        events = self._events_with_span()
        assert Compacter._is_clean_cut(events=events, cut=3) is False

    def test_find_cut_point_raises_when_no_clean_cut_exists(self) -> None:
        """A span covering the whole compactable prefix has no clean cut."""
        big: int = KEEP_RECENT_TOKENS + 1
        events = [
            _make_event(kind="tool_call", token_usage=10, tool_call_id="A"),  # 0
            _make_event(kind="tool_result", token_usage=big, tool_call_id="A"),  # 1
        ]
        with pytest.raises(ValueError, match="clean cut"):
            Compacter._find_cut_point(events=events)


# ---------------------------------------------------------------------------
# _find_cut_point: Rule 2 — first user_message protection
# ---------------------------------------------------------------------------


class TestFindCutPointFirstUserMessageProtection:
    def test_cut_advances_past_first_user_message(self) -> None:
        """If natural cut lands on the first user_message, advance to idx+1."""
        big: int = KEEP_RECENT_TOKENS + 1
        events = [
            _make_event(kind="session_started", token_usage=5),  # idx 0
            _make_event(kind="user_message", token_usage=5),  # idx 1  ← first user msg
            _make_event(kind="assistant_message", token_usage=big),  # idx 2  ← retained
        ]
        # Walking: idx2 → big > threshold; candidate_cut = 2 - 1 = 1.
        # events[1].kind == "user_message" AND it is the first user_message
        # → advance to 1 + 1 = 2.
        cut = Compacter._find_cut_point(events=events)
        assert cut == 2

    def test_cut_at_first_user_message_itself_advances(self) -> None:
        """candidate_cut == first_user_idx forces advance to first_user_idx+1."""
        big: int = KEEP_RECENT_TOKENS + 1
        events = [
            _make_event(kind="user_message", token_usage=5),  # idx 0  ← first user msg
            _make_event(kind="assistant_message", token_usage=5),  # idx 1
            _make_event(kind="assistant_message", token_usage=big),  # idx 2  ← retained
        ]
        # candidate_cut = 2 - 1 = 1; first_user_idx = 0; 1 > 0 so rule 2 does NOT trigger.
        cut = Compacter._find_cut_point(events=events)
        assert cut == 1

    def test_rule2_raises_when_no_events_after_first_user_message(self) -> None:
        """Advancing past first_user_message keeps a valid cut when room remains."""
        big: int = KEEP_RECENT_TOKENS + 1
        events = [
            _make_event(kind="user_message", token_usage=big),  # idx 0  ← only event
            _make_event(kind="session_started", token_usage=big),  # idx 1 — retained
        ]
        # candidate_cut = 1 - 1 = 0; events[0].kind == "user_message" == first_user_message
        # → first_user_idx = 0; candidate_cut = 0 <= 0 → advance to 0+1 = 1.
        # 1 < len(events)=2 → valid cut.
        cut = Compacter._find_cut_point(events=events)
        assert cut == 1


# ---------------------------------------------------------------------------
# _find_cut_point: error paths
# ---------------------------------------------------------------------------


class TestFindCutPointErrors:
    def test_raises_on_list_too_short(self) -> None:
        events = [_make_event(kind="user_message", token_usage=100)]
        with pytest.raises(ValueError, match="too short"):
            Compacter._find_cut_point(events=events)

    def test_raises_when_threshold_never_crossed(self) -> None:
        """No compaction needed when total tokens stay under the threshold."""
        events = [
            _make_event(kind="user_message", token_usage=10),
            _make_event(kind="assistant_message", token_usage=10),
        ]
        with pytest.raises(ValueError, match="does not exceed KEEP_RECENT_TOKENS"):
            Compacter._find_cut_point(events=events)

    def test_raises_when_retain_window_covers_entire_list(self) -> None:
        """Raise when a tool span covers the whole compactable prefix.

        The retreat needed to keep the span whole walks the cut below index 0,
        so no clean cut exists.
        """
        big: int = KEEP_RECENT_TOKENS + 1
        big_events = [
            _make_event(kind="tool_call", token_usage=5, tool_call_id="A"),
            _make_event(kind="tool_result", token_usage=big, tool_call_id="A"),
        ]
        with pytest.raises(ValueError):
            Compacter._find_cut_point(events=big_events)


# ---------------------------------------------------------------------------
# _build_compaction_input
# ---------------------------------------------------------------------------


class TestBuildCompactionInput:
    def test_user_and_assistant_messages_rendered(self) -> None:
        events = [
            _make_event(kind="user_message", content="Hello"),
            _make_event(kind="assistant_message", content="Hi there"),
        ]
        result = Compacter._build_compaction_input(events=events)
        assert "user: Hello" in result
        assert "assistant: Hi there" in result

    def test_tool_call_and_result_rendered(self) -> None:
        events = [
            _make_event(
                kind="tool_call",
                tool_name="bash",
                tool_input={"command": "ls"},
            ),
            _make_event(
                kind="tool_result",
                tool_name="bash",
                tool_output="file1.py\nfile2.py",
            ),
        ]
        result = Compacter._build_compaction_input(events=events)
        assert "tool_call [bash]:" in result
        assert "tool_result [bash]: file1.py" in result

    def test_lifecycle_events_skipped(self) -> None:
        events = [
            _make_event(kind="session_started"),
            _make_event(kind="run_started"),
            _make_event(kind="user_message", content="Do the thing"),
            _make_event(kind="run_completed"),
        ]
        result = Compacter._build_compaction_input(events=events)
        assert "session_started" not in result
        assert "run_started" not in result
        assert "run_completed" not in result
        assert "user: Do the thing" in result

    def test_steering_message_rendered(self) -> None:
        events = [_make_event(kind="steering_message", content="Focus on tests")]
        result = Compacter._build_compaction_input(events=events)
        assert "system (steering): Focus on tests" in result

    def test_prior_compaction_summary_rendered(self) -> None:
        events = [_make_event(kind="compaction_summary", content="Prior history summary")]
        result = Compacter._build_compaction_input(events=events)
        assert "[prior summary]: Prior history summary" in result

    def test_empty_events_returns_empty_string(self) -> None:
        assert Compacter._build_compaction_input(events=[]) == ""

    def test_only_lifecycle_events_returns_empty_string(self) -> None:
        events = [
            _make_event(kind="session_started"),
            _make_event(kind="run_completed"),
        ]
        assert Compacter._build_compaction_input(events=events) == ""


# ---------------------------------------------------------------------------
# compact(): full happy-path
# ---------------------------------------------------------------------------


class TestCompactHappyPath:
    @pytest.mark.asyncio
    async def test_compact_returns_correct_ids(self) -> None:
        """compact() sets first_kept_entry_id and cut_point_entry_id correctly."""
        big: int = KEEP_RECENT_TOKENS + 1
        e0 = _make_event(kind="user_message", token_usage=10, content="First message")
        e1 = _make_event(kind="assistant_message", token_usage=10, content="First reply")
        e2 = _make_event(kind="assistant_message", token_usage=big, content="Big reply")

        # _find_cut_point: walking reversed: e2 → accumulated=big > threshold → candidate_cut=1
        # events[1].kind == "assistant_message", safe.
        # first_user_idx=0; candidate_cut(1) > first_user_idx(0) → no rule 2 trigger.
        # cut = 1 → compacted=[e0,e1], retained=[e2]

        llm = _mock_llm(summary="Concise summary of e0 and e1.")
        result = await Compacter.compact(events=[e0, e1, e2], model_name="claude-3", llm=llm)

        assert result.cut_point_entry_id == e1.event_id
        assert result.first_kept_entry_id == e2.event_id
        assert result.summary_text == "Concise summary of e0 and e1."

    @pytest.mark.asyncio
    async def test_compact_token_counts(self) -> None:
        """tokens_before = sum of compacted event token_usage; tokens_after = ceil(len/4)."""
        big: int = KEEP_RECENT_TOKENS + 1
        e0 = _make_event(kind="user_message", token_usage=100, content="u")
        e1 = _make_event(kind="assistant_message", token_usage=200, content="a")
        e2 = _make_event(kind="assistant_message", token_usage=big, content="b")

        summary = "x" * 40  # 40 chars → ceil(40/4) = 10 tokens
        llm = _mock_llm(summary=summary)
        result = await Compacter.compact(events=[e0, e1, e2], model_name="m", llm=llm)

        assert result.tokens_before == 300  # e0 + e1
        assert result.tokens_after == math.ceil(40 / 4)

    @pytest.mark.asyncio
    async def test_compact_invokes_llm_with_messages(self) -> None:
        """The LLM's ainvoke is called exactly once."""
        # Three events so the retained tail is non-empty after the cut
        # (a real compacted session always has a large retained tail).
        big: int = KEEP_RECENT_TOKENS + 1
        e0 = _make_event(kind="user_message", token_usage=10, content="u")
        e1 = _make_event(kind="assistant_message", token_usage=10, content="a")
        e2 = _make_event(kind="assistant_message", token_usage=big, content="b")

        llm = _mock_llm(summary="summary")
        await Compacter.compact(events=[e0, e1, e2], model_name="m", llm=llm)

        llm.ainvoke.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_compact_with_none_token_usages(self) -> None:
        """token_usage=None for compacted events contributes 0 to tokens_before."""
        big: int = KEEP_RECENT_TOKENS + 1
        e0 = _make_event(kind="user_message", token_usage=None, content="u")
        e1 = _make_event(kind="assistant_message", token_usage=None, content="a")
        e2 = _make_event(kind="assistant_message", token_usage=big, content="b")

        llm = _mock_llm(summary="s")
        result = await Compacter.compact(events=[e0, e1, e2], model_name="m", llm=llm)

        assert result.tokens_before == 0

    @pytest.mark.asyncio
    async def test_compact_preserves_tool_pair_rule(self) -> None:
        """compact() never splits a tool_call/tool_result span (retreats above it)."""
        big: int = KEEP_RECENT_TOKENS + 1
        e0 = _make_event(kind="user_message", token_usage=10, content="do it")
        e1 = _make_event(kind="assistant_message", token_usage=10, content="ok")  # ← cut here
        e2 = _make_event(kind="tool_call", token_usage=5, tool_name="bash", tool_input={}, tool_call_id="A")
        e3 = _make_event(
            kind="tool_result", token_usage=big, tool_name="bash", tool_output="done", tool_call_id="A"
        )

        llm = _mock_llm(summary="summary")
        result = await Compacter.compact(events=[e0, e1, e2, e3], model_name="m", llm=llm)

        # The candidate (e2) splits span A=(2,3); the cut retreats above it to e1,
        # keeping the whole tool group on the retained side.
        assert result.cut_point_entry_id == e1.event_id
        assert result.first_kept_entry_id == e2.event_id


# ---------------------------------------------------------------------------
# compact(): LLM response content formats
# ---------------------------------------------------------------------------


class TestCompactLLMContentFormats:
    @pytest.mark.asyncio
    async def test_list_content_blocks_joined(self) -> None:
        """Structured content lists (Anthropic format) are joined into a string."""
        big: int = KEEP_RECENT_TOKENS + 1
        e0 = _make_event(kind="user_message", token_usage=10, content="u")
        e1 = _make_event(kind="assistant_message", token_usage=10, content="a")
        e2 = _make_event(kind="assistant_message", token_usage=big, content="b")

        # ``spec=BaseChatModel`` keeps the double from fabricating ``.bound`` or
        # ``.active_llm``, which an unwrapping probe would otherwise follow.
        llm = MagicMock(spec=BaseChatModel)
        response = MagicMock()
        response.content = [
            {"type": "text", "text": "Part one. "},
            {"type": "text", "text": "Part two."},
        ]
        llm.ainvoke = AsyncMock(return_value=response)

        result = await Compacter.compact(events=[e0, e1, e2], model_name="m", llm=llm)
        assert result.summary_text == "Part one. Part two."


# ---------------------------------------------------------------------------
# _cap_compacted_events
# ---------------------------------------------------------------------------


class TestCapCompactedEvents:
    """_cap_compacted_events splits the compacted slice when it exceeds the budget."""

    def _make_events_with_usage(
        self,
        usages: list[int],
        kind: str = "user_message",
    ) -> list[SessionHistoryEventDAO]:
        return [_make_event(kind=kind, token_usage=u) for u in usages]

    def test_returns_all_events_when_under_budget(self) -> None:
        """No split when total token_usage fits within max_token_units."""
        events = self._make_events_with_usage([100, 200, 300])
        head, overflow = Compacter._cap_compacted_events(events=events, max_token_units=1000)
        assert len(head) == 3
        assert overflow == []

    def test_returns_all_events_when_exactly_at_budget(self) -> None:
        """Total equal to budget → no split (> not >=)."""
        events = self._make_events_with_usage([500, 500])
        head, overflow = Compacter._cap_compacted_events(events=events, max_token_units=1000)
        assert len(head) == 2
        assert overflow == []

    def test_splits_at_first_event_that_would_exceed_budget(self) -> None:
        """Head contains events that fit; overflow is the first event that exceeds."""
        events = self._make_events_with_usage([300, 400, 500])
        # After e0: 300 <= 600 → ok
        # After e1: 700 > 600 AND idx=1 > 0 → split here
        head, overflow = Compacter._cap_compacted_events(events=events, max_token_units=600)
        assert len(head) == 1
        assert len(overflow) == 2
        assert head[0].payload.token_usage == 300
        assert overflow[0].payload.token_usage == 400

    def test_always_keeps_at_least_one_event_in_head(self) -> None:
        """Even when the first event exceeds the budget, it stays in head."""
        events = self._make_events_with_usage([9999, 100])
        head, overflow = Compacter._cap_compacted_events(events=events, max_token_units=10)
        assert len(head) == 1
        assert len(overflow) == 1
        assert head[0].payload.token_usage == 9999

    def test_none_token_usage_treated_as_zero(self) -> None:
        """None token_usage contributes 0 to the running total."""
        events = [
            _make_event(kind="user_message", token_usage=None),
            _make_event(kind="assistant_message", token_usage=None),
            _make_event(kind="assistant_message", token_usage=500),
        ]
        # 0 + 0 + 500 = 500 <= 600 → no split
        head, overflow = Compacter._cap_compacted_events(events=events, max_token_units=600)
        assert len(head) == 3
        assert overflow == []

    def test_split_preserves_event_identity(self) -> None:
        """head + overflow reconstructs the original list in the same order."""
        usages = [100, 200, 300, 400, 500]
        events = self._make_events_with_usage(usages)
        head, overflow = Compacter._cap_compacted_events(events=events, max_token_units=350)
        assert [e.payload.token_usage for e in head + overflow] == usages


# ---------------------------------------------------------------------------
# compact(): cap integration
# ---------------------------------------------------------------------------


class TestCompactWithCap:
    """compact() applies _cap_compacted_events; overflow moves to retained."""

    @pytest.mark.asyncio
    async def test_overflow_events_become_first_kept_entry(self) -> None:
        """When the compacted slice exceeds the cap, first_kept_entry_id points to
        the first overflow event, not the original retained event."""
        big: int = KEEP_RECENT_TOKENS + 1
        cap: int = 50

        # compacted = [e0(30), e1(30), e2(30)] → total 90 > cap=50
        # after cap: head=[e0], overflow=[e1, e2], retained=[e3]
        # new retained_events = [e1, e2, e3] → first_kept = e1
        e0 = _make_event(kind="user_message", token_usage=30, content="u0")
        e1 = _make_event(kind="assistant_message", token_usage=30, content="a1")
        e2 = _make_event(kind="assistant_message", token_usage=30, content="a2")
        e3 = _make_event(kind="assistant_message", token_usage=big, content="retained")

        llm = _mock_llm(summary="summary")
        result = await Compacter.compact(
            events=[e0, e1, e2, e3],
            model_name="m",
            llm=llm,
            context_window=cap * COMPACTION_INPUT_SAFETY_DIVISOR + RESERVED_TOKEN_LIMIT,
        )

        assert result.cut_point_entry_id == e0.event_id
        assert result.first_kept_entry_id == e1.event_id

    @pytest.mark.asyncio
    async def test_tokens_before_counts_only_capped_head(self) -> None:
        """tokens_before reflects the head only, not the full compacted slice."""
        big: int = KEEP_RECENT_TOKENS + 1
        cap: int = 50

        e0 = _make_event(kind="user_message", token_usage=30, content="u0")
        e1 = _make_event(kind="assistant_message", token_usage=30, content="a1")
        e2 = _make_event(kind="assistant_message", token_usage=big, content="retained")

        llm = _mock_llm(summary="s")
        result = await Compacter.compact(
            events=[e0, e1, e2],
            model_name="m",
            llm=llm,
            context_window=cap * COMPACTION_INPUT_SAFETY_DIVISOR + RESERVED_TOKEN_LIMIT,
        )

        # head=[e0(30)] after cap; tokens_before = 30
        assert result.tokens_before == 30

    @pytest.mark.asyncio
    async def test_no_cap_when_compacted_events_fit(self) -> None:
        """When the compacted slice is within budget, compact() behaves as before."""
        big: int = KEEP_RECENT_TOKENS + 1
        e0 = _make_event(kind="user_message", token_usage=10, content="u")
        e1 = _make_event(kind="assistant_message", token_usage=10, content="a")
        e2 = _make_event(kind="assistant_message", token_usage=big, content="b")

        llm = _mock_llm(summary="summary")
        # context_window large enough that cap >> 20 (total of compacted events)
        result = await Compacter.compact(
            events=[e0, e1, e2],
            model_name="m",
            llm=llm,
            context_window=1_000_000,
        )

        assert result.cut_point_entry_id == e1.event_id
        assert result.first_kept_entry_id == e2.event_id


# ---------------------------------------------------------------------------
# _max_compaction_input_token_units
# ---------------------------------------------------------------------------


class TestMaxCompactionInputTokenUnits:
    def test_applies_safety_divisor_and_reserved_headroom(self) -> None:
        """Budget = (context_window - RESERVED_TOKEN_LIMIT) // DIVISOR."""
        result = _max_compaction_input_token_units(context_window=1_050_000)
        expected = (1_050_000 - RESERVED_TOKEN_LIMIT) // COMPACTION_INPUT_SAFETY_DIVISOR
        assert result == expected

    def test_returns_at_least_one(self) -> None:
        """Even a tiny context window produces a budget >= 1."""
        result = _max_compaction_input_token_units(context_window=1)
        assert result >= 1

    def test_zero_available_clamps_to_one(self) -> None:
        """When context_window <= RESERVED_TOKEN_LIMIT, budget is clamped to 1."""
        result = _max_compaction_input_token_units(context_window=RESERVED_TOKEN_LIMIT - 1)
        assert result == 1


# ---------------------------------------------------------------------------
# _invoke_llm_summary request shaping (85.a.1)
# ---------------------------------------------------------------------------


class _CapturingCodexLane:
    """Direct model recognized as ChatGPT-backend through its ``.bound`` model.

    ``_uses_chatgpt_backend_responses`` unwraps ``.bound`` to the real
    ``ChatOpenAI`` rooted at the ChatGPT backend, while ``_is_pool_bound``
    stays False because the stub exposes no ``.active_llm``.
    """

    def __init__(self) -> None:
        self.bound = ChatOpenAI(
            model="gpt-5",
            api_key="sk-test",  # type: ignore[arg-type]
            openai_api_base="https://chatgpt.com/backend-api/codex",  # type: ignore[call-arg]
            use_responses_api=True,
        )
        self.captured_input: list[Any] | None = None
        self.captured_kwargs: dict[str, Any] | None = None

    async def ainvoke(self, input: list[Any], **kwargs: Any) -> AIMessage:
        self.captured_input = input
        self.captured_kwargs = kwargs
        return AIMessage(content="summary")


class _PoolShapedLane:
    """Stub the existing ``_is_pool_bound`` detector recognizes as a pool."""

    def __init__(self) -> None:
        self.active_llm: object = object()
        self.captured_input: list[Any] | None = None
        self.captured_kwargs: dict[str, Any] | None = None

    async def ainvoke(self, input: list[Any], **kwargs: Any) -> AIMessage:
        self.captured_input = input
        self.captured_kwargs = kwargs
        return AIMessage(content="summary")


class TestInvokeLlmSummaryShaping:
    """85.a.1 — direct models use the adapter; pools are passed raw input."""

    @pytest.mark.asyncio
    async def test_non_codex_summary_keeps_max_tokens(self) -> None:
        """A non-Codex direct model still receives ``max_tokens`` and the system message."""
        llm = _mock_llm(summary="s")

        await Compacter._invoke_llm_summary(compaction_input="input", model_name="m", llm=llm)

        call = llm.ainvoke.call_args
        assert call.kwargs["max_tokens"] == RESERVED_TOKEN_LIMIT
        assert any(isinstance(m, SystemMessage) for m in call.kwargs["input"])

    @pytest.mark.asyncio
    async def test_direct_codex_summary_uses_adapter_result(self) -> None:
        """A direct ChatGPT-backend model gets human-only messages and instructions, no cap."""
        llm = _CapturingCodexLane()

        await Compacter._invoke_llm_summary(
            compaction_input="input",
            model_name="gpt-5",
            llm=llm,  # type: ignore[arg-type]
        )

        assert llm.captured_kwargs is not None
        assert "max_tokens" not in llm.captured_kwargs
        assert "max_output_tokens" not in llm.captured_kwargs
        assert llm.captured_kwargs["instructions"].startswith("You are a conversation compactor")
        assert llm.captured_input is not None
        assert all(not isinstance(m, SystemMessage) for m in llm.captured_input)
        assert any(isinstance(m, HumanMessage) for m in llm.captured_input)

    @pytest.mark.asyncio
    async def test_pool_summary_is_not_pre_shaped(self) -> None:
        """A pool-bound LLM receives the raw system message and raw ``max_tokens``."""
        llm = _PoolShapedLane()

        with patch("src.agents.slo_agent.compaction.compacter.adapt_chatgpt_backend_request") as adapter:
            await Compacter._invoke_llm_summary(
                compaction_input="input",
                model_name="m",
                llm=llm,  # type: ignore[arg-type]
            )

        adapter.assert_not_called()
        assert llm.captured_kwargs == {"max_tokens": RESERVED_TOKEN_LIMIT}
        assert llm.captured_input is not None
        assert any(isinstance(m, SystemMessage) for m in llm.captured_input)


# ---------------------------------------------------------------------------
# OAuth wire regression (85.a.1)
# ---------------------------------------------------------------------------


def _build_jwt(*, claims: dict[str, Any]) -> str:
    """Build a fake unsigned JWT carrying ``claims`` in its payload segment."""
    header_b64: str = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode("ascii")
    payload_b64: str = (
        base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).rstrip(b"=").decode("ascii")
    )
    return f"{header_b64}.{payload_b64}.signature"


def _oauth_cred() -> CredentialDAO:
    """Build an OAuth OpenAI credential whose token yields a ChatGPT account id."""
    return CredentialDAO(
        provider=ProviderName.OPENAI,
        auth_type=AuthType.OAUTH,
        access_token=_build_jwt(
            claims={"https://api.openai.com/auth": {"chatgpt_account_id": "acct-summary"}},
        ),
        refresh_token="rt-test",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="openid profile email offline_access",
    )


class TestChatGptBackendSummaryRequest:
    """85.a.1 — the real OAuth compaction request carries no output-token field."""

    @pytest.mark.asyncio
    async def test_compact_sends_instructions_without_output_token_kwargs(self) -> None:
        """Capture the outbound ChatGPT-backend body from a real ``/compact`` request."""
        captured: dict[str, Any] = {}

        async def _handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content.decode())
            sse: bytes = (
                b"event: response.created\n"
                b'data: {"type": "response.created", "response": {"id": "resp_test", "status": "in_progress"}}\n\n'
                b"event: response.completed\n"
                b'data: {"type": "response.completed", "response": {"id": "resp_test", "status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "summary"}]}]}}\n\n'
            )
            return httpx.Response(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                content=sse,
            )

        mock_client: httpx.AsyncClient = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        chat = build_chatgpt_backed_chat_openai(
            model_name="gpt-5",
            cred=_oauth_cred(),
            session_id="sess-summary",
            http_async_client=mock_client,
        )

        big: int = KEEP_RECENT_TOKENS + 1
        events = [
            _make_event(kind="user_message", token_usage=10, content="u"),
            _make_event(kind="assistant_message", token_usage=10, content="a"),
            _make_event(kind="assistant_message", token_usage=big, content="b"),
        ]

        try:
            await Compacter.compact(events=events, model_name="gpt-5", llm=chat)
        except Exception:  # noqa: BLE001
            # The synthetic SSE need only reach the wire-capture seam.
            pass

        body: dict[str, Any] = captured["body"]
        assert "max_tokens" not in body
        assert "max_output_tokens" not in body
        assert "max_completion_tokens" not in body
        assert isinstance(body.get("instructions"), str)
        assert "You are a conversation compactor" in body["instructions"]
        assert all(item.get("role") != "system" for item in body["input"] if isinstance(item, dict))
