"""Tests for capability-driven ``MethodSelectWidget``."""

from __future__ import annotations

from typing import Optional

import pytest
from textual.app import App, ComposeResult
from textual.widgets import RadioButton

from src.auth.credential_dao import AuthType, ProviderName
from src.auth.oauth_provider import OAuthLoginMethod
from src.tui.authentication.widgets.method_select import MethodSelectWidget


class _Harness(App):
    """Mount a supplied method widget and record its selected method."""

    def __init__(self, *, login_methods: frozenset[OAuthLoginMethod]) -> None:
        """Store the injected capabilities for the mounted widget."""
        super().__init__()
        self._login_methods: frozenset[OAuthLoginMethod] = login_methods
        self.received_method: Optional[AuthType | OAuthLoginMethod] = None
        self.back_requested: bool = False
        self.cancelled: bool = False

    def compose(self) -> ComposeResult:
        """Yield a capability-configured selector without provider-specific labels."""
        yield MethodSelectWidget(
            provider=ProviderName.ANTHROPIC,
            login_methods=self._login_methods,
        )

    def on_method_select_widget_chosen(self, event: MethodSelectWidget.Chosen) -> None:
        """Record the chosen typed capability for assertion."""
        self.received_method = event.method

    def on_method_select_widget_back_requested(self, event: MethodSelectWidget.BackRequested) -> None:
        """Record that Back was requested."""
        self.back_requested = True

    def on_method_select_widget_cancelled(self, event: MethodSelectWidget.Cancelled) -> None:
        """Record that Cancel was clicked."""
        self.cancelled = True


class TestMethodSelectWidget:
    """The radios strictly mirror injected OAuth capabilities plus API key."""

    @pytest.mark.asyncio
    async def test_continue_when_browser_only_emits_browser_authorization(self) -> None:
        """A browser-only capability set defaults to browser authorization."""
        app: _Harness = _Harness(
            login_methods=frozenset({OAuthLoginMethod.BROWSER_AUTHORIZATION}),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            labels: list[str] = [str(button.label) for button in app.query(RadioButton)]
            await pilot.click("#method-continue")
            await pilot.pause()

        assert labels == ["Browser authorization", "Paste an API key"]
        assert app.received_method is OAuthLoginMethod.BROWSER_AUTHORIZATION

    @pytest.mark.asyncio
    async def test_continue_when_device_capable_emits_device_authorization(self) -> None:
        """A device-capable injected set renders the headless capability exactly once."""
        app: _Harness = _Harness(
            login_methods=frozenset(
                {
                    OAuthLoginMethod.BROWSER_AUTHORIZATION,
                    OAuthLoginMethod.DEVICE_AUTHORIZATION,
                }
            ),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            labels: list[str] = [str(button.label) for button in app.query(RadioButton)]
            await pilot.click("#method-device_authorization")
            await pilot.click("#method-continue")
            await pilot.pause()

        assert labels == [
            "Browser authorization",
            "Device authorization (headless)",
            "Paste an API key",
        ]
        assert app.received_method is OAuthLoginMethod.DEVICE_AUTHORIZATION

    @pytest.mark.asyncio
    async def test_continue_when_api_key_selected_emits_api_key(self) -> None:
        """API key remains a top-level persisted-method choice."""
        app: _Harness = _Harness(
            login_methods=frozenset({OAuthLoginMethod.BROWSER_AUTHORIZATION}),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#method-api-key")
            await pilot.click("#method-continue")
            await pilot.pause()

        assert app.received_method is AuthType.API_KEY

    @pytest.mark.asyncio
    async def test_back_and_cancel_emit_their_messages(self) -> None:
        """Navigation controls remain independent of capabilities."""
        app: _Harness = _Harness(
            login_methods=frozenset({OAuthLoginMethod.BROWSER_AUTHORIZATION}),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#method-back")
            await pilot.click("#method-cancel")
            await pilot.pause()

        assert app.back_requested is True
        assert app.cancelled is True
