"""Unit tests for the forced-send terminal capability resolver (108.2 §2).

The resolver decides whether the terminal can report Ctrl+Enter distinctly
from Enter; the TUI shows a one-line hint on first start when it cannot.
"""

from __future__ import annotations

import pytest

from src.tui.keyboard_capability import ctrl_enter_detectable, ctrl_enter_hint_line


class TestCtrlEnterDetectable:
    @pytest.mark.parametrize(
        "environment",
        [
            {"TERM": "xterm-kitty"},
            {"TERM": "xterm-ghostty"},
            {"TERM": "wezterm"},
            {"TERM": "contour"},
            {"TERM": "foot"},
            {"TERM_PROGRAM": "kitty"},
            {"TERM_PROGRAM": "ghostty"},
            {"TERM_PROGRAM": "wezterm"},
            {"TERM_PROGRAM": "contour"},
            {"TERM_PROGRAM": "foot"},
            {"TERM": "xterm-kitty", "TERM_PROGRAM": "something-else"},
        ],
    )
    def test_known_protocol_terminals_report_ctrl_enter(self, environment: dict[str, str]) -> None:
        """A kitty-protocol terminal family reports Ctrl+Enter as its own key."""
        assert ctrl_enter_detectable(env=environment) is True

    @pytest.mark.parametrize(
        "environment",
        [
            {},
            {"TERM": "dumb"},
            {"TERM": "xterm-256color"},
            {"TERM": "alacritty"},
            {"TERM_PROGRAM": "iTerm.app"},
            {"TERM_PROGRAM": "Apple_Terminal"},
            {"TERM": "screen-256color", "TERM_PROGRAM": "tmux"},
        ],
    )
    def test_other_terminals_cannot_report_ctrl_enter(self, environment: dict[str, str]) -> None:
        """Terminals outside the kitty family deliver Ctrl+Enter as plain Enter."""
        assert ctrl_enter_detectable(env=environment) is False


class TestCtrlEnterHintLine:
    def test_hint_line_names_alt_enter_and_force_for_undetectable_terminals(self) -> None:
        """The hint tells the operator about Alt+Enter and /force in one line."""
        hint: str | None = ctrl_enter_hint_line(env={"TERM": "dumb"})
        assert hint is not None
        assert "Alt+Enter" in hint
        assert "/force" in hint

    def test_detectable_terminals_render_no_hint(self) -> None:
        """A kitty-protocol terminal needs no hint line."""
        assert ctrl_enter_hint_line(env={"TERM": "xterm-kitty"}) is None

    def test_renderer_reports_the_same_line_as_the_direct_call(self) -> None:
        """The bound renderer answers with the same verdict as the resolver."""
        from src.tui.keyboard_capability import ctrl_enter_hint_renderer

        renderer = ctrl_enter_hint_renderer(env={"TERM": "dumb"})
        assert renderer() == ctrl_enter_hint_line(env={"TERM": "dumb"})
