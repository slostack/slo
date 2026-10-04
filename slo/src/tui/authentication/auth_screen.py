"""``AuthenticationScreen`` — the modal that drives the auth flow (02.b.5)."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widget import Widget

from config.logger import log_error, log_info
from src.auth.credential_dao import (
    AuthenticationFileDAO,
    AuthType,
    OpenRouterAuthenticationResultDAO,
    CredentialDAO,
    ProviderName,
)
from src.auth.credential_store import CredentialStore
from src.auth.oauth_errors import (
    OAuthCallbackPortInUseError,
    OAuthDeviceAuthorizationDeniedError,
    OAuthDeviceAuthorizationExpiredError,
    OAuthDeviceAuthorizationProtocolError,
    OAuthDeviceAuthorizationUnsupportedError,
    OAuthStateError,
    OAuthTimeoutError,
    OAuthTokenError,
)
from src.auth.openrouter_authentication import OpenRouterAuthenticationService
from src.auth.oauth_provider import OAuthLoginMethod
from src.auth.provider_factory import OAuthAuthenticationFlow, OAuthFactory, OAuthFlowFactory
from src.tui.authentication.auth_state import ScreenState
from src.tui.authentication.widgets.api_key_input import ApiKeyInputWidget
from src.tui.authentication.widgets.method_select import MethodSelectWidget
from src.tui.authentication.widgets.oauth_status import (
    AuthorizationResponseSubmitted,
    OAuthStatusWidget,
)
from src.tui.authentication.widgets.provider_select import ProviderSelectWidget
from src.tui.authentication.widgets.success_widget import SuccessWidget

__all__ = ["AuthenticationScreen", "OAuthFactory"]


class AuthenticationScreen(ModalScreen[Optional[CredentialDAO]]):
    """Walks the user through provider → method → credential → success.

    Returns the persisted ``CredentialDAO`` on success, ``None`` on
    cancel.

    Dependencies are constructor-injected so tests can swap in a faux
    store and a faux OAuth factory without monkeypatching.
    """

    CSS_PATH = "auth_screen.tcss"

    BINDINGS = [
        Binding(key="escape", action="cancel", description="cancel"),
    ]

    def __init__(
        self,
        *,
        store: Optional[CredentialStore] = None,
        oauth_factory: Optional[OAuthFactory] = None,
        openrouter_factory: Optional[Callable[[], OpenRouterAuthenticationService]] = None,
    ) -> None:
        """Wire up dependencies with production defaults.

        Args:
            store (Optional[CredentialStore]): Persistence layer.
                Defaults to a store rooted at ``cfg("SLO_AUTH_FILE")``.
            oauth_factory (Optional[OAuthFactory]): Maps a
                ``ProviderName`` and login method to a fresh flow. Defaults to
                an ``OAuthFlowFactory()`` instance, whose ``__call__`` builds the
                selected browser or device flow.
            openrouter_factory: Builds one candidate-verification service per submission.
        """
        super().__init__()
        self._store: CredentialStore = store or CredentialStore()
        self._oauth_factory: OAuthFactory = oauth_factory or OAuthFlowFactory()
        self._openrouter_factory = openrouter_factory or (
            lambda: OpenRouterAuthenticationService(store=self._store)
        )
        self._openrouter_service: Optional[OpenRouterAuthenticationService] = None
        self._api_key_task: Optional[asyncio.Task[None]] = None
        self._api_key_attempt = 0
        self._state: ScreenState = ScreenState.PROVIDER
        self._chosen_provider: Optional[ProviderName] = None
        self._active_login_methods: frozenset[OAuthLoginMethod] = frozenset()
        self._active_oauth_login_method: OAuthLoginMethod | None = None
        self._authorization_response_queue: asyncio.Queue[str] | None = None
        self._begin_oauth_task: Optional[asyncio.Task[None]] = None
        self._oauth_task: Optional[asyncio.Task[CredentialDAO]] = None
        self._body: Optional[Vertical] = None

    def compose(self) -> ComposeResult:
        """Mount the initial ``ProviderSelectWidget`` inside a body container."""
        with Vertical(id="auth-modal-body") as body:
            self._body = body
            yield ProviderSelectWidget(id="auth-step")

    async def action_cancel(self) -> None:
        """Dismiss with ``None``; cancel the OAuth task if it is in flight."""
        await self._cancel_api_key_attempt()
        await self._cancel_oauth_if_running()
        self._discard_authorization_response_queue()
        self.dismiss(None)

    # ---- Provider-select handlers ----

    async def on_provider_select_widget_chosen(self, event: ProviderSelectWidget.Chosen) -> None:
        """Move to method step, or directly to API-key for API-key-only providers.

        The factory's empty OAuth capability set skips method selection for
        API-key-only providers.

        Args:
            event (ProviderSelectWidget.Chosen): Carries ``provider``.
        """
        self._openrouter_service = None
        self._chosen_provider = event.provider
        self._active_login_methods = self._login_methods_for(provider=event.provider)
        if not self._active_login_methods:
            await self._swap_step(widget=ApiKeyInputWidget(provider=event.provider))
            self._state = ScreenState.API_KEY
            return
        await self._swap_step(
            widget=MethodSelectWidget(
                provider=event.provider,
                login_methods=self._active_login_methods,
            )
        )
        self._state = ScreenState.METHOD

    async def on_provider_select_widget_cancelled(self, event: ProviderSelectWidget.Cancelled) -> None:
        """Treat Cancel button identical to Esc."""
        await self.action_cancel()

    # ---- Method-select handlers ----

    async def on_method_select_widget_chosen(self, event: MethodSelectWidget.Chosen) -> None:
        """Branch into OAuth or paste-API-key.

        Args:
            event (MethodSelectWidget.Chosen): Carries ``method``.
        """
        assert self._chosen_provider is not None
        if event.method is AuthType.API_KEY:
            await self._swap_step(widget=ApiKeyInputWidget(provider=self._chosen_provider))
            self._state = ScreenState.API_KEY
            return
        assert isinstance(event.method, OAuthLoginMethod)
        login_method: OAuthLoginMethod = event.method
        self._active_oauth_login_method = login_method
        self._begin_oauth_task = asyncio.create_task(
            self._begin_oauth(
                provider=self._chosen_provider,
                login_method=login_method,
            )
        )
        self._begin_oauth_task.add_done_callback(self._on_begin_oauth_done)

    async def on_method_select_widget_back_requested(self, event: MethodSelectWidget.BackRequested) -> None:
        """Go back to provider selection."""
        await self._swap_step(widget=ProviderSelectWidget())
        self._state = ScreenState.PROVIDER

    async def on_method_select_widget_cancelled(self, event: MethodSelectWidget.Cancelled) -> None:
        """Cancel from method step."""
        await self.action_cancel()

    # ---- OAuth-status handlers ----

    async def on_oauth_status_widget_back_requested(self, event: OAuthStatusWidget.BackRequested) -> None:
        """Cancel the in-flight OAuth task and re-show cached method choices."""
        await self._cancel_oauth_if_running()
        self._discard_authorization_response_queue()
        await self._show_method_select()

    async def on_oauth_status_widget_cancelled(self, event: OAuthStatusWidget.Cancelled) -> None:
        """Cancel from OAuth step."""
        await self.action_cancel()

    async def on_authorization_response_submitted(self, event: AuthorizationResponseSubmitted) -> None:
        """Put one opaque browser response into this attempt's queue.

        Args:
            event (AuthorizationResponseSubmitted): The unparsed, cleared-widget response.
        """
        if self._authorization_response_queue is None:
            return
        if not self._authorization_response_queue.empty():
            self.query_one(OAuthStatusWidget).set_response_already_submitted()
            return
        self._authorization_response_queue.put_nowait(event.authorization_response)

    # ---- API-key handlers ----

    async def on_api_key_input_widget_submitted(self, event: ApiKeyInputWidget.Submitted) -> None:
        """Delegate OpenRouter verification or persist an existing direct-provider key.

        Args:
            event (ApiKeyInputWidget.Submitted): Carries the raw key.
        """
        assert self._chosen_provider is not None
        if self._chosen_provider is ProviderName.OPENROUTER:
            self._start_openrouter_attempt(submitted_key=event.api_key)
            return
        cred: CredentialDAO = CredentialDAO(
            provider=self._chosen_provider,
            auth_type=AuthType.API_KEY,
            access_token=event.api_key,
        )
        self._store.persist(cred=cred)
        log_info(msg=f"AuthenticationScreen persisted api_key provider={cred.provider.value}")
        await self._swap_step(widget=SuccessWidget(subject=None))
        self._state = ScreenState.SUCCESS

    async def on_api_key_input_widget_back_requested(self, event: ApiKeyInputWidget.BackRequested) -> None:
        """Re-show method-select, or provider-select for API-key-only providers.

        Providers with no OAuth capabilities return directly to provider selection
        after any verification attempt has been cancelled and awaited.
        """
        assert self._chosen_provider is not None
        await self._cancel_api_key_attempt()
        if not self._active_login_methods:
            await self._show_provider_select()
            return
        await self._show_method_select()

    async def on_api_key_input_widget_cancelled(self, event: ApiKeyInputWidget.Cancelled) -> None:
        """Cancel from API-key step."""
        await self.action_cancel()

    # ---- Success handler ----

    async def on_success_widget_closed(self, event: SuccessWidget.Closed) -> None:
        """Final dismiss returns the persisted credential."""
        if self._openrouter_service is not None:
            self.dismiss(self._openrouter_service.verified_credential())
            return
        cred: Optional[CredentialDAO] = self._oauth_result() or self._last_persisted()
        self.dismiss(cred)

    def _start_openrouter_attempt(self, *, submitted_key: str) -> None:
        """Start one tracked service attempt; repeated submissions do nothing.

        Args:
            submitted_key: Private candidate forwarded only to the service.
        """
        if self._api_key_task is not None and not self._api_key_task.done():
            return
        self._api_key_attempt += 1
        self._openrouter_service = self._openrouter_factory()
        self.query_one(ApiKeyInputWidget).show_status(message="Verifying OpenRouter key…", busy=True)
        self._api_key_task = asyncio.create_task(
            self._run_openrouter_attempt(
                service=self._openrouter_service, submitted_key=submitted_key, attempt=self._api_key_attempt
            )
        )

    async def _run_openrouter_attempt(
        self, *, service: OpenRouterAuthenticationService, submitted_key: str, attempt: int
    ) -> None:
        """Apply the current OpenRouter authentication outcome to the API-key step.

        WHAT: Invokes one private candidate verification and paints only its safe,
            current result.
        WHO: The tracked task created by ``_start_openrouter_attempt`` calls this.
        WHEN: Runs after the API-key widget disables duplicate submission and ends
            when the result is painted, cancelled, or superseded by navigation.

        Args:
            service (OpenRouterAuthenticationService): Single-use authentication owner.
            submitted_key (str): Private candidate, never rendered.
            attempt (int): Token invalidated before navigation cancellation.
        """
        result = await self._invoke_openrouter_attempt(service=service, submitted_key=submitted_key)
        if not self._is_current_openrouter_attempt(attempt=attempt):
            return
        await self._paint_openrouter_attempt_result(result=result)

    @staticmethod
    async def _invoke_openrouter_attempt(
        *, service: OpenRouterAuthenticationService, submitted_key: str
    ) -> OpenRouterAuthenticationResultDAO:
        """Invoke one service attempt while preserving cancellation semantics.

        WHAT: Delegates private candidate verification to the authentication owner.
        WHO: ``_run_openrouter_attempt`` uses this narrow await boundary.
        WHEN: Runs once per enabled API-key Save action before presentation logic.

        Args:
            service (OpenRouterAuthenticationService): Single-use authentication owner.
            submitted_key (str): Private candidate forwarded only to the service.

        Returns:
            OpenRouterAuthenticationResultDAO: The service's safe authentication result.
        """
        return await service.invoke(submitted_key=submitted_key)

    def _is_current_openrouter_attempt(self, *, attempt: int) -> bool:
        """Return whether an authentication result still belongs to the mounted step.

        WHAT: Rejects outcomes invalidated by Back, Cancel, unmount, or a newer save.
        WHO: ``_run_openrouter_attempt`` checks this after its service await.
        WHEN: Runs immediately before any result can change the visible modal state.

        Args:
            attempt (int): Task token captured when the attempt started.

        Returns:
            bool: True when the task still owns the current API-key presentation.
        """
        return attempt == self._api_key_attempt

    async def _paint_openrouter_attempt_result(
        self, *, result: OpenRouterAuthenticationResultDAO
    ) -> None:
        """Paint the safe result from the current OpenRouter authentication attempt.

        WHAT: Routes verified results to success and non-verified results to the
            still-mounted API-key widget.
        WHO: ``_run_openrouter_attempt`` calls this after validating the task token.
        WHEN: Runs once after a service attempt completes without cancellation.

        Args:
            result (OpenRouterAuthenticationResultDAO): Safe result returned by the authentication service.
        """
        if result.key_verified:
            await self._swap_step(widget=SuccessWidget(subject=None, message=result.safe_message))
            self._state = ScreenState.SUCCESS
            return
        self.query_one(ApiKeyInputWidget).show_status(message=result.safe_message, busy=False)

    async def _cancel_api_key_attempt(self) -> None:
        """Invalidate late results, cancel and await work before modal navigation."""
        self._api_key_attempt += 1
        task = self._api_key_task
        self._api_key_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        if self._openrouter_service is not None and self._openrouter_service.result.replacement_saved:
            self.notify("Authentication cancelled; verified key was saved.")

    async def _show_provider_select(self) -> None:
        """Replace the current step with the ordinary provider selector."""
        await self._swap_step(widget=ProviderSelectWidget())
        self._state = ScreenState.PROVIDER

    async def on_unmount(self) -> None:
        """Await authentication teardown when the modal is removed externally."""
        await self._cancel_api_key_attempt()

    # ---- Internal helpers ----

    async def _begin_oauth(
        self,
        *,
        provider: ProviderName,
        login_method: OAuthLoginMethod,
    ) -> None:
        """Mount status UI and start one selected OAuth interaction."""
        self._discard_authorization_response_queue()
        status = OAuthStatusWidget(provider=provider, login_method=login_method)
        await self._swap_step(widget=status)
        self._authorization_response_queue = (
            asyncio.Queue() if login_method is OAuthLoginMethod.BROWSER_AUTHORIZATION else None
        )
        flow: OAuthAuthenticationFlow = self._oauth_factory(
            provider=provider,
            login_method=login_method,
            present_browser_authorization=status.set_browser_presentation,
            present_device_authorization=status.set_device_presentation,
            authorization_response_receiver=self._authorization_response_receiver(),
            present_callback_unavailable=status.set_callback_unavailable,
        )
        self._state = ScreenState.OAUTH
        self._oauth_task = asyncio.create_task(flow.invoke())
        self._oauth_task.add_done_callback(self._on_oauth_done)

    def _authorization_response_receiver(self) -> Callable[[], Awaitable[str]] | None:
        """Return this browser attempt's receiver, or None for device authorization."""
        if self._authorization_response_queue is None:
            return None
        return self._authorization_response_queue.get

    def _login_methods_for(self, *, provider: ProviderName) -> frozenset[OAuthLoginMethod]:
        """Resolve one provider's supported OAuth interactions, once.

        The single capability read in the UI layer. Delegates to the provider's
        ``supported_login_methods()`` through the factory's capability resolver;
        the screen never infers capability from the provider name.
        """
        return self._oauth_factory.supported_login_methods(provider=provider)

    async def _show_method_select(self) -> None:
        """Re-render the cached capability list without re-reading the factory."""
        assert self._chosen_provider is not None
        await self._swap_step(
            widget=MethodSelectWidget(
                provider=self._chosen_provider,
                login_methods=self._active_login_methods,
            )
        )
        self._state = ScreenState.METHOD

    def _discard_authorization_response_queue(self) -> None:
        """Forget the current attempt's browser response channel."""
        self._authorization_response_queue = None

    def _on_begin_oauth_done(self, task: asyncio.Task[None]) -> None:
        """Paint the safe sign-in error when an attempt failed before its flow started.

        WHAT: Surfaces factory or mount failures that would otherwise be lost as
            "Task exception was never retrieved" while the modal stays on its preparing text.
            A failure before the status widget exists has nowhere to paint and is only logged.
            The attempt's browser response channel is closed first, like ``_on_oauth_done``,
            so a code pasted after the failure is not queued for a reader that never comes.
        WHO: Done callback on the start task that ``on_method_select_widget_chosen`` creates.
        WHEN: Once, as soon as ``_begin_oauth`` returns, raises, or is cancelled.

        Args:
            task (asyncio.Task[None]): The finished ``_begin_oauth`` task.
        """
        if task.cancelled():
            return
        exc: Optional[BaseException] = task.exception()
        if exc is None:
            return
        self._discard_authorization_response_queue()
        if not self.query(OAuthStatusWidget):
            log_error(
                msg=f"AuthenticationScreen could not start sign-in type={type(exc).__name__}",
                stack_trace=False,
            )
            return
        self._render_oauth_error(exc=exc)

    def _on_oauth_done(self, task: asyncio.Task[CredentialDAO]) -> None:
        """Done callback — persist on success, render error on failure.

        Args:
            task (asyncio.Task[CredentialDAO]): The completed OAuth task.
        """
        if task.cancelled():
            self._discard_authorization_response_queue()
            return
        exc: Optional[BaseException] = task.exception()
        if exc is not None:
            self._discard_authorization_response_queue()
            self._render_oauth_error(exc=exc)
            return
        cred: CredentialDAO = task.result()
        self._discard_authorization_response_queue()
        self._store.persist(cred=cred)
        log_info(msg=f"AuthenticationScreen persisted oauth provider={cred.provider.value}")
        asyncio.create_task(self._swap_step(widget=SuccessWidget(subject=cred.subject)))
        self._state = ScreenState.SUCCESS

    _ERROR_MESSAGES: dict[type[BaseException], str] = {
        OAuthStateError: "Sign-in failed: state mismatch. Use Back to retry.",
        OAuthCallbackPortInUseError: (
            "Sign-in failed: Slo could not bind the local callback port. "
            "Another process may already be using it. Free the port and retry."
        ),
        OAuthDeviceAuthorizationUnsupportedError: (
            "Device sign-in is not available for this provider. Use browser sign-in."
        ),
        OAuthDeviceAuthorizationExpiredError: "Device sign-in expired. Use Back to start a new attempt.",
        OAuthDeviceAuthorizationDeniedError: "Device sign-in was denied. Use Back to retry.",
        OAuthDeviceAuthorizationProtocolError: "Device sign-in failed. Use Back to retry.",
        OAuthTokenError: "Sign-in failed. Use Back to retry.",
    }
    """Lookup table mapping OAuth exception classes to fixed safe user-facing strings.

    Unknown exception types fall through to the default branch in
    :meth:`_render_oauth_error`.
    """

    def _render_oauth_error(self, *, exc: BaseException) -> None:
        """Update the OAuthStatus widget's error region.

        Args:
            exc (BaseException): The exception the task raised.
        """
        status: OAuthStatusWidget = self.query_one(OAuthStatusWidget)
        if isinstance(exc, OAuthTimeoutError):
            status.set_error(message=self._timeout_message(exc=exc))
            return
        message: str | None = self._ERROR_MESSAGES.get(type(exc))
        if message is not None:
            status.set_error(message=message)
            return
        log_error(
            msg=f"AuthenticationScreen unexpected OAuth exception type={type(exc).__name__}", e=Exception()
        )
        status.set_error(message="Sign-in failed. Use Back to retry.")

    @staticmethod
    def _timeout_message(*, exc: OAuthTimeoutError) -> str:
        """Map the two safe deadline kinds to distinguishable screen copy."""
        if exc.kind == "attempt":
            return "Sign-in was not completed in time. Use Back to start a new attempt."
        return "Sign-in timed out. Use Back to retry."

    async def _cancel_oauth_if_running(self) -> None:
        """Cancel the OAuth task if alive; await its termination."""
        if self._oauth_task is None or self._oauth_task.done():
            return
        self._oauth_task.cancel()
        try:
            await self._oauth_task
        except (asyncio.CancelledError, Exception):
            pass

    def _oauth_result(self) -> Optional[CredentialDAO]:
        """Return the OAuth task's credential, if it completed cleanly.

        Returns:
            Optional[CredentialDAO]: ``None`` when no task ran (API-key
                path) or when the task failed.
        """
        if self._oauth_task is None or not self._oauth_task.done():
            return None
        if self._oauth_task.cancelled():
            return None
        if self._oauth_task.exception() is not None:
            return None
        return self._oauth_task.result()

    def _last_persisted(self) -> Optional[CredentialDAO]:
        """Return the stored row for ``_chosen_provider``, if any.

        Used by the API-key success path where ``_oauth_task`` is
        ``None`` but the store already holds the row we just wrote.

        Returns:
            Optional[CredentialDAO]: The stored row or ``None``.
        """
        if self._chosen_provider is None:
            return None
        envelope: AuthenticationFileDAO = self._store.load()
        return envelope.providers.get(self._chosen_provider)

    async def _swap_step(self, *, widget: Widget) -> None:
        """Mount ``widget`` as the only child of the body container.

        Args:
            widget (Widget): New step widget to render.
        """
        assert self._body is not None
        await self._body.remove_children()
        await self._body.mount(widget)
