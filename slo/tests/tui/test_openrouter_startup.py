"""Offline pending startup contracts through the production session and app."""

import asyncio
from contextlib import nullcontext
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage

from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO
from src.agents.model_catalog.seed import SeedModelCatalog
from src.cli.typer_dispatch import TyperDispatch
from src.agents.model_catalog.service import ModelCatalogService, ModelPreparationRequiredError
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.auth.credential_store import CredentialStore
from src.channels.dao import ChannelMessageDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.integrations.openrouter.client import OpenRouterAPIClient
from src.tui.app import SloTUI
from tests.conftest import GatedFauxChatModel

_REAL_CREDENTIAL_RESOLVE = CredentialResolver.resolve


@pytest.fixture
def real_catalog_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the stored synthetic credential instead of the TUI-wide auth fake."""
    monkeypatch.setattr(CredentialResolver, "resolve", _REAL_CREDENTIAL_RESOLVE)


def test_interactive_dispatch_constructs_pending_session(tmp_path: Path) -> None:
    """The actual synchronous entry does not strict-build a cold OpenRouter route."""
    config = SessionConfigDAO(workdir=tmp_path, model_name="openrouter:author/cold", enable_history=False)
    with (
        patch("src.cli.typer_dispatch.interactive_logging", return_value=nullcontext()),
        patch.object(TyperDispatch, "_build_session_config", return_value=config),
        patch.object(SloAgentSession, "_load_plugins"),
        patch("src.cli.typer_dispatch.SloTUI") as tui,
    ):
        TyperDispatch.tui(workdir=tmp_path)
    session = tui.call_args.kwargs["session"]
    assert session.preparation_status == "pending"
    assert session.active_model_name == config.model_name
    tui.return_value.run.assert_called_once_with(mouse=True)


async def test_unmount_cancels_pending_worker(tmp_path: Path) -> None:
    """Teardown awaits its worker so a late catalog cannot mutate a closed app."""
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def prepare_models(*, model_names: tuple[str, ...]) -> ModelCatalogSnapshotDAO:
        """Wait until the app cancels, without timers or I/O."""
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        raise AssertionError("unreachable")

    with (
        patch.object(ModelCatalogService, "prepare_models", side_effect=prepare_models),
        patch("src.tui.app.ModelSuggestionProjection.refresh_authentication"),
        patch.object(SloTUI, "_has_credential_for_active_model", return_value=True),
        patch.object(SloAgentSession, "_load_plugins"),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path, model_name="openrouter:author/cold", enable_history=False
            ),
            allow_pending_preparation=True,
        )
        app = SloTUI(session=session)
        async with app.run_test():
            await asyncio.wait_for(started.wait(), timeout=2)
        assert cancelled.is_set()
        assert app._preparation_task is not None and app._preparation_task.cancelled()
        assert session.preparation_status == "failed"


async def test_new_openrouter_session_is_pending_and_starts_its_own_worker(tmp_path: Path) -> None:
    """`/new` defers a cold OpenRouter route and starts preparation for its replacement."""
    route = "openrouter:author/cold"
    snapshot = SeedModelCatalog.load()
    entry = snapshot.entries["gpt-5.4"].model_copy(update={"model_name": route})
    snapshot = snapshot.model_copy(update={"entries": {**snapshot.entries, route: entry}})
    started = asyncio.Event()
    release = asyncio.Event()

    async def prepare_models(*, model_names: tuple[str, ...]) -> ModelCatalogSnapshotDAO:
        assert model_names == (route,)
        started.set()
        await release.wait()
        return snapshot

    with (
        patch.object(ModelCatalogService, "load", return_value=snapshot),
        patch.object(ModelCatalogService, "prepare_models", side_effect=prepare_models),
        patch("src.tui.app.ModelSuggestionProjection.refresh_authentication"),
        patch.object(SloTUI, "_has_credential_for_active_model", return_value=True),
        patch.object(SloAgentSession, "_load_plugins"),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, model_name=route, enable_history=False),
            catalog_snapshot=snapshot,
        )
        app = SloTUI(session=session)
        async with app.run_test(size=(100, 28)) as pilot:
            await pilot.pause()
            with patch.object(SloAgentSession, "build", wraps=SloAgentSession.build) as build:
                await app._start_new_session(requested_name=None)
            build.assert_called_once()
            assert build.call_args.kwargs["allow_pending_preparation"] is True
            replacement = app._session
            assert replacement is not session
            assert replacement.active_model_name == route
            assert replacement.preparation_status == "pending"
            await asyncio.wait_for(started.wait(), timeout=2)
            assert app._preparation_task is not None
            release.set()
            await app._preparation_task
            await pilot.pause()
            assert replacement.preparation_status == "ready"
            assert app._session is replacement


async def test_new_cancels_old_preparation_worker_before_replacement(tmp_path: Path) -> None:
    """An old pending worker cannot adopt or render into the replacement session."""
    route = "openrouter:author/cold"
    snapshot = SeedModelCatalog.load()
    entry = snapshot.entries["gpt-5.4"].model_copy(update={"model_name": route})
    snapshot = snapshot.model_copy(update={"entries": {**snapshot.entries, route: entry}})
    old_started = asyncio.Event()
    old_cancelled = asyncio.Event()
    replacement_started = asyncio.Event()
    replacement_release = asyncio.Event()
    calls = 0

    async def prepare_models(*, model_names: tuple[str, ...]) -> ModelCatalogSnapshotDAO:
        nonlocal calls
        assert model_names == (route,)
        calls += 1
        if calls == 1:
            old_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                old_cancelled.set()
        replacement_started.set()
        await replacement_release.wait()
        return snapshot

    with (
        patch.object(ModelCatalogService, "load", return_value=snapshot),
        patch.object(ModelCatalogService, "prepare_models", side_effect=prepare_models),
        patch("src.tui.app.ModelSuggestionProjection.refresh_authentication"),
        patch.object(SloTUI, "_has_credential_for_active_model", return_value=True),
        patch.object(SloAgentSession, "_load_plugins"),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, model_name=route, enable_history=False),
            allow_pending_preparation=True,
        )
        app = SloTUI(session=session)
        async with app.run_test(size=(100, 28)):
            await asyncio.wait_for(old_started.wait(), timeout=2)
            await app._start_new_session(requested_name=None)
            replacement = app._session
            assert replacement is not session
            assert old_cancelled.is_set()
            assert session.preparation_status == "failed"
            await asyncio.wait_for(replacement_started.wait(), timeout=2)
            assert replacement.preparation_status == "pending"
            replacement_release.set()
            assert app._preparation_task is not None
            await app._preparation_task
            assert replacement.preparation_status == "ready"
            assert app._session is replacement


async def test_pending_session_gates_without_resolving_unknown_capabilities(tmp_path: Path) -> None:
    """A cold route retains identity and unknown limits until preparation succeeds."""
    config = SessionConfigDAO(workdir=tmp_path, model_name="openrouter:author/cold", enable_history=False)
    with pytest.raises(ModelPreparationRequiredError):
        SloAgentSession.build(config=config)
    session = SloAgentSession.build(config=config, allow_pending_preparation=True)
    assert session.preparation_status == "pending"
    assert session.active_model_name == config.model_name
    assert session.usage_snapshot().requests_per_minute_limit is None
    assert session.usage_snapshot().context_window_snapshot is None
    with pytest.raises(ModelPreparationRequiredError):
        await anext(session.invoke(text="must not run"))
    with pytest.raises(RuntimeError, match="preparation"):
        session.switch_model(model_name="gpt-5.4")
    direct_snapshot = SeedModelCatalog.load()
    with patch.object(
        ModelCatalogService, "prepare_models", new=AsyncMock(return_value=direct_snapshot)
    ) as prepare:
        result = await session.prepare_model_selection(model_name="openrouter:author/other")
    assert "preparation" in result
    prepare.assert_not_awaited()


async def test_mounted_pending_startup_allows_direct_selection_and_ignores_cancelled_old_worker(
    tmp_path: Path,
) -> None:
    """A mounted direct recovery cancels the old pending worker without restoring its route."""
    snapshot = SeedModelCatalog.load()
    route = "openrouter:author/cold"
    entry = snapshot.entries["gpt-5.4"].model_copy(update={"model_name": route})
    snapshot = snapshot.model_copy(update={"entries": {**snapshot.entries, route: entry}})
    started = asyncio.Event()
    release = asyncio.Event()

    async def prepare_models(*, model_names: tuple[str, ...]) -> ModelCatalogSnapshotDAO:
        """Block only the original OpenRouter startup route behind a lifecycle barrier."""
        if model_names == (route,):
            started.set()
            await release.wait()
        return snapshot

    with (
        patch.object(ModelCatalogService, "load", return_value=snapshot),
        patch.object(ModelCatalogService, "prepare_models", side_effect=prepare_models),
        patch("src.tui.app.ModelSuggestionProjection.refresh_authentication"),
        patch.object(SloTUI, "_has_credential_for_active_model", return_value=True),
        patch.object(SloAgentSession, "_load_plugins"),
        patch("src.agents.slo_agent.sessions.service.CredentialResolver.require"),
        patch("src.agents.slo_agent.sessions.service.UserPreferencesStore.upsert") as save,
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, model_name=route, enable_history=False),
            allow_pending_preparation=True,
        )
        app = SloTUI(session=session)
        async with app.run_test(size=(100, 28)) as pilot:
            await asyncio.wait_for(started.wait(), timeout=2)
            await app._dispatch_slash_command(line="/model gpt-5.4")
            await pilot.pause()
            assert session.active_model_name == "gpt-5.4"
            assert session._agent is None
            assert session.preparation_status == "ready"
            assert session.catalog_snapshot is snapshot
            assert session._config is not None and session._config.model_pool_dao is None
            assert app._preparation_task is not None
            app._preparation_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await app._preparation_task
            assert session.active_model_name == "gpt-5.4"
            release.set()
        save.assert_called_once_with(model_name="gpt-5.4")


@pytest.mark.parametrize("fail", [False, True])
async def test_mounted_startup_shared_worker_gates_and_recovers(
    tmp_path: Path,
    fail: bool,
    monkeypatch: pytest.MonkeyPatch,
    isolated_catalog: CredentialStore,
    real_catalog_credentials: None,
) -> None:
    """Mounted startup retains queued prompts and retries real catalog admission safely."""
    monkeypatch.setenv(name="SLO_CHANNEL_POLL_MS", value="3600000")
    catalog_release: asyncio.Event = asyncio.Event()
    catalog_started: asyncio.Event = asyncio.Event()
    requests: list[str] = []
    key_requests: int = 0
    route: str = "openrouter:vendor/startup-journey"
    secret: str = "fixture-startup-catalog"
    isolated_catalog.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=secret,
        )
    )

    async def _catalog_response(request: httpx.Request) -> httpx.Response:
        """Provide the real catalog client deterministic, offline HTTP responses."""
        nonlocal key_requests
        assert request.url.host == "openrouter.ai"
        assert request.headers["authorization"] == f"Bearer {secret}"
        requests.append(request.url.path)
        if request.url.path == "/api/v1/key":
            key_requests += 1
            if key_requests == 1:
                catalog_started.set()
                await catalog_release.wait()
                if fail:
                    return httpx.Response(status_code=503, json={"error": "synthetic catalog outage"})
            return httpx.Response(status_code=200, json={"data": {}}, request=request)
        if request.url.path == "/api/v1/models/user":
            return httpx.Response(
                status_code=200,
                json={
                    "data": [
                        {
                            "id": "vendor/startup-journey",
                            "name": "Startup Journey",
                            "context_length": 64000,
                            "supported_parameters": ["tools"],
                            "architecture": {
                                "input_modalities": ["text"],
                                "output_modalities": ["text"],
                            },
                        }
                    ]
                },
                request=request,
            )
        raise AssertionError(f"Unexpected OpenRouter catalog path: {request.url.path}")

    model: GatedFauxChatModel = GatedFauxChatModel(
        responses=[
            AIMessage(content="blocked answer"),
            AIMessage(content="still blocked answer"),
            AIMessage(content="ready answer"),
        ],
        first_call_release=asyncio.Event(),
    )
    model.first_call_release.set()
    config = SessionConfigDAO(workdir=tmp_path, model_name=route, enable_history=True)
    gateway: ChannelGateway = ChannelGateway(repository=ChannelRepository(db_path=tmp_path / "channels.db"))
    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=str(uuid4()),
        config=config,
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        enable_history=True,
        pending_preparation=True,
    )
    app = SloTUI(session=session, channel_gateway=gateway)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(_catalog_response)) as http_client:

            def _client_factory(*, credential: CredentialDAO) -> OpenRouterAPIClient:
                """Inject only the catalog service's third-party HTTP client."""
                return OpenRouterAPIClient(credential=credential, http_client=http_client)

            with patch("src.agents.model_catalog.service.OpenRouterAPIClient", side_effect=_client_factory):
                async with app.run_test(size=(100, 28)) as pilot:
                    await asyncio.wait_for(catalog_started.wait(), timeout=5.0)
                    preparation_task: Optional[asyncio.Task[None]] = app._preparation_task
                    assert preparation_task is not None
                    app._start_session_preparation()
                    assert app._preparation_task is preparation_task
                    assert requests == ["/api/v1/key"]
                    poller = session.channel_poller
                    assert poller is not None
                    channel_adapter = app.channel_adapter
                    assert channel_adapter is not None
                    poller.pause(reason="startup test hold")
                    await app._submit_or_queue_prompt(text="blocked")
                    await app._dispatch_slash_command(line="/model openrouter:author/other")
                    assert app._in_flight_task is None
                    assert session.active_model_name == route
                    assert session.preparation_status == "pending"
                    assert app._preparation_task is preparation_task
                    initial_queue: list[ChannelMessageDAO] = await channel_adapter.queued()
                    assert [
                        row.message_contents for row in initial_queue if row.message_type == "prompt"
                    ] == ["blocked"]
                    assert all(
                        row.accepted_at is None for row in initial_queue if row.message_type == "prompt"
                    )
                    painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                    assert "Preparing model catalog" in painted

                    catalog_release.set()
                    await preparation_task
                    await pilot.pause()
                    expected_prompts: list[str] = ["blocked"]
                    if fail:
                        assert session.preparation_status == "failed"
                        painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                        assert "synthetic catalog outage" not in painted
                        assert "/auth" in painted and "/model refresh" in painted
                        await app._submit_or_queue_prompt(text="still blocked")
                        expected_prompts.append("still blocked")
                        failed_queue: list[ChannelMessageDAO] = await channel_adapter.queued()
                        assert [
                            row.message_contents for row in failed_queue if row.message_type == "prompt"
                        ] == expected_prompts
                        assert all(
                            row.accepted_at is None for row in failed_queue if row.message_type == "prompt"
                        )
                        await app._dispatch_slash_command(line="/model refresh")
                        retry_task: Optional[asyncio.Task[None]] = app._preparation_task
                        assert retry_task is not None
                        assert retry_task is not preparation_task
                        await retry_task

                    assert session.preparation_status == "ready"
                    assert session.catalog_snapshot is not None
                    assert route in session.catalog_snapshot.entries
                    assert session.session_id == app._session.session_id
                    queued: list[ChannelMessageDAO] = await channel_adapter.queued()
                    assert [
                        row.message_contents for row in queued if row.message_type == "prompt"
                    ] == expected_prompts
                    assert all(row.accepted_at is None for row in queued if row.message_type == "prompt")

                    await app._submit_or_queue_prompt(text="ready")
                    poller.resume()
                    participant_id: UUID = channel_participant_id_for_session(session_id=session.session_id)

                    async def _all_prompts_replied() -> bool:
                        conversation: list[ChannelMessageDAO] = (
                            await gateway.repository.list_conversation_messages(
                                agent_session_id=participant_id
                            )
                        )
                        prompt_rows: list[ChannelMessageDAO] = [
                            row for row in conversation if row.message_type == "prompt"
                        ]
                        reply_rows: list[ChannelMessageDAO] = [
                            row for row in conversation if row.message_type == "reply"
                        ]
                        return (
                            [row.message_contents for row in prompt_rows] == [*expected_prompts, "ready"]
                            and len(reply_rows) == len(prompt_rows)
                            and all(row.accepted_at is not None for row in prompt_rows)
                        )

                    async with asyncio.timeout(10.0):
                        while not await _all_prompts_replied():
                            await asyncio.sleep(0.02)
                    conversation: list[ChannelMessageDAO] = (
                        await gateway.repository.list_conversation_messages(agent_session_id=participant_id)
                    )
                    prompt_rows: list[ChannelMessageDAO] = [
                        row for row in conversation if row.message_type == "prompt"
                    ]
                    reply_rows: list[ChannelMessageDAO] = [
                        row for row in conversation if row.message_type == "reply"
                    ]
                    assert len(prompt_rows) == len(reply_rows) == len(expected_prompts) + 1
                    assert all(row.cancelled_at is None for row in prompt_rows)
                    assert [row.in_reply_to_id for row in reply_rows] == [row.id for row in prompt_rows]
                    assert len(model.provider_calls) == len(prompt_rows)
                    assert [call[-1] for call in model.provider_calls] == [
                        *expected_prompts,
                        "ready",
                    ]
                    assert session.history_store is not None
                    events = await session.history_store.load_events(session_id=session.session_id)
                    recorded_prompts: list[str] = [
                        event.payload.content
                        for event in events
                        if event.kind == "user_message" and event.payload.content is not None
                    ]
                    assert recorded_prompts == [*expected_prompts, "ready"]

    finally:
        catalog_release.set()
        await session.stop_channel_delivery(reason="test_done")
        await gateway.close()

    assert requests == (
        ["/api/v1/key", "/api/v1/key", "/api/v1/models/user"]
        if fail
        else ["/api/v1/key", "/api/v1/models/user"]
    )
