"""Unit tests for ``SessionTreeBuilder`` (sub-spec 42.a.2)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.history.tree_builder import SessionTreeBuilder, SessionTreeNode


def _build_event(
    *,
    kind: str,
    event_id: str = "",
    turn_id: str | None = None,
    sequence: int = 0,
    iteration: int = 0,
    content: str | None = None,
    tool_name: str | None = None,
    tool_input: dict[str, Any] | None = None,
    tool_output: str | None = None,
    tool_call_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    message: str | None = None,
    error_message: str | None = None,
) -> SessionHistoryEventDAO:
    """Build a ``SessionHistoryEventDAO`` for tests."""
    return SessionHistoryEventDAO(
        event_id=event_id or f"event-{sequence}",
        session_id="test-session",
        turn_id=turn_id,
        sequence=sequence,
        kind=kind,  # type: ignore[arg-type]
        iteration=iteration,
        recorded_at=datetime.now(timezone.utc),
        payload=SessionHistoryEventPayloadDAO(
            content=content,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            tool_call_id=tool_call_id,
            metadata=metadata or {},
            message=message,
            error_message=error_message,
        ),
    )


def _tree_depth(*, node: SessionTreeNode) -> int:
    """Return the maximum depth of a tree rooted at ``node`` (leaf = 1)."""
    if not node.children:
        return 1
    return 1 + max(_tree_depth(node=child) for child in node.children)


class TestSessionTreeBuilderBuild:
    """Tests for ``SessionTreeBuilder.build()``."""

    def test_build_empty_events(self) -> None:
        """Empty events return an empty session root."""
        result = SessionTreeBuilder.build(events=[])

        assert result.kind == "session"
        assert "(empty)" in result.label
        assert result.children == []

    def test_build_single_user_message(self) -> None:
        """One user_message produces a root → turn → user_message tree."""
        events = [
            _build_event(
                kind="user_message",
                turn_id="turn-1",
                sequence=1,
                content="hello",
            ),
        ]
        result = SessionTreeBuilder.build(events=events)

        assert result.kind == "session"
        assert len(result.children) == 1
        turn = result.children[0]
        assert turn.kind == "turn"
        assert "Turn 1" in turn.label
        assert len(turn.children) == 1
        assert turn.children[0].kind == "user_message"
        assert "hello" in turn.children[0].label

    def test_build_tool_call_result_pair(self) -> None:
        """tool_result nests under its tool_call; siblings stay flat under the turn.

        ``parent_entry_id`` is the store's linear lineage pointer (each event ->
        previous event), so it must NOT be followed for non-tool_result events.
        Only the tool_result nests; user_message and tool_call are flat siblings.
        """
        events = [
            _build_event(
                kind="user_message",
                turn_id="turn-1",
                sequence=1,
                content="do it",
                metadata={"entry_id": "e1", "parent_entry_id": None},
            ),
            _build_event(
                kind="tool_call",
                turn_id="turn-1",
                sequence=2,
                tool_name="bash",
                tool_call_id="tc1",
                metadata={"entry_id": "e2", "parent_entry_id": "e1"},
            ),
            _build_event(
                kind="tool_result",
                turn_id="turn-1",
                sequence=3,
                tool_name="bash",
                tool_call_id="tc1",
                tool_output="ok",
                metadata={"entry_id": "e3", "parent_entry_id": "e2"},
            ),
        ]
        result = SessionTreeBuilder.build(events=events)

        turn = result.children[0]
        # user_message and tool_call are flat siblings under the turn — NOT chained.
        child_kinds = [c.kind for c in turn.children]
        assert child_kinds == ["user_message", "tool_call"]
        user_node = turn.children[0]
        assert user_node.children == []
        # tool_result is the sole child of its tool_call.
        tool_call_node = turn.children[1]
        assert len(tool_call_node.children) == 1
        assert tool_call_node.children[0].kind == "tool_result"
        assert "ok" in tool_call_node.children[0].label

    def test_build_long_lineage_chain_stays_shallow(self) -> None:
        """A long linear parent_entry_id chain does not produce a deep tree.

        Regression for the ``/tree`` RecursionError: the store threads
        ``parent_entry_id`` as a linear chain (each event -> previous event).
        Following it for every event rebuilt the whole log as one branch as deep
        as the event count, overflowing the stack on render. The builder must
        keep the tree shallow regardless of chain length.
        """
        events: list = []
        previous_entry_id: str | None = None
        for sequence in range(1, 501):
            entry_id = f"e{sequence}"
            events.append(
                _build_event(
                    kind="tool_call" if sequence % 2 else "assistant_message",
                    turn_id="turn-1",
                    sequence=sequence,
                    content=f"step {sequence}",
                    tool_call_id=f"tc{sequence}",
                    metadata={"entry_id": entry_id, "parent_entry_id": previous_entry_id},
                )
            )
            previous_entry_id = entry_id

        result = SessionTreeBuilder.build(events=events)

        assert _tree_depth(node=result) <= 4
        turn = result.children[0]
        assert len(turn.children) == 500

    def test_tool_result_with_missing_tool_call_stays_flat(self) -> None:
        """A tool_result whose parent_entry_id is unknown stays on the timeline."""
        events = [
            _build_event(
                kind="tool_result",
                turn_id="turn-1",
                sequence=1,
                tool_output="orphaned",
                metadata={"entry_id": "e1", "parent_entry_id": "does-not-exist"},
            ),
        ]
        result = SessionTreeBuilder.build(events=events)

        turn = result.children[0]
        assert turn.children[0].kind == "tool_result"
        assert turn.children[0].parent is not None
        assert turn.children[0].parent.kind == "turn"

    def test_tool_result_with_non_tool_call_parent_stays_flat(self) -> None:
        """A tool_result pointing at a non-tool_call parent stays on the timeline."""
        events = [
            _build_event(
                kind="user_message",
                turn_id="turn-1",
                sequence=1,
                content="hi",
                metadata={"entry_id": "e1", "parent_entry_id": None},
            ),
            _build_event(
                kind="tool_result",
                turn_id="turn-1",
                sequence=2,
                tool_output="weird",
                metadata={"entry_id": "e2", "parent_entry_id": "e1"},
            ),
        ]
        result = SessionTreeBuilder.build(events=events)

        turn = result.children[0]
        # tool_result is NOT nested under the user_message; both are flat siblings.
        assert [c.kind for c in turn.children] == ["user_message", "tool_result"]
        assert turn.children[0].children == []

    def test_build_multiple_turns(self) -> None:
        """Two user messages in different turn_ids produce two turn nodes."""
        events = [
            _build_event(
                kind="user_message",
                turn_id="turn-1",
                sequence=1,
                content="first",
                metadata={"entry_id": "e1"},
            ),
            _build_event(
                kind="user_message",
                turn_id="turn-2",
                sequence=2,
                content="second",
                metadata={"entry_id": "e2"},
            ),
        ]
        result = SessionTreeBuilder.build(events=events)

        assert len(result.children) == 2
        assert result.children[0].kind == "turn"
        assert "first" in result.children[0].label
        assert result.children[1].kind == "turn"
        assert "second" in result.children[1].label

    def test_build_steering_message(self) -> None:
        """Steering message renders with ⏳ emoji and correct label."""
        events = [
            _build_event(
                kind="steering_message",
                turn_id="turn-1",
                sequence=1,
                content="fix typo",
            ),
        ]
        result = SessionTreeBuilder.build(events=events)

        turn = result.children[0]
        assert turn.children[0].kind == "steering_message"
        assert "⏳" in turn.children[0].label
        assert "fix typo" in turn.children[0].label

    def test_build_compaction_summary(self) -> None:
        """Compaction summary renders with 📦 emoji."""
        events = [
            _build_event(
                kind="compaction_summary",
                turn_id="turn-1",
                sequence=1,
                content="Previous conversation summary",
            ),
        ]
        result = SessionTreeBuilder.build(events=events)

        turn = result.children[0]
        assert turn.children[0].kind == "compaction_summary"
        assert "📦" in turn.children[0].label
        assert "CompactionSummary" in turn.children[0].label

    def test_label_truncation(self) -> None:
        """Long content is truncated to 80 chars."""
        long_content = "a" * 200
        events = [
            _build_event(
                kind="user_message",
                turn_id="turn-1",
                sequence=1,
                content=long_content,
            ),
        ]
        result = SessionTreeBuilder.build(events=events)

        turn = result.children[0]
        label = turn.children[0].label
        # Should be truncated to 80 chars + "..."
        assert len(label.split(": ", 1)[1]) <= 83  # 80 + "..."
        assert label.endswith("...")

    def test_turn_label_from_user_message(self) -> None:
        """Turn label derives from the first user_message."""
        events = [
            _build_event(
                kind="assistant_message",
                turn_id="turn-1",
                sequence=1,
                content="hi",
            ),
            _build_event(
                kind="user_message",
                turn_id="turn-1",
                sequence=2,
                content="hello there",
            ),
        ]
        result = SessionTreeBuilder.build(events=events)

        turn = result.children[0]
        assert "hello there" in turn.label

    def test_preamble_events_go_to_root(self) -> None:
        """Events with no turn_id are preamble and go directly under root."""
        events = [
            _build_event(
                kind="session_started",
                turn_id=None,
                sequence=1,
                content="",
            ),
            _build_event(
                kind="user_message",
                turn_id="turn-1",
                sequence=2,
                content="hello",
            ),
        ]
        result = SessionTreeBuilder.build(events=events)

        # Preamble node is a direct child of root, not under a turn
        preamble_kinds = [c.kind for c in result.children if c.kind != "turn"]
        assert "session_started" in preamble_kinds
        turn_kinds = [c.kind for c in result.children if c.kind == "turn"]
        assert "turn" in turn_kinds
