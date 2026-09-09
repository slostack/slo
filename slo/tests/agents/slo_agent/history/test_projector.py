"""Tests for ``SessionHistoryProjector`` (sub-spec 05.d §8)."""

from __future__ import annotations

import pytest

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.history.projector import SessionHistoryProjector


def _event(
    *,
    kind: str,
    turn_id: str | None = "t1",
    payload: SessionHistoryEventPayloadDAO | None = None,
) -> SessionHistoryEventDAO:
    """Build a canonical event for projector tests."""
    return SessionHistoryEventDAO(
        session_id="s",
        turn_id=turn_id,
        kind=kind,  # type: ignore[arg-type]
        payload=payload or SessionHistoryEventPayloadDAO(),
    )


class TestBuildMessageHistory:
    """Reconstruct ``list[BaseMessage]`` from canonical events."""

    @pytest.mark.asyncio
    async def test_reconstructs_user_ai_and_tool_messages(self) -> None:
        events = [
            _event(
                kind="user_message",
                payload=SessionHistoryEventPayloadDAO(content="hi"),
            ),
            _event(
                kind="tool_call",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="read",
                    tool_call_id="call_1",
                    tool_input={"path": "foo.txt"},
                ),
            ),
            _event(
                kind="tool_result",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="read",
                    tool_call_id="call_1",
                    tool_output="file body",
                ),
            ),
            _event(
                kind="assistant_message",
                payload=SessionHistoryEventPayloadDAO(content="done"),
            ),
            _event(kind="run_completed"),
        ]

        messages: list[BaseMessage] = await SessionHistoryProjector.build_message_history(
            events=events,
        )

        assert isinstance(messages[0], HumanMessage)
        assert messages[0].content == "hi"
        assert isinstance(messages[1], AIMessage)
        assert messages[1].tool_calls and messages[1].tool_calls[0]["name"] == "read"
        assert isinstance(messages[2], ToolMessage)
        assert messages[2].content == "file body"
        assert isinstance(messages[3], AIMessage)
        assert messages[3].content == "done"

    @pytest.mark.asyncio
    async def test_excludes_incomplete_turns(self) -> None:
        events = [
            _event(
                kind="user_message",
                turn_id="t-completed",
                payload=SessionHistoryEventPayloadDAO(content="completed turn"),
            ),
            _event(kind="run_completed", turn_id="t-completed"),
            _event(
                kind="user_message",
                turn_id="t-pending",
                payload=SessionHistoryEventPayloadDAO(content="never finished"),
            ),
            # No terminal record for t-pending.
        ]

        messages: list[BaseMessage] = await SessionHistoryProjector.build_message_history(
            events=events,
        )

        contents: list[str] = [m.content for m in messages if isinstance(m.content, str)]
        assert "completed turn" in contents
        assert "never finished" not in contents

    @pytest.mark.asyncio
    async def test_excludes_requested_completed_turn_ids(self) -> None:
        """A caller can omit one completed turn from one rebuild call."""
        events = [
            _event(
                kind="user_message",
                turn_id="t-keep",
                payload=SessionHistoryEventPayloadDAO(content="keep me"),
            ),
            _event(kind="run_completed", turn_id="t-keep"),
            _event(
                kind="user_message",
                turn_id="t-drop",
                payload=SessionHistoryEventPayloadDAO(content="drop me"),
            ),
            _event(kind="run_failed", turn_id="t-drop"),
        ]

        messages: list[BaseMessage] = await SessionHistoryProjector.build_message_history(
            events=events,
            excluded_turn_ids={"t-drop"},
        )

        contents: list[str] = [m.content for m in messages if isinstance(m.content, str)]
        assert "keep me" in contents
        assert "drop me" not in contents

    @pytest.mark.asyncio
    async def test_ignores_lifecycle_only_events(self) -> None:
        events = [
            _event(kind="run_started"),
            _event(kind="run_completed"),
        ]

        assert await SessionHistoryProjector.build_message_history(events=events) == []


class TestHealDanglingToolCalls:
    """A ``tool_call`` with no ``tool_result`` must not break the resumed session."""

    @pytest.mark.asyncio
    async def test_failed_turn_with_unanswered_tool_call_gets_synthetic_result(self) -> None:
        """A hung tool in a ``run_failed`` turn yields a placeholder ToolMessage."""
        events = [
            _event(
                kind="user_message",
                payload=SessionHistoryEventPayloadDAO(content="benchmark the child"),
            ),
            _event(
                kind="tool_call",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="bash",
                    tool_call_id="toolu_hung",
                    tool_input={"command": "readline"},
                ),
            ),
            # The tool hung — no tool_result was ever recorded — but the turn
            # still terminated (run_failed), so it counts as "completed".
            _event(kind="run_failed"),
        ]

        messages: list[BaseMessage] = await SessionHistoryProjector.build_message_history(
            events=events,
        )

        assert isinstance(messages[-1], ToolMessage)
        assert messages[-1].tool_call_id == "toolu_hung"
        assert "interrupted" in messages[-1].content

    @pytest.mark.asyncio
    async def test_every_tool_use_id_is_answered_after_healing(self) -> None:
        """No ``tool_use`` id is left without a matching ``tool_result``."""
        events = [
            _event(
                kind="tool_call",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="bash",
                    tool_call_id="toolu_hung",
                    tool_input={"command": "x"},
                ),
            ),
            _event(kind="run_aborted"),
        ]

        messages: list[BaseMessage] = await SessionHistoryProjector.build_message_history(
            events=events,
        )

        tool_use_ids: set[str] = {
            call["id"] for m in messages if isinstance(m, AIMessage) for call in (m.tool_calls or [])
        }
        answered_ids: set[str] = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
        assert tool_use_ids
        assert tool_use_ids <= answered_ids

    @pytest.mark.asyncio
    async def test_answered_tool_calls_are_left_untouched(self) -> None:
        """A normally-completed tool call is not double-answered."""
        events = [
            _event(
                kind="tool_call",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="read",
                    tool_call_id="call_ok",
                    tool_input={"path": "foo"},
                ),
            ),
            _event(
                kind="tool_result",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="read",
                    tool_call_id="call_ok",
                    tool_output="body",
                ),
            ),
            _event(kind="run_completed"),
        ]

        messages: list[BaseMessage] = await SessionHistoryProjector.build_message_history(
            events=events,
        )

        results: list[ToolMessage] = [m for m in messages if isinstance(m, ToolMessage)]
        assert len(results) == 1
        assert results[0].content == "body"

    @pytest.mark.asyncio
    async def test_does_not_include_system_prompt(self) -> None:
        events = [
            _event(
                kind="user_message",
                payload=SessionHistoryEventPayloadDAO(content="hi"),
            ),
            _event(kind="run_completed"),
        ]

        messages: list[BaseMessage] = await SessionHistoryProjector.build_message_history(
            events=events,
        )

        from langchain_core.messages import SystemMessage

        assert not any(isinstance(m, SystemMessage) for m in messages)

    @pytest.mark.asyncio
    async def test_assistant_delta_does_not_enter_next_turn_message_history(self) -> None:
        events = [
            _event(
                kind="assistant_delta",
                payload=SessionHistoryEventPayloadDAO(
                    delta_kind="thinking_delta",
                    delta="internal visible summary",
                ),
            ),
            _event(
                kind="assistant_message",
                payload=SessionHistoryEventPayloadDAO(content="final answer"),
            ),
            _event(kind="run_completed"),
        ]

        messages = await SessionHistoryProjector.build_message_history(events=events)

        assert len(messages) == 1
        assert messages[0].content == "final answer"


class TestParallelToolCallProjection:
    """Parallel tool-call groups project to exactly one ``AIMessage``."""

    @pytest.mark.asyncio
    async def test_anchor_event_emits_one_ai_message_with_full_sibling_list(self) -> None:
        """Two parallel tool_call events produce one AIMessage carrying both tool_calls."""
        parallel_calls = [
            {"name": "read", "args": {"path": "a.txt"}, "id": "call_A", "type": "tool_call"},
            {"name": "read", "args": {"path": "b.txt"}, "id": "call_B", "type": "tool_call"},
        ]
        events = [
            _event(
                kind="user_message",
                payload=SessionHistoryEventPayloadDAO(content="read both"),
            ),
            _event(
                kind="tool_call",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="read",
                    tool_call_id="call_A",
                    tool_input={"path": "a.txt"},
                    tool_calls=parallel_calls,
                ),
            ),
            _event(
                kind="tool_call",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="read",
                    tool_call_id="call_B",
                    tool_input={"path": "b.txt"},
                    tool_calls=parallel_calls,
                ),
            ),
            _event(
                kind="tool_result",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="read",
                    tool_call_id="call_A",
                    tool_output="content of a",
                ),
            ),
            _event(
                kind="tool_result",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="read",
                    tool_call_id="call_B",
                    tool_output="content of b",
                ),
            ),
            _event(kind="run_completed"),
        ]

        messages = await SessionHistoryProjector.build_message_history(events=events)

        ai_messages = [m for m in messages if isinstance(m, AIMessage) and m.tool_calls]
        assert len(ai_messages) == 1, f"Expected 1 AIMessage, got {len(ai_messages)}"
        assert len(ai_messages[0].tool_calls) == 2
        assert [tc["id"] for tc in ai_messages[0].tool_calls] == ["call_A", "call_B"]

    @pytest.mark.asyncio
    async def test_reconstructed_history_has_no_duplicate_tool_use_ids(self) -> None:
        """All tool_use IDs across the reconstructed message list must be unique."""
        parallel_calls = [
            {"name": "read", "args": {"path": "x.txt"}, "id": "id_X", "type": "tool_call"},
            {"name": "read", "args": {"path": "y.txt"}, "id": "id_Y", "type": "tool_call"},
        ]
        events = [
            _event(kind="user_message", payload=SessionHistoryEventPayloadDAO(content="q")),
            _event(
                kind="tool_call",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="read",
                    tool_call_id="id_X",
                    tool_input={"path": "x.txt"},
                    tool_calls=parallel_calls,
                ),
            ),
            _event(
                kind="tool_call",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="read",
                    tool_call_id="id_Y",
                    tool_input={"path": "y.txt"},
                    tool_calls=parallel_calls,
                ),
            ),
            _event(
                kind="tool_result",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="read",
                    tool_call_id="id_X",
                    tool_output="x",
                ),
            ),
            _event(
                kind="tool_result",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="read",
                    tool_call_id="id_Y",
                    tool_output="y",
                ),
            ),
            _event(kind="run_completed"),
        ]

        messages = await SessionHistoryProjector.build_message_history(events=events)

        all_ids = [tc["id"] for m in messages if isinstance(m, AIMessage) for tc in (m.tool_calls or [])]
        assert len(all_ids) == len(set(all_ids)), f"Duplicate tool_use IDs: {all_ids}"

    @pytest.mark.asyncio
    async def test_single_tool_call_with_tool_calls_populated_still_emits(self) -> None:
        """A single-entry tool_calls list is not suppressed by the secondary-event guard."""
        single_call = [
            {"name": "bash", "args": {"cmd": "ls"}, "id": "call_S", "type": "tool_call"},
        ]
        events = [
            _event(kind="user_message", payload=SessionHistoryEventPayloadDAO(content="list")),
            _event(
                kind="tool_call",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="bash",
                    tool_call_id="call_S",
                    tool_input={"cmd": "ls"},
                    tool_calls=single_call,
                ),
            ),
            _event(
                kind="tool_result",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="bash",
                    tool_call_id="call_S",
                    tool_output="file.txt",
                ),
            ),
            _event(kind="run_completed"),
        ]

        messages = await SessionHistoryProjector.build_message_history(events=events)

        ai_messages = [m for m in messages if isinstance(m, AIMessage) and m.tool_calls]
        assert len(ai_messages) == 1
        assert ai_messages[0].tool_calls[0]["id"] == "call_S"

    @pytest.mark.asyncio
    async def test_fallback_path_without_tool_calls_field_is_unaffected(self) -> None:
        """Events with tool_calls=None still reconstruct via _tool_calls_fallback."""
        events = [
            _event(kind="user_message", payload=SessionHistoryEventPayloadDAO(content="go")),
            _event(
                kind="tool_call",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="ls",
                    tool_call_id="call_F",
                    tool_input={"path": "."},
                    tool_calls=None,
                ),
            ),
            _event(
                kind="tool_result",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="ls",
                    tool_call_id="call_F",
                    tool_output=".",
                ),
            ),
            _event(kind="run_completed"),
        ]

        messages = await SessionHistoryProjector.build_message_history(events=events)

        ai_messages = [m for m in messages if isinstance(m, AIMessage) and m.tool_calls]
        assert len(ai_messages) == 1
        assert ai_messages[0].tool_calls[0]["id"] == "call_F"


class TestWorkflowUpdateProjection:
    """``workflow_update`` synthetic turns enter model context (spec 57.a.4)."""

    @pytest.mark.asyncio
    async def test_projector_includes_workflow_update_as_human_message(self) -> None:
        """A workflow_update event projects to a bracketed ``HumanMessage``."""
        events = [
            _event(
                kind="workflow_update",
                turn_id="wf-turn-1",
                payload=SessionHistoryEventPayloadDAO(
                    content="[workflow wf-3f2a] phase 1: 2 task(s), all_completed=True",
                    metadata={"workflow_id": "wf-3f2a", "inbox_message_id": "msg-1"},
                ),
            ),
        ]

        messages: list[BaseMessage] = await SessionHistoryProjector.build_message_history(
            events=events,
        )

        assert len(messages) == 1
        assert isinstance(messages[0], HumanMessage)
        assert messages[0].content == (
            "[workflow update] [workflow wf-3f2a] phase 1: 2 task(s), all_completed=True"
        )

    @pytest.mark.asyncio
    async def test_projector_orders_workflow_update_chronologically(self) -> None:
        """A between-turn workflow note replays between the surrounding turns."""
        events = [
            _event(
                kind="user_message",
                turn_id="t1",
                payload=SessionHistoryEventPayloadDAO(content="first turn"),
            ),
            _event(kind="run_completed", turn_id="t1"),
            _event(
                kind="workflow_update",
                turn_id="wf-turn-1",
                payload=SessionHistoryEventPayloadDAO(content="phase 1 done"),
            ),
            _event(
                kind="user_message",
                turn_id="t2",
                payload=SessionHistoryEventPayloadDAO(content="second turn"),
            ),
            _event(kind="run_completed", turn_id="t2"),
        ]

        messages = await SessionHistoryProjector.build_message_history(events=events)

        contents: list[str] = [m.content for m in messages if isinstance(m.content, str)]
        assert contents == ["first turn", "[workflow update] phase 1 done", "second turn"]

    @pytest.mark.asyncio
    async def test_projector_still_excludes_audit_kinds(self) -> None:
        """Regression: audit kinds stay out of model context alongside workflow notes."""
        events = [
            _event(
                kind="workflow_update",
                turn_id="wf-turn-1",
                payload=SessionHistoryEventPayloadDAO(content="phase 1 done"),
            ),
            _event(
                kind="run_retrying",
                turn_id="wf-turn-1",
                payload=SessionHistoryEventPayloadDAO(content="retrying"),
            ),
            _event(
                kind="route_switched",
                turn_id="wf-turn-1",
                payload=SessionHistoryEventPayloadDAO(content="switched"),
            ),
            _event(
                kind="stream_reconnecting",
                turn_id="wf-turn-1",
                payload=SessionHistoryEventPayloadDAO(content="reconnecting"),
            ),
        ]

        messages = await SessionHistoryProjector.build_message_history(events=events)

        assert len(messages) == 1
        assert messages[0].content == "[workflow update] phase 1 done"

    @pytest.mark.asyncio
    async def test_incomplete_turn_exclusion_unaffected(self) -> None:
        """Regression: synthetic workflow turns do not loosen the incomplete-turn rule."""
        events = [
            _event(
                kind="workflow_update",
                turn_id="wf-turn-1",
                payload=SessionHistoryEventPayloadDAO(content="phase 1 done"),
            ),
            _event(
                kind="user_message",
                turn_id="t-pending",
                payload=SessionHistoryEventPayloadDAO(content="never finished"),
            ),
            # No terminal record for t-pending.
        ]

        messages = await SessionHistoryProjector.build_message_history(events=events)

        contents: list[str] = [m.content for m in messages if isinstance(m.content, str)]
        assert contents == ["[workflow update] phase 1 done"]
