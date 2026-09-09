"""Regression pins for documented headless OAuth timeout semantics."""

from __future__ import annotations

from pathlib import Path


def test_headless_readme_documents_separate_oauth_deadlines() -> None:
    """Keep callback rows headless-safe and retain both 900-second attempt rows."""
    readme: str = Path("docs/SLO_HEADLESS_README.md").read_text(encoding="utf-8")
    callback_rows: list[str] = [line for line in readme.splitlines() if "`SLO_OAUTH_TIMEOUT_SECONDS`" in line]

    assert len(callback_rows) == 2
    assert all("interactive auth only" not in row for row in callback_rows)
    assert readme.count("| `SLO_OAUTH_MANUAL_TIMEOUT_SECONDS` | `900` |") == 2
    assert readme.count("| `SLO_OAUTH_DEVICE_TIMEOUT_SECONDS` | `900` |") == 2
