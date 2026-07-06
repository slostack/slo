"""Rotating-verb thinking spinner widget for the Slo TUI (sub-spec 02.a.3).

A ``Static`` widget that cycles through a verb list every
``interval_seconds`` (default 1.5 s) while a prompt is in flight.
``SloTUI`` mounts it at the start of ``_run_prompt`` and keeps it in a
fixed status region above the prompt until the run finishes.
"""

from __future__ import annotations

from itertools import cycle
from typing import Iterator

from textual.widgets import Static

__all__ = ["ThinkingSpinner"]


_VERBS: tuple[str, ...] = (
    "Pondering",
    "Investigating",
    "Crafting",
    "Reading",
    "Working",
    "Thinking",
)
"""Rotating verbs surfaced in the spinner. Ordered to match Claude
Code's cadence — ``Pondering`` first, ``Thinking`` last, then cycles."""


class ThinkingSpinner(Static):
    """A ``Static`` widget that rotates through verbs on a fixed interval."""

    DEFAULT_CSS = ""

    def __init__(self, *, interval_seconds: float = 1.5) -> None:
        """Configure the spinner and seed it with the first verb.

        Args:
            interval_seconds (float): How often the verb rotates.
                Defaults to ``1.5`` seconds.
        """
        super().__init__()
        self._interval_seconds: float = interval_seconds
        self._verb_cycle: Iterator[str] = cycle(_VERBS)
        self._current_verb: str = next(self._verb_cycle)
        self._override_status: str | None = None
        self.add_class("thinking-spinner")
        self.update(self._format_verb(verb=self._current_verb))

    def on_mount(self) -> None:
        """Start the interval timer that rotates the verb.

        Called by Textual once the widget enters the DOM. Delegates
        the per-tick work to ``_rotate_verb`` so that method stays
        independently testable.
        """
        self.set_interval(interval=self._interval_seconds, callback=self._rotate_verb)

    def _rotate_verb(self) -> None:
        """Advance to the next verb and refresh the rendered text.

        Invoked by the Textual interval timer (and directly by tests
        that drive the rotation manually).
        """
        self._current_verb = next(self._verb_cycle)
        if self._override_status is not None:
            self.update(self._override_status)
            return
        self.update(self._format_verb(verb=self._current_verb))

    def set_override_status(self, *, text: str | None) -> None:
        """Override the rotating verb with an explicit runtime status line.

        Args:
            text (str | None): Explicit status text, or ``None`` to resume rotation.
        """
        self._override_status = text
        if text is not None:
            self.update(text)
            return
        self.update(self._format_verb(verb=self._current_verb))

    @staticmethod
    def _format_verb(*, verb: str) -> str:
        """Render the verb into the displayed spinner line.

        Args:
            verb (str): The current verb in the rotation.

        Returns:
            str: ``"✦ <verb>…"`` — the Claude-Code-style spinner line.
        """
        return f"✦ {verb}…"
