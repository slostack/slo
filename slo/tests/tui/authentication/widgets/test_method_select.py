"""Tests for ``MethodSelectWidget`` (02.b.5)."""

from __future__ import annotations

from typing import Optional

import pytest
from textual.app import App, ComposeResult

from src.auth.credential_dao import AuthType, ProviderName
from src.tui.authentication.widgets.method_select import MethodSelectWidget


class _Harness(App):
    """Mount one ``MethodSelectWidget`` keyed to ANTHROPIC for testing."""

    def __init__(self) -> None:
        """Initialise message-capture slots used by the assertions."""
        super().__init__()
        self.received_method: Optional[AuthType] = None
        self.back_requested: bool = False
        self.cancelled: bool = False

    def compose(self) -> ComposeResult:
        """Yield a ``MethodSelectWidget`` keyed to Anthropic."""
        yield MethodSelectWidget(provider=ProviderName.ANTHROPIC)

    def on_method_select_widget_chosen(self, event: MethodSelectWidget.Chosen) -> None:
        """Record the chosen ``AuthType`` for assertion."""
        self.received_method = event.method

    def on_method_select_widget_back_requested(self, event: MethodSelectWidget.BackRequested) -> None:
        """Record that Back was requested."""
        self.back_requested = True

    def on_method_select_widget_cancelled(self, event: MethodSelectWidget.Cancelled) -> None:
        """Record that Cancel was clicked."""
        self.cancelled = True


class TestMethodSelectWidget:
    """``Chosen`` carries the right ``AuthType``; back/cancel fire too."""

    @pytest.mark.asyncio
    async def test_default_continue_emits_oauth(self) -> None:
        """Default radio is OAuth → Continue emits OAuth."""
        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#method-continue")
            await pilot.pause()

        assert app.received_method is AuthType.OAUTH

    @pytest.mark.asyncio
    async def test_selecting_api_key_then_continue_emits_api_key(self) -> None:
        """Switching to the api-key radio updates ``Chosen``."""
        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#method-api-key")
            await pilot.pause()
            await pilot.click("#method-continue")
            await pilot.pause()

        assert app.received_method is AuthType.API_KEY

    @pytest.mark.asyncio
    async def test_back_emits_back_requested(self) -> None:
        """Back button fires the BackRequested message."""
        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#method-back")
            await pilot.pause()

        assert app.back_requested is True

    @pytest.mark.asyncio
    async def test_cancel_emits_cancelled(self) -> None:
        """Cancel button fires the Cancelled message."""
        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#method-cancel")
            await pilot.pause()

        assert app.cancelled is True
