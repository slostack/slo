"""``OAuthFlow``: provider-agnostic PKCE orchestrator (02.b.3).

Extended by 06.a (codex-oauth-redirect-uri-fix): ``_CallbackServer``
accepts an optional ``CallbackBind`` from the provider; the ephemeral
``127.0.0.1:0`` shape remains the default for providers that do not
override ``OAuthProvider.callback_bind``.
"""

from __future__ import annotations

import asyncio
import errno
import webbrowser
from types import TracebackType
from typing import Any, Callable, Optional, cast

from aiohttp import web

from config.cfg import cfg
from config.logger import log_info
from src.auth.credential_dao import CredentialDAO
from src.auth.oauth_errors import (
    OAuthCallbackPortInUseError,
    OAuthStateError,
    OAuthTimeoutError,
    OAuthTokenError,
)
from src.auth.oauth_provider import CallbackBind, OAuthProvider
from src.auth.pkce import (
    code_challenge_s256,
    generate_code_verifier,
    generate_state,
)

__all__ = ["OAuthFlow"]

_DEFAULT_HOST: str = "127.0.0.1"
_DEFAULT_CALLBACK_PATH: str = "/callback"
_DEFAULT_TIMEOUT_SECONDS: int = 60


class OAuthFlow:
    """Run one PKCE OAuth flow end-to-end against any ``OAuthProvider``.

    Constructed by the modal (02.b.5) per attempt and discarded after
    ``start`` returns or raises. Holds no long-lived state.
    """

    def __init__(
        self,
        *,
        provider: OAuthProvider,
        timeout_seconds: Optional[int] = None,
        webbrowser_open: Callable[[str], bool] = webbrowser.open,
    ) -> None:
        """Inject the provider and optional overrides for tests.

        Args:
            provider (OAuthProvider): Provider with endpoint specifics.
            timeout_seconds (Optional[int]): Callback wait. Defaults to
                ``cfg("SLO_OAUTH_TIMEOUT_SECONDS")``.
            webbrowser_open (Callable[[str], bool]): Injected for tests
                so URLs can be recorded without a real browser.
        """
        self._provider: OAuthProvider = provider
        self._timeout: int = timeout_seconds or int(
            cfg(key="SLO_OAUTH_TIMEOUT_SECONDS") or _DEFAULT_TIMEOUT_SECONDS
        )
        self._open: Callable[[str], bool] = webbrowser_open

    async def start(self) -> CredentialDAO:
        """Run the PKCE flow and return a populated ``CredentialDAO``.

        Reads ``provider.callback_bind`` once and hands it to the
        callback server. When the provider returns ``None`` the server
        binds an ephemeral port (the 02.b.3 default); otherwise it binds
        the fixed host/port/path the provider declares.

        Returns:
            CredentialDAO: ``auth_type=OAUTH`` populated by
                ``provider.parse_token_response``.

        Raises:
            OAuthCallbackPortInUseError: Fixed-port bind hit EADDRINUSE.
            OAuthTimeoutError: User did not complete sign-in in time.
            OAuthStateError: Callback state mismatch.
            OAuthTokenError: Token endpoint returned non-2xx.
        """
        verifier: str = generate_code_verifier()
        challenge: str = code_challenge_s256(verifier=verifier)
        state: str = self._provider.authorization_state(verifier=verifier)
        bind: Optional[CallbackBind] = self._provider.callback_bind
        async with _CallbackServer(timeout=self._timeout, bind=bind) as server:
            auth_url: str = self._provider.authorization_url(
                code_challenge=challenge,
                state=state,
                redirect_uri=server.redirect_uri,
            )
            log_info(msg=f"OAuthFlow.start opening {self._provider.provider_name.value}")
            self._open(auth_url)
            code: str = await server.wait_for_code(expected_state=state)
        return await self._provider.exchange_code(
            code=code,
            verifier=verifier,
            state=state,
            redirect_uri=server.redirect_uri,
        )


class _CallbackServer:
    """One-shot localhost HTTP server for the OAuth redirect.

    Constructed without a ``bind``, this binds an ephemeral port on
    ``127.0.0.1`` at path ``/callback`` — the original 02.b.3 shape used
    by Anthropic and Faux. Constructed with a ``CallbackBind``, it binds
    the configured host/port/path and advertises the bind's pre-computed
    ``redirect_uri`` string, which is allowed to differ from what the
    socket itself reports (for example, ``localhost`` advertised while
    the socket binds ``127.0.0.1`` — the Codex case in 06.a).
    """

    def __init__(
        self,
        *,
        timeout: int,
        bind: Optional[CallbackBind] = None,
    ) -> None:
        """Cache the timeout and optional bind; defer bind to ``__aenter__``.

        Args:
            timeout (int): Seconds before ``wait_for_code`` raises.
            bind (CallbackBind, optional): Fixed-port bind config. When
                ``None``, defaults to ephemeral ``127.0.0.1:/callback``.
                Defaults to None.
        """
        self._timeout: int = timeout
        self._bind: Optional[CallbackBind] = bind
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._port: Optional[int] = None
        self._code_future: Optional[asyncio.Future[tuple[str, str]]] = None

    @property
    def redirect_uri(self) -> str:
        """Return the redirect URI the running flow should advertise.

        For a fixed-port bind, returns the bind's pre-computed URI —
        which may use a different hostname than what the socket is
        bound to. For an ephemeral bind, returns
        ``http://127.0.0.1:<port>/callback`` once the socket is bound.

        Returns:
            str: The redirect URI to advertise.

        Raises:
            RuntimeError: ``redirect_uri`` read before ``__aenter__``
                on the ephemeral path (the fixed-bind path can be read
                pre-bind because the URI is pre-computed).
        """
        if self._bind is not None:
            return self._bind.redirect_uri
        if self._port is None:
            raise RuntimeError("_CallbackServer.redirect_uri read before bind.")
        return f"http://{_DEFAULT_HOST}:{self._port}{_DEFAULT_CALLBACK_PATH}"

    async def __aenter__(self) -> "_CallbackServer":
        """Bind the configured (or default) host/port/path and serve one route.

        Returns:
            _CallbackServer: ``self``, after the socket is bound.

        Raises:
            OAuthCallbackPortInUseError: Fixed-port bind hit
                ``EADDRINUSE``. Only raised when a ``CallbackBind`` is
                supplied; ephemeral binds cannot collide.
        """
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        self._code_future = loop.create_future()
        host: str = self._bind.host if self._bind is not None else _DEFAULT_HOST
        port: int = self._bind.port if self._bind is not None else 0
        path: str = self._bind.path if self._bind is not None else _DEFAULT_CALLBACK_PATH
        app: web.Application = web.Application()
        app.router.add_get(path, self._handle_callback)
        self._runner = web.AppRunner(app=app)
        await self._runner.setup()
        self._site = web.TCPSite(runner=self._runner, host=host, port=port)
        await self._start_site_or_translate_bind_error()
        self._port = self._read_bound_port()
        log_info(msg=f"_CallbackServer bound {host}:{self._port}{path}")
        return self

    async def _start_site_or_translate_bind_error(self) -> None:
        """Start the ``TCPSite`` and translate fixed-port ``EADDRINUSE``.

        Cleans up the runner before re-raising so a failed bind never
        leaks an active ``AppRunner``. ``EADDRINUSE`` is translated to
        ``OAuthCallbackPortInUseError`` only when a fixed ``bind`` is in
        play — ephemeral binds cannot fail this way.

        Raises:
            OAuthCallbackPortInUseError: Fixed-port bind hit
                ``EADDRINUSE``.
            OSError: Any other socket bind failure, after runner cleanup.
        """
        assert self._site is not None
        assert self._runner is not None
        try:
            await self._site.start()
            return
        except OSError as exc:
            await self._runner.cleanup()
            if self._bind is not None and exc.errno == errno.EADDRINUSE:
                raise OAuthCallbackPortInUseError(port=self._bind.port) from exc
            raise

    def _read_bound_port(self) -> int:
        """Inspect the running site for the OS-picked port.

        Returns:
            int: The TCP port the OS bound for ``127.0.0.1:0``.

        Raises:
            RuntimeError: If the site is not yet started.
        """
        if self._site is None:
            raise RuntimeError("_CallbackServer._read_bound_port called before start.")
        # ``_server`` and ``sockets`` are aiohttp private API; the cast +
        # Any annotation keeps mypy quiet without lying about the type.
        server: Any = self._site._server  # type: ignore[attr-defined]
        sockets: list[Any] = cast(list[Any], getattr(server, "sockets", []) or [])
        if server is None or not sockets:
            raise RuntimeError("_CallbackServer site has no bound sockets.")
        return int(sockets[0].getsockname()[1])

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        """Tear down the runner; cancel any in-flight handler.

        Args:
            exc_type (Optional[type[BaseException]]): Exception class, if any.
            exc (Optional[BaseException]): Exception instance, if any.
            tb (Optional[TracebackType]): Traceback, if any.
        """
        if self._runner is not None:
            await self._runner.cleanup()

    async def wait_for_code(self, *, expected_state: str) -> str:
        """Block until the callback arrives or the timeout fires.

        Args:
            expected_state (str): State we sent in the auth URL.

        Returns:
            str: The ``code`` query parameter from the redirect.

        Raises:
            OAuthTimeoutError: Timeout elapsed first.
            OAuthStateError: Callback ``state`` did not match.
        """
        if self._code_future is None:
            raise RuntimeError("_CallbackServer.wait_for_code called before bind.")
        try:
            received: tuple[str, str] = await asyncio.wait_for(
                self._code_future,
                timeout=self._timeout,
            )
        except asyncio.TimeoutError as exc:
            raise OAuthTimeoutError() from exc
        code, state = received
        if state != expected_state:
            raise OAuthStateError(expected=expected_state, got=state)
        return code

    async def _handle_callback(self, request: web.Request) -> web.Response:
        """Capture (code, state) and render the user-facing success page.

        Args:
            request (web.Request): The incoming redirect.

        Returns:
            web.Response: Plain HTML telling the user to close the tab.
        """
        code: str = request.query.get("code", "")
        state: str = request.query.get("state", "")
        if self._code_future is not None and not self._code_future.done():
            self._code_future.set_result((code, state))
        return web.Response(
            text=(
                "<html><body style='font-family:monospace;padding:2em'>"
                "<h2>Signed in.</h2><p>You may close this tab.</p>"
                "</body></html>"
            ),
            content_type="text/html",
        )
