"""Bounded modal integration for API-key-only OpenRouter authentication."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from src.agents.model_catalog.dao import CatalogRefreshResultDAO
from textual.app import App
from textual.widgets import Button, Input, Static

from src.auth.credential_dao import AuthType, CredentialDAO, OpenRouterAuthenticationResultDAO, ProviderName
from src.auth.credential_store import CredentialStore
from src.auth.openrouter_authentication import OpenRouterAuthenticationService
from src.auth.provider_factory import OAuthFlowFactory
from src.integrations.openrouter.client import OpenRouterAPIClient
from src.tui.authentication.auth_screen import AuthenticationScreen
from src.tui.authentication.widgets.api_key_input import ApiKeyInputWidget
from src.tui.authentication.widgets.provider_select import ProviderSelectWidget
from src.tui.authentication.widgets.success_widget import SuccessWidget
from tests.tui.authentication._painted_output import assert_widget_painted, wait_until_painted


@pytest.mark.parametrize("provider", [ProviderName.OPENROUTER, ProviderName.KIMI_FOR_CODING])
def test_api_key_only_capability(provider: ProviderName) -> None:
    """Both API-key-only providers expose an empty OAuth capability set."""
    assert not OAuthFlowFactory.supported_login_methods(provider=provider)


@pytest.mark.parametrize("navigation", ["back", "cancel", "unmount"])
async def test_openrouter_modal_delegates_and_cancels(tmp_path: Path, navigation: str) -> None:
    """Submission is tracked, cleared, duplicate-disabled and awaited on Back."""
    path = (tmp_path / "private" / "authentication.json").resolve()
    assert path.is_relative_to(tmp_path.resolve())
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def invoke(*, submitted_key: str) -> OpenRouterAuthenticationResultDAO:
        """Block a synthetic attempt until modal cancellation reaches it."""
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return OpenRouterAuthenticationResultDAO(safe_message="Unused.")

    service = Mock(spec=OpenRouterAuthenticationService)
    service.invoke = AsyncMock(side_effect=invoke)
    service.result = OpenRouterAuthenticationResultDAO(
        safe_message="Authentication cancelled; no key was saved."
    )
    screen = AuthenticationScreen(store=CredentialStore(path=path), openrouter_factory=lambda: service)
    app: App[None] = App()
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        assert ProviderName.OPENROUTER in [provider for provider, _ in ProviderSelectWidget.PROVIDERS]
        await screen.on_provider_select_widget_chosen(
            ProviderSelectWidget.Chosen(provider=ProviderName.OPENROUTER)
        )
        widget = screen.query_one(ApiKeyInputWidget)
        widget.query_one(Input).value = "candidate-sentinel"
        await pilot.pause()
        assert await pilot.click("#api-key-save")
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert widget.query_one("#api-key-save", Button).disabled
        assert widget.query_one(Input).value == ""
        await screen.on_api_key_input_widget_submitted(ApiKeyInputWidget.Submitted(api_key="duplicate"))
        if navigation == "back":
            await screen.on_api_key_input_widget_back_requested(ApiKeyInputWidget.BackRequested())
            assert screen.query(ProviderSelectWidget)
            await screen.on_provider_select_widget_chosen(
                ProviderSelectWidget.Chosen(provider=ProviderName.KIMI_FOR_CODING)
            )
            assert screen._openrouter_service is None
        elif navigation == "cancel":
            await screen.action_cancel()
        else:
            await app.pop_screen()
        assert cancelled.is_set()
        service.invoke.assert_awaited_once_with(submitted_key="candidate-sentinel")
        assert not path.exists()


@pytest.mark.parametrize("size", [(80, 24), (60, 15)])
@pytest.mark.parametrize("verified", [False, True])
async def test_modal_paints_safe_result(tmp_path: Path, size: tuple[int, int], verified: bool) -> None:
    """The actual modal paints literal safe status and never paints the submitted key."""
    path = (tmp_path / "private" / "authentication.json").resolve()
    assert path.is_relative_to(tmp_path.resolve())
    service = Mock(spec=OpenRouterAuthenticationService)
    message = "Key verified; catalog checked." if verified else "Authentication failed [retry]."
    service.invoke = AsyncMock(
        return_value=OpenRouterAuthenticationResultDAO(key_verified=verified, safe_message=message)
    )
    screen = AuthenticationScreen(store=CredentialStore(path=path), openrouter_factory=lambda: service)
    app: App[None] = App()
    async with app.run_test(size=size) as pilot:
        await app.push_screen(screen)
        await screen.on_provider_select_widget_chosen(
            ProviderSelectWidget.Chosen(provider=ProviderName.OPENROUTER)
        )
        screen.query_one(Input).value = "candidate-sentinel"
        await screen.query_one(ApiKeyInputWidget)._handle_save()
        painted = await wait_until_painted(pilot=pilot, text=message)
        assert "".join(message.split()) in painted
        assert "sentinel" not in painted
        assert ("Close" if verified else "Cancel") in painted


@pytest.mark.parametrize("size", [(80, 24), (60, 15)])
async def test_mounted_listing_credential_change_paints_retry_without_success(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    """A real mounted modal paints listing-time credential rotation as a retry, not success."""
    path = (tmp_path / "private" / "authentication.json").resolve()
    assert path.is_relative_to(tmp_path.resolve())
    store = CredentialStore(path=path)
    catalog = Mock()
    refresh_started = asyncio.Event()
    release_refresh = asyncio.Event()

    async def refresh(**kwargs: object) -> CatalogRefreshResultDAO:
        """Hold catalog refresh until the mounted modal has a visible loading state."""
        del kwargs
        refresh_started.set()
        await release_refresh.wait()
        return CatalogRefreshResultDAO(
            status="credential_changed", catalog_generation=3, safe_message="raw-sentinel"
        )

    catalog.refresh = AsyncMock(side_effect=refresh)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code=200, json={"data": {}}))
    ) as http:

        def client_factory(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Construct the actual local-only verification client."""
            return OpenRouterAPIClient(credential=credential, http_client=http)

        service = OpenRouterAuthenticationService(
            store=store,
            client_factory=client_factory,
            catalog_service=catalog,
        )
        screen = AuthenticationScreen(store=store, openrouter_factory=lambda: service)
        app: App[None] = App()
        async with app.run_test(size=size) as pilot:
            await app.push_screen(screen)
            await screen.on_provider_select_widget_chosen(
                ProviderSelectWidget.Chosen(provider=ProviderName.OPENROUTER)
            )
            screen.query_one(Input).value = "listing-change-candidate"
            await screen.query_one(ApiKeyInputWidget)._handle_save()
            await asyncio.wait_for(refresh_started.wait(), timeout=2)
            release_refresh.set()
            message = "Credential changed; retry authentication."
            status_widget = screen.query_one("#api-key-error", Static)
            painted = await wait_until_painted(pilot=pilot, text=message, widget=status_widget)
            assert_widget_painted(app=app, widget=status_widget, text=message)
            viewport = "".join(strip.text for strip in screen._compositor.render_strips())
            assert "listing-change-candidate" not in viewport
            assert "raw-sentinel" not in viewport
            assert "listing-change-candidate" not in painted
            assert not screen.query(SuccessWidget)
            assert screen.query(ApiKeyInputWidget)
            assert service.verified_credential() is None


async def test_mounted_post_save_cancellation_paints_saved_state(tmp_path: Path) -> None:
    """A real mounted modal preserves and presents a key saved before cancellation."""
    path = (tmp_path / "private" / "authentication.json").resolve()
    assert path.is_relative_to(tmp_path.resolve())
    store = CredentialStore(path=path)
    catalog = Mock()
    refresh_started = asyncio.Event()

    async def refresh(**kwargs: object) -> CatalogRefreshResultDAO:
        """Block after persistence until navigation cancels the tracked attempt."""
        del kwargs
        refresh_started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    catalog.refresh = AsyncMock(side_effect=refresh)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code=200, json={"data": {}}))
    ) as http:

        def client_factory(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Construct the real local-only verification client."""
            return OpenRouterAPIClient(credential=credential, http_client=http)

        service = OpenRouterAuthenticationService(
            store=store,
            client_factory=client_factory,
            catalog_service=catalog,
        )
        screen = AuthenticationScreen(store=store, openrouter_factory=lambda: service)
        app: App[None] = App()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.push_screen(screen)
            await screen.on_provider_select_widget_chosen(
                ProviderSelectWidget.Chosen(provider=ProviderName.OPENROUTER)
            )
            screen.query_one(Input).value = "mounted-post-save-candidate"
            await screen.query_one(ApiKeyInputWidget)._handle_save()
            await asyncio.wait_for(refresh_started.wait(), timeout=2)
            await screen.on_api_key_input_widget_back_requested(ApiKeyInputWidget.BackRequested())
            assert service.result.safe_message == "Authentication cancelled; verified key was saved."
            assert screen.query(ProviderSelectWidget)
    assert store.load().providers[ProviderName.OPENROUTER].access_token == "mounted-post-save-candidate"
    assert service.result.replacement_saved


def test_auth_dismissal_without_landing_model_preserves_active_route() -> None:
    """A newly authenticated provider without a default cannot switch to None."""
    from src.tui.app import SloTUI

    app = Mock(spec=SloTUI)
    app._session = Mock(active_model_name="gpt-6-astra")
    with patch("src.tui.app.default_model_for_provider", return_value=None):
        SloTUI._on_auth_dismissed(
            app,
            value=CredentialDAO(
                provider=ProviderName.OPENROUTER,
                auth_type=AuthType.API_KEY,
                access_token="candidate-sentinel",
            ),
        )
    app._session.switch_model.assert_not_called()
