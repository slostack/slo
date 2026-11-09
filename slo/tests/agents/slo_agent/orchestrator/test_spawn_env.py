"""Tests for the common headless-child environment and capture policy."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.orchestrator.spawn_env import (
    AgentLaunchPolicy,
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


@pytest.mark.parametrize(argnames="username", argvalues=["bridge-user", "", None])
def test_child_env_preserves_user_when_present_without_inventing_one(
    monkeypatch: pytest.MonkeyPatch, username: str | None
) -> None:
    """Keep the supplied Keychain account name; absence must not select another account."""
    monkeypatch.delenv(name="USER", raising=False)
    if username is not None:
        monkeypatch.setenv(name="USER", value=username)

    child_env: dict[str, str] = build_headless_child_env()

    assert child_env.get("USER") == username
    assert ("USER" in child_env) == (username is not None)


def test_launch_policy_preserves_user_snapshot_without_forwarding_related_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Account metadata survives launch snapshots without expanding to USER-prefixed secrets."""
    monkeypatch.setenv(name="USER", value="bridge-user")
    monkeypatch.setenv(name="USER_TOKEN", value="synthetic-secret")
    monkeypatch.setenv(name="SLO_USER_PASSWORD", value="synthetic-secret")
    launch_policy = AgentLaunchPolicy()
    monkeypatch.setenv(name="USER", value="changed-after-snapshot")

    child_env: dict[str, str] = launch_policy.build_environment()

    assert child_env["USER"] == "bridge-user"
    assert "USER_TOKEN" not in child_env
    assert "SLO_USER_PASSWORD" not in child_env


def test_child_env_includes_nonsecret_slo_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-secret SLO configuration passes to a child."""
    monkeypatch.setenv("SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS", "7200")

    child_env: dict[str, str] = build_headless_child_env()

    assert child_env["SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS"] == "7200"


def test_child_env_forwards_plugin_disable_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Feature 75 plugin kill switch reaches headless children explicitly."""
    monkeypatch.setenv("SLO_PLUGINS_DISABLED", "1")

    child_env: dict[str, str] = build_headless_child_env()

    assert child_env["SLO_PLUGINS_DISABLED"] == "1"


@pytest.mark.parametrize(
    "name",
    [
        "SLO_OPENAI_API_KEY",
        "SLO_UPSTREAM_TOKEN",
        "SLO_DEPLOY_SECRET",
        "SLO_DATABASE_PASSWORD",
    ],
)
def test_child_env_drops_secret_marked_vars(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Secret-marked SLO variables do not cross a spawn boundary."""
    monkeypatch.setenv(name, "secret")

    child_env: dict[str, str] = build_headless_child_env()

    assert name not in child_env


def test_child_env_drops_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    """Foreign import roots never cross into trusted checkout module spawns."""
    monkeypatch.setenv("PYTHONPATH", "/hostile/project")

    child_env: dict[str, str] = build_headless_child_env()

    assert "PYTHONPATH" not in child_env


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
    with open_capture_file_append(
        history_root=tmp_path, session_id="session", name="stdout.jsonl"
    ) as capture:
        capture.write(b"one\n")

    assert (tmp_path / "session" / "stdout.jsonl").read_bytes() == b"one\n"
