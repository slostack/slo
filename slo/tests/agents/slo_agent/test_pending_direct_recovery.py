"""Pending direct-provider escape and late startup invalidation."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession


@pytest.mark.parametrize("startup_fails", [False, True])
async def test_direct_selection_invalidates_pending_startup(tmp_path: Path, startup_fails: bool) -> None:
    """A late old startup result cannot replace a prepared direct selection."""
    session = SloAgentSession.build(config=SessionConfigDAO(
        workdir=tmp_path, model_name="openrouter:vendor/pending", enable_history=False,
    ), allow_pending_preparation=True)
    started = asyncio.Event()
    release = asyncio.Event()
    snapshot = SeedModelCatalog.load()

    async def prepare(*, model_names: tuple[str, ...]) -> object:
        """Hold only the old gateway preparation at a deterministic barrier."""
        if model_names == ("openrouter:vendor/pending",):
            started.set()
            await release.wait()
            if startup_fails:
                raise ValueError("synthetic startup failure")
        return snapshot

    with (
        patch("src.agents.slo_agent.sessions.service.ModelCatalogService.prepare_models", side_effect=prepare),
        patch("src.agents.slo_agent.sessions.service.CredentialResolver.require"),
        patch("src.agents.slo_agent.sessions.service.UserPreferencesStore.upsert") as save,
    ):
        task = asyncio.create_task(session.prepare_startup())
        await started.wait()
        rejected = await session.prepare_model_selection(model_name="openrouter:vendor/other")
        assert "pending" in rejected
        message = await session.prepare_model_selection(model_name="gpt-5.4")
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        assert "active model switched to gpt-5.4" in message
        assert session.active_model_name == "gpt-5.4"
        assert session.preparation_status == "ready"
        assert session.catalog_snapshot is snapshot
        assert session._config.model_pool_dao is None
        save.assert_called_once_with(model_name="gpt-5.4")


async def test_direct_selection_preserves_runtime_route_when_pending_startup_is_cancelled(tmp_path: Path) -> None:
    """A cancelled old startup cannot restore its route after a direct selection commits."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="openrouter:vendor/pending",
            enable_history=False,
        ),
        allow_pending_preparation=True,
    )
    started = asyncio.Event()
    release = asyncio.Event()
    snapshot = SeedModelCatalog.load()

    async def prepare(*, model_names: tuple[str, ...]) -> object:
        """Hold the old route while allowing the direct route to prepare independently."""
        if model_names == ("openrouter:vendor/pending",):
            started.set()
            await release.wait()
        return snapshot

    with (
        patch("src.agents.slo_agent.sessions.service.ModelCatalogService.prepare_models", side_effect=prepare),
        patch("src.agents.slo_agent.sessions.service.CredentialResolver.require"),
        patch("src.agents.slo_agent.sessions.service.UserPreferencesStore.upsert") as save,
    ):
        task = asyncio.create_task(session.prepare_startup())
        await started.wait()
        message = await session.prepare_model_selection(model_name="gpt-5.4")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert "active model switched to gpt-5.4" in message
    assert session.active_model_name == "gpt-5.4"
    assert session.preparation_status == "ready"
    assert session.catalog_snapshot is snapshot
    assert session._config is not None and session._config.model_pool_dao is None
    save.assert_called_once_with(model_name="gpt-5.4")
