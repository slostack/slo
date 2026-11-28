"""Legacy scheduler guards (111.a.7 A1, A8; B14, B16) — strict xfail until flips."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_FORBIDDEN_TOKENS: tuple[str, ...] = (
    "src.scheduling",
    "src/scheduling",
    "src.cli.schedule.app",
    "src/cli/schedule/",
    "InboxImporter",
    "inbox_import",
    "_import_legacy_inbox",
    "session_inbox",
    "ScheduleStore",
    "ScheduleExecutor",
    "ScheduleFireLock",
    "ScheduleCleanupService",
    "ScheduleReportWriter",
    "ScheduleSubprocessRunner",
    "CalendarTriggerDAO",
    "WebhookTargetDAO",
    "SlackTargetDAO",
    "NotificationTargetDAO",
    "slo schedule execute",
    "schedule install",
    "schedule uninstall",
)

_SCOPE: tuple[Path, ...] = (
    Path("src"),
    Path("config"),
    Path("tests"),
    Path("skills"),
    Path("README.md"),
)


def _forbidden_matches() -> list[str]:
    """Scan the source tree for forbidden tokens; return every match."""
    matches: list[str] = []
    for root in _SCOPE:
        if root.is_file():
            candidates: list[Path] = [root]
        else:
            candidates = sorted(root.rglob("*.py")) + sorted(root.rglob("*.md"))
        for path in candidates:
            if "test_no_legacy_scheduler" in path.name:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for token in _FORBIDDEN_TOKENS:
                if token in text:
                    matches.append(f"{path}: {token!r}")
    return matches


def test_source_tree_has_no_legacy_scheduler_or_inbox_names() -> None:
    """A1 (B14): no forbidden token appears in the source tree."""
    assert _forbidden_matches() == [], f"forbidden tokens: {_forbidden_matches()}"


def test_readme_has_no_retired_scheduler_commands() -> None:
    """A8: the README names no retired scheduler command."""
    text = Path("README.md").read_text(encoding="utf-8")
    for command in (
        "slo schedule execute",
        "slo schedule run",
        "slo schedule install",
        "slo schedule uninstall",
        "slo schedule reports",
        "slo schedule show-report",
        "slo schedule cleanup",
    ):
        assert command not in text, f"README names {command!r}"


def test_readme_documents_the_new_schedule_verbs() -> None:
    """A8: the README documents every verb of the single schedule group."""
    text = Path("README.md").read_text(encoding="utf-8")
    for verb in (
        "add",
        "edit",
        "show",
        "list",
        "trigger",
        "start",
        "stop",
        "delete",
        "report",
        "worker",
        "status",
    ):
        assert f"slo schedule {verb}" in text, f"README does not document slo schedule {verb}"
