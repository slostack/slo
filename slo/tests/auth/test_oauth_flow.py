"""Tests for ``_CallbackServer`` and ``OAuthFlow`` (02.b.3, extended by 06.a)."""

import asyncio
import socket
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import ClientSession, web

from src.auth.credential_dao import AuthType, ProviderName
from src.auth.oauth_errors import (
    OAuthCallbackPortInUseError,
    OAuthStateError,
    OAuthTimeoutError,
    OAuthTokenError,
)
from src.auth.oauth_flow import OAuthFlow, _CallbackServer, _DEFAULT_TIMEOUT_SECONDS
from src.auth.oauth_provider import CallbackBind, FauxOAuthProvider


class TestCallbackServerLifecycle:
    """``_CallbackServer`` binds an ephemeral port and shuts down cleanly."""

    @pytest.mark.asyncio
    async def test_binds_ephemeral_port_and_exposes_redirect_uri(self) -> None:
        """``redirect_uri`` resolves to ``http://127.0.0.1:<port>/callback``."""
        async with _CallbackServer(timeout=1) as srv:
            assert srv.redirect_uri.startswith("http://127.0.0.1:")
            assert srv.redirect_uri.endswith("/callback")

    @pytest.mark.asyncio
    async def test_redirect_uri_read_before_bind_raises(self) -> None:
        """Defensive: reading before ``__aenter__`` is a programmer error."""
        srv: _CallbackServer = _CallbackServer(timeout=1)
        with pytest.raises(RuntimeError, match="before bind"):
            _ = srv.redirect_uri


class TestCallbackServerWaitForCode:
    """Happy path, timeout, and state mismatch."""

    @pytest.mark.asyncio
    async def test_returns_code_when_callback_arrives(self) -> None:
        """End-to-end: spin server, hit it with aiohttp, assert code."""
        async with _CallbackServer(timeout=2) as srv:

            async def _hit() -> None:
                async with ClientSession() as http:
                    await http.get(
                        url=f"{srv.redirect_uri}?code=demo&state=s",
                    )

            asyncio.create_task(_hit())
            code: str = await srv.wait_for_code(expected_state="s")
            assert code == "demo"

    @pytest.mark.asyncio
    async def test_raises_timeout_when_no_callback(self) -> None:
        """Short timeout, no callback → ``OAuthTimeoutError``."""
        async with _CallbackServer(timeout=1) as srv:
            with pytest.raises(OAuthTimeoutError):
                await srv.wait_for_code(expected_state="s")

    @pytest.mark.asyncio
    async def test_raises_state_error_on_mismatch(self) -> None:
        """Callback state ≠ expected → ``OAuthStateError``."""
        async with _CallbackServer(timeout=2) as srv:

            async def _hit() -> None:
                async with ClientSession() as http:
                    await http.get(
                        url=f"{srv.redirect_uri}?code=demo&state=wrong",
                    )

            asyncio.create_task(_hit())
            with pytest.raises(OAuthStateError):
                await srv.wait_for_code(expected_state="right")


class TestOAuthFlowStart:
    """End-to-end orchestration with a Faux provider."""

    @pytest.mark.asyncio
    async def test_start_opens_browser_with_provider_url(self) -> None:
        """``webbrowser_open`` receives the provider's authorization URL."""
        recorded_urls: list[str] = []

        async def _hit_after(*, url: str) -> None:
            # Pull code+state out of url, then call back.
            import urllib.parse as up

            recorded_urls.append(url)
            qs = dict(up.parse_qsl(up.urlsplit(url).query))
            assert qs["redirect_uri"]
            async with ClientSession() as http:
                await http.get(
                    url=f"{qs['redirect_uri']}?code=auth-code&state={qs['state']}",
                )

        def _opener(url: str) -> bool:
            asyncio.create_task(_hit_after(url=url))
            return True

        with patch.object(
            FauxOAuthProvider,
            "exchange_code",
            new_callable=AsyncMock,
            return_value=FauxOAuthProvider().parse_token_response(payload={}),
        ):
            flow: OAuthFlow = OAuthFlow(
                provider=FauxOAuthProvider(),
                timeout_seconds=3,
                webbrowser_open=_opener,
            )
            cred = await flow.start()

        assert len(recorded_urls) == 1
        assert recorded_urls[0].startswith("https://faux.example.com/oauth/authorize?")
        assert cred.auth_type is AuthType.OAUTH

    @pytest.mark.asyncio
    async def test_provider_exchange_code_raises_on_non_2xx(self) -> None:
        """A 4xx token endpoint still translates to ``OAuthTokenError`` via the provider."""

        async def _bad_token(request: web.Request) -> web.Response:
            """Return HTTP 400 for any POST."""
            return web.Response(status=400, text="bad")

        app: web.Application = web.Application()
        app.router.add_post("/oauth/token", _bad_token)
        runner: web.AppRunner = web.AppRunner(app=app)
        await runner.setup()
        site: web.TCPSite = web.TCPSite(runner=runner, host="127.0.0.1", port=0)
        await site.start()
        try:
            server = site._server  # type: ignore[attr-defined]
            assert server is not None
            sockets = getattr(server, "sockets", None)
            assert sockets
            port: int = sockets[0].getsockname()[1]

            class _Provider(FauxOAuthProvider):
                """Faux provider with token endpoint pointed at the local stub."""

                @property
                def token_endpoint(self) -> str:
                    """Override to point at the local 400 stub."""
                    return f"http://127.0.0.1:{port}/oauth/token"

            provider: _Provider = _Provider()
            with pytest.raises(OAuthTokenError, match="HTTP 400"):
                await provider.exchange_code(
                    code="ignored",
                    verifier="v",
                    state="s",
                    redirect_uri="http://127.0.0.1/callback",
                )
        finally:
            await runner.cleanup()


class TestOAuthFlowInit:
    """``OAuthFlow.__init__`` resolves ``timeout_seconds`` across three branches."""

    def test_init_uses_arg_when_provided(self) -> None:
        """Explicit ``timeout_seconds=`` wins over both cfg and the default."""
        flow: OAuthFlow = OAuthFlow(
            provider=FauxOAuthProvider(),
            timeout_seconds=11,
            webbrowser_open=lambda url: True,
        )

        assert flow._timeout == 11

    def test_init_uses_cfg_timeout_when_arg_omitted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No arg, ``cfg('SLO_OAUTH_TIMEOUT_SECONDS')`` returns a value → uses it."""
        monkeypatch.setattr(
            "src.auth.oauth_flow.cfg",
            lambda *, key: "23" if key == "SLO_OAUTH_TIMEOUT_SECONDS" else None,
        )

        flow: OAuthFlow = OAuthFlow(
            provider=FauxOAuthProvider(),
            webbrowser_open=lambda url: True,
        )

        assert flow._timeout == 23

    def test_init_falls_back_to_default_when_cfg_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No arg, cfg returns ``None`` → ``_DEFAULT_TIMEOUT_SECONDS``."""
        monkeypatch.setattr(
            "src.auth.oauth_flow.cfg",
            lambda *, key: None,
        )

        flow: OAuthFlow = OAuthFlow(
            provider=FauxOAuthProvider(),
            webbrowser_open=lambda url: True,
        )

        assert flow._timeout == _DEFAULT_TIMEOUT_SECONDS


class _FixedBindFauxProvider(FauxOAuthProvider):
    """Faux provider whose ``callback_bind`` returns a test-supplied bind.

    Used by ``TestCallbackServerFixedBind`` and
    ``TestOAuthFlowReadsProviderBind`` to drive the fixed-bind code path
    against a real but ephemeral port from the ``free_port`` fixture,
    rather than hard-coding Codex's production port 1455.
    """

    def __init__(self, *, bind: CallbackBind) -> None:
        """Capture the bind the override should return.

        Args:
            bind (CallbackBind): The bind ``callback_bind`` returns.
        """
        super().__init__()
        self._bind: CallbackBind = bind

    @property
    def callback_bind(self) -> Optional[CallbackBind]:
        """Return the captured bind.

        Returns:
            Optional[CallbackBind]: The bind supplied at construction.
        """
        return self._bind


class TestCallbackServerFixedBind:
    """``_CallbackServer`` honours an explicit ``CallbackBind``."""

    @pytest.mark.asyncio
    async def test_binds_fixed_port_and_path(self, free_port: int) -> None:
        """Fixed-bind path uses the bind's port/path; redirect URI uses ``public_host``."""
        bind: CallbackBind = CallbackBind(
            host="127.0.0.1",
            port=free_port,
            path="/auth/callback",
            public_host="localhost",
        )

        async with _CallbackServer(timeout=2, bind=bind) as srv:
            assert srv.redirect_uri == f"http://localhost:{free_port}/auth/callback"
            async with ClientSession() as http:
                async with http.get(
                    url=f"http://127.0.0.1:{free_port}/auth/callback?code=c&state=s",
                ) as resp:
                    assert resp.status == 200

    @pytest.mark.asyncio
    async def test_redirect_uri_readable_before_bind_on_fixed_path(self) -> None:
        """Pre-bind ``redirect_uri`` works on the fixed path (URI is pre-computed)."""
        bind: CallbackBind = CallbackBind(
            host="127.0.0.1",
            port=1455,
            path="/auth/callback",
            public_host="localhost",
        )
        srv: _CallbackServer = _CallbackServer(timeout=1, bind=bind)

        assert srv.redirect_uri == "http://localhost:1455/auth/callback"

    @pytest.mark.asyncio
    async def test_raises_port_in_use_when_fixed_port_already_bound(self, free_port: int) -> None:
        """Holding the port externally → ``OAuthCallbackPortInUseError`` on bind."""
        blocker: socket.socket = socket.socket(
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        blocker.bind(("127.0.0.1", free_port))
        blocker.listen(1)
        try:
            bind: CallbackBind = CallbackBind(
                host="127.0.0.1",
                port=free_port,
                path="/auth/callback",
                public_host="localhost",
            )
            with pytest.raises(OAuthCallbackPortInUseError) as exc_info:
                async with _CallbackServer(timeout=1, bind=bind):
                    pass
            assert exc_info.value.port == free_port
        finally:
            blocker.close()

    @pytest.mark.asyncio
    async def test_non_eaddrinuse_oserror_propagates_unchanged(self, free_port: int) -> None:
        """OSError with a non-EADDRINUSE errno re-raises and cleans up the runner."""
        bind: CallbackBind = CallbackBind(
            host="127.0.0.1",
            port=free_port,
            path="/auth/callback",
            public_host="localhost",
        )
        original_oserror: OSError = OSError(13, "Permission denied")

        async def _failing_start(self: web.TCPSite) -> None:
            """Stub for ``TCPSite.start`` that simulates a permission error."""
            raise original_oserror

        with patch.object(web.TCPSite, "start", _failing_start):
            with pytest.raises(OSError) as exc_info:
                async with _CallbackServer(timeout=1, bind=bind):
                    pass

        assert exc_info.value is original_oserror
        assert not isinstance(exc_info.value, OAuthCallbackPortInUseError)

    @pytest.mark.asyncio
    async def test_port_released_after_fixed_bind_failure(self, free_port: int) -> None:
        """After ``EADDRINUSE`` translation the aiohttp runner is cleaned up.

        Once the external blocker releases the port, the same port is
        rebindable by a fresh ``_CallbackServer`` — i.e. the failed
        attempt did not leak an active ``AppRunner``.
        """
        blocker: socket.socket = socket.socket(
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
        blocker.bind(("127.0.0.1", free_port))
        blocker.listen(1)
        bind: CallbackBind = CallbackBind(
            host="127.0.0.1",
            port=free_port,
            path="/auth/callback",
            public_host="localhost",
        )
        try:
            with pytest.raises(OAuthCallbackPortInUseError):
                async with _CallbackServer(timeout=1, bind=bind):
                    pass
        finally:
            blocker.close()

        async with _CallbackServer(timeout=1, bind=bind) as srv:
            assert srv.redirect_uri.endswith(f":{free_port}/auth/callback")


class TestOAuthFlowReadsProviderBind:
    """``OAuthFlow.start`` threads ``provider.callback_bind`` into the server."""

    @pytest.mark.asyncio
    async def test_authorize_url_carries_provider_redirect_uri(self, free_port: int) -> None:
        """Provider declares a fixed bind → the authorize URL advertises it."""
        bind: CallbackBind = CallbackBind(
            host="127.0.0.1",
            port=free_port,
            path="/auth/callback",
            public_host="localhost",
        )
        recorded_urls: list[str] = []

        async def _hit_after(*, url: str) -> None:
            """Capture the URL and synthesise the OAuth redirect callback."""
            import urllib.parse as up

            recorded_urls.append(url)
            qs: dict[str, str] = dict(up.parse_qsl(up.urlsplit(url).query))
            async with ClientSession() as http:
                await http.get(
                    url=f"http://127.0.0.1:{free_port}/auth/callback" f"?code=auth-code&state={qs['state']}",
                )

        def _opener(url: str) -> bool:
            """Stand in for ``webbrowser.open``; fire the synthetic callback."""
            asyncio.create_task(_hit_after(url=url))
            return True

        with patch.object(
            _FixedBindFauxProvider,
            "exchange_code",
            new_callable=AsyncMock,
            return_value=FauxOAuthProvider().parse_token_response(payload={}),
        ):
            flow: OAuthFlow = OAuthFlow(
                provider=_FixedBindFauxProvider(bind=bind),
                timeout_seconds=3,
                webbrowser_open=_opener,
            )
            cred = await flow.start()

        assert len(recorded_urls) == 1
        assert f"redirect_uri=http%3A%2F%2Flocalhost%3A{free_port}%2Fauth%2Fcallback" in recorded_urls[0]
        assert cred.auth_type is AuthType.OAUTH

        assert len(recorded_urls) == 1
        assert f"redirect_uri=http%3A%2F%2Flocalhost%3A{free_port}%2Fauth%2Fcallback" in recorded_urls[0]
        assert cred.auth_type is AuthType.OAUTH

    @pytest.mark.asyncio
    async def test_start_forwards_state_into_provider_exchange_code(self) -> None:
        """The flow passes the validated callback state into provider exchange."""
        provider: FauxOAuthProvider = FauxOAuthProvider()
        recorded_call: dict[str, str] = {}

        async def _exchange_code(*, code: str, verifier: str, state: str, redirect_uri: str):
            recorded_call.update(
                {
                    "code": code,
                    "verifier": verifier,
                    "state": state,
                    "redirect_uri": redirect_uri,
                }
            )
            return provider.parse_token_response(payload={})

        async def _hit_after(*, url: str) -> None:
            import urllib.parse as up

            qs: dict[str, str] = dict(up.parse_qsl(up.urlsplit(url).query))
            async with ClientSession() as http:
                await http.get(url=f"{qs['redirect_uri']}?code=auth-code&state={qs['state']}")

        def _opener(url: str) -> bool:
            asyncio.create_task(_hit_after(url=url))
            return True

        with patch.object(provider, "exchange_code", new=AsyncMock(side_effect=_exchange_code)):
            flow: OAuthFlow = OAuthFlow(
                provider=provider,
                timeout_seconds=3,
                webbrowser_open=_opener,
            )
            await flow.start()

        assert recorded_call["code"] == "auth-code"
        assert recorded_call["state"]
        assert recorded_call["redirect_uri"].startswith("http://127.0.0.1:")

    @pytest.mark.asyncio
    async def test_anthropic_authorize_url_uses_verifier_as_state(self) -> None:
        """Anthropic parity path reuses the PKCE verifier as the authorize state."""
        from src.auth.providers.anthropic_provider import AnthropicOAuthProvider

        recorded_urls: list[str] = []

        async def _hit_after(*, url: str) -> None:
            import urllib.parse as up

            recorded_urls.append(url)
            qs: dict[str, str] = dict(up.parse_qsl(up.urlsplit(url).query))
            async with ClientSession() as http:
                await http.get(url=f"{qs['redirect_uri']}?code=auth-code&state={qs['state']}")

        def _opener(url: str) -> bool:
            asyncio.create_task(_hit_after(url=url))
            return True

        provider: AnthropicOAuthProvider = AnthropicOAuthProvider()
        with patch.object(
            AnthropicOAuthProvider,
            "exchange_code",
            new_callable=AsyncMock,
            return_value=provider.parse_token_response(payload={"access_token": "sk-ant-oat01-test"}),
        ) as mock_exchange:
            flow: OAuthFlow = OAuthFlow(
                provider=provider,
                timeout_seconds=3,
                webbrowser_open=_opener,
            )
            await flow.start()

        assert len(recorded_urls) == 1
        import urllib.parse as up
        query: dict[str, str] = dict(up.parse_qsl(up.urlsplit(recorded_urls[0]).query))
        assert query["state"] == mock_exchange.await_args.kwargs["verifier"]
