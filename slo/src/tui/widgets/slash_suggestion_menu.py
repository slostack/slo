"""Prompt-adjacent suggestion menu for slash commands."""

from __future__ import annotations

from textual import events
from textual.content import Content
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
        self.window_start: int = 0
        self.add_class("-hidden")

    def compose(self) -> ComposeResult:
        """Compose the static text surface used for row rendering.

        Yields:
            ComposeResult: Single ``Static`` render target.
        """
        yield Static("", classes="slash-suggestion-lines", markup=False)

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
        self._paint_window()

    def on_resize(self, event: events.Resize) -> None:
        """Recompute the viewport after terminal layout changes without resetting selection."""
        self._paint_window()

    def _paint_window(self) -> None:
        """Paint only height-bounded candidates, keeping the selected identity visible."""
        row_height = self._row_height()
        capacity = max(1, min(25, (self.app.size.height - 8) // row_height))
        highlight = self._state.highlighted_index
        self.window_start = max(0, min(self.window_start, max(0, len(self._state.rows) - capacity)))
        if highlight < self.window_start:
            self.window_start = highlight
        if highlight >= self.window_start + capacity:
            self.window_start = highlight - capacity + 1
        width = max(1, self.app.size.width - 6)
        detail_width = width
        lines: list[str] = []
        window_end = min(len(self._state.rows), self.window_start + capacity)
        for index in range(self.window_start, window_end):
            row = self._state.rows[index]
            prefix = "›" if index == highlight else " "
            label = row.label
            if self._state.kind == "path":
                label = self._single_line_path_label(label=label)
            lines.append(f"{prefix} {label}")
            if self._state.kind != "path":
                lines.append(f"  {self._detail_for_terminal(row_detail=row.detail or '')}")
        if not lines:
            lines.append("No models match — change search or /model refresh")
        else:
            total = self._state.total_matches or len(self._state.rows)
            visible_count = window_end - self.window_start
            lines.append(f"Showing {visible_count} of {total} — type to narrow")
        content = Content("\n").join(
            Content(line).truncate(detail_width if line.startswith("  ") else width)
            for entry in lines
            for line in entry.splitlines()
        )
        self.query_one(".slash-suggestion-lines", Static).update(content)

    @staticmethod
    def _single_line_path_label(*, label: str) -> str:
        """Escape every splitlines separator when painting paths, never insertion tokens.

        Args:
            label (str): Literal filesystem candidate label.

        Returns:
            str: Display-only label that occupies one logical menu row.
        """
        escapes: dict[str, str | int | None] = {
            "\n": r"\n",
            "\r": r"\r",
            "\v": r"\v",
            "\f": r"\f",
            "\x1c": r"\x1c",
            "\x1d": r"\x1d",
            "\x1e": r"\x1e",
            "\x85": r"\x85",
            "\u2028": r"\u2028",
            "\u2029": r"\u2029",
        }
        return label.translate(str.maketrans(escapes))

    def _row_height(self) -> int:
        """Size path windows as single-line rows; retain command/model detail capacity.

        Returns:
            int: Maximum painted line count per candidate in the current menu.
        """
        if self._state.kind == "path":
            return 1
        return max(
            (
                1 + max(1, len(self._detail_for_terminal(row_detail=row.detail or "").splitlines()))
                for row in self._state.rows
            ),
            default=2,
        )

    @staticmethod
    def _detail_for_terminal(*, row_detail: str) -> str:
        """Give explicit disable semantics a separate line without clipping status/context.

        Args:
            row_detail (str): Full one-line picker detail.

        Returns:
            str: Original detail or status/context followed by a reasoning line.
        """
        if "unavailable for ChatGPT/Codex" in row_detail:
            return "\n  ".join(row_detail.replace("; Platform", " · Platform").split(" · "))
        if "provider default; controls unavailable" in row_detail:
            return "\n  ".join(row_detail.split(" · "))
        if "subscription configured; not checked" in row_detail:
            return "\n  ".join(row_detail.split(" · ", maxsplit=1))
        marker: str = " · reasoning "
        if marker not in row_detail:
            return row_detail
        prefix, reasoning = row_detail.rsplit(marker, maxsplit=1)
        if reasoning != "disable supported" and not reasoning.endswith("; provider default"):
            return row_detail
        return f"{prefix}\n  reasoning {reasoning}"

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
        if state.total_matches > len(state.rows):
            lines.append(f"Showing {len(state.rows)} of {state.total_matches} — type to narrow")
        return "\n".join(lines)
