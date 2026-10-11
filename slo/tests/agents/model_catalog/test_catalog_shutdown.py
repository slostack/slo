"""Controlled task ownership and cancellation tests; no external I/O."""

import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.model_catalog.dao import CatalogRefreshResultDAO, ModelCatalogCacheDAO
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.model_catalog.store import ModelCatalogStore
from src.agents.slo_agent.history.atomic_io import AtomicWriteOutcomeDAO
from src.auth.credential_dao import ProviderName


async def test_shutdown_drains_reset_cancelled_refresh_before_returning() -> None:
    """Synchronous reset retains cleanup ownership until async shutdown drains it."""
    started = asyncio.Event()
    cancelling = asyncio.Event()
    release = asyncio.Event()

    async def refresh_owner() -> CatalogRefreshResultDAO:
        """Delay cancellation cleanup at a deterministic barrier."""
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelling.set()
            await release.wait()
        raise AssertionError("Refresh owner must be cancelled")

    task = asyncio.create_task(refresh_owner())
    ModelCatalogService._refresh_tasks[
        (ProviderName.OPENROUTER, "fixture", id(asyncio.get_running_loop()), "test")
    ] = task
    await started.wait()
    ModelCatalogService.reset()
    await cancelling.wait()
    try:
        shutdown = asyncio.create_task(ModelCatalogService.shutdown())
        release.set()
        await shutdown
        assert task.done()
        assert not ModelCatalogService._refresh_tasks
        assert not ModelCatalogService._retiring_refresh_tasks
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_repeated_cancellation_drains_threaded_writer_before_lease_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated owner cancellation cannot detach a still-running persistence worker."""
    path = tmp_path / "cache.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    completed = threading.Event()

    def write(*, cache: ModelCatalogCacheDAO, override_path: Path) -> AtomicWriteOutcomeDAO:
        """Block a local writer until both cancellation attempts have been delivered."""
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=5)
        completed.set()
        return AtomicWriteOutcomeDAO(committed=True, durability_warning=False)

    monkeypatch.setattr(ModelCatalogStore, "write_provider_cache", write)
    owner = asyncio.create_task(
        ModelCatalogService._write_cache_under_lease(cache=ModelCatalogCacheDAO(), cache_path=path)
    )
    await started.wait()
    try:
        owner.cancel()
        checkpoint = asyncio.Event()
        loop.call_soon(checkpoint.set)
        await checkpoint.wait()
        owner.cancel()
        checkpoint.clear()
        loop.call_soon(checkpoint.set)
        await checkpoint.wait()
        assert not owner.done(), "Writer ownership was lost before the thread completed"
    finally:
        release.set()
        await asyncio.gather(owner, return_exceptions=True)
    assert completed.is_set()
    assert owner.cancelled()


async def test_forced_refresh_joins_existing_same_fingerprint_owner(tmp_path: Path) -> None:
    """A forced caller joins the active same-key refresh instead of duplicating provider work."""
    from tests.agents.model_catalog.test_openrouter_lifecycle import FakeOpenRouterClient
    from src.auth.credential_dao import AuthType, CredentialDAO, CredentialSource, ResolvedCredentialDAO

    cache_path = tmp_path / "model_catalog_cache.v2.json"
    assert cache_path.parent.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="fixture-key",
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingClient(FakeOpenRouterClient):
        """Block the provider owner after the exact shared-flight admission point."""

        async def get_current_key(self):
            """Hold verification until both callers have joined the one owner."""
            self.key_calls += 1
            started.set()
            await release.wait()
            return await super().get_current_key()

    client = BlockingClient(credential=credential)
    ModelCatalogService.reset()
    first = asyncio.create_task(
        ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=False,
            resolved_credential=resolved,
            client_factory=lambda credential: client,
            cache_path=cache_path,
        )
    )
    await started.wait()
    forced = asyncio.create_task(
        ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            resolved_credential=resolved,
            client_factory=lambda credential: client,
            cache_path=cache_path,
        )
    )
    await asyncio.sleep(0)
    assert client.key_calls == 1
    release.set()
    first_result, forced_result = await asyncio.gather(first, forced)

    assert first_result.status == forced_result.status == "refreshed"
    assert client.key_calls == 2
    assert client.model_calls == 1


async def test_headless_runner_shutdowns_global_catalog_after_run() -> None:
    """The process-owned headless runner drains global refresh work during teardown."""
    from src.cli.headless import HeadlessRunner

    runner = object.__new__(HeadlessRunner)
    shutdown = AsyncMock()
    with patch.object(ModelCatalogService, "shutdown", shutdown):
        await runner._shutdown_model_catalog()
    shutdown.assert_awaited_once_with()
