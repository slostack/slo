"""Deterministic final cache-read interleavings over private durable bytes."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.model_catalog.dao import (
    ModelCatalogCacheDAO,
    ModelCatalogEntryDAO,
    ProviderCatalogCacheDAO,
)
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.service import ModelCatalogService, ModelPreparationRequiredError
from src.agents.model_catalog.store import ModelCatalogStore
from src.auth.credential_dao import ProviderName


def _cache_with_entry(*, api_model_name: str, max_tokens: int) -> ModelCatalogCacheDAO:
    """Build a distinguishable OpenRouter cache slice for final-read ordering tests.

    Args:
        api_model_name (str): Exact synthetic remote model identity.
        max_tokens (int): Distinguishable prepared local output cap.

    Returns:
        ModelCatalogCacheDAO: One schema-two cache containing the requested route.
    """
    seed_entry: ModelCatalogEntryDAO = SeedModelCatalog.load().entries["gpt-5.4"]
    entry: ModelCatalogEntryDAO = seed_entry.model_copy(
        update={
            "model_name": f"openrouter:{api_model_name}",
            "api_model_name": api_model_name,
            "provider": ProviderName.OPENROUTER,
            "runtime_profile": seed_entry.runtime_profile.model_copy(update={"max_tokens": max_tokens}),
        }
    )
    return ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint="a",
                last_success_at=datetime.now(tz=timezone.utc).isoformat(),
                entries=[entry],
            )
        ]
    )


@pytest.mark.parametrize("rotate", [False, True])
async def test_final_read_revalidates_publication_and_credential(tmp_path: Path, rotate: bool) -> None:
    """Never swap an old candidate after its final read yields to a newer publication."""
    cache_path = tmp_path / "catalog.json"
    assert cache_path.resolve().is_relative_to(tmp_path.resolve())
    cache = _cache_with_entry(api_model_name="vendor/older", max_tokens=1_024)
    ModelCatalogStore.write_provider_cache(cache=cache, override_path=cache_path)
    original_read = ModelCatalogStore.load_provider_cache
    original_thread = asyncio.to_thread
    read_finished = asyncio.Event()
    release_read = asyncio.Event()
    identity = "a"
    reads = 0

    def effective_identity() -> str:
        """Return only the mutable synthetic credential identity."""
        return identity

    async def held_read(function: object, *args: object, **kwargs: object) -> object:
        """Hold delivery after real bytes are read, not before the cache read."""
        nonlocal reads
        if function == ModelCatalogStore.load_provider_cache:
            result = original_read(override_path=cache_path)
            reads += 1
            if reads == 1:
                read_finished.set()
                await release_read.wait()
            return result
        return await original_thread(function, *args, **kwargs)

    ModelCatalogService.reset()
    candidate = await ModelCatalogService._build_publication_candidate(cache=cache)
    with (
        patch.object(ModelCatalogService, "_effective_fingerprint_for_resolved_credential", side_effect=effective_identity),
        patch("src.agents.model_catalog.service.asyncio.to_thread", side_effect=held_read),
    ):
        task = asyncio.create_task(ModelCatalogService._publish_admission_candidate_if_current(
            candidate=candidate, fingerprint="a", cache=cache,
        ))
        await read_finished.wait()
        winner_cache = _cache_with_entry(api_model_name="vendor/newer", max_tokens=512)
        ModelCatalogService._active_openrouter_fingerprint = "a"
        ModelCatalogService._publish_candidate(
            candidate=await ModelCatalogService._build_publication_candidate(cache=winner_cache),
            fingerprint="a",
        )
        winner = ModelCatalogService._snapshot
        if rotate:
            identity = "b"
        release_read.set()
        if rotate:
            with pytest.raises(ModelPreparationRequiredError, match="credential changed"):
                await task
        else:
            await task
        assert ModelCatalogService._snapshot is winner
        assert winner is not None
        assert "openrouter:vendor/newer" in winner.entries
        assert "openrouter:vendor/older" not in winner.entries
        assert winner.entries["openrouter:vendor/newer"].runtime_profile.max_tokens == 512
    ModelCatalogService.reset()
