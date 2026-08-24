"""Tests for ``ApiKeyInputWidget`` (02.b.5)."""
from __future__ import annotations

from typing import Optional

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from src.auth.credential_dao import ProviderName
from src.tui.authentication.widgets.api_key_input import ApiKeyInputWidget


class _Harness(App):
    """Mount the widget and record what it emits."""

    def __init__(self) -> None:
        """Initialise message-capture slots used by the assertions."""
        super().__init__()
        self.received_key: Optional[str] = None
        self.back_requested: bool = False
        self.cancelled: bool = False

    def compose(self) -> ComposeResult:
        """Yield the single ``ApiKeyInputWidget`` under test."""
        yield ApiKeyInputWidget(provider=ProviderName.OPENAI)

    def on_api_key_input_widget_submitted(
        self, event: ApiKeyInputWidget.Submitted
    ) -> None:
        """Record the submitted key for assertion."""
        self.received_key = event.api_key

    def on_api_key_input_widget_back_requested(
        self, event: ApiKeyInputWidget.BackRequested
    ) -> None:
        """Record that Back was requested."""
        self.back_requested = True

    def on_api_key_input_widget_cancelled(
        self, event: ApiKeyInputWidget.Cancelled
    ) -> None:
        """Record that Cancel was clicked."""
        self.cancelled = True


class TestApiKeyInputWidget:
    """Save with non-empty key emits ``Submitted``; empty shows error."""

    @pytest.mark.asyncio
    async def test_save_with_non_empty_key_emits_submitted(self) -> None:
        """Typed key → Submitted carries the value."""
        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            pilot.app.query_one("#api-key-input", Input).value = "sk-test"
            await pilot.click("#api-key-save")
            await pilot.pause()

        assert app.received_key == "sk-test"

    @pytest.mark.asyncio
    async def test_save_with_empty_key_shows_inline_error(self) -> None:
        """Empty input → error label populated, no Submitted."""
        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#api-key-save")
            await pilot.pause()

            error_label: str = str(
                pilot.app.query_one("#api-key-error", Static).content
            )

        assert "required" in error_label.lower()
        assert app.received_key is None

    @pytest.mark.asyncio
    async def test_back_emits_back_requested(self) -> None:
        """Back button fires the BackRequested message."""
        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#api-key-back")
            await pilot.pause()

        assert app.back_requested is True

    @pytest.mark.asyncio
    async def test_cancel_emits_cancelled(self) -> None:
        """Cancel button fires the Cancelled message."""
        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#api-key-cancel")
            await pilot.pause()

        assert app.cancelled is True
