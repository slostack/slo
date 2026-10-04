"""Real-process late-writer proof for F86-25 / 86.a.2 section 7.4."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import multiprocessing
from multiprocessing.synchronize import Event
from pathlib import Path
from typing import Optional

import pytest

from src.agents.model_catalog.dao import ModelCatalogCacheDAO, ProviderCatalogCacheDAO
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.model_catalog.store import ModelCatalogStore
from src.auth.credential_dao import (
    AuthType,
    CredentialDAO,
    CredentialSource,
    ProviderName,
    ResolvedCredentialDAO,
)
from src.integrations.openrouter.dao import (
    OpenRouterKeyVerificationDAO,
    OpenRouterModelsResponseDAO,
    credential_fingerprint,
)


class _LocalCatalogClient:
    """Synthetic metadata source; a stale caller must never reach either method."""

    def __init__(self, *, credential: CredentialDAO, stale: bool) -> None:
        """Capture only test data and count calls for the child-process assertions."""
        self.credential = credential
        self.stale = stale
        self.calls: list[str] = []

    async def get_current_key(self) -> OpenRouterKeyVerificationDAO:
        """Return synthetic same-key evidence without any HTTP or resolver access."""
        self.calls.append("key")
        return OpenRouterKeyVerificationDAO(
            credential_fingerprint=credential_fingerprint(access_token=self.credential.access_token),
            verified_at=datetime.now(tz=timezone.utc),
        )

    async def list_user_models(self) -> OpenRouterModelsResponseDAO:
        """Supply distinguishable complete lists so an old overwrite cannot pass."""
        self.calls.append("models")
        model_id = "vendor/obsolete" if self.stale else "vendor/winner"
        return OpenRouterModelsResponseDAO(
            data=[
                {
                    "id": model_id,
                    "context_length": 1000,
                    "supported_parameters": ["tools"],
                    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                }
            ]
        )


def _refresh_process(*, root: Path, observed: Event, resume: Event, stale: bool) -> None:
    """Run one isolated refresh; the parent releases and joins both children.

    Args:
        root: Resolved pytest tmp_path, the only permitted filesystem root.
        observed: Child-to-parent acknowledgement of the old pre-lease read.
        resume: Parent-to-child barrier released only after the winner exits.
        stale: Whether this child is the delayed older force-refresh caller.
    """
    asyncio.run(_refresh_process_async(root=root, observed=observed, resume=resume, stale=stale))


async def _refresh_process_async(*, root: Path, observed: Event, resume: Event, stale: bool) -> None:
    """Exercise real service, flock and atomic persistence with a pre-lease barrier.

    The wrapper delays acquisition, not the protected operation. No lock, cache
    read, freshness decision, write or publication is replaced. All child writes
    (including lock and atomic temporary files) stay below the validated root.
    """
    assert root == root.resolve(strict=True)
    cache_path = root / "model_catalog_cache.v2.json"
    overrides_path = root / "absent-overrides.json"
    for path in (cache_path, overrides_path, root / "model_catalog_cache.v2.lock"):
        assert path.resolve().is_relative_to(root)
    original_lease = ModelCatalogStore.refresh_lease

    @asynccontextmanager
    async def delayed_lease(*, cache_path: Optional[Path] = None) -> AsyncIterator[None]:
        """Acknowledge the completed initial read, then await the winner's exit."""
        observed.set()
        assert await asyncio.to_thread(resume.wait, timeout=15), "parent did not release old refresh"
        async with original_lease(cache_path=cache_path):
            yield

    with pytest.MonkeyPatch.context() as patch:
        # Spawn does not inherit pytest fixtures: explicitly isolate override I/O.
        patch.setattr(ModelCatalogStore, "overrides_path", lambda: overrides_path)
        if stale:
            patch.setattr(ModelCatalogStore, "refresh_lease", delayed_lease)
        ModelCatalogService.reset()
        credential = CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token="synthetic-ordering-key",
        )
        client = _LocalCatalogClient(credential=credential, stale=stale)
        result = await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            resolved_credential=ResolvedCredentialDAO(
                credential=credential, source=CredentialSource.ENVIRONMENT
            ),
            client_factory=lambda credential: client,
            cache_path=cache_path,
        )
        assert result.status == ("fresh" if stale else "refreshed")
        assert client.calls == ([] if stale else ["key", "models"])
        snapshot = ModelCatalogService.load()
        assert result.catalog_generation == snapshot.generation == 1
        assert "openrouter:vendor/winner" in snapshot.entries
        assert "openrouter:vendor/obsolete" not in snapshot.entries
        await ModelCatalogService.shutdown()


def test_force_refresh_when_older_process_resumes_preserves_newer_publication(tmp_path: Path) -> None:
    """An old same-key force caller adopts the winner without fetching or writing.

    The old child acknowledges its initial disk read before the new child starts.
    The parent joins the new child (persistence AND publication completed), captures
    the exact bytes, then releases the old child. Timeouts only bound failures;
    no sleep or scheduler-dependent negative assertion establishes ordering.
    """
    root = tmp_path.resolve(strict=True)
    cache_path = root / "model_catalog_cache.v2.json"
    assert cache_path.resolve().is_relative_to(root)
    baseline = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint=credential_fingerprint(access_token="synthetic-ordering-key"),
                last_success_at="2020-01-01T00:00:00+00:00",
            )
        ]
    )
    ModelCatalogStore.write_provider_cache(cache=baseline, override_path=cache_path)
    context = multiprocessing.get_context("spawn")
    observed = context.Event()
    resume = context.Event()
    older = context.Process(
        target=_refresh_process, kwargs=dict(root=root, observed=observed, resume=resume, stale=True)
    )
    newer = context.Process(
        target=_refresh_process, kwargs=dict(root=root, observed=observed, resume=resume, stale=False)
    )
    older.start()
    try:
        assert observed.wait(timeout=15), "old child did not finish its pre-lease read"
        newer.start()
        newer.join(timeout=15)
        assert newer.exitcode == 0, "new child failed to persist and publish"
        assert older.pid != newer.pid
        winner_bytes = cache_path.read_bytes()
        saved = ModelCatalogStore.load_provider_cache(override_path=cache_path)
        assert saved is not None
        assert (
            saved.provider_slices[0].credential_fingerprint
            == baseline.provider_slices[0].credential_fingerprint
        )
        assert [entry.model_name for entry in saved.provider_slices[0].entries] == [
            "openrouter:vendor/winner"
        ]
        resume.set()
        older.join(timeout=15)
        assert older.exitcode == 0, "old child did not adopt the newer publication"
        assert cache_path.read_bytes() == winner_bytes
    finally:
        resume.set()
        older.join(timeout=35)
        if newer.pid is not None:
            newer.join(timeout=35)
    assert not older.is_alive()
    assert not newer.is_alive()
