"""Tests for ``AuthenticationScreen`` (02.b.5)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from textual.app import App
from textual.widgets import Input

from src.auth.credential_dao import (
    AuthType,
    CredentialDAO,
    ProviderName,
)
from src.auth.credential_store import CredentialStore
from src.auth.oauth_errors import OAuthCallbackPortInUseError, OAuthTimeoutError
from src.auth.oauth_flow import OAuthFlow
from src.auth.oauth_provider import FauxOAuthProvider
from src.tui.authentication import AuthenticationScreen
from src.tui.authentication.widgets.api_key_input import ApiKeyInputWidget
from src.tui.authentication.widgets.method_select import MethodSelectWidget
from src.tui.authentication.widgets.oauth_status import OAuthStatusWidget
from src.tui.authentication.widgets.provider_select import ProviderSelectWidget
from src.tui.authentication.widgets.success_widget import SuccessWidget


def _build_store(tmp_path: Path) -> CredentialStore:
    """Return a tmp-rooted store for the test.

    Args:
        tmp_path (Path): pytest tmp_path fixture.

    Returns:
        CredentialStore: Store rooted at ``<tmp_path>/global/authentication.json``.
    """
    return CredentialStore(path=tmp_path / "global" / "authentication.json")


class _Harness(App):
    """Mount ``AuthenticationScreen`` and capture the dismissal value."""

    def __init__(
        self,
        *,
        store: CredentialStore,
        oauth_factory: Callable[..., OAuthFlow],
    ) -> None:
        """Wire the harness with injected dependencies.

        Args:
            store (CredentialStore): Store passed through to the modal.
            oauth_factory (Callable[..., OAuthFlow]): Factory for OAuth
                flows; production calls it with ``provider=...`` keyword.
        """
        super().__init__()
        self._store: CredentialStore = store
        self._oauth_factory: Callable[..., OAuthFlow] = oauth_factory
        self.dismissed_with: Optional[CredentialDAO] = None
        self.completed: asyncio.Event = asyncio.Event()

    def on_mount(self) -> None:
        """Push ``AuthenticationScreen`` and register the dismiss callback."""
        self.push_screen(
            AuthenticationScreen(store=self._store, oauth_factory=self._oauth_factory),
            callback=self._on_dismiss,
        )

    def _on_dismiss(self, value: Optional[CredentialDAO]) -> None:
        """Record the dismissal value and unblock the awaiting test.

        Args:
            value (Optional[CredentialDAO]): Whatever the modal dismissed with.
        """
        self.dismissed_with = value
        self.completed.set()


def _faux_factory(*, provider: ProviderName) -> OAuthFlow:
    """Build a no-op ``OAuthFlow`` for tests that never run OAuth.

    Args:
        provider (ProviderName): Ignored; included for shape parity.

    Returns:
        OAuthFlow: Wired around ``FauxOAuthProvider``.
    """
    return OAuthFlow(provider=FauxOAuthProvider(provider=provider))


class TestAuthenticationScreenApiKeyPath:
    """End-to-end API-key flow persists and dismisses with the credential."""

    @pytest.mark.asyncio
    async def test_api_key_path_persists_and_dismisses(self, tmp_path: Path) -> None:
        """Provider → method → api_key → save → close → dismiss(cred)."""
        store: CredentialStore = _build_store(tmp_path)
        harness: _Harness = _Harness(store=store, oauth_factory=_faux_factory)

        async with harness.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()
            await pilot.click("#method-api-key")
            await pilot.pause()
            await pilot.click("#method-continue")
            await pilot.pause()
            pilot.app.screen.query_one(
                ApiKeyInputWidget,
            ).query_one("#api-key-input", Input).value = "sk-test"
            await pilot.click("#api-key-save")
            await pilot.pause()
            await pilot.click("#success-close")
            await harness.completed.wait()

        assert harness.dismissed_with is not None
        envelope = store.load()
        assert ProviderName.ANTHROPIC in envelope.providers
        assert envelope.providers[ProviderName.ANTHROPIC].access_token == "sk-test"


class TestAuthenticationScreenOAuthFailure:
    """OAuth failure renders inline error and keeps the modal open."""

    @pytest.mark.asyncio
    async def test_oauth_timeout_renders_error_and_does_not_dismiss(self, tmp_path: Path) -> None:
        """``OAuthTimeoutError`` → OAuthStatusWidget shows error; modal stays."""
        store: CredentialStore = _build_store(tmp_path)

        def _factory(*, provider: ProviderName) -> OAuthFlow:
            """Return an OAuth flow that fails with ``OAuthTimeoutError``."""
            flow = MagicMock(spec=OAuthFlow)
            flow.start = AsyncMock(side_effect=OAuthTimeoutError())
            return flow

        harness: _Harness = _Harness(store=store, oauth_factory=_factory)

        async with harness.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()
            await pilot.click("#method-continue")  # OAuth is default
            await pilot.pause()
            await asyncio.sleep(0.05)
            await pilot.pause()
            status: OAuthStatusWidget = pilot.app.screen.query_one(OAuthStatusWidget)
            from textual.widgets import Static

            error_label: str = str(status.query_one("#oauth-error", Static).content)
            assert "timed out" in error_label.lower()

        assert harness.dismissed_with is None


class TestAuthenticationScreenOAuthPortCollision:
    """Fixed-port bind collisions render an inline actionable message."""

    @pytest.mark.asyncio
    async def test_oauth_callback_port_in_use_renders_error(self, tmp_path: Path) -> None:
        """``OAuthCallbackPortInUseError`` → actionable inline auth-screen copy."""
        store: CredentialStore = _build_store(tmp_path)

        def _factory(*, provider: ProviderName) -> OAuthFlow:
            flow = MagicMock(spec=OAuthFlow)
            flow.start = AsyncMock(side_effect=OAuthCallbackPortInUseError(port=53692))
            return flow

        harness: _Harness = _Harness(store=store, oauth_factory=_factory)

        async with harness.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()
            await pilot.click("#method-continue")
            await pilot.pause()
            await asyncio.sleep(0.05)
            await pilot.pause()
            status: OAuthStatusWidget = pilot.app.screen.query_one(OAuthStatusWidget)
            from textual.widgets import Static

            error_label: str = str(status.query_one("#oauth-error", Static).content)
            assert "could not bind the local callback port" in error_label.lower()


class TestAuthenticationScreenCancel:
    """Esc dismisses with ``None`` and cleans up the OAuth task."""

    @pytest.mark.asyncio
    async def test_escape_dismisses_with_none(self, tmp_path: Path) -> None:
        """Pressing Esc from provider step → dismiss(None)."""
        store: CredentialStore = _build_store(tmp_path)
        harness: _Harness = _Harness(store=store, oauth_factory=_faux_factory)

        async with harness.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await harness.completed.wait()

        assert harness.dismissed_with is None
        assert store.load().providers == {}


class TestAuthenticationScreenBackNavigation:
    """Back from method → provider re-renders ProviderSelectWidget."""

    @pytest.mark.asyncio
    async def test_back_from_method_returns_to_provider(self, tmp_path: Path) -> None:
        """Provider → method → Back → provider."""
        store: CredentialStore = _build_store(tmp_path)
        harness: _Harness = _Harness(store=store, oauth_factory=_faux_factory)

        async with harness.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()
            await pilot.click("#method-back")
            await pilot.pause()

            assert pilot.app.screen.query_one(ProviderSelectWidget) is not None


class TestAuthenticationScreenOAuthCancelPath:
    """Back during in-flight OAuth cancels without persisting or mounting Success."""

    @pytest.mark.asyncio
    async def test_oauth_cancelled_path_does_nothing(self, tmp_path: Path) -> None:
        """Start OAuth, click Back → no SuccessWidget mounted, no row persisted."""
        store: CredentialStore = _build_store(tmp_path)

        async def _never_returns() -> CredentialDAO:
            """Stand in for an OAuth flow that never completes."""
            await asyncio.Event().wait()
            raise AssertionError("unreachable")  # pragma: no cover

        def _factory(*, provider: ProviderName) -> OAuthFlow:
            """Return an OAuth flow whose ``start`` hangs forever."""
            flow = MagicMock(spec=OAuthFlow)
            flow.start = AsyncMock(side_effect=_never_returns)
            return flow

        harness: _Harness = _Harness(store=store, oauth_factory=_factory)

        async with harness.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()
            await pilot.click("#method-continue")  # OAuth is default
            await pilot.pause()
            await pilot.click("#oauth-back")
            await pilot.pause()

            success_widgets: list[SuccessWidget] = list(
                pilot.app.screen.query(SuccessWidget),
            )
            assert success_widgets == []

        assert store.load().providers == {}


class TestAuthenticationScreenOAuthSuccessPath:
    """OAuth success persists the credential and dismisses with the DAO."""

    @pytest.mark.asyncio
    async def test_oauth_success_path_persists_and_dismisses_with_credential(self, tmp_path: Path) -> None:
        """Inject a faux flow returning a known DAO → dismiss callback receives it."""
        store: CredentialStore = _build_store(tmp_path)
        expected_credential: CredentialDAO = CredentialDAO(
            provider=ProviderName.ANTHROPIC,
            auth_type=AuthType.OAUTH,
            access_token="oauth-success-token",
            refresh_token="oauth-refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=3600),
            subject="user@example.com",
        )

        def _factory(*, provider: ProviderName) -> OAuthFlow:
            """Return an OAuth flow whose ``start`` resolves to ``expected_credential``."""
            flow = MagicMock(spec=OAuthFlow)
            flow.start = AsyncMock(return_value=expected_credential)
            return flow

        harness: _Harness = _Harness(store=store, oauth_factory=_factory)

        async with harness.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()
            await pilot.click("#method-continue")  # OAuth is default
            await pilot.pause()
            await asyncio.sleep(0.05)
            await pilot.pause()
            await pilot.click("#success-close")
            await harness.completed.wait()

        assert harness.dismissed_with is not None
        assert harness.dismissed_with.access_token == "oauth-success-token"
        envelope = store.load()
        assert ProviderName.ANTHROPIC in envelope.providers
        assert envelope.providers[ProviderName.ANTHROPIC].access_token == "oauth-success-token"


class TestAuthenticationScreenKimiForCodingPath:
    """Kimi For Coding skips MethodSelectWidget and goes directly to ApiKeyInputWidget."""

    @pytest.mark.asyncio
    async def test_kimi_for_coding_skips_method_select_and_shows_api_key(self, tmp_path: Path) -> None:
        """Selecting Kimi For Coding → Continue → ApiKeyInputWidget appears immediately."""
        from textual.widgets import RadioButton, RadioSet

        store: CredentialStore = _build_store(tmp_path)
        harness: _Harness = _Harness(store=store, oauth_factory=_faux_factory)

        async with harness.run_test() as pilot:
            await pilot.pause()
            radio_set = pilot.app.screen.query_one("#provider-radio", RadioSet)
            buttons = list(radio_set.query(RadioButton))
            await pilot.click(buttons[2])  # Kimi For Coding is the third radio (index 2)
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()

            assert pilot.app.screen.query_one(ApiKeyInputWidget) is not None
            method_widgets = list(pilot.app.screen.query(MethodSelectWidget))
            assert method_widgets == []

    @pytest.mark.asyncio
    async def test_kimi_for_coding_api_key_path_persists_and_dismisses(self, tmp_path: Path) -> None:
        """Kimi For Coding → api_key → save → close → dismiss with persisted KIMI_FOR_CODING cred."""
        from textual.widgets import RadioButton, RadioSet

        store: CredentialStore = _build_store(tmp_path)
        harness: _Harness = _Harness(store=store, oauth_factory=_faux_factory)

        async with harness.run_test() as pilot:
            await pilot.pause()
            radio_set = pilot.app.screen.query_one("#provider-radio", RadioSet)
            buttons = list(radio_set.query(RadioButton))
            await pilot.click(buttons[2])
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()
            pilot.app.screen.query_one(
                ApiKeyInputWidget,
            ).query_one("#api-key-input", Input).value = "sk-kimi-test"
            await pilot.click("#api-key-save")
            await pilot.pause()
            await pilot.click("#success-close")
            await harness.completed.wait()

        assert harness.dismissed_with is not None
        envelope = store.load()
        assert ProviderName.KIMI_FOR_CODING in envelope.providers
        assert envelope.providers[ProviderName.KIMI_FOR_CODING].access_token == "sk-kimi-test"

    @pytest.mark.asyncio
    async def test_kimi_for_coding_back_from_api_key_returns_to_provider_select(self, tmp_path: Path) -> None:
        """Kimi For Coding → api_key → Back → ProviderSelectWidget (not MethodSelectWidget)."""
        from textual.widgets import RadioButton, RadioSet

        store: CredentialStore = _build_store(tmp_path)
        harness: _Harness = _Harness(store=store, oauth_factory=_faux_factory)

        async with harness.run_test() as pilot:
            await pilot.pause()
            radio_set = pilot.app.screen.query_one("#provider-radio", RadioSet)
            buttons = list(radio_set.query(RadioButton))
            await pilot.click(buttons[2])
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()
            await pilot.click("#api-key-back")
            await pilot.pause()

            assert pilot.app.screen.query_one(ProviderSelectWidget) is not None
            method_widgets = list(pilot.app.screen.query(MethodSelectWidget))
            assert method_widgets == []
