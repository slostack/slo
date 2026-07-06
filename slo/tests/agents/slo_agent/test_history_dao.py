"""Tests for ``SessionHistoryEventDAO`` and ``HistoryEventKind`` (sub-spec 01.f)."""

from __future__ import annotations

import pytest

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)


class TestExistingHistoryKinds:
    """Existing HistoryEventKind values still round-trip correctly."""

    def test_run_completed_kind_accepted(self) -> None:
        """Existing ``run_completed`` kind is still valid after the extension."""
        event: SessionHistoryEventDAO = SessionHistoryEventDAO(
            session_id="s1",
            kind="run_completed",
        )

        assert event.kind == "run_completed"

    def test_tool_call_kind_accepted(self) -> None:
        """Existing ``tool_call`` kind is still valid after the extension."""
        event: SessionHistoryEventDAO = SessionHistoryEventDAO(
            session_id="s1",
            kind="tool_call",
        )

        assert event.kind == "tool_call"


class TestSubAgentHistoryKinds:
    """New orchestrator/sub-agent ``HistoryEventKind`` values (sub-spec 01.f)."""

    def test_orchestrator_started_kind_accepted(self) -> None:
        """``orchestrator_started`` is a valid ``HistoryEventKind``."""
        event: SessionHistoryEventDAO = SessionHistoryEventDAO(
            session_id="s1",
            kind="orchestrator_started",
        )

        assert event.kind == "orchestrator_started"

    def test_sub_agent_spawned_kind_accepted(self) -> None:
        """``sub_agent_spawned`` is a valid ``HistoryEventKind``."""
        event: SessionHistoryEventDAO = SessionHistoryEventDAO(
            session_id="s1",
            kind="sub_agent_spawned",
        )

        assert event.kind == "sub_agent_spawned"

    def test_sub_agent_completed_kind_accepted(self) -> None:
        """``sub_agent_completed`` is a valid ``HistoryEventKind``."""
        event: SessionHistoryEventDAO = SessionHistoryEventDAO(
            session_id="s1",
            kind="sub_agent_completed",
        )

        assert event.kind == "sub_agent_completed"

    def test_sub_agent_metadata_survives_round_trip(self) -> None:
        """``sub_agent_id`` and ``task_id`` in ``payload.metadata`` survive serialisation."""
        event: SessionHistoryEventDAO = SessionHistoryEventDAO(
            session_id="s1",
            kind="sub_agent_spawned",
            payload=SessionHistoryEventPayloadDAO(
                metadata={
                    "sub_agent_id": "child-uuid-1",
                    "task_id": "task-abc",
                }
            ),
        )
        raw: str = event.model_dump_json()
        recovered: SessionHistoryEventDAO = SessionHistoryEventDAO.model_validate_json(raw)

        assert recovered.payload.metadata["sub_agent_id"] == "child-uuid-1"
        assert recovered.payload.metadata["task_id"] == "task-abc"

    def test_sub_agent_completed_with_terminal_kind_in_metadata(self) -> None:
        """``terminal_kind`` metadata field survives round-trip for completed events."""
        event: SessionHistoryEventDAO = SessionHistoryEventDAO(
            session_id="s1",
            kind="sub_agent_completed",
            payload=SessionHistoryEventPayloadDAO(
                metadata={
                    "sub_agent_id": "child-1",
                    "task_id": "t1",
                    "terminal_kind": "sub_agent_failed",
                }
            ),
        )
        recovered: SessionHistoryEventDAO = SessionHistoryEventDAO.model_validate_json(
            event.model_dump_json()
        )

        assert recovered.payload.metadata["terminal_kind"] == "sub_agent_failed"
