"""``AuthenticationScreen`` — the modal that drives the auth flow (02.b.5)."""

from __future__ import annotations

import asyncio
from typing import Callable, Optional, Protocol

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widget import Widget

from config.logger import log_error, log_info
from src.auth.credential_dao import (
    AuthenticationFileDAO,
    AuthType,
    CredentialDAO,
    ProviderName,
)
from src.auth.credential_store import CredentialStore
from src.auth.oauth_errors import (
    OAuthCallbackPortInUseError,
    OAuthStateError,
    OAuthTimeoutError,
    OAuthTokenError,
)
from src.auth.oauth_flow import OAuthFlow
from src.auth.provider_factory import OAuthFlowFactory
from src.tui.authentication.auth_state import ScreenState
from src.tui.authentication.widgets.api_key_input import ApiKeyInputWidget
from src.tui.authentication.widgets.method_select import MethodSelectWidget
from src.tui.authentication.widgets.oauth_status import OAuthStatusWidget
from src.tui.authentication.widgets.provider_select import ProviderSelectWidget
from src.tui.authentication.widgets.success_widget import SuccessWidget

__all__ = ["AuthenticationScreen", "OAuthFactory"]


class OAuthFactory(Protocol):
    """Builds a fresh ``OAuthFlow`` for a given provider.

    The Protocol shape forces keyword-only calls at the call site so
    ``self._oauth_factory(provider=provider)`` is the only valid form,
    matching the named-arguments convention.
    """

    def __call__(self, *, provider: ProviderName) -> OAuthFlow:
        """Return a fresh ``OAuthFlow`` wired for ``provider``."""
        ...


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
    ) -> None:
        """Wire up dependencies with production defaults.

        Args:
            store (Optional[CredentialStore]): Persistence layer.
                Defaults to a store rooted at ``cfg("SLO_AUTH_FILE")``.
            oauth_factory (Optional[OAuthFactory]): Maps a
                ``ProviderName`` to a fresh ``OAuthFlow``. Defaults to
                ``OAuthFlowFactory.for_provider``.
        """
        super().__init__()
        self._store: CredentialStore = store or CredentialStore()
        self._oauth_factory: OAuthFactory = oauth_factory or self._default_oauth_factory
        self._state: ScreenState = ScreenState.PROVIDER
        self._chosen_provider: Optional[ProviderName] = None
        self._oauth_task: Optional[asyncio.Task[CredentialDAO]] = None
        self._body: Optional[Vertical] = None

    @staticmethod
    def _default_oauth_factory(*, provider: ProviderName) -> OAuthFlow:
        """Build a production ``OAuthFlow`` for ``provider``.

        Used as the default for the ``oauth_factory`` constructor argument
        so the type is explicit and callable without a lambda.

        Args:
            provider (ProviderName): The provider to wire the flow for.

        Returns:
            OAuthFlow: A fresh flow obtained from ``OAuthFlowFactory``.
        """
        return OAuthFlowFactory.for_provider(provider=provider)

    def compose(self) -> ComposeResult:
        """Mount the initial ``ProviderSelectWidget`` inside a body container."""
        with Vertical(id="auth-modal-body") as body:
            self._body = body
            yield ProviderSelectWidget(id="auth-step")

    async def action_cancel(self) -> None:
        """Dismiss with ``None``; cancel the OAuth task if it is in flight."""
        await self._cancel_oauth_if_running()
        self.dismiss(None)

    # ---- Provider-select handlers ----

    async def on_provider_select_widget_chosen(self, event: ProviderSelectWidget.Chosen) -> None:
        """Move to method step, or directly to API-key for API-key-only providers.

        Kimi For Coding only supports API-key authentication, so the
        ``MethodSelectWidget`` step is skipped for that provider.

        Args:
            event (ProviderSelectWidget.Chosen): Carries ``provider``.
        """
        self._chosen_provider = event.provider
        if event.provider is ProviderName.KIMI_FOR_CODING:
            await self._swap_step(widget=ApiKeyInputWidget(provider=event.provider))
            self._state = ScreenState.API_KEY
            return
        await self._swap_step(widget=MethodSelectWidget(provider=event.provider))
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
        if event.method is AuthType.OAUTH:
            await self._begin_oauth(provider=self._chosen_provider)
            return
        await self._swap_step(widget=ApiKeyInputWidget(provider=self._chosen_provider))
        self._state = ScreenState.API_KEY

    async def on_method_select_widget_back_requested(self, event: MethodSelectWidget.BackRequested) -> None:
        """Go back to provider selection."""
        await self._swap_step(widget=ProviderSelectWidget())
        self._state = ScreenState.PROVIDER

    async def on_method_select_widget_cancelled(self, event: MethodSelectWidget.Cancelled) -> None:
        """Cancel from method step."""
        await self.action_cancel()

    # ---- OAuth-status handlers ----

    async def on_oauth_status_widget_back_requested(self, event: OAuthStatusWidget.BackRequested) -> None:
        """Cancel the in-flight OAuth task and re-show method-select."""
        await self._cancel_oauth_if_running()
        assert self._chosen_provider is not None
        await self._swap_step(widget=MethodSelectWidget(provider=self._chosen_provider))
        self._state = ScreenState.METHOD

    async def on_oauth_status_widget_cancelled(self, event: OAuthStatusWidget.Cancelled) -> None:
        """Cancel from OAuth step."""
        await self.action_cancel()

    # ---- API-key handlers ----

    async def on_api_key_input_widget_submitted(self, event: ApiKeyInputWidget.Submitted) -> None:
        """Persist the pasted key and move to success.

        Args:
            event (ApiKeyInputWidget.Submitted): Carries the raw key.
        """
        assert self._chosen_provider is not None
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

        Kimi For Coding has no method-selection step, so Back from the API-key
        widget returns directly to provider selection.
        """
        assert self._chosen_provider is not None
        if self._chosen_provider is ProviderName.KIMI_FOR_CODING:
            await self._swap_step(widget=ProviderSelectWidget())
            self._state = ScreenState.PROVIDER
            return
        await self._swap_step(widget=MethodSelectWidget(provider=self._chosen_provider))
        self._state = ScreenState.METHOD

    async def on_api_key_input_widget_cancelled(self, event: ApiKeyInputWidget.Cancelled) -> None:
        """Cancel from API-key step."""
        await self.action_cancel()

    # ---- Success handler ----

    async def on_success_widget_closed(self, event: SuccessWidget.Closed) -> None:
        """Final dismiss returns the persisted credential."""
        cred: Optional[CredentialDAO] = self._oauth_result() or self._last_persisted()
        self.dismiss(cred)

    # ---- Internal helpers ----

    async def _begin_oauth(self, *, provider: ProviderName) -> None:
        """Swap to the status widget and spawn the OAuth task.

        Args:
            provider (ProviderName): The provider the user picked.
        """
        flow: OAuthFlow = self._oauth_factory(provider=provider)
        status: OAuthStatusWidget = OAuthStatusWidget(provider=provider)
        await self._swap_step(widget=status)
        self._state = ScreenState.OAUTH
        self._oauth_task = asyncio.create_task(flow.start())
        self._oauth_task.add_done_callback(self._on_oauth_done)

    def _on_oauth_done(self, task: asyncio.Task[CredentialDAO]) -> None:
        """Done callback — persist on success, render error on failure.

        Args:
            task (asyncio.Task[CredentialDAO]): The completed OAuth task.
        """
        if task.cancelled():
            return
        exc: Optional[BaseException] = task.exception()
        if exc is not None:
            self._render_oauth_error(exc=exc)
            return
        cred: CredentialDAO = task.result()
        self._store.persist(cred=cred)
        log_info(msg=f"AuthenticationScreen persisted oauth provider={cred.provider.value}")
        asyncio.create_task(self._swap_step(widget=SuccessWidget(subject=cred.subject)))
        self._state = ScreenState.SUCCESS

    _ERROR_MESSAGES: dict[type[BaseException], Callable[[BaseException], str]] = {
        OAuthTimeoutError: lambda exc: "Sign-in timed out. Use Back to retry.",
        OAuthStateError: lambda exc: "Sign-in failed: state mismatch. Use Back to retry.",
        OAuthCallbackPortInUseError: (
            lambda exc: "Sign-in failed: Slo could not bind the local callback port. "
            "Another process may already be using it. Free the port and retry."
        ),
        OAuthTokenError: lambda exc: f"Sign-in failed: {exc}",
    }
    """Lookup table replacing the OAuth-error isinstance chain.

    Each entry maps an exception class to a callable that produces the
    user-facing message. Unknown exception types fall through to the
    default branch in :meth:`_render_oauth_error`.
    """

    def _render_oauth_error(self, *, exc: BaseException) -> None:
        """Update the OAuthStatus widget's error region.

        Args:
            exc (BaseException): The exception the task raised.
        """
        status: OAuthStatusWidget = self.query_one(OAuthStatusWidget)
        message_builder: Optional[Callable[[BaseException], str]] = self._ERROR_MESSAGES.get(type(exc))
        if message_builder is not None:
            status.set_error(message=message_builder(exc))
            return
        log_error(msg="AuthenticationScreen: unexpected OAuth exception", e=exc)
        status.set_error(message=f"Sign-in failed: {exc}")

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
