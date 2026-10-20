"""Provider-agnostic browser OAuth orchestration and manual-response parsing."""

from __future__ import annotations

import asyncio
import errno
import time
import webbrowser
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Awaitable, Callable, Optional, cast
from urllib.parse import parse_qs, urlsplit

from aiohttp import web
from pydantic import BaseModel, ConfigDict

from config.cfg import cfg
from config.logger import log_info
from src.auth.browser_host import BrowserHost
from src.auth.credential_dao import CredentialDAO
from src.auth.oauth_errors import OAuthCallbackPortInUseError, OAuthStateError, OAuthTimeoutError
from src.auth.oauth_provider import CallbackBind, OAuthProvider
from src.auth.pkce import code_challenge_s256, generate_code_verifier

__all__ = [
    "AuthorizationCodeDAO",
    "AuthorizationPresentationDAO",
    "AuthorizationResponseParser",
    "OAuthFlow",
]

_DEFAULT_HOST: str = "127.0.0.1"
_DEFAULT_CALLBACK_PATH: str = "/callback"
_DEFAULT_TIMEOUT_SECONDS: int = 60
_DEFAULT_MANUAL_TIMEOUT_SECONDS: int = 900


class AuthorizationPresentationDAO(BaseModel):
    """Instructions published before Slo attempts to open a browser."""

    model_config = ConfigDict(frozen=True)

    authorize_url: str
    redirect_uri: str
    instructions: str


@dataclass(frozen=True)
class AuthorizationCodeDAO:
    """One validated code held only until the token exchange completes."""

    code: str


class AuthorizationResponseParser:
    """Parse one opaque browser response without retaining its raw value."""

    @classmethod
    def parse(cls, *, authorization_response: str, expected_state: str) -> AuthorizationCodeDAO:
        """Validate one pasted redirect, code/state pair, query string, or bare code.

        WHO: OAuthFlow calls this only for its UI-owned response receiver.
        WHEN: A user has explicitly submitted one authorization response.

        Raises:
            OAuthStateError: A supplied state does not match this PKCE attempt.
            ValueError: The response does not contain a usable authorization code.
        """
        response: str = authorization_response.strip()
        code, supplied_state = cls._parse_response(response=response)
        cls._validate_state(expected_state=expected_state, supplied_state=supplied_state)
        return AuthorizationCodeDAO(code=code)

    @classmethod
    def _parse_response(cls, *, response: str) -> tuple[str, str | None]:
        """Choose the documented response shape in its precedence order."""
        if not response:
            raise ValueError("Authorization response is invalid.")
        if "://" in response:
            return cls._parse_query(query=urlsplit(response).query)
        if "#" in response and "=" not in response:
            code, supplied_state = response.split("#", maxsplit=1)
            return cls._validate_code(code=code), supplied_state or None
        if response.startswith("code=") or "&code=" in response:
            return cls._parse_query(query=response.lstrip("?"))
        return cls._validate_code(code=response), None

    @classmethod
    def _parse_query(cls, *, query: str) -> tuple[str, str | None]:
        """Extract a code and optional state from a URL or query string."""
        values: dict[str, list[str]] = parse_qs(qs=query, keep_blank_values=True)
        code_values: list[str] = values.get("code", [])
        code: str = code_values[0] if code_values else ""
        state_values: list[str] = values.get("state", [])
        supplied_state: str | None = state_values[0] if state_values else None
        return cls._validate_code(code=code), supplied_state

    @classmethod
    def _validate_code(cls, *, code: str) -> str:
        """Reject an absent response code with fixed, non-secret copy."""
        if code:
            return code
        raise ValueError("Authorization response is invalid.")

    @classmethod
    def _validate_state(cls, *, expected_state: str, supplied_state: str | None) -> None:
        """Check state only when the user response actually carried one."""
        if supplied_state is None or supplied_state == expected_state:
            return
        raise OAuthStateError()


class OAuthFlow:
    """Run one PKCE browser OAuth attempt against one provider."""

    def __init__(
        self,
        *,
        provider: OAuthProvider,
        present_authorization: Callable[[AuthorizationPresentationDAO], None],
        present_callback_unavailable: Callable[[], None] = lambda: None,
        authorization_response_receiver: Callable[[], Awaitable[str]] | None = None,
        timeout_seconds: float | None = None,
        manual_timeout_seconds: float | None = None,
        webbrowser_open: Callable[[str], bool] = webbrowser.open,
        browser_host: BrowserHost | None = None,
    ) -> None:
        """Store presentation, callback, and browser seams for one attempt.

        WHAT: Captures one attempt's provider, presentation sinks, and response channels.
        WHO: OAuthFlowFactory constructs this after browser authorization is selected.
        WHEN: Once per authentication attempt; no values survive invocation.

        Args:
            provider (OAuthProvider): Provider that owns authorization and token exchange.
            present_authorization (Callable[[AuthorizationPresentationDAO], None]): Browser instruction sink.
            present_callback_unavailable (Callable[[], None], optional): Callback-deadline status sink.
                Defaults to a no-op.
            authorization_response_receiver (Callable[[], Awaitable[str]] | None, optional):
                Optional manual browser response receiver. Defaults to None.
            timeout_seconds (float | None, optional): Local callback deadline. Defaults to None.
            manual_timeout_seconds (float | None, optional): Whole-attempt manual deadline. Defaults to None.
            webbrowser_open (Callable[[str], bool], optional): Best-effort browser opener. Defaults to webbrowser.open.
            browser_host (BrowserHost | None, optional): Decides whether the opener may run.
                Defaults to None, meaning ``BrowserHost.current()``.
        """
        self._provider: OAuthProvider = provider
        self._present_authorization: Callable[[AuthorizationPresentationDAO], None] = present_authorization
        self._present_callback_unavailable: Callable[[], None] = present_callback_unavailable
        self._response_receiver: Callable[[], Awaitable[str]] | None = authorization_response_receiver
        self._timeout: float = timeout_seconds or int(
            cfg(key="SLO_OAUTH_TIMEOUT_SECONDS") or _DEFAULT_TIMEOUT_SECONDS
        )
        self._manual_timeout: float = manual_timeout_seconds or int(
            cfg(key="SLO_OAUTH_MANUAL_TIMEOUT_SECONDS") or _DEFAULT_MANUAL_TIMEOUT_SECONDS
        )
        self._open: Callable[[str], bool] = webbrowser_open
        self._browser_host: BrowserHost = browser_host or BrowserHost.current()

    async def invoke(self) -> CredentialDAO:
        """Present, attempt browser opening, receive a code, and exchange it.

        WHO: AuthenticationScreen invokes the selected interaction.
        WHEN: After it has created the optional one-attempt response queue.
        """
        verifier: str = generate_code_verifier()
        challenge: str = code_challenge_s256(verifier=verifier)
        state: str = self._provider.authorization_state(verifier=verifier)
        bind: CallbackBind | None = self._provider.callback_bind
        async with _CallbackServer(
            timeout=self._timeout,
            bind=bind,
            provider_name=self._provider.provider_name.value,
        ) as server:
            presentation: AuthorizationPresentationDAO = self._build_presentation(
                challenge=challenge,
                state=state,
                redirect_uri=server.redirect_uri,
            )
            self._present_authorization(presentation)
            # Open alongside the code race: a launcher that blocks must not hold back a pasted code.
            browser_open: asyncio.Task[None] = asyncio.create_task(
                self._attempt_browser_open(authorize_url=presentation.authorize_url)
            )
            try:
                authorization_code: AuthorizationCodeDAO = await self._receive_authorization_code(
                    expected_state=state,
                    callback_server=server,
                    attempt_deadline_seconds=self._manual_timeout,
                )
            finally:
                browser_open.cancel()
                await asyncio.gather(browser_open, return_exceptions=True)
            redirect_uri: str = server.redirect_uri
        return await self._provider.exchange_code(
            code=authorization_code.code,
            verifier=verifier,
            state=state,
            redirect_uri=redirect_uri,
        )

    def _build_presentation(
        self,
        *,
        challenge: str,
        state: str,
        redirect_uri: str,
    ) -> AuthorizationPresentationDAO:
        """Build the complete browser instruction before attempting local opening."""
        return AuthorizationPresentationDAO(
            authorize_url=self._provider.authorization_url(
                code_challenge=challenge,
                state=state,
                redirect_uri=redirect_uri,
            ),
            redirect_uri=redirect_uri,
            instructions="Open this URL in any browser, then paste the displayed code or final redirect.",
        )

    async def _attempt_browser_open(self, *, authorize_url: str) -> None:
        """Best-effort open the local browser off the event loop, without exposing the URL.

        WHAT: Skips opening on a headless host, where ``webbrowser`` would start a console
            browser that waits for exit on the TUI terminal. Otherwise runs the opener in a
            worker thread so a slow or blocking launcher cannot freeze the modal.
        WHO: ``invoke`` runs this as a task alongside ``_receive_authorization_code``.
        WHEN: Once per browser authorization attempt, right after the instructions are presented;
            ``invoke`` cancels the wait when the code race ends (the launcher thread is not stopped).

        Args:
            authorize_url (str): Secret-bearing authorization URL; never logged.
        """
        if not self._browser_host.can_open_graphical_browser():
            return
        try:
            await asyncio.to_thread(self._open, authorize_url)
        except Exception:
            log_info(msg=f"OAuthFlow browser unavailable for {self._provider.provider_name.value}")

    async def _receive_authorization_code(
        self,
        *,
        expected_state: str,
        callback_server: "_CallbackServer",
        attempt_deadline_seconds: float,
    ) -> AuthorizationCodeDAO:
        """Race callback and optional pasted response until one validated code arrives."""
        callback_task: asyncio.Task[str] = asyncio.create_task(
            callback_server.wait_for_code(expected_state=expected_state)
        )
        tasks: set[asyncio.Task[str]] = {callback_task}
        if self._response_receiver is not None:
            tasks.add(asyncio.ensure_future(self._response_receiver()))
        deadline: float = time.monotonic() + attempt_deadline_seconds
        try:
            while tasks:
                remaining_seconds: float = deadline - time.monotonic()
                if remaining_seconds <= 0:
                    raise OAuthTimeoutError(kind="attempt")
                done, _pending = await asyncio.wait(
                    tasks,
                    timeout=remaining_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    raise OAuthTimeoutError(kind="attempt")
                for task in done:
                    tasks.remove(task)
                    try:
                        value: str = task.result()
                    except OAuthTimeoutError as error:
                        if task is callback_task and self._response_receiver is not None:
                            self._set_callback_unavailable()
                            continue
                        raise error
                    if task is callback_task:
                        return AuthorizationCodeDAO(code=value)
                    return AuthorizationResponseParser.parse(
                        authorization_response=value,
                        expected_state=expected_state,
                    )
            raise OAuthTimeoutError(kind="attempt")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def _set_callback_unavailable(self) -> None:
        """Publish the browser callback-deadline downgrade through its explicit UI sink.

        WHAT: Tells the presentation layer that manual response input remains available.
        WHO: _receive_authorization_code calls this after only the loopback deadline lapses.
        WHEN: A browser attempt has an active manual receiver and no local callback response.
        """
        self._present_callback_unavailable()


class _CallbackServer:
    """One-shot localhost HTTP server for the OAuth redirect."""

    def __init__(
        self, *, timeout: float, bind: CallbackBind | None = None, provider_name: str = "oauth"
    ) -> None:
        """Cache listener configuration until asynchronous binding starts."""
        self._timeout: float = timeout
        self._bind: CallbackBind | None = bind
        self._provider_name: str = provider_name
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._port: int | None = None
        self._code_future: asyncio.Future[tuple[str, str]] | None = None

    @property
    def redirect_uri(self) -> str:
        """Return the provider callback URI after the listener has bound."""
        if self._bind is not None:
            return self._bind.redirect_uri
        if self._port is None:
            raise RuntimeError("_CallbackServer.redirect_uri read before bind.")
        return f"http://{_DEFAULT_HOST}:{self._port}{_DEFAULT_CALLBACK_PATH}"

    async def __aenter__(self) -> "_CallbackServer":
        """Bind the one callback route and record only a safe lifecycle log."""
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
        log_info(msg=f"OAuthFlow callback server ready for {self._provider_name}")
        return self

    async def _start_site_or_translate_bind_error(self) -> None:
        """Translate only fixed-port collisions while cleaning up failed binds."""
        assert self._site is not None
        assert self._runner is not None
        try:
            await self._site.start()
        except OSError as exc:
            await self._runner.cleanup()
            if self._bind is not None and exc.errno == errno.EADDRINUSE:
                raise OAuthCallbackPortInUseError(port=self._bind.port) from exc
            raise

    def _read_bound_port(self) -> int:
        """Read the OS-assigned ephemeral port from the active aiohttp server."""
        if self._site is None:
            raise RuntimeError("_CallbackServer._read_bound_port called before start.")
        server: Any = self._site._server  # type: ignore[attr-defined]
        sockets: list[Any] = cast(list[Any], getattr(server, "sockets", []) or [])
        if server is None or not sockets:
            raise RuntimeError("_CallbackServer site has no bound sockets.")
        return int(sockets[0].getsockname()[1])

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the listener before any token exchange can begin."""
        if self._runner is not None:
            await self._runner.cleanup()

    async def wait_for_code(self, *, expected_state: str) -> str:
        """Wait for a local callback and validate its mandatory state value."""
        if self._code_future is None:
            raise RuntimeError("_CallbackServer.wait_for_code called before bind.")
        try:
            code, state = await asyncio.wait_for(self._code_future, timeout=self._timeout)
        except asyncio.TimeoutError as exc:
            raise OAuthTimeoutError() from exc
        if state != expected_state:
            raise OAuthStateError()
        return code

    async def _handle_callback(self, request: web.Request) -> web.Response:
        """Capture callback fields in memory and send the browser success page."""
        code: str = request.query.get("code", "")
        state: str = request.query.get("state", "")
        if self._code_future is not None and not self._code_future.done():
            self._code_future.set_result((code, state))
        return web.Response(
            text="<html><body><h2>Signed in.</h2><p>You may close this tab.</p></body></html>",
            content_type="text/html",
        )
