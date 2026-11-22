"""Terminal capability resolution for forced-send keys (108.2 §2).

The kitty keyboard protocol (or an equivalent modifyOtherKeys mode) is what
lets a terminal report Ctrl+Enter distinctly from Enter. Terminals that do
not support it deliver Ctrl+Enter as a plain Enter, so the TUI shows a
one-line hint on first start and the operator falls back to Alt+Enter or
``/force <text>`` — both of which work everywhere.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

__all__ = ["ctrl_enter_detectable", "ctrl_enter_hint_line", "ctrl_enter_hint_renderer"]


_TERM_VALUES_WITH_CTRL_ENTER: frozenset[str] = frozenset(
    {
        "xterm-kitty",
        "xterm-ghostty",
        "ghostty",
        "wezterm",
        "contour",
        "foot",
    }
)
"""``TERM`` values whose terminfo entry carries the kitty keyboard protocol."""

_TERM_PROGRAM_VALUES_WITH_CTRL_ENTER: frozenset[str] = frozenset(
    {
        "kitty",
        "ghostty",
        "wezterm",
        "contour",
        "foot",
    }
)
"""``TERM_PROGRAM`` values that implement the kitty keyboard protocol."""


def ctrl_enter_detectable(*, env: Optional[dict[str, str]] = None) -> bool:
    """Resolve whether this terminal can report Ctrl+Enter distinctly from Enter.

    The check is declarative: it reads the terminal identifiers the
    environment already carries and matches them against the known
    kitty-protocol family. Anything unmatched falls back to "not detectable",
    which only costs the operator a hint line — never a broken send, because
    Alt+Enter and ``/force`` reach the queue everywhere.

    Args:
        env (Optional[dict[str, str]]): Environment to inspect; defaults to
            the process environment.

    Returns:
        bool: ``True`` when Ctrl+Enter is expected to arrive as its own key.
    """
    environment: dict[str, str] = env if env is not None else dict(os.environ)
    term_value: str = environment.get("TERM", "").lower()
    term_program_value: str = environment.get("TERM_PROGRAM", "").lower()
    return (
        term_value in _TERM_VALUES_WITH_CTRL_ENTER
        or term_program_value in _TERM_PROGRAM_VALUES_WITH_CTRL_ENTER
    )


def ctrl_enter_hint_line(*, env: Optional[dict[str, str]] = None) -> Optional[str]:
    """Return the one-line forced-send hint when Ctrl+Enter is not detectable.

    Args:
        env (Optional[dict[str, str]]): Environment to inspect; defaults to
            the process environment.

    Returns:
        Optional[str]: The hint line for terminals that cannot report
            Ctrl+Enter distinctly, or ``None`` when no hint is needed.
    """
    if ctrl_enter_detectable(env=env):
        return None
    return (
        "Tip: Ctrl+Enter may be indistinguishable from Enter in this terminal — "
        "use Alt+Enter or /force <text> to send forced (108.2)."
    )


def ctrl_enter_hint_renderer(*, env: Optional[dict[str, str]] = None) -> Callable[[], Optional[str]]:
    """Return a zero-argument renderer bound to one environment snapshot.

    Args:
        env (Optional[dict[str, str]]): Environment the renderer inspects;
            ``None`` binds the live process environment.

    Returns:
        Callable[[], Optional[str]]: The hint-line renderer for that snapshot.
    """

    def _render() -> Optional[str]:
        """Return the hint line for the bound environment."""
        return ctrl_enter_hint_line(env=env)

    return _render
