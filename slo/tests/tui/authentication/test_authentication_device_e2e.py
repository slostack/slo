"""End-to-end OpenAI device authorization journey through real production components.

Drives the real ``AuthenticationScreen`` → real ``OAuthFlowFactory`` instance →
real ``DeviceAuthorizationFlow`` → real ``OpenAICodexOAuthProvider`` against a local
aiohttp server that returns OpenAI's live usercode response shape (string
``interval`` and ``expires_at``). The only substitutions are dependency-injection
seams: a factory subclass resolves a provider subclass whose device endpoints point
at the local server. Assertions read the compositor's painted viewport, not widget
model state, because the reported defect was "instructions never appear".
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from textual.app import App
from textual.pilot import Pilot
from textual.widgets import RadioButton, RadioSet

from src.auth.credential_dao import ProviderName
from src.auth.credential_store import CredentialStore
from src.auth.oauth_provider import OAuthProvider
from src.auth.provider_factory import OAuthFlowFactory
from src.auth.providers.openai_codex_provider import OpenAICodexOAuthProvider
from src.tui.authentication import AuthenticationScreen
from tests.tui.authentication._painted_output import (
    painted_link_targets,
    painted_text,
    painted_widget_strips,
    wait_until_painted,
)

_VERIFICATION_URL: str = "https://auth.openai.com/codex/device"
_USER_CODE: str = "DUMMY-E2E-CODE"
_DEVICE_START_FAILED_MESSAGE: str = "Device sign-in failed. Use Back to retry."
_LIVE_CODE_PROMPT: str = "Enter this code"
# Each bounded paint wait lasts about 5s; the live usercode call may take longer.
_LIVE_START_WAITS: int = 4


class _LocalDeviceServer:
    """Local stand-in for OpenAI's device usercode and token endpoints."""

    def __init__(self, *, start_handler: Callable[[web.Request], Awaitable[web.Response]]) -> None:
        """Keep the start response script; polling always reports pending.

        Args:
            start_handler (Callable[[web.Request], Awaitable[web.Response]]): Usercode endpoint script.
        """
        self._start_handler: Callable[[web.Request], Awaitable[web.Response]] = start_handler
        self._runner: web.AppRunner | None = None
        self.origin: str = ""

    async def __aenter__(self) -> "_LocalDeviceServer":
        """Bind both routes on an ephemeral loopback port.

        Returns:
            _LocalDeviceServer: This server, with ``origin`` set to its loopback address.
        """
        app: web.Application = web.Application()
        app.router.add_post("/usercode", self._start_handler)
        app.router.add_post("/token", self._pending_poll)
        self._runner = web.AppRunner(app=app)
        await self._runner.setup()
        site: web.TCPSite = web.TCPSite(runner=self._runner, host="127.0.0.1", port=0)
        await site.start()
        server: Any = site._server  # type: ignore[attr-defined]
        self.origin = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Close the listener after the pilot has cancelled the sign-in attempt."""
        if self._runner is not None:
            await self._runner.cleanup()

    @staticmethod
    async def _pending_poll(request: web.Request) -> web.Response:
        """Report the authorization as still pending (OpenAI's 403 poll status).

        Args:
            request (web.Request): Ignored poll request.

        Returns:
            web.Response: An empty HTTP 403 response.
        """
        return web.Response(status=403)


async def _live_shaped_start(request: web.Request) -> web.Response:
    """Return OpenAI's observed 200 usercode body with dummy identifiers.

    Args:
        request (web.Request): Ignored usercode request.

    Returns:
        web.Response: JSON with string ``interval`` and ``expires_at``, as the live endpoint sends.
    """
    return web.json_response(
        data={
            "device_auth_id": "dummy-e2e-device-auth-id",
            "user_code": _USER_CODE,
            "interval": "5",
            "expires_at": "2026-09-14T12:15:00.000000+00:00",
        }
    )


async def _failing_start(request: web.Request) -> web.Response:
    """Reject the usercode request with a server error.

    Args:
        request (web.Request): Ignored usercode request.

    Returns:
        web.Response: An empty HTTP 500 response.
    """
    return web.Response(status=500)


def _local_factory(*, origin: str) -> OAuthFlowFactory:
    """Return a real factory instance whose OpenAI provider talks to the local server.

    Only provider resolution is overridden; capability validation, method dispatch,
    and flow construction stay the production ``OAuthFlowFactory`` code.

    Args:
        origin (str): Loopback origin of the local device server.

    Returns:
        OAuthFlowFactory: Production factory subclass resolving the local Codex provider.
    """

    class _LocalCodexProvider(OpenAICodexOAuthProvider):
        """Production Codex provider with device endpoints on the local server."""

        @property
        def device_authorization_start_endpoint(self) -> str:
            """Return the local usercode endpoint."""
            return f"{origin}/usercode"

        @property
        def device_authorization_token_endpoint(self) -> str:
            """Return the local token endpoint."""
            return f"{origin}/token"

    class _LocalOAuthFlowFactory(OAuthFlowFactory):
        """Production factory that resolves OpenAI to the local provider."""

        @classmethod
        def _concrete_for(cls, *, provider: ProviderName) -> OAuthProvider:
            """Return the local Codex provider for this journey."""
            return _LocalCodexProvider()

    return _LocalOAuthFlowFactory()


class _Harness(App):
    """Push the real authentication modal with injected store and factory."""

    def __init__(self, *, store: CredentialStore, oauth_factory: OAuthFlowFactory) -> None:
        """Keep the temporary store and the local-provider factory.

        Args:
            store (CredentialStore): Temporary credential store.
            oauth_factory (OAuthFlowFactory): Real factory instance resolving the local provider.
        """
        super().__init__()
        self._store: CredentialStore = store
        self._oauth_factory: OAuthFlowFactory = oauth_factory

    def on_mount(self) -> None:
        """Open the authentication modal the way first-run and ``/auth`` do."""
        self.push_screen(AuthenticationScreen(store=self._store, oauth_factory=self._oauth_factory))


async def _choose_openai_device_authorization(*, pilot: Pilot) -> None:
    """Select OpenAI, then device authorization, through the modal's real controls.

    Args:
        pilot (Pilot): Pilot driving the harness.
    """
    await pilot.pause()
    provider_radios: RadioSet = pilot.app.screen.query_one("#provider-radio", RadioSet)
    await pilot.click(list(provider_radios.query(RadioButton))[1])
    await pilot.click("#provider-continue")
    await pilot.pause()
    await pilot.click("#method-device_authorization")
    await pilot.click("#method-continue")


@pytest.mark.asyncio
async def test_openai_device_authorization_paints_live_shaped_instructions(tmp_path: Path) -> None:
    """The live usercode shape paints the verification URL, user code, and a clickable link."""
    store: CredentialStore = CredentialStore(path=tmp_path / "authentication.json")
    async with _LocalDeviceServer(start_handler=_live_shaped_start) as server:
        harness: _Harness = _Harness(store=store, oauth_factory=_local_factory(origin=server.origin))
        async with harness.run_test(size=(80, 24)) as pilot:
            await _choose_openai_device_authorization(pilot=pilot)
            painted: str = await wait_until_painted(pilot=pilot, text=_USER_CODE)
            link_targets: set[str] = painted_link_targets(
                strips=painted_widget_strips(app=pilot.app, widget=pilot.app.screen.query_one("#oauth-url"))
            )
            await pilot.press("escape")
            await pilot.pause()

    assert _USER_CODE in painted
    assert _VERIFICATION_URL in painted
    assert link_targets == {_VERIFICATION_URL}


@pytest.mark.asyncio
async def test_openai_device_authorization_start_failure_paints_visible_error(tmp_path: Path) -> None:
    """A rejected device start paints the safe error text inside the 80x24 viewport."""
    store: CredentialStore = CredentialStore(path=tmp_path / "authentication.json")
    async with _LocalDeviceServer(start_handler=_failing_start) as server:
        harness: _Harness = _Harness(store=store, oauth_factory=_local_factory(origin=server.origin))
        async with harness.run_test(size=(80, 24)) as pilot:
            await _choose_openai_device_authorization(pilot=pilot)
            painted: str = await wait_until_painted(pilot=pilot, text=_DEVICE_START_FAILED_MESSAGE)
            await pilot.press("escape")
            await pilot.pause()

    assert "".join(_DEVICE_START_FAILED_MESSAGE.split()) in painted
    assert _USER_CODE not in painted


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_live_openai_device_authorization_paints_instructions_then_cancels(tmp_path: Path) -> None:
    """Opt-in live smoke: the real OpenAI usercode endpoint paints the URL and code, then Esc cancels.

    Uses the production ``OAuthFlowFactory()`` and provider with no endpoint overrides.
    It stops at the painted instructions: Esc cancels before any approval, so polling
    never completes and no credential is written. The device authorization id is never
    painted, so no assertion message can print it.
    """
    store_path: Path = tmp_path / "authentication.json"
    harness: _Harness = _Harness(store=CredentialStore(path=store_path), oauth_factory=OAuthFlowFactory())
    async with harness.run_test(size=(80, 24)) as pilot:
        await _choose_openai_device_authorization(pilot=pilot)
        painted: str = ""
        for _network_wait in range(_LIVE_START_WAITS):
            painted = await wait_until_painted(pilot=pilot, text=_LIVE_CODE_PROMPT)
            if "".join(_LIVE_CODE_PROMPT.split()) in painted:
                break
        link_targets: set[str] = painted_link_targets(
            strips=painted_widget_strips(app=pilot.app, widget=pilot.app.screen.query_one("#oauth-url"))
        )
        painted_code: str = painted_text(
            strips=painted_widget_strips(app=pilot.app, widget=pilot.app.screen.query_one("#oauth-redirect"))
        )
        await pilot.press("escape")
        await pilot.pause()

    assert _VERIFICATION_URL in painted
    assert link_targets == {_VERIFICATION_URL}
    assert re.fullmatch(pattern=r"[A-Z0-9-]{4,}", string=painted_code) is not None
    assert not store_path.exists()
