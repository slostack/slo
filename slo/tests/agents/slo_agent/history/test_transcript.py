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
from src.agents.slo_agent.message_text import merge_reasoning_delta


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


def _thinking(
    *, delta_kind: str, delta: str | None = None, content: str | None = None
) -> SessionHistoryEventDAO:
    """Build one persisted thinking marker or delta for block ``thinking:0:0``.

    Args:
        delta_kind (str): ``thinking_start``, ``thinking_delta`` or ``thinking_end``.
        delta (str | None): Streamed text for a delta.
        content (str | None): Completed segment text carried by an end marker.

    Returns:
        SessionHistoryEventDAO: An ``assistant_delta`` history event.
    """
    return _event(
        kind="assistant_delta",
        payload=SessionHistoryEventPayloadDAO(
            delta_kind=delta_kind, block_id="thinking:0:0", delta=delta, content=content  # type: ignore[arg-type]
        ),
    )


class TestThinkingSegmentReplay:
    """Resumed thinking keeps the segment boundaries the live stream showed."""

    def test_separate_segments_replay_as_separate_paragraphs(self) -> None:
        """Summary parts sharing a block id must not run together on resume."""
        events = [
            _thinking(delta_kind="thinking_start"),
            _thinking(delta_kind="thinking_end"),
            _thinking(delta_kind="thinking_start"),
            _thinking(delta_kind="thinking_delta", delta="**Planning multi-agent delegation**"),
            _thinking(delta_kind="thinking_end", content="**Planning multi-agent delegation**"),
            _thinking(delta_kind="thinking_start"),
            _thinking(delta_kind="thinking_delta", delta="**Designing parallel workflow**"),
            _thinking(delta_kind="thinking_end", content="**Designing parallel workflow**"),
            _event(kind="assistant_message", payload=SessionHistoryEventPayloadDAO(content="done")),
        ]

        entries = ReplayEntryProjector.build_entries(events=events)

        assert (
            entries[0].reasoning == "**Planning multi-agent delegation**\n\n**Designing parallel workflow**"
        )

    def test_streamed_deltas_within_one_segment_join_verbatim(self) -> None:
        """Token deltas of one open segment keep their exact spacing."""
        events = [
            _thinking(delta_kind="thinking_start"),
            _thinking(delta_kind="thinking_delta", delta="Plan the "),
            _thinking(delta_kind="thinking_delta", delta="work"),
            _thinking(delta_kind="thinking_delta", delta=" carefully."),
            _thinking(delta_kind="thinking_end", content="Plan the work carefully."),
            _event(kind="assistant_message", payload=SessionHistoryEventPayloadDAO(content="done")),
        ]

        entries = ReplayEntryProjector.build_entries(events=events)

        assert entries[0].reasoning == "Plan the work carefully."

    def test_summary_parts_without_completed_text_merge_like_the_live_view(self) -> None:
        """A contentless end keeps the deltas, merged with the live view's spacing.

        Mirrors a real persisted history whose summary titles stream back to
        back and whose ``thinking_end`` carries no completed text.
        """
        events = [
            _thinking(delta_kind="thinking_start"),
            _thinking(delta_kind="thinking_delta", delta="**Planning clear implementation explanation**"),
            _thinking(delta_kind="thinking_delta", delta="**Outlining detailed specification**"),
            _thinking(delta_kind="thinking_end"),
            _event(kind="assistant_message", payload=SessionHistoryEventPayloadDAO(content="done")),
        ]

        entries = ReplayEntryProjector.build_entries(events=events)

        assert (
            entries[0].reasoning
            == "**Planning clear implementation explanation** **Outlining detailed specification**"
        )

    def test_replayed_deltas_equal_the_live_merge(self) -> None:
        """Replay and the live thinking widget share one delta-merge owner."""
        deltas = ["**Checking**", "the repo", ", then", "re-reading", " files.", "(fast)"]
        expected = ""
        for delta in deltas:
            expected = merge_reasoning_delta(existing=expected, delta=delta)
        events = [_thinking(delta_kind="thinking_delta", delta=delta) for delta in deltas]
        events.append(_event(kind="assistant_message", payload=SessionHistoryEventPayloadDAO(content="done")))

        entries = ReplayEntryProjector.build_entries(events=events)

        assert entries[0].reasoning == expected
        assert expected == "**Checking** the repo, then re-reading files. (fast)"

    def test_late_thinking_end_repairs_glued_summary_parts(self) -> None:
        """The completed segment text wins, even when its end follows a tool call.

        Mirrors a real persisted history: summary parts stream as back-to-back
        deltas with no separator, the turn is flushed by a tool call, and the
        properly spaced segment text only arrives in the later ``thinking_end``.
        """
        spaced = "**Planning multi-agent delegation** **Designing parallel workflow**"
        events = [
            _thinking(delta_kind="thinking_start"),
            _thinking(delta_kind="thinking_end"),
            _thinking(delta_kind="thinking_start"),
            _thinking(delta_kind="thinking_delta", delta="**Planning multi-agent delegation**"),
            _thinking(delta_kind="thinking_delta", delta="**Designing parallel workflow**"),
            _event(
                kind="tool_call",
                payload=SessionHistoryEventPayloadDAO(tool_name="ls", tool_call_id="c1", tool_input={}),
            ),
            _thinking(delta_kind="thinking_end", content=spaced),
        ]

        entries = ReplayEntryProjector.build_entries(events=events)

        assert [entry.kind for entry in entries] == ["assistant", "tool"]
        assert entries[0].reasoning == spaced

    def test_thinking_end_before_flush_replaces_streamed_deltas(self) -> None:
        """An end that arrives inside the turn repairs that turn's segment."""
        events = [
            _thinking(delta_kind="thinking_start"),
            _thinking(delta_kind="thinking_delta", delta="**A**"),
            _thinking(delta_kind="thinking_delta", delta="**B**"),
            _thinking(delta_kind="thinking_end", content="**A** **B**"),
            _event(kind="assistant_message", payload=SessionHistoryEventPayloadDAO(content="done")),
        ]

        entries = ReplayEntryProjector.build_entries(events=events)

        assert entries[0].reasoning == "**A** **B**"

    def test_contentless_thinking_end_keeps_streamed_deltas(self) -> None:
        """Without completed text, replay keeps exactly what was streamed."""
        events = [
            _thinking(delta_kind="thinking_start"),
            _thinking(delta_kind="thinking_delta", delta="kept"),
            _thinking(delta_kind="thinking_end"),
            _event(kind="assistant_message", payload=SessionHistoryEventPayloadDAO(content="done")),
        ]

        entries = ReplayEntryProjector.build_entries(events=events)

        assert entries[0].reasoning == "kept"

    def test_late_thinking_end_does_not_open_a_turn_for_the_next_iteration(self) -> None:
        """A late end repairs its own turn and never relabels the next iteration's thinking."""
        events = [
            _thinking(delta_kind="thinking_delta", delta="**First**"),
            _event(
                kind="tool_call",
                payload=SessionHistoryEventPayloadDAO(tool_name="ls", tool_call_id="c1", tool_input={}),
            ),
            _thinking(delta_kind="thinking_end", content="**First**"),
            _event(
                kind="assistant_delta",
                iteration=1,
                payload=SessionHistoryEventPayloadDAO(
                    delta_kind="thinking_delta", block_id="thinking:1:0", delta="**Second**"
                ),
            ),
            _event(
                kind="assistant_message", iteration=1, payload=SessionHistoryEventPayloadDAO(content="done")
            ),
        ]

        entries = ReplayEntryProjector.build_entries(events=events)

        assert [(entry.kind, entry.iteration, entry.reasoning) for entry in entries] == [
            ("assistant", 0, "**First**"),
            ("tool", 0, None),
            ("assistant", 1, "**Second**"),
        ]
