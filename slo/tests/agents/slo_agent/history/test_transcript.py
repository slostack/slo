"""Tests for ``ReplayEntryProjector`` (sub-spec 05.a §7.4, 05.d §8; feature 15)."""

from __future__ import annotations

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.history.transcript import (
    ReplayEntryProjector,
    TranscriptEntryDAO,
)


def _event(
    *,
    kind: str,
    turn_id: str | None = "t1",
    iteration: int = 0,
    payload: SessionHistoryEventPayloadDAO | None = None,
) -> SessionHistoryEventDAO:
    """Build a minimal canonical event for projection tests.

    Args:
        kind (str): The history event kind.
        turn_id (str | None): Owning turn id.
        iteration (int): ReAct iteration.
        payload (SessionHistoryEventPayloadDAO | None): Optional payload.

    Returns:
        SessionHistoryEventDAO: A minimal canonical event.
    """
    return SessionHistoryEventDAO(
        session_id="s",
        turn_id=turn_id,
        iteration=iteration,
        kind=kind,  # type: ignore[arg-type]
        payload=payload or SessionHistoryEventPayloadDAO(),
    )


class TestBuildEntries:
    """``ReplayEntryProjector.build_entries`` — completed replay entries."""

    def test_user_message_becomes_a_user_entry(self) -> None:
        events = [
            _event(kind="user_message", payload=SessionHistoryEventPayloadDAO(content="hello")),
            _event(kind="run_completed"),
        ]

        entries: list[TranscriptEntryDAO] = ReplayEntryProjector.build_entries(events=events)

        assert entries == [TranscriptEntryDAO(kind="user", content="hello")]

    def test_steering_message_is_prefixed(self) -> None:
        events = [
            _event(kind="steering_message", payload=SessionHistoryEventPayloadDAO(content="wait")),
        ]

        entries = ReplayEntryProjector.build_entries(events=events)

        assert entries == [TranscriptEntryDAO(kind="user", content="(steer) wait")]

    def test_lifecycle_only_events_produce_no_entries(self) -> None:
        events = [_event(kind="run_started"), _event(kind="run_completed")]

        assert ReplayEntryProjector.build_entries(events=events) == []

    def test_reasoning_and_answer_fold_into_one_assistant_entry(self) -> None:
        events = [
            _event(
                kind="assistant_delta",
                payload=SessionHistoryEventPayloadDAO(delta_kind="thinking_delta", delta="reasoning"),
            ),
            _event(
                kind="assistant_delta",
                payload=SessionHistoryEventPayloadDAO(delta_kind="text_delta", delta="partial"),
            ),
            _event(
                kind="assistant_message",
                payload=SessionHistoryEventPayloadDAO(content="final answer"),
            ),
            _event(kind="run_completed"),
        ]

        entries = ReplayEntryProjector.build_entries(events=events)

        assert entries == [
            TranscriptEntryDAO(
                kind="assistant",
                reasoning="reasoning",
                answer="final answer",
                terminal_note=None,
            )
        ]

    def test_redacted_only_reasoning_does_not_replay_as_visible_text(self) -> None:
        events = [
            _event(
                kind="assistant_delta",
                payload=SessionHistoryEventPayloadDAO(
                    delta_kind="thinking_start", block_id="thinking:0:0", redacted=True
                ),
            ),
            _event(
                kind="assistant_delta",
                payload=SessionHistoryEventPayloadDAO(
                    delta_kind="thinking_end", block_id="thinking:0:0", redacted=True
                ),
            ),
            _event(kind="assistant_message", payload=SessionHistoryEventPayloadDAO(content="final answer")),
            _event(kind="run_completed"),
        ]

        entries = ReplayEntryProjector.build_entries(events=events)

        assert entries == [
            TranscriptEntryDAO(kind="assistant", reasoning=None, answer="final answer", terminal_note=None)
        ]

    def test_aborted_turn_keeps_partial_answer_and_terminal_note(self) -> None:
        events = [
            _event(
                kind="assistant_delta",
                payload=SessionHistoryEventPayloadDAO(delta_kind="text_delta", delta="partial answer"),
            ),
            _event(kind="run_aborted"),
        ]

        entries = ReplayEntryProjector.build_entries(events=events)

        assert entries == [
            TranscriptEntryDAO(kind="assistant", answer="partial answer", terminal_note="aborted")
        ]

    def test_failed_turn_carries_error_message_as_terminal_note(self) -> None:
        events = [
            _event(
                kind="assistant_delta",
                payload=SessionHistoryEventPayloadDAO(delta_kind="text_delta", delta="partial answer"),
            ),
            _event(kind="run_failed", payload=SessionHistoryEventPayloadDAO(error_message="boom")),
        ]

        entries = ReplayEntryProjector.build_entries(events=events)

        assert entries == [
            TranscriptEntryDAO(kind="assistant", answer="partial answer", terminal_note="boom")
        ]

    def test_tool_call_and_result_pair_into_one_tool_entry(self) -> None:
        events = [
            _event(
                kind="tool_call",
                iteration=1,
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="read",
                    tool_call_id="call-1",
                    tool_input={"path": "a.py"},
                ),
            ),
            _event(
                kind="tool_result",
                iteration=1,
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="read",
                    tool_call_id="call-1",
                    tool_output="3 lines",
                ),
            ),
        ]

        entries = ReplayEntryProjector.build_entries(events=events)

        assert entries == [
            TranscriptEntryDAO(
                kind="tool",
                iteration=1,
                tool_name="read",
                tool_input={"path": "a.py"},
                output="3 lines",
            )
        ]

    def test_full_turn_orders_assistant_then_tool(self) -> None:
        events = [
            _event(kind="user_message", payload=SessionHistoryEventPayloadDAO(content="do it")),
            _event(
                kind="assistant_delta",
                payload=SessionHistoryEventPayloadDAO(delta_kind="thinking_delta", delta="planning"),
            ),
            _event(
                kind="tool_call",
                payload=SessionHistoryEventPayloadDAO(tool_name="ls", tool_call_id="c1", tool_input={}),
            ),
            _event(
                kind="tool_result",
                payload=SessionHistoryEventPayloadDAO(
                    tool_name="ls", tool_call_id="c1", tool_output="2 entries"
                ),
            ),
            _event(kind="assistant_message", payload=SessionHistoryEventPayloadDAO(content="done")),
            _event(kind="run_completed"),
        ]

        kinds = [entry.kind for entry in ReplayEntryProjector.build_entries(events=events)]

        assert kinds == ["user", "assistant", "tool", "assistant"]


class TestRenderMarkdown:
    """``ReplayEntryProjector.render_markdown`` — derived markdown body."""

    def test_render_markdown_round_trips_expected_sections(self) -> None:
        events = [
            _event(kind="user_message", payload=SessionHistoryEventPayloadDAO(content="hello")),
            _event(kind="assistant_message", payload=SessionHistoryEventPayloadDAO(content="hi back")),
        ]

        body: str = ReplayEntryProjector.render_markdown(events=events)

        assert "## User" in body
        assert "hello" in body
        assert "## Assistant" in body
        assert "hi back" in body

    def test_render_markdown_is_empty_for_no_visible_events(self) -> None:
        events = [_event(kind="run_started"), _event(kind="run_completed")]

        assert ReplayEntryProjector.render_markdown(events=events) == ""


class TestWorkflowUpdateReplay:
    """``workflow_update`` events replay as note entries (spec 57.a.4)."""

    def test_replay_renders_workflow_update_as_note_entry(self) -> None:
        """A workflow_update event folds into one ``kind="note"`` entry."""
        events = [
            _event(
                kind="user_message",
                turn_id="t1",
                payload=SessionHistoryEventPayloadDAO(content="hello"),
            ),
            _event(kind="run_completed", turn_id="t1"),
            _event(
                kind="workflow_update",
                turn_id="wf-turn-1",
                payload=SessionHistoryEventPayloadDAO(
                    content="[workflow wf-3f2a] phase 1: COMPLETE",
                ),
            ),
        ]

        entries: list[TranscriptEntryDAO] = ReplayEntryProjector.build_entries(events=events)

        assert entries == [
            TranscriptEntryDAO(kind="user", content="hello"),
            TranscriptEntryDAO(kind="note", content="⊛ [workflow wf-3f2a] phase 1: COMPLETE"),
        ]

    def test_workflow_update_renders_in_markdown_export(self) -> None:
        """``render_markdown`` includes a workflow-update section."""
        events = [
            _event(
                kind="workflow_update",
                turn_id="wf-turn-1",
                payload=SessionHistoryEventPayloadDAO(content="phase 1 done"),
            ),
        ]

        markdown: str = ReplayEntryProjector.render_markdown(events=events)

        assert "### Workflow update" in markdown
        assert "phase 1 done" in markdown
