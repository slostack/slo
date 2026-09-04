"""Tests for the common headless-child environment and capture policy."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.orchestrator.spawn_env import (
    build_headless_child_env,
    open_capture_file_append,
)


def test_child_env_includes_exact_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exact non-secret process basics pass to a child."""
    monkeypatch.setenv("PATH", "/bin")
    monkeypatch.setenv("HOME", "/home/slo")

    child_env: dict[str, str] = build_headless_child_env()

    assert child_env["PATH"] == "/bin"
    assert child_env["HOME"] == "/home/slo"


def test_child_env_includes_nonsecret_slo_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-secret SLO configuration passes to a child."""
    monkeypatch.setenv("SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS", "7200")

    child_env: dict[str, str] = build_headless_child_env()

    assert child_env["SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS"] == "7200"


def test_child_env_drops_secret_marked_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Secret-marked SLO variables do not cross a spawn boundary."""
    monkeypatch.setenv("SLO_OPENAI_API_KEY", "secret")

    child_env: dict[str, str] = build_headless_child_env()

    assert "SLO_OPENAI_API_KEY" not in child_env


def test_child_env_drops_unrelated_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unrelated parent environment variables do not cross a spawn boundary."""
    monkeypatch.setenv("UNRELATED_PARENT_VALUE", "drop-me")

    child_env: dict[str, str] = build_headless_child_env()

    assert "UNRELATED_PARENT_VALUE" not in child_env


def test_child_env_injects_workflow_and_extra() -> None:
    """Workflow identifiers and non-empty per-spawn values are injected."""
    child_env: dict[str, str] = build_headless_child_env(
        workflow_id="wf-1",
        extra={"SLO_PARENT_PID": "42", "EMPTY": ""},
    )

    assert child_env["SLO_WORKFLOW_ID"] == "wf-1"
    assert child_env["SLO_PARENT_PID"] == "42"
    assert "EMPTY" not in child_env


def test_child_env_drops_empty_extra() -> None:
    """Empty per-spawn values are omitted from the child environment."""
    child_env: dict[str, str] = build_headless_child_env(extra={"EMPTY": ""})

    assert "EMPTY" not in child_env


def test_open_capture_file_append_creates_session_capture(tmp_path: Path) -> None:
    """Capture opener creates a session directory and appends binary content."""
    with open_capture_file_append(history_root=tmp_path, session_id="session", name="stdout.jsonl") as capture:
        capture.write(b"one\n")

    assert (tmp_path / "session" / "stdout.jsonl").read_bytes() == b"one\n"
