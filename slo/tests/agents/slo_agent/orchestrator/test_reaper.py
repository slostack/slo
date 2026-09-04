"""Tests for identity-verified fleet child reaping."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from src.agents.slo_agent.orchestrator.reaper import FleetReaper


class TestFleetReaperIdentity:
    """FleetReaper identity verification guards pid signals."""

    def test_verify_identity_accepts_matching_argv(self, monkeypatch) -> None:
        """A live child argv naming its session id passes verification."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: True
        )
        monkeypatch.setattr(
            FleetReaper,
            "_read_process_args",
            lambda *, pid: "slo run --session-id child-1",
        )

        assert FleetReaper.verify_child_identity(pid=123, session_id="child-1") is True

    def test_verify_identity_rejects_recycled_pid(self, monkeypatch) -> None:
        """A live pid with another child's argv is rejected as recycled."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: True
        )
        monkeypatch.setattr(FleetReaper, "_read_process_args", lambda *, pid: "slo run --session-id other")

        assert FleetReaper.verify_child_identity(pid=123, session_id="child-1") is False

    def test_verify_identity_rejects_session_id_prefix(self, monkeypatch) -> None:
        """A prefixed foreign session id cannot authorize a child signal."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: True
        )
        monkeypatch.setattr(
            FleetReaper,
            "_read_process_args",
            lambda *, pid: "slo run --session-id child-123",
        )

        assert FleetReaper.verify_child_identity(pid=123, session_id="child-1") is False

    def test_verify_identity_rejects_prompt_text_session_id(self, monkeypatch) -> None:
        """A prompt argument containing a session option cannot authorize a signal."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: True
        )
        monkeypatch.setattr(
            FleetReaper,
            "_read_process_args",
            lambda *, pid: 'slo run -p "say --session-id child-1"',
        )

        assert FleetReaper.verify_child_identity(pid=123, session_id="child-1") is False

    def test_verify_identity_rejects_dead_pid(self, monkeypatch) -> None:
        """A dead pid is rejected without reading its command line."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: False
        )

        assert FleetReaper.verify_child_identity(pid=123, session_id="child-1") is False

    def test_verify_identity_rejects_unreadable_args(self, monkeypatch) -> None:
        """A live pid with unreadable argv is not safe to signal."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: True
        )
        monkeypatch.setattr(FleetReaper, "_read_process_args", lambda *, pid: None)

        assert FleetReaper.verify_child_identity(pid=123, session_id="child-1") is False


class TestFleetReaperReap:
    """FleetReaper terminate protocol outcomes."""

    async def test_reap_returns_graceful_when_term_suffices(self, monkeypatch) -> None:
        """A child exiting during SIGTERM grace is reported graceful."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: True
        )
        signal: MagicMock = MagicMock()
        monkeypatch.setattr(FleetReaper, "_signal", signal)
        monkeypatch.setattr(FleetReaper, "_await_exit", AsyncMock(return_value=True))

        assert await FleetReaper.reap(pid=123) == "graceful"
        signal.assert_called_once()

    async def test_reap_returns_killed_when_kill_required(self, monkeypatch) -> None:
        """A child surviving SIGTERM grace is reported killed after SIGKILL."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: True
        )
        signal: MagicMock = MagicMock()
        monkeypatch.setattr(FleetReaper, "_signal", signal)
        monkeypatch.setattr(FleetReaper, "_await_exit", AsyncMock(side_effect=[False, True]))

        assert await FleetReaper.reap(pid=123) == "killed"
        assert signal.call_count == 2

    async def test_reap_returns_unresolved_when_kill_does_not_confirm_exit(self, monkeypatch) -> None:
        """A PID surviving SIGKILL grace remains unresolved, never reaped."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: True
        )
        signal: MagicMock = MagicMock()
        monkeypatch.setattr(FleetReaper, "_signal", signal)
        monkeypatch.setattr(FleetReaper, "_await_exit", AsyncMock(side_effect=[False, False]))

        assert await FleetReaper.reap(pid=123) == "unresolved"
        assert signal.call_count == 2

    async def test_reap_returns_already_dead(self, monkeypatch) -> None:
        """A missing pid produces no signal and reports already dead."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: False
        )
        signal: MagicMock = MagicMock()
        monkeypatch.setattr(FleetReaper, "_signal", signal)

        assert await FleetReaper.reap(pid=123) == "already_dead"
        signal.assert_not_called()
