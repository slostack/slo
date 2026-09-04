"""Braille-activity thinking spinner widget for the Slo TUI (sub-spec 02.a.3, restyled in 72.a.5).

A small ``Horizontal`` container with two child ``Static`` surfaces: an
accent braille activity glyph that rotates every ``_BRAILLE_INTERVAL_SECONDS``
while a prompt is in flight, and a muted status text that rotates through a
verb list every ``interval_seconds`` (default 1.5 s) or carries an explicit
retry/compaction override. ``SloTUI`` mounts it at the start of
``_run_prompt`` and keeps it in a fixed status region above the prompt until
the run finishes.
"""

from __future__ import annotations

from itertools import cycle
from typing import Iterator, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.timer import Timer
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

_BRAILLE_FRAMES: tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
"""Ordered braille animation glyphs for the fast activity indicator."""

_BRAILLE_INTERVAL_SECONDS: float = 0.08
"""Fast glyph rotation cadence — terminal-friendly activity framing."""


class ThinkingSpinner(Horizontal):
    """Render active work as an accent braille glyph and muted status text.

    WHAT: Separates fast visual activity from the existing slow human-readable
    verb/status cadence. WHO: ``SloTUI._mount_spinner`` owns its lifetime.
    WHEN: Mounted only while a prompt is in flight; retry/compaction status
    overrides replace the text but never stop the activity glyph.
    """

    DEFAULT_CSS = """
    ThinkingSpinner { width: 100%; height: auto; padding: 0 1; }
    ThinkingSpinner .thinking-spinner-glyph { color: $accent; text-style: bold; }
    ThinkingSpinner .thinking-spinner-text { color: $text-muted; text-style: italic; }
    """

    def __init__(self, *, interval_seconds: float = 1.5) -> None:
        """Build the spinner with independent glyph and text cycles.

        Args:
            interval_seconds (float): Existing slow verb rotation interval.
                Defaults to ``1.5`` seconds.
        """
        super().__init__()
        self._interval_seconds: float = interval_seconds
        self._verb_cycle: Iterator[str] = cycle(_VERBS)
        self._braille_cycle: Iterator[str] = cycle(_BRAILLE_FRAMES)
        self._current_verb: str = next(self._verb_cycle)
        self._current_braille: str = next(self._braille_cycle)
        self._override_status: Optional[str] = None
        self._braille_timer: Optional[Timer] = None
        self._glyph: Static = Static(self._current_braille, classes="thinking-spinner-glyph")
        self._text: Static = Static(
            self._format_verb(verb=self._current_verb),
            classes="thinking-spinner-text",
        )
        self.add_class("thinking-spinner")

    def compose(self) -> ComposeResult:
        """Yield the accent activity glyph followed by the muted status text.

        Yields:
            ComposeResult: Two local spinner display surfaces.
        """
        yield self._glyph
        yield self._text

    def on_mount(self) -> None:
        """Start independent fast glyph and slow word timers for a mounted run.

        Called by Textual once the widget enters the DOM. Delegates the
        per-tick work to ``_rotate_braille`` and ``_rotate_verb`` so those
        methods stay independently testable.
        """
        self._braille_timer = self.set_interval(
            interval=_BRAILLE_INTERVAL_SECONDS,
            callback=self._rotate_braille,
        )
        self.set_interval(interval=self._interval_seconds, callback=self._rotate_verb)

    def _rotate_braille(self) -> None:
        """Advance only the braille glyph; override text remains untouched.

        Invoked by the fast Textual interval timer (and directly by tests
        that drive the rotation manually).
        """
        self._current_braille = next(self._braille_cycle)
        self._glyph.update(self._current_braille)

    def _render_status_text(self) -> str:
        """Return override text when present, otherwise the current verb copy.

        Returns:
            str: The status wording the text surface should show.
        """
        if self._override_status is not None:
            return self._override_status
        return self._format_verb(verb=self._current_verb)

    def _rotate_verb(self) -> None:
        """Advance the slow verb and refresh only the text surface.

        Invoked by the slow Textual interval timer (and directly by tests
        that drive the rotation manually).
        """
        self._current_verb = next(self._verb_cycle)
        self._text.update(self._render_status_text())

    def set_override_status(self, *, text: Optional[str]) -> None:
        """Replace or restore status wording without stopping braille activity.

        Args:
            text (Optional[str]): Explicit runtime status, or None to restore verbs.
        """
        self._override_status = text
        self._text.update(self._render_status_text())

    @staticmethod
    def _format_verb(*, verb: str) -> str:
        """Render the verb into the displayed status text.

        Args:
            verb (str): The current verb in the rotation.

        Returns:
            str: ``"<verb>…"`` — the readable half of the spinner line.
        """
        return f"{verb}…"
