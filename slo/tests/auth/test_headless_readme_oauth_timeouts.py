"""Regression pins for documented OAuth timeout semantics."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_readme_documents_separate_oauth_deadlines() -> None:
    """README keeps the callback deadline distinct from both 900-second attempt deadlines."""
    readme: str = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())

    assert "`SLO_OAUTH_TIMEOUT_SECONDS` (loopback callback, default `60`)" in readme
    assert (
        "`SLO_OAUTH_MANUAL_TIMEOUT_SECONDS` (whole browser/manual attempt including paste, default `900`)"
        in readme
    )
    assert "`SLO_OAUTH_DEVICE_TIMEOUT_SECONDS` (device attempt, default `900`)" in readme
    assert "interactive auth only" not in readme
