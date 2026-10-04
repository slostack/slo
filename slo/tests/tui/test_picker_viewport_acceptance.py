"""Offline painted acceptance for F86-31 viewport counts (synthetic rows)."""

from unittest.mock import patch

import httpx
import pytest
from textual.app import App, ComposeResult

from src.tui.slash_suggestion_engine import SlashSuggestionRowDAO, SlashSuggestionStateDAO
from src.tui.widgets.slash_suggestion_menu import SlashSuggestionMenu


class PickerApp(App[None]):
    """Mount the production menu without sessions, credentials or persistence."""

    def compose(self) -> ComposeResult:
        """Yield the production viewport for pilot-driven paint assertions."""
        yield SlashSuggestionMenu()


async def test_footer_counts_painted_rows_after_resize_and_wrap() -> None:
    """Report visible rows, not candidate count, while retaining selected identity."""
    state = SlashSuggestionStateDAO(
        visible=True,
        rows=[SlashSuggestionRowDAO(insert_text=f"route-{i:02}", label=f"route-{i:02}") for i in range(25)],
        total_matches=1000,
    )
    with (
        patch.object(httpx.HTTPTransport, "handle_request", side_effect=AssertionError("network forbidden")),
        patch.object(
            httpx.AsyncHTTPTransport, "handle_async_request", side_effect=AssertionError("network forbidden")
        ),
    ):
        app = PickerApp()
        async with app.run_test(size=(80, 24)) as pilot:
            menu = app.query_one(SlashSuggestionMenu)
            menu.update_state(state=state)
            await pilot.pause()
            painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "Showing 8 of 1000" in painted
            await pilot.resize_terminal(width=60, height=15)
            menu.update_state(state=state.with_highlight_delta(delta=-1))
            await pilot.pause()
            painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "Showing 3 of 1000" in painted
            assert "› route-24" in painted and "route-00" not in painted
            menu.update_state(state=state)
            await pilot.pause()
            painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "› route-00" in painted and "route-24" not in painted


@pytest.mark.parametrize("row_count", [0, 1])
async def test_small_viewport_empty_and_single_candidate(row_count: int) -> None:
    """Paint empty guidance or the exact uncapped count without selectable placeholders.

    Args:
        row_count (int): Synthetic catalog cardinality at the renderer boundary.
    """
    state = SlashSuggestionStateDAO(
        visible=True,
        rows=[SlashSuggestionRowDAO(insert_text="route", label="route")] * row_count,
        total_matches=row_count,
    )
    with (
        patch.object(httpx.HTTPTransport, "handle_request", side_effect=AssertionError("network forbidden")),
        patch.object(
            httpx.AsyncHTTPTransport, "handle_async_request", side_effect=AssertionError("network forbidden")
        ),
    ):
        app = PickerApp()
        async with app.run_test(size=(60, 15)) as pilot:
            menu = app.query_one(SlashSuggestionMenu)
            menu.update_state(state=state)
            await pilot.pause()
            painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            if row_count:
                assert "Showing 1 of 1" in painted
                assert "› route" in painted
            else:
                assert "No models match" in painted and "/model refresh" in painted
                assert state.with_highlight_delta(delta=1).highlighted_row is None
                assert "Showing" not in painted
            menu.update_state(state=SlashSuggestionStateDAO())
            await pilot.pause()
            painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "Showing" not in painted and "No models match" not in painted
