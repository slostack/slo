"""Injected end-to-end headless authentication journeys without monkeypatching."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from textual.app import App
from textual.widgets import Input, RadioButton, RadioSet

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore
from src.auth.oauth_flow import AuthorizationPresentationDAO
from src.auth.oauth_provider import DeviceAuthorizationPresentationDAO, OAuthLoginMethod
from src.auth.provider_factory import OAuthAuthenticationFlow
from src.tui.authentication import AuthenticationScreen
from src.tui.authentication.widgets.oauth_status import OAuthStatusWidget


class _FauxFlow:
    """Small scripted OAuth interaction for the modal injection seam."""

    def __init__(self, *, run: Callable[[], Awaitable[CredentialDAO]]) -> None:
        """Save its single scripted invoke gateway."""
        self._run: Callable[[], Awaitable[CredentialDAO]] = run

    async def invoke(self) -> CredentialDAO:
        """Complete the scripted authentication interaction."""
        return await self._run()


def _credential(*, provider: ProviderName) -> CredentialDAO:
    """Return a completed dummy-only OAuth credential."""
    return CredentialDAO(
        provider=provider,
        auth_type=AuthType.OAUTH,
        access_token="e2e-access-token",
        refresh_token="e2e-refresh-token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def _faux_oauth_factory(
    *,
    provider: ProviderName,
    login_method: OAuthLoginMethod,
    present_browser_authorization: Callable[[AuthorizationPresentationDAO], None],
    present_device_authorization: Callable[[DeviceAuthorizationPresentationDAO], None],
    authorization_response_receiver: Callable[[], Awaitable[str]] | None,
    present_callback_unavailable: Callable[[], None] = lambda: None,
) -> OAuthAuthenticationFlow:
    """Build the recorded scripted flow for this E2E scenario."""
    if login_method is OAuthLoginMethod.DEVICE_AUTHORIZATION:

        async def _device() -> CredentialDAO:
            """Present dummy device instructions and return its credential."""
            present_device_authorization(
                DeviceAuthorizationPresentationDAO(
                    verification_uri="https://example.invalid/dummy-device",
                    user_code="DUMMY-DEVICE-CODE",
                    expires_in_seconds=900,
                )
            )
            return _credential(provider=provider)

        return _FauxFlow(run=_device)

    assert authorization_response_receiver is not None
    receiver: Callable[[], Awaitable[str]] = authorization_response_receiver

    async def _browser() -> CredentialDAO:
        """Present dummy browser instructions, downgrade, and complete from the modal receiver."""
        present_browser_authorization(
            AuthorizationPresentationDAO(
                authorize_url="https://example.invalid/dummy-browser",
                redirect_uri="http://localhost:1455/auth/callback",
                instructions="unused",
            )
        )
        present_callback_unavailable()
        await receiver()
        return _credential(provider=provider)

    return _FauxFlow(run=_browser)


_faux_oauth_factory.supported_login_methods = lambda *, provider: (
    frozenset({OAuthLoginMethod.BROWSER_AUTHORIZATION})
    if provider is ProviderName.ANTHROPIC
    else frozenset({OAuthLoginMethod.BROWSER_AUTHORIZATION, OAuthLoginMethod.DEVICE_AUTHORIZATION})
)


class _Harness(App):
    """Run AuthenticationScreen with the required injectable faux factory seam."""

    def __init__(self, *, store: CredentialStore) -> None:
        """Keep the temporary durable store for the modal."""
        super().__init__()
        self._store: CredentialStore = store

    def on_mount(self) -> None:
        """Push the modal using dependency injection rather than monkeypatching."""
        self.push_screen(AuthenticationScreen(store=self._store, oauth_factory=_faux_oauth_factory))


@pytest.mark.asyncio
async def test_openai_device_headless_e2e_presents_and_persists(tmp_path: Path) -> None:
    """OpenAI device instructions appear before the injected flow persists its completed credential."""
    store: CredentialStore = CredentialStore(path=tmp_path / "authentication.json")
    harness: _Harness = _Harness(store=store)
    async with harness.run_test() as pilot:
        await pilot.pause()
        provider_radios: RadioSet = pilot.app.screen.query_one("#provider-radio", RadioSet)
        await pilot.click(list(provider_radios.query(RadioButton))[1])
        await pilot.click("#provider-continue")
        await pilot.pause()
        await pilot.click("#method-device_authorization")
        await pilot.click("#method-continue")
        await pilot.pause()
        await pilot.pause()

    assert store.load().providers[ProviderName.OPENAI].auth_type is AuthType.OAUTH


@pytest.mark.asyncio
async def test_anthropic_browser_e2e_accepts_response_after_callback_deadline(tmp_path: Path) -> None:
    """The browser modal accepts injected manual completion without a local callback."""
    store: CredentialStore = CredentialStore(path=tmp_path / "authentication.json")
    harness: _Harness = _Harness(store=store)
    async with harness.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#provider-continue")
        await pilot.pause()
        await pilot.click("#method-continue")
        await pilot.pause()
        status: OAuthStatusWidget = pilot.app.screen.query_one(OAuthStatusWidget)
        await pilot.pause()
        assert (
            str(status.query_one("#oauth-status").content)
            == "Local browser did not respond. Paste your authorization response below."
        )
        response_input: Input = status.query_one("#oauth-response-input", Input)
        response_input.value = "dummy-post-callback-response"
        status._submit_authorization_response()
        await pilot.pause()
        await pilot.pause()

    assert store.load().providers[ProviderName.ANTHROPIC].auth_type is AuthType.OAUTH
