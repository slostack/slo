"""Painted-output tests for clickable authorization links in ``OAuthStatusWidget``.

These tests read the compositor's painted strips so they prove what a terminal
receives: the full wrapped URL text and segments whose hyperlink target (OSC 8)
is the exact URL. Dummy ``example.invalid`` URLs only; no secret-bearing values.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.strip import Strip

import src.tui.authentication as authentication_package
from src.auth.credential_dao import ProviderName
from src.auth.oauth_flow import AuthorizationPresentationDAO
from src.auth.oauth_provider import DeviceAuthorizationPresentationDAO, OAuthLoginMethod
from src.tui.authentication.widgets.oauth_status import OAuthStatusWidget
from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME
from tests.tui.authentication._painted_output import painted_link_targets, painted_text, painted_widget_strips

_AUTH_SCREEN_TCSS: Path = Path(authentication_package.__file__).parent / "auth_screen.tcss"
_BROWSER_URL: str = "https://example.invalid/authorize?scope=[dummy]&" + "x" * 300
_DEVICE_URL: str = "https://example.invalid/codex/device"
_REDIRECT_URI: str = "http://localhost:1455/auth/callback"


class _Harness(App):
    """Mount one status widget with the modal stylesheet and record requested URL opens."""

    CSS_PATH = str(_AUTH_SCREEN_TCSS)

    def __init__(
        self,
        *,
        login_method: OAuthLoginMethod,
        open_url_error: Exception | None = None,
        theme_name: str = SLO_DARK_THEME.name,
    ) -> None:
        """Keep the interaction type, an optional open-URL failure, and the Slo theme to paint with.

        Args:
            login_method (OAuthLoginMethod): Browser or device interaction to mount.
            open_url_error (Exception | None, optional): Raised by open_url when set. Defaults to None.
            theme_name (str, optional): Registered Slo theme to apply. Defaults to slo-dark.
        """
        super().__init__()
        self.register_theme(SLO_DEFAULT_THEME)
        self.register_theme(SLO_DARK_THEME)
        self.theme = theme_name
        self._login_method: OAuthLoginMethod = login_method
        self._open_url_error: Exception | None = open_url_error
        self.opened_urls: list[str] = []

    def compose(self) -> ComposeResult:
        """Yield the status widget inside the modal body container the stylesheet targets."""
        with Vertical(id="auth-modal-body"):
            yield OAuthStatusWidget(provider=ProviderName.OPENAI, login_method=self._login_method)

    def open_url(self, url: str, *, new_tab: bool = True) -> None:
        """Record the URL instead of launching a browser, or raise the injected failure.

        Args:
            url (str): URL the link asked the app to open.
            new_tab (bool, optional): Unused Textual flag. Defaults to True.
        """
        if self._open_url_error is not None:
            raise self._open_url_error
        self.opened_urls.append(url)


def _browser_presentation() -> AuthorizationPresentationDAO:
    """Return dummy-only browser instructions with a long, bracket-bearing URL.

    Returns:
        AuthorizationPresentationDAO: Presentation whose URL contains ``[dummy]``, which Textual
            would parse as markup, and 300 characters without whitespace.
    """
    return AuthorizationPresentationDAO(
        authorize_url=_BROWSER_URL,
        redirect_uri=_REDIRECT_URI,
        instructions="unused",
    )


class TestAuthorizationLinkPainting:
    """Browser and device presentations paint one clickable, wrapped link."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("theme_name", [SLO_DARK_THEME.name, SLO_DEFAULT_THEME.name])
    async def test_browser_presentation_paints_link_targeting_authorization_url(
        self, theme_name: str
    ) -> None:
        """In both Slo themes the full URL paints literally, wraps at 80 columns, and every link targets it.

        Args:
            theme_name (str): Slo theme applied before painting.
        """
        app: _Harness = _Harness(login_method=OAuthLoginMethod.BROWSER_AUTHORIZATION, theme_name=theme_name)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.query_one(OAuthStatusWidget).set_browser_presentation(presentation=_browser_presentation())
            await pilot.pause()

            url_strips: list[Strip] = painted_widget_strips(app=app, widget=app.query_one("#oauth-url"))
            redirect_strips: list[Strip] = painted_widget_strips(
                app=app, widget=app.query_one("#oauth-redirect")
            )

            assert _BROWSER_URL in painted_text(strips=url_strips)
            assert len(url_strips) > 1
            assert painted_link_targets(strips=url_strips) == {_BROWSER_URL}
            assert painted_link_targets(strips=redirect_strips) == set()

    @pytest.mark.asyncio
    async def test_device_presentation_paints_link_targeting_verification_url(self) -> None:
        """The device verification URL paints as a link through the same rendering unit."""
        app: _Harness = _Harness(login_method=OAuthLoginMethod.DEVICE_AUTHORIZATION)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.query_one(OAuthStatusWidget).set_device_presentation(
                presentation=DeviceAuthorizationPresentationDAO(
                    verification_uri=_DEVICE_URL,
                    user_code="DUMMY-CODE",
                    expires_in_seconds=900,
                )
            )
            await pilot.pause()

            url_strips: list[Strip] = painted_widget_strips(app=app, widget=app.query_one("#oauth-url"))

            assert _DEVICE_URL in painted_text(strips=url_strips)
            assert painted_link_targets(strips=url_strips) == {_DEVICE_URL}


class TestAuthorizationLinkClick:
    """Clicking the painted link asks the app to open the exact URL, best effort."""

    @pytest.mark.asyncio
    async def test_click_when_presented_opens_exact_url(self) -> None:
        """A click on the painted URL passes the exact authorization URL to app.open_url."""
        app: _Harness = _Harness(login_method=OAuthLoginMethod.BROWSER_AUTHORIZATION)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.query_one(OAuthStatusWidget).set_browser_presentation(presentation=_browser_presentation())
            await pilot.pause()
            await pilot.click("#oauth-url")
            await pilot.pause()

        assert app.opened_urls == [_BROWSER_URL]

    @pytest.mark.asyncio
    async def test_enter_when_link_focused_opens_exact_url(self) -> None:
        """Pressing Enter on the focused link (Link's inherited binding) passes the exact URL to app.open_url."""
        app: _Harness = _Harness(login_method=OAuthLoginMethod.BROWSER_AUTHORIZATION)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.query_one(OAuthStatusWidget).set_browser_presentation(presentation=_browser_presentation())
            await pilot.pause()
            app.query_one("#oauth-url").focus()
            await pilot.press("enter")
            await pilot.pause()

        assert app.opened_urls == [_BROWSER_URL]

    @pytest.mark.asyncio
    async def test_click_when_open_url_raises_keeps_url_painted(self) -> None:
        """A failing browser launch never escapes into Textual and never hides the URL."""
        app: _Harness = _Harness(
            login_method=OAuthLoginMethod.BROWSER_AUTHORIZATION,
            open_url_error=RuntimeError("no browser"),
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.query_one(OAuthStatusWidget).set_browser_presentation(presentation=_browser_presentation())
            await pilot.pause()
            await pilot.click("#oauth-url")
            await pilot.pause()

            url_strips: list[Strip] = painted_widget_strips(app=app, widget=app.query_one("#oauth-url"))

            assert _BROWSER_URL in painted_text(strips=url_strips)
            assert app.return_code is None

    @pytest.mark.asyncio
    async def test_click_when_not_yet_presented_opens_nothing(self) -> None:
        """Before any presentation arrives the empty link is inert."""
        app: _Harness = _Harness(login_method=OAuthLoginMethod.BROWSER_AUTHORIZATION)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.click("#oauth-url")
            await pilot.pause()

        assert app.opened_urls == []
