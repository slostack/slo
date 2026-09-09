"""Tests for typed browser/device ``OAuthStatusWidget`` presentations."""

from __future__ import annotations

from typing import Optional

import pytest
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Input, Static

from src.auth.credential_dao import ProviderName
from src.auth.oauth_flow import AuthorizationPresentationDAO
from src.auth.oauth_provider import DeviceAuthorizationPresentationDAO, OAuthLoginMethod
from src.tui.authentication.widgets.oauth_status import (
    AuthorizationResponseSubmitted,
    OAuthStatusWidget,
)


class _Harness(App):
    """Mount one status widget and retain its emitted opaque response."""

    def __init__(self, *, login_method: OAuthLoginMethod) -> None:
        """Capture the interaction type under test."""
        super().__init__()
        self._login_method: OAuthLoginMethod = login_method
        self.response: Optional[str] = None
        self.back_requested: bool = False
        self.cancelled: bool = False

    def compose(self) -> ComposeResult:
        """Yield a single status widget under the auth modal body for the injected interaction."""
        with Container(id="auth-modal-body"):
            yield OAuthStatusWidget(provider=ProviderName.OPENAI, login_method=self._login_method)

    def on_authorization_response_submitted(self, event: AuthorizationResponseSubmitted) -> None:
        """Record opaque text without parsing it."""
        self.response = event.authorization_response

    def on_oauth_status_widget_back_requested(self, event: OAuthStatusWidget.BackRequested) -> None:
        """Record that Back was requested."""
        self.back_requested = True

    def on_oauth_status_widget_cancelled(self, event: OAuthStatusWidget.Cancelled) -> None:
        """Record that Cancel was clicked."""
        self.cancelled = True


class TestOAuthStatusWidget:
    """Browser and device presentations remain passive and safe."""

    @pytest.mark.asyncio
    async def test_browser_presentation_renders_url_redirect_and_clears_opaque_input(self) -> None:
        """Browser instructions render literal text and clear after submit."""
        app: _Harness = _Harness(login_method=OAuthLoginMethod.BROWSER_AUTHORIZATION)
        authorization_url: str = "https://example.invalid/authorize?" + "x" * 300
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            widget: OAuthStatusWidget = app.query_one(OAuthStatusWidget)
            widget.set_browser_presentation(
                presentation=AuthorizationPresentationDAO(
                    authorize_url=authorization_url,
                    redirect_uri="http://localhost:1455/auth/callback",
                    instructions="unused",
                )
            )
            response_input: Input = app.query_one("#oauth-response-input", Input)
            response_input.value = "opaque-response"
            widget._submit_authorization_response()
            await pilot.pause()

            url: Static = app.query_one("#oauth-url", Static)
            redirect: Static = app.query_one("#oauth-redirect", Static)
            assert str(url.content) == authorization_url
            assert str(redirect.content) == "http://localhost:1455/auth/callback"
            assert "markup=False" not in str(url.content)
            assert "markup=False" not in str(redirect.content)
            assert response_input.value == ""
            assert "state" not in str(app.query_one("#oauth-response-instruction", Static).content).lower()

        assert app.response == "opaque-response"

    @pytest.mark.asyncio
    async def test_browser_presentation_paints_complete_no_whitespace_url_at_eighty_columns(self) -> None:
        """The painted screen retains every URL character at 80 columns without horizontal scrolling.

        Asserts the compositor's painted cells, not widget-local model state: the
        widget's own render_lines would report the full logical line even if the
        stylesheet clipped, scrolled, or occluded it.
        """
        app: _Harness = _Harness(login_method=OAuthLoginMethod.BROWSER_AUTHORIZATION)
        authorization_url: str = "https://example.invalid/authorize?" + "x" * 300
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            widget: OAuthStatusWidget = app.query_one(OAuthStatusWidget)
            widget.set_browser_presentation(
                presentation=AuthorizationPresentationDAO(
                    authorize_url=authorization_url,
                    redirect_uri="http://localhost:1455/auth/callback",
                    instructions="unused",
                )
            )
            await pilot.pause()

            url: Static = app.query_one("#oauth-url", Static)
            url_region = url.region
            painted_cells: str = "\n".join(
                app.screen._compositor.render_strips()[line].text
                for line in range(url_region.y, url_region.y + url_region.height)
            )
            painted_url: str = "".join(painted_cells.split())

            assert authorization_url in painted_url
            assert url.scroll_offset.x == 0

    @pytest.mark.asyncio
    async def test_callback_unavailable_keeps_browser_input_enabled(self) -> None:
        """The callback deadline downgrade is status-only, not a browser-flow failure."""
        app: _Harness = _Harness(login_method=OAuthLoginMethod.BROWSER_AUTHORIZATION)
        async with app.run_test() as pilot:
            await pilot.pause()
            widget: OAuthStatusWidget = app.query_one(OAuthStatusWidget)
            widget.set_callback_unavailable()
            await pilot.pause()
            status: str = str(app.query_one("#oauth-status", Static).content)
            response_input: Input = app.query_one("#oauth-response-input", Input)

        assert status == "Local browser did not respond. Paste your authorization response below."
        assert response_input.disabled is False

    @pytest.mark.asyncio
    async def test_device_presentation_renders_url_code_and_hides_redirect_submit(self) -> None:
        """Device flows show only their verification instructions and passive status."""
        app: _Harness = _Harness(login_method=OAuthLoginMethod.DEVICE_AUTHORIZATION)
        async with app.run_test() as pilot:
            await pilot.pause()
            widget: OAuthStatusWidget = app.query_one(OAuthStatusWidget)
            widget.set_device_presentation(
                presentation=DeviceAuthorizationPresentationDAO(
                    verification_uri="https://example.invalid/device",
                    user_code="DUMMY-ONLY",
                    expires_in_seconds=900,
                )
            )
            await pilot.pause()
            assert str(app.query_one("#oauth-url", Static).content) == "https://example.invalid/device"
            assert str(app.query_one("#oauth-redirect", Static).content) == "DUMMY-ONLY"
            assert app.query_one("#oauth-response-input", Input).display is False
            assert app.query_one("#oauth-submit-response").disabled is True

    @pytest.mark.asyncio
    async def test_second_submit_has_no_widget_retained_value(self) -> None:
        """Every submit posts then clears, leaving duplicate handling to the screen queue owner."""
        app: _Harness = _Harness(login_method=OAuthLoginMethod.BROWSER_AUTHORIZATION)
        async with app.run_test() as pilot:
            await pilot.pause()
            response_input: Input = app.query_one("#oauth-response-input", Input)
            response_input.value = "first-response"
            app.query_one(OAuthStatusWidget)._submit_authorization_response()
            await pilot.pause()

        assert app.response == "first-response"

    @pytest.mark.asyncio
    async def test_back_and_cancel_emit_their_messages(self) -> None:
        """Persistent navigation controls remain available on browser status."""
        app: _Harness = _Harness(login_method=OAuthLoginMethod.BROWSER_AUTHORIZATION)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#oauth-back")
            await pilot.click("#oauth-cancel")
            await pilot.pause()

        assert app.back_requested is True
        assert app.cancelled is True
