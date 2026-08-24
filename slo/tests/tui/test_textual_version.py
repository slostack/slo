"""Guardrail asserting the Textual pin ships native mouse text selection.

The copy-ui-text feature depends on Textual >= 8.2.7, which is the first widely
used release that gives slo both native mouse drag-selection and the
``events.TextSelected`` event. If the pin ever regresses below that, mouse
selection and auto-copy silently stop working — this test fails loudly instead.
"""

from __future__ import annotations

import textual
from textual.app import App
from textual.screen import Screen


def _parse_version(*, raw: str) -> tuple[int, int, int]:
    """Parse the leading ``major.minor.patch`` of a version string to ints.

    Ignores any pre-release or build suffix (e.g. ``8.2.8rc1``) by keeping only
    the leading digits of each of the first three dotted segments. Called only by
    ``test_textual_is_at_least_native_selection``.

    Args:
        raw (str): A version string such as ``"8.2.8"``.

    Returns:
        tuple[int, int, int]: The parsed ``(major, minor, patch)`` triple.
    """
    parts: list[str] = raw.split(".")[:3]
    numbers: list[int] = []
    for part in parts:
        digits: str = "".join(ch for ch in part if ch.isdigit())
        numbers.append(int(digits) if digits else 0)
    while len(numbers) < 3:
        numbers.append(0)
    return numbers[0], numbers[1], numbers[2]


def test_textual_is_at_least_native_selection() -> None:
    """Installed Textual is >= 8.2.7 and exposes the selection APIs slo needs."""
    assert _parse_version(raw=textual.__version__) >= (8, 2, 7)
    assert hasattr(textual.events, "TextSelected")
    assert hasattr(App, "ALLOW_SELECT")
    assert hasattr(Screen, "get_selected_text")
