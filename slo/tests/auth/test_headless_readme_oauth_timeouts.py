"""Regression pins for documented headless OAuth timeout semantics."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_research_documents_separate_oauth_deadlines() -> None:
    """RESEARCH.md keeps the callback deadline distinct from both 900-second attempt deadlines."""
    research: str = (ROOT / "RESEARCH.md").read_text(encoding="utf-8")

    assert "`SLO_OAUTH_TIMEOUT_SECONDS` (callback) default `60`" in research
    assert "`SLO_OAUTH_MANUAL_TIMEOUT_SECONDS` (browser/manual attempt) default `900`" in research
    assert "`SLO_OAUTH_DEVICE_TIMEOUT_SECONDS` (device attempt) default `900`" in research
    assert "interactive auth only" not in research
