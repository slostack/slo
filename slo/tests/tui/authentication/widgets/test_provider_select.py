"""Tests for ``ProviderSelectWidget`` (02.b.5)."""
from __future__ import annotations

from typing import Optional

import pytest
from textual.app import App, ComposeResult

from src.auth.credential_dao import ProviderName
from src.tui.authentication.widgets.provider_select import ProviderSelectWidget


class _Harness(App):
    """Mount one widget for the test pilot."""

    def __init__(self) -> None:
        """Initialise message-capture slots used by the assertions."""
        super().__init__()
        self.received_provider: Optional[ProviderName] = None
        self.cancelled: bool = False

    def compose(self) -> ComposeResult:
        """Yield the single ``ProviderSelectWidget`` under test."""
        yield ProviderSelectWidget()

    def on_provider_select_widget_chosen(
        self, event: ProviderSelectWidget.Chosen
    ) -> None:
        """Record the chosen provider for assertion."""
        self.received_provider = event.provider

    def on_provider_select_widget_cancelled(
        self, event: ProviderSelectWidget.Cancelled
    ) -> None:
        """Record that Cancel was clicked."""
        self.cancelled = True


class TestProviderSelectWidget:
    """Provider-select emits the right ``Chosen`` / ``Cancelled``."""

    @pytest.mark.asyncio
    async def test_default_continue_emits_anthropic(self) -> None:
        """Continue with default radio → ANTHROPIC."""
        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()

        assert app.received_provider is ProviderName.ANTHROPIC

    @pytest.mark.asyncio
    async def test_selecting_openai_emits_openai(self) -> None:
        """Second radio (index 1) → OPENAI."""
        from textual.widgets import RadioButton, RadioSet

        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            radio_set = app.query_one("#provider-radio", RadioSet)
            buttons = list(radio_set.query(RadioButton))
            await pilot.click(buttons[1])
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()

        assert app.received_provider is ProviderName.OPENAI

    @pytest.mark.asyncio
    async def test_selecting_kimi_for_coding_emits_kimi_for_coding(self) -> None:
        """Third radio (index 2) → KIMI_FOR_CODING."""
        from textual.widgets import RadioButton, RadioSet

        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            radio_set = app.query_one("#provider-radio", RadioSet)
            buttons = list(radio_set.query(RadioButton))
            await pilot.click(buttons[2])
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()

        assert app.received_provider is ProviderName.KIMI_FOR_CODING

    @pytest.mark.asyncio
    async def test_cancel_emits_cancelled(self) -> None:
        """Cancel button fires the Cancelled message."""
        app: _Harness = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#provider-cancel")
            await pilot.pause()

        assert app.cancelled is True
