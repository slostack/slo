"""Real schema-2 admission delivery races and reversible operator overrides."""

import asyncio
from collections.abc import Callable
from typing import ParamSpec, TypeVar
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.model_catalog.dao import (
    CatalogRefreshResultDAO,
    ModelCatalogCacheDAO,
    ProviderCatalogCacheDAO,
)
from src.agents.model_catalog.service import ModelCatalogService, ModelPreparationRequiredError
from src.agents.model_catalog.store import ModelCatalogStore
from src.auth.credential_dao import (
    AuthType,
    CredentialDAO,
    CredentialSource,
    ProviderName,
    ResolvedCredentialDAO,
)
from src.auth.credential_resolver import CredentialResolver
from src.integrations.openrouter.dao import credential_fingerprint
from tests.agents.model_catalog.test_openrouter_converter_metadata import _entry

P = ParamSpec("P")
R = TypeVar("R")


@pytest.mark.parametrize("rotation", [False, True])
async def test_first_actual_store_read_cannot_admit_after_winner(tmp_path: Path, rotation: bool) -> None:
    """Hold delivery after disk read, then commit removal or rotate the effective key."""
    path = tmp_path / "model_catalog_cache.v2.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic-real-store-a"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE)
    fingerprint = credential_fingerprint(access_token=credential.access_token)
    entry = _entry()
    now = datetime.now(tz=timezone.utc).isoformat()
    initial = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint=fingerprint,
                key_verified_at=now,
                last_success_at=now,
                entries=[entry],
            )
        ]
    )
    ModelCatalogStore.write_provider_cache(cache=initial, override_path=path)
    read_complete = asyncio.Event()
    release = asyncio.Event()
    original_thread = asyncio.to_thread
    first = True

    async def deliver_read(function: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
        """Execute the real loader before pausing only its first async delivery."""
        nonlocal first
        result = await original_thread(function, *args, **kwargs)
        if function == ModelCatalogStore.load_provider_cache and first:
            first = False
            assert result == initial
            read_complete.set()
            await release.wait()
        return result

    with (
        patch("src.agents.model_catalog.store._global_dir", return_value=tmp_path),
        patch.object(CredentialResolver, "resolve_with_source", return_value=resolved) as resolver,
        patch(
            "src.agents.model_catalog.service.OpenRouterAPIClient",
            side_effect=AssertionError("HTTP forbidden"),
        ) as client,
        patch("src.agents.model_catalog.service.asyncio.to_thread", side_effect=deliver_read),
    ):
        ModelCatalogService.reset()
        ModelCatalogService.load()
        task = asyncio.create_task(ModelCatalogService.prepare_models(model_names=(entry.model_name,)))
        try:
            await asyncio.wait_for(read_complete.wait(), timeout=5)
            if rotation:
                resolver.return_value = resolved.model_copy(
                    update={
                        "credential": credential.model_copy(update={"access_token": "synthetic-real-store-b"})
                    }
                )
            else:
                removed = initial.model_copy(
                    update={
                        "provider_slices": [initial.provider_slices[0].model_copy(update={"entries": []})]
                    }
                )
                ModelCatalogStore.write_provider_cache(cache=removed, override_path=path)
                ModelCatalogService._publish_candidate(
                    candidate=await ModelCatalogService._build_publication_candidate(cache=removed),
                    fingerprint=fingerprint,
                )
            release.set()
            with patch.object(
                ModelCatalogService,
                "refresh",
                return_value=CatalogRefreshResultDAO(
                    status="fresh",
                    catalog_generation=ModelCatalogService.load().generation,
                    safe_message="Complete winner already published.",
                ),
            ):
                with pytest.raises(ModelPreparationRequiredError):
                    await task
            client.assert_not_called()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await ModelCatalogService.shutdown()
            ModelCatalogService.reset()


def test_override_removal_restores_raw_provider_entry(tmp_path: Path) -> None:
    """Load real restriction bytes, remove them, and restore the unchanged raw slice."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    overrides_path = tmp_path / "overrides.json"
    for path in (cache_path, overrides_path):
        assert path.resolve().is_relative_to(tmp_path.resolve())
    entry = _entry()
    cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint="synthetic-cache-provenance",
                entries=[entry],
            )
        ]
    )
    ModelCatalogStore.write_provider_cache(cache=cache, override_path=cache_path)
    raw = cache_path.read_bytes()
    runtime = entry.runtime_profile.model_copy(update={"max_tokens": 100})
    overrides_path.write_text(
        json.dumps(
            [
                {
                    "model_name": entry.model_name,
                    "display_name": "Restricted label",
                    "visible_in_picker": False,
                    "runtime_profile": runtime.model_dump(mode="json"),
                }
            ]
        ),
        encoding="utf-8",
    )
    with (
        patch("src.agents.model_catalog.store._global_dir", return_value=tmp_path),
        patch.object(ModelCatalogStore, "overrides_path", return_value=overrides_path),
        patch(
            "src.agents.model_catalog.service.OpenRouterAPIClient",
            side_effect=AssertionError("HTTP forbidden"),
        ),
    ):
        try:
            ModelCatalogService.reset()
            restricted = ModelCatalogService.load().entries[entry.model_name]
            assert restricted.display_name == "Restricted label"
            assert restricted.visible_in_picker is False
            assert restricted.runtime_profile.max_tokens == 100
            assert cache_path.read_bytes() == raw
            overrides_path.unlink()
            ModelCatalogService.reset()
            assert ModelCatalogService.load().entries[entry.model_name] == entry
            assert cache_path.read_bytes() == raw
        finally:
            ModelCatalogService.reset()
