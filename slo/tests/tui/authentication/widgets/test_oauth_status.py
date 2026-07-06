"""Tests for ``OAuthStatusWidget`` (02.b.5)."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from src.auth.credential_dao import ProviderName
from src.tui.authentication.widgets.oauth_status import OAuthStatusWidget


class _Harness(App):
    """Mount the widget and record what it emits."""

    def __init__(self) -> None:
        """Initialise message-capture slots used by the assertions."""
        super().__init__()
        self.back_requested: bool = False
        self.cancelled: bool = False

    def compose(self) -> ComposeResult:
        """Yield a single ``OAuthStatusWidget`` keyed to OpenAI."""
        yield OAuthStatusWidget(provider=ProviderName.OPENAI)

    def on_oauth_status_widget_back_requested(
        self, event: OAuthStatusWidget.BackRequested
    ) -> None:
        """Record that Back was requested."""
        self.back_requested = True

    def on_oauth_status_widget_cancelled(
        self, event: OAuthStatusWidget.Cancelled
    ) -> None:
        """Record that Cancel was clicked."""
        self.cancelled = True


class TestOAuthStatusWidget:
    """``set_auth_url`` / ``set_error`` mutate visible state; buttons fire."""

    @pytest.mark.asyncio
    async def test_set_auth_url_updates_banner(self) -> None:
        """Setting the URL replaces the placeholder."""
        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            widget: OAuthStatusWidget = pilot.app.query_one(OAuthStatusWidget)
            widget.set_auth_url(url="https://example.com/auth?x=1")
            await pilot.pause()

            url_label: str = str(
                pilot.app.query_one("#oauth-url", Static).renderable
            )

        assert "https://example.com/auth?x=1" in url_label

    @pytest.mark.asyncio
    async def test_set_error_populates_error_region(self) -> None:
        """Error message lands in the error region; status updates."""
        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            widget: OAuthStatusWidget = pilot.app.query_one(OAuthStatusWidget)
            widget.set_error(message="Sign-in timed out.")
            await pilot.pause()

            error_label: str = str(
                pilot.app.query_one("#oauth-error", Static).renderable
            )
            status_label: str = str(
                pilot.app.query_one("#oauth-status", Static).renderable
            )

        assert "timed out" in error_label.lower()
        assert "failed" in status_label.lower()

    @pytest.mark.asyncio
    async def test_back_button_fires_back_requested(self) -> None:
        """Back button → BackRequested."""
        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#oauth-back")
            await pilot.pause()

        assert app.back_requested is True

    @pytest.mark.asyncio
    async def test_cancel_button_fires_cancelled(self) -> None:
        """Cancel button → Cancelled."""
        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#oauth-cancel")
            await pilot.pause()

        assert app.cancelled is True
