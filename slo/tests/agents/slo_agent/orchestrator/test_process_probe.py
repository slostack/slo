"""Tests for the conservative process-liveness probe."""

from __future__ import annotations

import os

import pytest

from src.agents.slo_agent.orchestrator.process_probe import ProcessProbe


def test_is_alive_returns_true_for_live_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful zero-signal probe proves the process is live."""
    monkeypatch.setattr(os, "kill", lambda pid, signal: None)

    assert ProcessProbe.is_alive(pid=123) is True


def test_is_alive_returns_false_for_missing_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only ProcessLookupError is proof that a process is dead."""
    def raise_missing(pid: int, signal: int) -> None:
        """Raise the missing-process error."""
        raise ProcessLookupError()

    monkeypatch.setattr(os, "kill", raise_missing)

    assert ProcessProbe.is_alive(pid=123) is False


def test_is_alive_returns_true_for_eperm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Permission errors prove another user's process still exists."""
    def raise_permission(pid: int, signal: int) -> None:
        """Raise the permission error."""
        raise PermissionError()

    monkeypatch.setattr(os, "kill", raise_permission)

    assert ProcessProbe.is_alive(pid=123) is True


def test_is_alive_returns_true_for_other_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown OS errors receive the conservative live verdict."""
    def raise_oserror(pid: int, signal: int) -> None:
        """Raise an unrelated operating-system error."""
        raise OSError("unexpected")

    monkeypatch.setattr(os, "kill", raise_oserror)

    assert ProcessProbe.is_alive(pid=123) is True


@pytest.mark.parametrize("pid", [0, -1])
def test_is_alive_rejects_non_positive_pid(pid: int) -> None:
    """Non-positive identifiers never probe the current process group."""
    assert ProcessProbe.is_alive(pid=pid) is False
