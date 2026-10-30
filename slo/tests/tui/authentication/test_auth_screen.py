"""Tests for ``AuthenticationScreen`` capability and OAuth task ownership."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NoReturn, Optional, Protocol

import pytest
from textual.app import App
from textual.widgets import Input, RadioButton, RadioSet, Static

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore
from src.auth.device_authorization import DeviceAuthorizationFlow
from src.auth.oauth_errors import OAuthTimeoutError, OAuthTokenError
from src.auth.oauth_flow import AuthorizationPresentationDAO
from src.auth.oauth_provider import DeviceAuthorizationPresentationDAO, OAuthLoginMethod
from src.auth.provider_factory import OAuthAuthenticationFlow
from src.tui.authentication import AuthenticationScreen
from src.tui.authentication.widgets.api_key_input import ApiKeyInputWidget
from src.tui.authentication.widgets.method_select import MethodSelectWidget
from src.tui.authentication.widgets.oauth_status import OAuthStatusWidget
from src.tui.authentication.widgets.provider_select import ProviderSelectWidget
from tests.tui.authentication._painted_output import wait_until_painted


def _build_store(tmp_path: Path) -> CredentialStore:
    """Return a temporary credential store for one test."""
    return CredentialStore(path=tmp_path / "global" / "authentication.json")


class _FauxFlow:
    """One injected flow whose result is scriptable without network access."""

    def __init__(self, *, invoke: Callable[[], Awaitable[CredentialDAO]]) -> None:
        """Store the one scripted interaction gateway."""
        self._invoke: Callable[[], Awaitable[CredentialDAO]] = invoke

    async def invoke(self) -> CredentialDAO:
        """Run the scripted credential outcome."""
        return await self._invoke()


class _BuildFlow(Protocol):
    """Keyword-only script contract consumed by the recording OAuth factory."""

    def __call__(
        self,
        *,
        provider: ProviderName,
        login_method: OAuthLoginMethod,
        browser_present: Callable[[AuthorizationPresentationDAO], None],
        device_present: Callable[[DeviceAuthorizationPresentationDAO], None],
        receiver: Callable[[], Awaitable[str]] | None,
        callback_unavailable: Callable[[], None],
    ) -> OAuthAuthenticationFlow:
        """Build a scripted interaction from the modal's captured callbacks."""
        ...


class _FauxOAuthFactory:
    """Record factory calls and provide declared capabilities to the modal."""

    def __init__(
        self,
        *,
        login_methods: frozenset[OAuthLoginMethod],
        build_flow: _BuildFlow,
    ) -> None:
        """Store capability and flow scripts for the test journey."""
        self._login_methods: frozenset[OAuthLoginMethod] = login_methods
        self._build_flow = build_flow
        self.supported_calls: list[ProviderName] = []
        self.calls: list[dict[str, object]] = []

    def supported_login_methods(self, *, provider: ProviderName) -> frozenset[OAuthLoginMethod]:
        """Return the configured capability set and record the single read."""
        self.supported_calls.append(provider)
        return self._login_methods

    def __call__(
        self,
        *,
        provider: ProviderName,
        login_method: OAuthLoginMethod,
        present_browser_authorization: Callable[[AuthorizationPresentationDAO], None],
        present_device_authorization: Callable[[DeviceAuthorizationPresentationDAO], None],
        authorization_response_receiver: Callable[[], Awaitable[str]] | None,
        present_callback_unavailable: Callable[[], None] = lambda: None,
    ) -> OAuthAuthenticationFlow:
        """Record exact five-argument wiring and build the scripted flow."""
        self.calls.append(
            {
                "provider": provider,
                "login_method": login_method,
                "present_browser_authorization": present_browser_authorization,
                "present_device_authorization": present_device_authorization,
                "authorization_response_receiver": authorization_response_receiver,
                "present_callback_unavailable": present_callback_unavailable,
            }
        )
        return self._build_flow(
            provider=provider,
            login_method=login_method,
            browser_present=present_browser_authorization,
            device_present=present_device_authorization,
            receiver=authorization_response_receiver,
            callback_unavailable=present_callback_unavailable,
        )


class _Harness(App):
    """Push the authentication modal and record its dismissal result."""

    def __init__(self, *, store: CredentialStore, oauth_factory: _FauxOAuthFactory) -> None:
        """Save injected collaborators for the mounted modal."""
        super().__init__()
        self._store: CredentialStore = store
        self._oauth_factory: _FauxOAuthFactory = oauth_factory
        self.dismissed_with: Optional[CredentialDAO] = None
        self.completed: asyncio.Event = asyncio.Event()

    def on_mount(self) -> None:
        """Push the modal after the application is ready."""
        self.push_screen(
            AuthenticationScreen(store=self._store, oauth_factory=self._oauth_factory),
            callback=self._on_dismiss,
        )

    def _on_dismiss(self, value: Optional[CredentialDAO]) -> None:
        """Record the modal result for test assertions."""
        self.dismissed_with = value
        self.completed.set()


def _credential(*, provider: ProviderName) -> CredentialDAO:
    """Create a completed, non-secret test credential."""
    return CredentialDAO(
        provider=provider,
        auth_type=AuthType.OAUTH,
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        subject="test@example.invalid",
    )


async def _never_complete() -> CredentialDAO:
    """Block until cancelled, representing an in-flight OAuth attempt."""
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


class TestAuthenticationScreen:
    """Screen owns capabilities, exactly one flow task, response queue, and persistence."""

    @pytest.mark.asyncio
    async def test_browser_selection_wires_the_verbatim_five_factory_arguments_and_submits_once(
        self, tmp_path: Path
    ) -> None:
        """Browser selection builds one queue-backed flow and rejects a second response."""
        received_responses: list[str] = []

        def _build_flow(
            provider: ProviderName,
            login_method: OAuthLoginMethod,
            browser_present: Callable[[AuthorizationPresentationDAO], None],
            device_present: Callable[[DeviceAuthorizationPresentationDAO], None],
            receiver: Callable[[], Awaitable[str]] | None,
            callback_unavailable: Callable[[], None],
        ) -> OAuthAuthenticationFlow:
            """Present dummy browser instructions then await one opaque response."""
            assert receiver is not None
            receiver_for_flow: Callable[[], Awaitable[str]] = receiver

            async def _invoke() -> CredentialDAO:
                """Complete after the receiver yields one response."""
                browser_present(
                    AuthorizationPresentationDAO(
                        authorize_url="https://example.invalid/dummy-browser",
                        redirect_uri="http://localhost:1455/auth/callback",
                        instructions="unused",
                    )
                )
                received_responses.append(await receiver_for_flow())
                return _credential(provider=provider)

            return _FauxFlow(invoke=_invoke)

        factory: _FauxOAuthFactory = _FauxOAuthFactory(
            login_methods=frozenset({OAuthLoginMethod.BROWSER_AUTHORIZATION}),
            build_flow=_build_flow,
        )
        store: CredentialStore = _build_store(tmp_path)
        harness: _Harness = _Harness(store=store, oauth_factory=factory)
        async with harness.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()
            await pilot.click("#method-continue")
            await pilot.pause()
            status: OAuthStatusWidget = pilot.app.screen.query_one(OAuthStatusWidget)
            response_input: Input = status.query_one("#oauth-response-input", Input)
            response_input.value = "first-opaque-response"
            status._submit_authorization_response()
            response_input.value = "second-opaque-response"
            status._submit_authorization_response()
            await pilot.pause()
            await pilot.pause()

            assert len(factory.calls) == 1
            call: dict[str, object] = factory.calls[0]
            assert call["provider"] is ProviderName.ANTHROPIC
            assert call["login_method"] is OAuthLoginMethod.BROWSER_AUTHORIZATION
            assert callable(call["present_browser_authorization"])
            assert callable(call["present_device_authorization"])
            assert callable(call["authorization_response_receiver"])
            assert callable(call["present_callback_unavailable"])

        assert received_responses in ([], ["first-opaque-response"])
        assert store.load().providers.get(ProviderName.ANTHROPIC) is None or (
            store.load().providers[ProviderName.ANTHROPIC].auth_type is AuthType.OAUTH
        )

    @pytest.mark.asyncio
    async def test_method_capabilities_are_resolved_once_and_reused_on_back(self, tmp_path: Path) -> None:
        """Forward selection and Back use the cached set without a second factory read."""
        factory: _FauxOAuthFactory = _FauxOAuthFactory(
            login_methods=frozenset(
                {OAuthLoginMethod.BROWSER_AUTHORIZATION, OAuthLoginMethod.DEVICE_AUTHORIZATION}
            ),
            build_flow=lambda provider, login_method, browser_present, device_present, receiver, callback_unavailable: _FauxFlow(
                invoke=_never_complete
            ),
        )
        harness: _Harness = _Harness(store=_build_store(tmp_path), oauth_factory=factory)
        async with harness.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()
            selector: MethodSelectWidget = pilot.app.screen.query_one(MethodSelectWidget)
            assert len(list(selector.query(RadioButton))) == 3
            await pilot.click("#method-continue")
            await pilot.pause()
            pilot.app.screen.query_one(OAuthStatusWidget).post_message(OAuthStatusWidget.BackRequested())
            await pilot.pause()
            assert pilot.app.screen.query_one(MethodSelectWidget) is not None

        assert factory.supported_calls == [ProviderName.ANTHROPIC]

    @pytest.mark.asyncio
    async def test_device_flow_persists_only_completed_credential(self, tmp_path: Path) -> None:
        """Device selection presents safe instructions and persists exactly the returned DAO."""

        def _build_flow(
            provider: ProviderName,
            login_method: OAuthLoginMethod,
            browser_present: Callable[[AuthorizationPresentationDAO], None],
            device_present: Callable[[DeviceAuthorizationPresentationDAO], None],
            receiver: Callable[[], Awaitable[str]] | None,
            callback_unavailable: Callable[[], None],
        ) -> OAuthAuthenticationFlow:
            """Build a completed device flow with no browser receiver."""
            assert login_method is OAuthLoginMethod.DEVICE_AUTHORIZATION
            assert receiver is None

            async def _invoke() -> CredentialDAO:
                """Publish safe device copy before returning its credential."""
                device_present(
                    DeviceAuthorizationPresentationDAO(
                        verification_uri="https://example.invalid/device",
                        user_code="DUMMY-ONLY",
                        expires_in_seconds=900,
                    )
                )
                return _credential(provider=provider)

            return _FauxFlow(invoke=_invoke)

        factory: _FauxOAuthFactory = _FauxOAuthFactory(
            login_methods=frozenset(
                {OAuthLoginMethod.BROWSER_AUTHORIZATION, OAuthLoginMethod.DEVICE_AUTHORIZATION}
            ),
            build_flow=_build_flow,
        )
        store: CredentialStore = _build_store(tmp_path)
        harness: _Harness = _Harness(store=store, oauth_factory=factory)
        async with harness.run_test() as pilot:
            await pilot.pause()
            radio_set: RadioSet = pilot.app.screen.query_one("#provider-radio", RadioSet)
            await pilot.click(list(radio_set.query(RadioButton))[1])
            await pilot.click("#provider-continue")
            await pilot.pause()
            await pilot.click("#method-device_authorization")
            await pilot.click("#method-continue")
            await pilot.pause()
            await pilot.pause()

        assert store.load().providers[ProviderName.OPENAI].auth_type is AuthType.OAUTH
        assert len(factory.calls) == 1

    @pytest.mark.asyncio
    async def test_back_cancel_and_escape_discard_browser_queue_without_persisting(
        self, tmp_path: Path
    ) -> None:
        """All cancellation routes await task cancellation and clear queue ownership."""
        factory: _FauxOAuthFactory = _FauxOAuthFactory(
            login_methods=frozenset({OAuthLoginMethod.BROWSER_AUTHORIZATION}),
            build_flow=lambda provider, login_method, browser_present, device_present, receiver, callback_unavailable: _FauxFlow(
                invoke=_never_complete
            ),
        )
        store: CredentialStore = _build_store(tmp_path)
        harness: _Harness = _Harness(store=store, oauth_factory=factory)
        async with harness.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()
            await pilot.click("#method-continue")
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, AuthenticationScreen)
            assert screen._authorization_response_queue is not None
            await screen.on_oauth_status_widget_back_requested(OAuthStatusWidget.BackRequested())
            await pilot.pause()
            assert screen._authorization_response_queue is None
            await pilot.press("escape")
            await harness.completed.wait()

        assert store.load().providers == {}

    @pytest.mark.asyncio
    async def test_timeout_and_static_token_copy_are_safe_and_distinguishable(self, tmp_path: Path) -> None:
        """Callback/attempt timeout and token failures have static body-free user copy."""
        outcomes: list[BaseException] = [
            OAuthTimeoutError(kind="callback"),
            OAuthTimeoutError(kind="attempt"),
            OAuthTokenError(status=500),
        ]
        messages: list[str] = []
        for outcome in outcomes:
            factory: _FauxOAuthFactory = _FauxOAuthFactory(
                login_methods=frozenset({OAuthLoginMethod.BROWSER_AUTHORIZATION}),
                build_flow=lambda provider, login_method, browser_present, device_present, receiver, callback_unavailable, result=outcome: _FauxFlow(
                    invoke=lambda: _raise(result)
                ),
            )
            harness: _Harness = _Harness(store=_build_store(tmp_path), oauth_factory=factory)
            async with harness.run_test() as pilot:
                await pilot.pause()
                await pilot.click("#provider-continue")
                await pilot.pause()
                await pilot.click("#method-continue")
                await pilot.pause()
                await pilot.pause()
                messages.append(str(pilot.app.screen.query_one("#oauth-error", Static).content))

        assert messages[0] != messages[1]
        assert messages[2] == "Sign-in failed. Use Back to retry."
        assert "500" not in messages[2]

    def test_default_oauth_factory_builds_selected_flow_without_injection(self, tmp_path: Path) -> None:
        """The production default factory accepts the exact call ``_begin_oauth`` makes.

        Regression: the default was the ``OAuthFlowFactory`` class, so this call raised
        ``TypeError`` inside an unobserved task and the modal never painted instructions.
        Constructing a device flow performs no network activity.
        """
        screen: AuthenticationScreen = AuthenticationScreen(store=_build_store(tmp_path))

        flow: OAuthAuthenticationFlow = screen._oauth_factory(
            provider=ProviderName.OPENAI,
            login_method=OAuthLoginMethod.DEVICE_AUTHORIZATION,
            present_browser_authorization=lambda presentation: None,
            present_device_authorization=lambda presentation: None,
            authorization_response_receiver=None,
            present_callback_unavailable=lambda: None,
        )

        assert isinstance(flow, DeviceAuthorizationFlow)


class TestBeginOAuthFailure:
    """A failure before the flow starts paints the safe error instead of being lost."""

    @pytest.mark.asyncio
    async def test_method_selection_when_factory_raises_paints_safe_error(self, tmp_path: Path) -> None:
        """A factory that raises (Defect 1b's shape) paints the generic sign-in error in the viewport."""
        factory: _FauxOAuthFactory = _FauxOAuthFactory(
            login_methods=frozenset({OAuthLoginMethod.BROWSER_AUTHORIZATION}),
            build_flow=_raise_type_error,
        )
        harness: _Harness = _Harness(store=_build_store(tmp_path), oauth_factory=factory)
        async with harness.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()
            await pilot.click("#method-continue")
            painted: str = await wait_until_painted(pilot=pilot, text=_GENERIC_SIGN_IN_ERROR)

        assert "".join(_GENERIC_SIGN_IN_ERROR.split()) in painted

    @pytest.mark.asyncio
    async def test_method_selection_when_factory_raises_discards_response_channel(
        self, tmp_path: Path
    ) -> None:
        """A failed start closes the browser response channel, so a later paste is not silently queued."""
        factory: _FauxOAuthFactory = _FauxOAuthFactory(
            login_methods=frozenset({OAuthLoginMethod.BROWSER_AUTHORIZATION}),
            build_flow=_raise_type_error,
        )
        harness: _Harness = _Harness(store=_build_store(tmp_path), oauth_factory=factory)
        async with harness.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.click("#provider-continue")
            await pilot.pause()
            await pilot.click("#method-continue")
            await wait_until_painted(pilot=pilot, text=_GENERIC_SIGN_IN_ERROR)
            screen = pilot.app.screen
            assert isinstance(screen, AuthenticationScreen)

            assert screen._authorization_response_queue is None

    @pytest.mark.asyncio
    async def test_begin_oauth_done_when_no_status_widget_leaves_step_unchanged(self, tmp_path: Path) -> None:
        """A failure before the status widget mounts has nowhere to paint and must not raise."""
        factory: _FauxOAuthFactory = _FauxOAuthFactory(
            login_methods=frozenset({OAuthLoginMethod.BROWSER_AUTHORIZATION}),
            build_flow=_raise_type_error,
        )
        harness: _Harness = _Harness(store=_build_store(tmp_path), oauth_factory=factory)
        async with harness.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, AuthenticationScreen)
            failed: asyncio.Task[None] = asyncio.create_task(_fail_before_flow())
            await asyncio.wait({failed})

            screen._on_begin_oauth_done(failed)
            await pilot.pause()

            assert len(screen.query(ProviderSelectWidget)) == 1
            assert len(screen.query(OAuthStatusWidget)) == 0

    @pytest.mark.asyncio
    async def test_begin_oauth_done_when_task_cancelled_returns_quietly(self, tmp_path: Path) -> None:
        """A cancelled start task is not a failure and paints nothing."""
        factory: _FauxOAuthFactory = _FauxOAuthFactory(
            login_methods=frozenset({OAuthLoginMethod.BROWSER_AUTHORIZATION}),
            build_flow=_raise_type_error,
        )
        harness: _Harness = _Harness(store=_build_store(tmp_path), oauth_factory=factory)
        async with harness.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, AuthenticationScreen)
            cancelled: asyncio.Task[None] = asyncio.create_task(_never_start())
            await pilot.pause()
            cancelled.cancel()
            await asyncio.wait({cancelled})

            screen._on_begin_oauth_done(cancelled)
            await pilot.pause()

            assert len(screen.query(ProviderSelectWidget)) == 1


_GENERIC_SIGN_IN_ERROR: str = "Sign-in failed. Use Back to retry."


def _raise_type_error(
    *,
    provider: ProviderName,
    login_method: OAuthLoginMethod,
    browser_present: Callable[[AuthorizationPresentationDAO], None],
    device_present: Callable[[DeviceAuthorizationPresentationDAO], None],
    receiver: Callable[[], Awaitable[str]] | None,
    callback_unavailable: Callable[[], None],
) -> NoReturn:
    """Fail flow construction the way the uncallable default factory did.

    Raises:
        TypeError: Always.
    """
    raise TypeError("factory is not callable")


async def _fail_before_flow() -> None:
    """Fail like a mount error inside ``_begin_oauth`` before any status widget exists.

    Raises:
        RuntimeError: Always.
    """
    raise RuntimeError("mount failed")


async def _never_start() -> None:
    """Wait until cancelled, like a start task abandoned by the screen."""
    await asyncio.Event().wait()


async def _raise(exc: BaseException) -> CredentialDAO:
    """Raise one scripted safe failure from an injected faux flow."""
    raise exc
