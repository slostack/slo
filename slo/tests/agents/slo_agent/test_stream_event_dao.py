"""Tests for ``AgentStreamEventDAO``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agents.slo_agent.events.stream import AgentStreamEventDAO


class TestAgentStreamEventDAO:
    """DAO convenience properties and invariants."""

    def test_is_terminal_is_true_for_run_completed(self) -> None:
        """Terminal run events report ``is_terminal=True``."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="run_completed",
            content="done",
        )

        assert event.is_terminal is True

    def test_is_terminal_is_false_for_text_delta(self) -> None:
        """Non-terminal visible deltas report ``is_terminal=False``."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="text_delta",
            delta="hi",
        )

        assert event.is_terminal is False

    def test_is_visible_delta_is_true_for_thinking_delta(self) -> None:
        """Thinking deltas are marked as visible deltas."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="thinking_delta",
            delta="reasoning",
        )

        assert event.is_visible_delta is True

    def test_is_visible_delta_is_false_for_tool_result(self) -> None:
        """Tool-result events are not visible assistant-text deltas."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="tool_result",
            tool_name="bash",
            content="stdout",
        )

        assert event.is_visible_delta is False

    def test_is_block_boundary_is_true_for_text_start(self) -> None:
        """Start events are marked as block boundaries."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(kind="text_start")

        assert event.is_block_boundary is True

    def test_is_block_boundary_is_false_for_text_delta(self) -> None:
        """Delta events are not block boundaries."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="text_delta",
            delta="hi",
        )

        assert event.is_block_boundary is False


class TestSubAgentEventFields:
    """Sub-agent identity fields and new lifecycle kind literals (sub-spec 01.f)."""

    def test_sub_agent_fields_default_to_none(self) -> None:
        """Existing events are unaffected — new fields default to ``None``."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(kind="text_delta", delta="hello")

        assert event.sub_agent_id is None
        assert event.task_id is None

    def test_is_sub_agent_event_is_false_for_orchestrator_event(self) -> None:
        """Orchestrator-pane events have ``is_sub_agent_event=False``."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(kind="text_delta", delta="x")

        assert event.is_sub_agent_event is False

    def test_is_sub_agent_event_is_true_when_sub_agent_id_set(self) -> None:
        """Events with a non-None ``sub_agent_id`` are sub-agent events."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="sub_agent_spawned",
            sub_agent_id="s-abc",
            task_id="t1",
        )

        assert event.is_sub_agent_event is True

    def test_sub_agent_spawned_kind_is_valid(self) -> None:
        """``sub_agent_spawned`` is a valid ``StreamEventKind``."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="sub_agent_spawned",
            sub_agent_id="s-abc",
            task_id="t1",
        )

        assert event.kind == "sub_agent_spawned"

    def test_sub_agent_completed_kind_is_valid(self) -> None:
        """``sub_agent_completed`` is a valid ``StreamEventKind``."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="sub_agent_completed",
            sub_agent_id="s-abc",
            task_id="t1",
        )

        assert event.kind == "sub_agent_completed"

    def test_sub_agent_failed_kind_is_valid(self) -> None:
        """``sub_agent_failed`` is a valid ``StreamEventKind``."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="sub_agent_failed",
            sub_agent_id="s-abc",
            task_id="t1",
        )

        assert event.kind == "sub_agent_failed"

    def test_sub_agent_lifecycle_kinds_are_not_terminal(self) -> None:
        """Sub-agent lifecycle events are not run-terminal events."""
        for kind in ("sub_agent_spawned", "sub_agent_completed", "sub_agent_failed"):
            event: AgentStreamEventDAO = AgentStreamEventDAO(
                kind=kind,  # type: ignore[arg-type]
                sub_agent_id="s",
                task_id="t",
            )
            assert event.is_terminal is False, f"expected is_terminal=False for {kind}"

    def test_round_trip_preserves_sub_agent_fields(self) -> None:
        """Sub-agent fields survive ``model_dump_json`` / ``model_validate_json``."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="text_delta",
            delta="hello",
            sub_agent_id="s-xyz",
            task_id="my-task",
        )
        recovered: AgentStreamEventDAO = AgentStreamEventDAO.model_validate_json(event.model_dump_json())

        assert recovered.sub_agent_id == "s-xyz"
        assert recovered.task_id == "my-task"
