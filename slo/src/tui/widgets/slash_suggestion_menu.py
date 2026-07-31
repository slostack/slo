"""Prompt-adjacent suggestion menu for slash commands."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from src.tui.slash_suggestion_engine import SlashSuggestionStateDAO

__all__ = ["SlashSuggestionMenu"]


class SlashSuggestionMenu(Vertical):
    """Render the current slash suggestion state above the prompt."""

    DEFAULT_CSS = """
    SlashSuggestionMenu {
        width: 100%;
        height: auto;
        background: $panel;
        border: round $accent;
        padding: 0 1;
        margin: 1 0 0 0;
    }

    SlashSuggestionMenu.-hidden {
        display: none;
    }

    SlashSuggestionMenu .slash-suggestion-lines {
        color: $text;
    }
    """

    def __init__(self) -> None:
        """Seed the menu hidden with an empty suggestion state."""
        super().__init__()
        self._state: SlashSuggestionStateDAO = SlashSuggestionStateDAO(visible=False)
        self.add_class("-hidden")

    def compose(self) -> ComposeResult:
        """Compose the static text surface used for row rendering.

        Yields:
            ComposeResult: Single ``Static`` render target.
        """
        yield Static("", classes="slash-suggestion-lines")

    def update_state(self, *, state: SlashSuggestionStateDAO) -> None:
        """Render the provided suggestion state, skipping unchanged updates.

        ``SloTUI.on_text_area_changed`` calls this on every prompt keystroke,
        including ordinary prose where ``state.visible`` is ``False`` every time.
        Each ``Static.update`` forces Textual to reflow the whole transcript
        (O(N) in mounted widgets), so re-rendering an unchanged state is the
        dominant source of typing lag in long sessions. This guard makes a
        no-change keystroke do zero DOM work.

        Args:
            state (SlashSuggestionStateDAO): Suggestion state to render.
        """
        if state == self._state:
            return
        self._state = state
        self.set_class(not state.visible, "-hidden")
        self.query_one(".slash-suggestion-lines", Static).update(self._render_lines(state=state))

    @staticmethod
    def _render_lines(*, state: SlashSuggestionStateDAO) -> str:
        """Render the visible row text for one suggestion state.

        Args:
            state (SlashSuggestionStateDAO): Suggestion state to render.

        Returns:
            str: Multi-line menu content.
        """
        if not state.visible:
            return ""
        lines: list[str] = []
        for index, row in enumerate(state.rows):
            prefix: str = "›" if index == state.highlighted_index else " "
            detail: str = f" — {row.detail}" if row.detail else ""
            lines.append(f"{prefix} {row.label}{detail}")
        return "\n".join(lines)
