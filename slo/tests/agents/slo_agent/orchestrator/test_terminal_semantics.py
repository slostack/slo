"""Tests for shared orchestration terminal-vocabulary projections."""

from __future__ import annotations

import pytest

from src.agents.slo_agent.orchestrator.dao import (
    TERMINAL_KIND_TO_HEADLESS_LIFECYCLE,
    exit_code_for_terminal_kind,
    lifecycle_kind_for_status,
    run_state_for_terminal_kind,
    status_for_lifecycle_kind,
    terminal_reason_for_status,
)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("run_completed", 0), ("run_aborted", 2), ("run_failed", 1)],
)
def test_exit_code_for_terminal_kind(kind: str, expected: int) -> None:
    """Terminal event kinds project to the correct POSIX exit code."""
    assert exit_code_for_terminal_kind(kind=kind) == expected


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("run_completed", "headless_run_completed"),
        ("run_aborted", "headless_run_aborted"),
        ("run_failed", "headless_run_failed"),
    ],
)
def test_headless_lifecycle_for_terminal_kind(kind: str, expected: str) -> None:
    """Terminal kinds project to lifecycle output with a failed fallback.

    WHAT: Verifies the centralized lifecycle map consumed by HeadlessRunner.
    WHO: The 71.a.0 terminal-vocabulary regression suite.
    WHEN: Whenever terminal event vocabulary or lifecycle output changes.

    Args:
        kind (str): Terminal stream kind under test.
        expected (str): Expected stderr lifecycle kind.
    """
    lifecycle_kind: str = TERMINAL_KIND_TO_HEADLESS_LIFECYCLE.get(
        kind,
        "headless_run_failed",
    )
    assert lifecycle_kind == expected


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("run_completed", "completed"),
        ("run_aborted", "aborted"),
        ("run_failed", "failed"),
        ("unknown", "failed"),
    ],
)
def test_run_state_for_terminal_kind(kind: str, expected: str) -> None:
    """Terminal event kinds project to the durable run state with a failed default."""
    assert run_state_for_terminal_kind(kind=kind) == expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("completed", "sub_agent_completed"),
        ("aborted", "sub_agent_aborted"),
        ("failed", "sub_agent_failed"),
        ("unknown", "sub_agent_failed"),
    ],
)
def test_lifecycle_kind_for_status(status: str, expected: str) -> None:
    """Child terminal statuses project to the pool lifecycle kind with a failed default."""
    assert lifecycle_kind_for_status(status=status) == expected


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("sub_agent_completed", "completed"),
        ("sub_agent_aborted", "aborted"),
        ("sub_agent_failed", "failed"),
        ("unknown", "failed"),
    ],
)
def test_status_for_lifecycle_kind(kind: str, expected: str) -> None:
    """Child lifecycle event kinds project to terminal statuses."""
    assert status_for_lifecycle_kind(kind=kind) == expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("completed", "completed"),
        ("aborted", "operator_abort"),
        ("failed", "failed"),
        ("unknown", "failed"),
    ],
)
def test_terminal_reason_for_status(status: str, expected: str) -> None:
    """Child statuses project to their default terminal reason with a failed default."""
    assert terminal_reason_for_status(status=status) == expected
