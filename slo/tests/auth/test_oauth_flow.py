"""Tests for ``_CallbackServer`` and ``OAuthFlow`` (02.b.3, extended by 06.a)."""

import asyncio
import socket
import threading
from collections.abc import Awaitable, Callable
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import ClientSession, web

from src.auth.browser_host import BrowserHost
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.oauth_errors import (
    OAuthCallbackPortInUseError,
    OAuthStateError,
    OAuthTimeoutError,
    OAuthTokenError,
)
from src.auth.oauth_flow import (
    AuthorizationPresentationDAO,
    OAuthFlow,
    _CallbackServer,
    _DEFAULT_TIMEOUT_SECONDS,
)
from src.auth.oauth_provider import CallbackBind, FauxOAuthProvider

_GRAPHICAL_HOST: BrowserHost = BrowserHost(environment={"DISPLAY": ":0"}, platform="linux")
"""Injected host where the opener runs, independent of the machine running the tests."""
_HEADLESS_HOST: BrowserHost = BrowserHost(environment={"TERM": "xterm-256color"}, platform="linux")
"""Injected SSH/container-like host where webbrowser would fall back to console browsers."""


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


class TestOAuthFlowInvoke:
    """End-to-end orchestration with a Faux provider."""

    @pytest.mark.asyncio
    async def test_invoke_opens_browser_with_provider_url(self) -> None:
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

        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()

        def _opener(url: str) -> bool:
            asyncio.run_coroutine_threadsafe(coro=_hit_after(url=url), loop=loop)
            return True

        with patch.object(
            FauxOAuthProvider,
            "exchange_code",
            new_callable=AsyncMock,
            return_value=FauxOAuthProvider().parse_token_response(payload={}),
        ):
            flow: OAuthFlow = OAuthFlow(
                provider=FauxOAuthProvider(),
                present_authorization=lambda presentation: None,
                timeout_seconds=3,
                webbrowser_open=_opener,
                browser_host=_GRAPHICAL_HOST,
            )
            cred = await flow.invoke()

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


class _NoNetworkFauxProvider(FauxOAuthProvider):
    """Faux provider whose code exchange returns the deterministic credential without HTTP."""

    async def exchange_code(
        self, *, code: str, verifier: str, state: str, redirect_uri: str
    ) -> CredentialDAO:
        """Return the faux credential for any code.

        WHO: OAuthFlow.invoke in TestOAuthFlowBrowserOpen.
        WHEN: After the pasted manual code wins the callback race.

        Args:
            code (str): Ignored authorization code.
            verifier (str): Ignored PKCE verifier.
            state (str): Ignored state.
            redirect_uri (str): Ignored redirect URI.

        Returns:
            CredentialDAO: The faux's deterministic credential.
        """
        return self.parse_token_response(payload={})


async def _manual_code() -> str:
    """Return a pasted authorization code immediately.

    Returns:
        str: A dummy manual authorization code.
    """
    return "manual-code"


class TestOAuthFlowBrowserOpen:
    """The browser convenience open is skipped on headless hosts and never delays the code race."""

    @staticmethod
    def _flow(
        *,
        host: BrowserHost,
        opener: Callable[[str], bool],
        receiver: Callable[[], Awaitable[str]],
    ) -> OAuthFlow:
        """Build one browser attempt that completes from a pasted code, whatever the opener does.

        Args:
            host (BrowserHost): Injected host deciding whether the opener may run.
            opener (Callable[[str], bool]): Recording stand-in for ``webbrowser.open``.
            receiver (Callable[[], Awaitable[str]]): Pasted-response receiver for the race.

        Returns:
            OAuthFlow: A flow wired to the no-network faux provider.
        """
        return OAuthFlow(
            provider=_NoNetworkFauxProvider(),
            present_authorization=lambda presentation: None,
            authorization_response_receiver=receiver,
            timeout_seconds=1,
            manual_timeout_seconds=2,
            webbrowser_open=opener,
            browser_host=host,
        )

    @pytest.mark.asyncio
    async def test_attempt_browser_open_when_host_is_headless_never_calls_opener(self) -> None:
        """No DISPLAY, WAYLAND_DISPLAY or BROWSER on Linux: the painted URL is the only path."""
        opened: list[str] = []

        def _opener(url: str) -> bool:
            """Record an open that must not happen."""
            opened.append(url)
            return True

        await self._flow(host=_HEADLESS_HOST, opener=_opener, receiver=_manual_code).invoke()

        assert opened == []

    @pytest.mark.asyncio
    async def test_attempt_browser_open_when_host_is_graphical_runs_opener_off_event_loop(self) -> None:
        """The opener runs in a worker thread, not the event loop thread."""
        loop_thread: threading.Thread = threading.current_thread()
        opener_threads: list[threading.Thread] = []
        opened: threading.Event = threading.Event()

        def _opener(url: str) -> bool:
            """Record which thread performed the open."""
            opener_threads.append(threading.current_thread())
            opened.set()
            return True

        async def _code_after_open() -> str:
            """Paste the code only once the opener has run, so the race cannot skip it."""
            await asyncio.to_thread(opened.wait, timeout=2)
            return "manual-code"

        await self._flow(host=_GRAPHICAL_HOST, opener=_opener, receiver=_code_after_open).invoke()

        assert len(opener_threads) == 1
        assert opener_threads[0] is not loop_thread

    @pytest.mark.asyncio
    async def test_invoke_when_opener_blocks_consumes_pasted_code_without_waiting(self) -> None:
        """A launcher that blocks (console browser ``p.wait()``) does not hold back the pasted code."""
        started: threading.Event = threading.Event()
        release: threading.Event = threading.Event()

        def _blocking_opener(url: str) -> bool:
            """Block like a console browser until the test releases it."""
            started.set()
            release.wait(timeout=5)
            return True

        async def _code_after_open_started() -> str:
            """Paste the code while the launcher is still blocked."""
            await asyncio.to_thread(started.wait, timeout=2)
            return "manual-code"

        flow: OAuthFlow = self._flow(
            host=_GRAPHICAL_HOST, opener=_blocking_opener, receiver=_code_after_open_started
        )
        try:
            credential: CredentialDAO = await asyncio.wait_for(flow.invoke(), timeout=1)
            assert not release.is_set()
        finally:
            release.set()

        assert credential.auth_type is AuthType.OAUTH


class TestOAuthFlowManualResponse:
    """Browser presentation and manual receiver race behavior."""

    async def test_invoke_presents_before_opener_and_exchanges_manual_code(self) -> None:
        """Presentation exposes URL/redirect before opening and a bare code needs no state."""
        events: list[str] = []
        presentation: AuthorizationPresentationDAO | None = None
        provider: FauxOAuthProvider = FauxOAuthProvider()

        def present(value: AuthorizationPresentationDAO) -> None:
            """Record presentation ordering without snapshotting secret URL values."""
            nonlocal presentation
            presentation = value
            events.append("present")

        def opener(url: str) -> bool:
            """Assert presentation happened before the browser convenience call."""
            assert presentation is not None
            assert url == presentation.authorize_url
            events.append("open")
            return False

        with patch.object(
            provider,
            "exchange_code",
            new=AsyncMock(return_value=provider.parse_token_response(payload={})),
        ) as exchange:
            flow: OAuthFlow = OAuthFlow(
                provider=provider,
                present_authorization=present,
                authorization_response_receiver=AsyncMock(return_value="manual-code"),
                timeout_seconds=1,
                manual_timeout_seconds=2,
                webbrowser_open=opener,
                browser_host=_GRAPHICAL_HOST,
            )
            credential = await flow.invoke()

        assert events == ["present", "open"]
        assert presentation is not None
        assert exchange.await_args is not None
        assert presentation.redirect_uri == exchange.await_args.kwargs["redirect_uri"]
        assert exchange.await_args.kwargs["code"] == "manual-code"
        assert credential.auth_type is AuthType.OAUTH

    async def test_invoke_absorbs_callback_timeout_until_manual_response_arrives(self) -> None:
        """A short callback deadline cannot cancel a still-live manual receiver."""
        provider: FauxOAuthProvider = FauxOAuthProvider()
        receiver: asyncio.Queue[str] = asyncio.Queue()
        unavailable_calls: list[bool] = []

        def _present_authorization(_: AuthorizationPresentationDAO) -> None:
            """Accept initial browser instructions without retaining their secret-bearing URL."""

        def _present_callback_unavailable() -> None:
            """Record the downgrade, then answer manually as a user reading it would.

            Submitting from here, rather than after a fixed sleep, guarantees the
            response arrives only once the callback deadline has passed. A sleep
            raced flow setup on loaded machines and could answer before the deadline.
            """
            unavailable_calls.append(True)
            receiver.put_nowait("manual-code")

        with patch.object(
            provider,
            "exchange_code",
            new=AsyncMock(return_value=provider.parse_token_response(payload={})),
        ):
            flow: OAuthFlow = OAuthFlow(
                provider=provider,
                present_authorization=_present_authorization,
                present_callback_unavailable=_present_callback_unavailable,
                authorization_response_receiver=receiver.get,
                timeout_seconds=0.01,
                manual_timeout_seconds=1,
                webbrowser_open=lambda url: False,
            )
            credential = await flow.invoke()

        assert credential.auth_type is AuthType.OAUTH
        assert unavailable_calls == [True]

    async def test_invoke_propagates_callback_timeout_without_manual_receiver(self) -> None:
        """The original loopback-only path keeps callback timeout terminal."""
        flow: OAuthFlow = OAuthFlow(
            provider=FauxOAuthProvider(),
            present_authorization=lambda presentation: None,
            timeout_seconds=0.01,
            manual_timeout_seconds=1,
            webbrowser_open=lambda url: False,
        )

        with pytest.raises(OAuthTimeoutError) as error:
            await flow.invoke()

        assert error.value.kind == "callback"

    async def test_invoke_raises_attempt_timeout_when_manual_receiver_never_responds(self) -> None:
        """The long whole-attempt deadline has distinct attempt timeout semantics."""
        receiver: asyncio.Queue[str] = asyncio.Queue()
        flow: OAuthFlow = OAuthFlow(
            provider=FauxOAuthProvider(),
            present_authorization=lambda presentation: None,
            authorization_response_receiver=receiver.get,
            timeout_seconds=1,
            manual_timeout_seconds=0.01,
            webbrowser_open=lambda url: False,
        )

        with pytest.raises(OAuthTimeoutError) as error:
            await flow.invoke()

        assert error.value.kind == "attempt"


class TestOAuthFlowInit:
    """``OAuthFlow.__init__`` resolves ``timeout_seconds`` across three branches."""

    def test_init_uses_arg_when_provided(self) -> None:
        """Explicit ``timeout_seconds=`` wins over both cfg and the default."""
        flow: OAuthFlow = OAuthFlow(
            provider=FauxOAuthProvider(),
            present_authorization=lambda presentation: None,
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
            present_authorization=lambda presentation: None,
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
            present_authorization=lambda presentation: None,
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
    """``OAuthFlow.invoke`` threads ``provider.callback_bind`` into the server."""

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

        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()

        def _opener(url: str) -> bool:
            """Stand in for ``webbrowser.open``; fire the synthetic callback."""
            asyncio.run_coroutine_threadsafe(coro=_hit_after(url=url), loop=loop)
            return True

        with patch.object(
            _FixedBindFauxProvider,
            "exchange_code",
            new_callable=AsyncMock,
            return_value=FauxOAuthProvider().parse_token_response(payload={}),
        ):
            flow: OAuthFlow = OAuthFlow(
                provider=_FixedBindFauxProvider(bind=bind),
                present_authorization=lambda presentation: None,
                timeout_seconds=3,
                webbrowser_open=_opener,
                browser_host=_GRAPHICAL_HOST,
            )
            cred = await flow.invoke()

        assert len(recorded_urls) == 1
        assert f"redirect_uri=http%3A%2F%2Flocalhost%3A{free_port}%2Fauth%2Fcallback" in recorded_urls[0]
        assert cred.auth_type is AuthType.OAUTH

    @pytest.mark.asyncio
    async def test_invoke_forwards_state_into_provider_exchange_code(self) -> None:
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

        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()

        def _opener(url: str) -> bool:
            asyncio.run_coroutine_threadsafe(coro=_hit_after(url=url), loop=loop)
            return True

        with patch.object(provider, "exchange_code", new=AsyncMock(side_effect=_exchange_code)):
            flow: OAuthFlow = OAuthFlow(
                provider=provider,
                present_authorization=lambda presentation: None,
                timeout_seconds=3,
                webbrowser_open=_opener,
                browser_host=_GRAPHICAL_HOST,
            )
            await flow.invoke()

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

        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()

        def _opener(url: str) -> bool:
            asyncio.run_coroutine_threadsafe(coro=_hit_after(url=url), loop=loop)
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
                present_authorization=lambda presentation: None,
                timeout_seconds=3,
                webbrowser_open=_opener,
                browser_host=_GRAPHICAL_HOST,
            )
            await flow.invoke()

        assert len(recorded_urls) == 1
        import urllib.parse as up

        query: dict[str, str] = dict(up.parse_qsl(up.urlsplit(recorded_urls[0]).query))
        assert mock_exchange.await_args is not None
        assert query["state"] == mock_exchange.await_args.kwargs["verifier"]

    @pytest.mark.asyncio
    async def test_anthropic_authorize_url_has_expected_safe_prefix_and_query_names(self) -> None:
        """Anthropic authorization URL exposes only its safe shape in regression assertions."""
        from src.auth.providers.anthropic_provider import AnthropicOAuthProvider

        recorded_urls: list[str] = []

        async def _hit_after(*, url: str) -> None:
            """Submit a synthetic callback while retaining only the URL shape assertion input."""
            import urllib.parse as up

            recorded_urls.append(url)
            query: dict[str, str] = dict(up.parse_qsl(up.urlsplit(url).query))
            async with ClientSession() as http:
                await http.get(url=f"{query['redirect_uri']}?code=dummy-code&state={query['state']}")

        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()

        def _opener(url: str) -> bool:
            """Schedule the local synthetic callback without logging authorization data."""
            asyncio.run_coroutine_threadsafe(coro=_hit_after(url=url), loop=loop)
            return True

        provider: AnthropicOAuthProvider = AnthropicOAuthProvider()
        with patch.object(
            AnthropicOAuthProvider,
            "exchange_code",
            new_callable=AsyncMock,
            return_value=provider.parse_token_response(payload={"access_token": "dummy-access-token"}),
        ):
            flow: OAuthFlow = OAuthFlow(
                provider=provider,
                present_authorization=lambda presentation: None,
                timeout_seconds=3,
                webbrowser_open=_opener,
                browser_host=_GRAPHICAL_HOST,
            )
            await flow.invoke()

        import urllib.parse as up

        authorize_url: str = recorded_urls[0]
        query_names: set[str] = {name for name, _value in up.parse_qsl(up.urlsplit(authorize_url).query)}
        assert authorize_url.startswith("https://claude.ai/oauth/authorize?")
        assert query_names == {
            "code_challenge",
            "state",
            "redirect_uri",
            "response_type",
            "client_id",
            "scope",
            "code_challenge_method",
            "code",
        }


async def test_fractional_deadline_cancellation_joins_receiver_and_closes_listener() -> None:
    """Cancelling a fractional-deadline attempt drains its receiver and callback socket."""
    entered = asyncio.Event()
    drained = asyncio.Event()
    presentations: list[AuthorizationPresentationDAO] = []

    async def receive() -> str:
        """Hold the response until cancellation, recording final cleanup."""
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            drained.set()
        raise AssertionError("unreachable")

    flow = OAuthFlow(
        provider=FauxOAuthProvider(),
        present_authorization=presentations.append,
        authorization_response_receiver=receive,
        timeout_seconds=30.5,
        manual_timeout_seconds=60.5,
        browser_host=_HEADLESS_HOST,
    )
    task = asyncio.create_task(flow.invoke())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert drained.is_set()
    from urllib.parse import urlsplit

    address = urlsplit(presentations[0].redirect_uri)
    assert address.hostname is not None and address.port is not None
    with socket.socket() as listener:
        listener.bind((address.hostname, address.port))


@pytest.mark.parametrize("timeout", [None, 0.0, 0.125])
def test_timeout_annotations_preserve_resolution(
    monkeypatch: pytest.MonkeyPatch, timeout: Optional[float]
) -> None:
    """Fractional seconds survive; zero and omission retain environment defaults."""
    monkeypatch.setattr("src.auth.oauth_flow.cfg", lambda *, key: "23")
    flow = OAuthFlow(
        provider=FauxOAuthProvider(),
        present_authorization=lambda presentation: None,
        timeout_seconds=timeout,
        manual_timeout_seconds=timeout,
        browser_host=_HEADLESS_HOST,
    )
    expected = timeout or 23
    assert flow._timeout == expected
    assert flow._manual_timeout == expected
    assert _CallbackServer(timeout=expected)._timeout == expected
