"""Offline pending startup contracts through the production session and app."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from contextlib import nullcontext

from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO
from src.agents.model_catalog.seed import SeedModelCatalog
from src.cli.typer_dispatch import TyperDispatch
from src.agents.model_catalog.service import ModelCatalogService, ModelPreparationRequiredError
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI


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
    with patch.object(ModelCatalogService, "prepare_models", new=AsyncMock(return_value=direct_snapshot)) as prepare:
        result = await session.prepare_model_selection(model_name="openrouter:author/other")
    assert "preparation" in result
    prepare.assert_not_awaited()


async def test_mounted_pending_startup_allows_direct_selection_and_ignores_cancelled_old_worker(tmp_path: Path) -> None:
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
async def test_mounted_startup_shared_worker_gates_and_recovers(tmp_path: Path, fail: bool) -> None:
    """Mounted UI paints safe pending/failure state and retries using one gateway."""
    snapshot = SeedModelCatalog.load()
    route = "openrouter:author/cold"
    entry = snapshot.entries["gpt-5.4"].model_copy(update={"model_name": route})
    snapshot = snapshot.model_copy(update={"entries": {**snapshot.entries, route: entry}})
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def prepare_models(*, model_names: tuple[str, ...]) -> ModelCatalogSnapshotDAO:
        """Hold the real startup path at its deterministic catalog boundary."""
        nonlocal calls
        calls += 1
        assert model_names == (route,)
        started.set()
        await release.wait()
        if fail and calls == 1:
            raise ValueError("PRIVATE_STARTUP_SENTINEL")
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
        async with app.run_test(size=(100, 28)) as pilot:
            await asyncio.wait_for(started.wait(), timeout=2)
            await pilot.pause()
            app._start_session_preparation()
            await app._submit_or_queue_prompt(text="blocked")
            await app._dispatch_slash_command(line="/model openrouter:author/other")
            assert app._in_flight_task is None
            assert session.active_model_name == route
            assert calls == 1
            painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "Preparing model catalog" in painted
            release.set()
            assert app._preparation_task is not None
            await app._preparation_task
            await pilot.pause()
            if fail:
                assert session.preparation_status == "failed"
                painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "PRIVATE_STARTUP_SENTINEL" not in painted
                assert "/auth" in painted and "/model refresh" in painted
                await app._submit_or_queue_prompt(text="still blocked")
                assert app._in_flight_task is None
                await app._dispatch_slash_command(line="/model refresh")
                assert app._preparation_task is not None
                await app._preparation_task
            assert session.preparation_status == "ready"
            assert session.catalog_snapshot == snapshot
            assert session.session_id == app._session.session_id
            with patch.object(app, "_start_accepted_prompt", new_callable=AsyncMock) as accepted:
                await app._submit_or_queue_prompt(text="ready")
                accepted.assert_awaited_once_with(text="ready")
