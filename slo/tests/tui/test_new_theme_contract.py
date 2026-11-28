"""Acceptance tests for the single, quiet slo-default TUI theme."""

from __future__ import annotations

import src.tui.theme as theme_module
from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME


def test_slo_default_theme_uses_the_new_surface_tokens() -> None:
    """Keep the canvas, user band, tool surface and structure ramp on spec values."""
    assert SLO_DEFAULT_THEME.name == "slo-default"
    assert SLO_DEFAULT_THEME.surface == "#1a1b26"
    assert SLO_DEFAULT_THEME.panel == "#1f2335"
    assert SLO_DEFAULT_THEME.variables["user-msg-bg"] == "#1f2335"
    assert SLO_DEFAULT_THEME.variables["tool-pending-bg"] == "#1a1b26"
    assert SLO_DEFAULT_THEME.variables["tool-success-bg"] == "#1a1b26"
    assert SLO_DEFAULT_THEME.variables["tool-error-bg"] == "#1a1b26"
    assert SLO_DEFAULT_THEME.variables["border-hairline"] == "#2a2f45"
    assert SLO_DEFAULT_THEME.variables["text-dim"] == "#8089b5"
    assert SLO_DEFAULT_THEME.variables["text-muted"] == "#a9b1d6"
    assert SLO_DEFAULT_THEME.variables["bar-track"] == "#24283b"
    assert SLO_DEFAULT_THEME.variables["tool-output-bg"] == "#16161e"
    assert SLO_DEFAULT_THEME.variables["status-error"] == "#f7768e"


def test_slo_dark_theme_is_restored_as_the_install_default() -> None:
    """Restore the near-black/green slo-dark palette alongside slo-default."""
    assert SLO_DARK_THEME.name == "slo-dark"
    assert SLO_DARK_THEME.primary == "#00ff7f"
    assert SLO_DARK_THEME.background == "#080808"
    assert SLO_DARK_THEME.variables["auth-selection-background"] == "#3e5148"
    assert theme_module.__all__ == ["SLO_DARK_THEME", "SLO_DEFAULT_THEME"]
