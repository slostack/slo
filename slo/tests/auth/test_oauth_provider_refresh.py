"""Tests for ``OAuthProvider.refresh`` (feature 07 §3.1).

The base-class ``refresh`` implements the standard OAuth 2.0 refresh
exchange; the tests run it against a local ``aiohttp.web`` stub so we
exercise the wire path (form-encoded POST, JSON parse, error mapping)
without leaving the box.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

import pytest
from aiohttp import web

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.oauth_errors import OAuthTokenError
from src.auth.oauth_provider import FauxOAuthProvider, OAuthProvider


_TokenHandler = Callable[[web.Request], Awaitable[web.Response]]


async def _spin_up_token_endpoint(*, handler: _TokenHandler) -> tuple[str, web.AppRunner]:
    """Start an ``aiohttp`` stub server exposing ``/oauth/token``.

    Args:
        handler (_TokenHandler): The POST handler to register.

    Returns:
        tuple[str, web.AppRunner]: The fully-qualified token URL and the
            running ``AppRunner`` so the caller can clean up.
    """
    app: web.Application = web.Application()
    app.router.add_post("/oauth/token", handler)
    runner: web.AppRunner = web.AppRunner(app=app)
    await runner.setup()
    site: web.TCPSite = web.TCPSite(runner=runner, host="127.0.0.1", port=0)
    await site.start()
    server = site._server  # type: ignore[attr-defined]
    assert server is not None
    sockets = getattr(server, "sockets", None)
    assert sockets
    port: int = sockets[0].getsockname()[1]
    return f"http://127.0.0.1:{port}/oauth/token", runner


def _provider_pointed_at(*, token_url: str) -> OAuthProvider:
    """Build a faux provider whose ``token_endpoint`` resolves to ``token_url``.

    Args:
        token_url (str): Stub token endpoint URL.

    Returns:
        OAuthProvider: A faux provider pointed at the stub.
    """

    class _Provider(FauxOAuthProvider):
        """Faux provider with the token endpoint overridden for tests."""

        @property
        def token_endpoint(self) -> str:
            """Override to point at the local stub."""
            return token_url

    return _Provider()


class TestOAuthProviderRefresh:
    """``OAuthProvider.refresh`` — standard OAuth 2.0 refresh exchange."""

    async def test_refresh_posts_form_encoded_body_and_returns_credential(
        self,
    ) -> None:
        """POSTs ``grant_type=refresh_token`` and parses the JSON response."""
        captured: dict[str, Any] = {}

        async def _handler(request: web.Request) -> web.Response:
            """Capture the form body and return a deterministic token payload."""
            captured["form"] = dict(await request.post())
            return web.json_response(
                data={
                    "access_token": "refreshed-access",
                    "refresh_token": "refreshed-refresh",
                    "expires_in": 3600,
                    "scope": "openid profile",
                },
            )

        token_url: str
        runner: web.AppRunner
        token_url, runner = await _spin_up_token_endpoint(handler=_handler)
        try:
            provider: OAuthProvider = _provider_pointed_at(token_url=token_url)

            cred: CredentialDAO = await provider.refresh(refresh_token="stale-refresh")

            assert captured["form"] == {
                "grant_type": "refresh_token",
                "refresh_token": "stale-refresh",
                "client_id": provider.client_id,
            }
            assert cred.auth_type is AuthType.OAUTH
            assert cred.provider is ProviderName.OPENAI
            # FauxOAuthProvider ignores the payload and returns its own
            # fixture values — we assert the refresh wiring, not the
            # provider's parse logic.
            assert cred.access_token == "faux-access"
        finally:
            await runner.cleanup()

    async def test_refresh_raises_oauth_token_error_on_non_2xx(self) -> None:
        """A 4xx response from the token endpoint surfaces as ``OAuthTokenError``."""

        async def _handler(request: web.Request) -> web.Response:
            """Return HTTP 400 for any POST."""
            return web.Response(status=400, text="invalid_grant")

        token_url: str
        runner: web.AppRunner
        token_url, runner = await _spin_up_token_endpoint(handler=_handler)
        try:
            provider: OAuthProvider = _provider_pointed_at(token_url=token_url)

            with pytest.raises(OAuthTokenError, match="HTTP 400"):
                await provider.refresh(refresh_token="any")
        finally:
            await runner.cleanup()
