"""Tests for the slash suggestion menu renderer."""

from __future__ import annotations

from src.tui.slash_suggestion_engine import SlashSuggestionRowDAO, SlashSuggestionStateDAO
from src.tui.widgets.slash_suggestion_menu import SlashSuggestionMenu


class TestSlashSuggestionMenu:
    """Visible rendering guarantees for the slash suggestion menu."""

    def test_render_lines_includes_all_visible_rows(self) -> None:
        """The menu renders every suggestion row instead of truncating after eight."""
        rows: list[SlashSuggestionRowDAO] = [
            SlashSuggestionRowDAO(insert_text=f"/cmd{i}", label=f"/cmd{i}")
            for i in range(11)
        ]
        state: SlashSuggestionStateDAO = SlashSuggestionStateDAO(
            visible=True,
            rows=rows,
            highlighted_index=0,
        )

        rendered: str = SlashSuggestionMenu._render_lines(state=state)

        assert "/cmd0" in rendered
        assert "/cmd10" in rendered
        assert rendered.count("/cmd") == 11
