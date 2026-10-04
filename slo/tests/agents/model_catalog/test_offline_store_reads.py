"""Offline catalog reads must not create private directories or write caches."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.agents.model_catalog.dao import ModelCatalogCacheDAO, ProviderCatalogCacheDAO
from src.agents.model_catalog.seed import SeedModelCatalog
from src.auth.credential_dao import ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.integrations.openrouter.client import OpenRouterAPIClient

from src.agents.model_catalog import store as store_module
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.model_catalog.store import ModelCatalogStore


def test_cold_load_and_projections_do_not_create_storage(tmp_path: Path) -> None:
    """Read absent cache/overrides without mkdir, chmod, or cache persistence."""
    from config.ai_model_config import MODEL_DEFAULTS
    from src.agents.reasoning_capabilities import MODEL_REASONING_CAPABILITIES
    from src.tui.model_catalog import MODEL_CATALOG

    missing = tmp_path / "absent"
    assert missing.resolve().is_relative_to(tmp_path.resolve())
    with (
        patch.object(store_module, "_global_dir", return_value=missing),
        patch.object(store_module, "_cfg", return_value=None),
        patch.object(ModelCatalogService, "_snapshot", None),
        patch.object(CredentialResolver, "resolve", side_effect=AssertionError("credential read")),
        patch.object(
            CredentialResolver, "resolve_with_source", side_effect=AssertionError("credential read")
        ),
        patch.object(OpenRouterAPIClient, "__init__", side_effect=AssertionError("client creation")),
        patch.object(httpx.Client, "send", side_effect=AssertionError("sync network")),
        patch.object(httpx.AsyncClient, "send", side_effect=AssertionError("async network")),
        patch.object(Path, "mkdir", side_effect=AssertionError("offline mkdir")),
        patch.object(store_module.os, "chmod", side_effect=AssertionError("offline chmod")),
        patch.object(ModelCatalogStore, "write_provider_cache", side_effect=AssertionError("cache write")),
    ):
        snapshot = ModelCatalogService.load()
        assert len(MODEL_DEFAULTS) == len(snapshot.entries)
        assert len(MODEL_REASONING_CAPABILITIES) == len(snapshot.entries)
        assert len(MODEL_CATALOG) > 0
    assert not missing.exists()


async def test_cold_load_is_write_free_inside_running_loop(tmp_path: Path) -> None:
    """The synchronous read contract is unchanged when a mounted async caller reads."""
    test_cold_load_and_projections_do_not_create_storage(tmp_path=tmp_path)


def test_cold_load_when_cached_provenance_is_mismatched_hides_rows_without_credential_io() -> None:
    """Hide a foreign cached OpenRouter row using only lifecycle-owned provenance."""
    seed = SeedModelCatalog.load()
    entry = seed.entries["gpt-5.4"].model_copy(
        update={"model_name": "openrouter:vendor/foreign", "provider": ProviderName.OPENROUTER}
    )
    cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint="fingerprint-a",
                entries=[entry],
            )
        ]
    )
    with (
        patch.object(ModelCatalogService, "_snapshot", None),
        patch.object(ModelCatalogService, "_active_openrouter_fingerprint", "fingerprint-b"),
        patch.object(ModelCatalogStore, "load_provider_cache", return_value=cache),
        patch.object(ModelCatalogStore, "load_overrides", return_value=[]),
        patch.object(CredentialResolver, "resolve", side_effect=AssertionError("credential read")),
        patch.object(
            CredentialResolver, "resolve_with_source", side_effect=AssertionError("credential read")
        ),
        patch.object(OpenRouterAPIClient, "__init__", side_effect=AssertionError("client creation")),
        patch.object(httpx.Client, "send", side_effect=AssertionError("sync network")),
        patch.object(httpx.AsyncClient, "send", side_effect=AssertionError("async network")),
        patch.object(ModelCatalogStore, "write_provider_cache", side_effect=AssertionError("cache write")),
    ):
        snapshot = ModelCatalogService.load()
        assert entry.model_name not in snapshot.entries
        assert (
            entry.model_name
            not in ModelCatalogService.supported_models_by_provider()[ProviderName.OPENROUTER]
        )
        with pytest.raises(ValueError, match="Unsupported model_name"):
            ModelCatalogService.entry_for_model(model_name=entry.model_name)


@pytest.mark.parametrize("fingerprint", [None, "", "fingerprint-b", "fingerprint-a"])
@pytest.mark.parametrize("age_seconds", [0, 3599, 3600, 3601])
def test_cold_load_hydrates_fresh_cached_lifecycle_status_without_credential_io(
    fingerprint: str | None, age_seconds: int
) -> None:
    """Only lifecycle-qualified matching evidence can claim a current checked catalog."""
    observed_at = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    entry = (
        SeedModelCatalog.load()
        .entries["gpt-5.4"]
        .model_copy(update={"model_name": "openrouter:vendor/cached", "provider": ProviderName.OPENROUTER})
    )
    cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint="fingerprint-a",
                key_verified_at=(observed_at - timedelta(minutes=10)).isoformat(),
                last_success_at=(observed_at - timedelta(seconds=age_seconds)).isoformat(),
                entries=[entry],
            )
        ]
    )
    ModelCatalogService.reset()
    with (
        patch.object(ModelCatalogService, "_snapshot", None),
        patch.object(ModelCatalogStore, "load_provider_cache", return_value=cache),
        patch.object(ModelCatalogStore, "load_overrides", return_value=[]),
        patch.object(CredentialResolver, "resolve", side_effect=AssertionError("credential read")),
        patch.object(
            CredentialResolver, "resolve_with_source", side_effect=AssertionError("credential read")
        ),
    ):
        with patch.object(ModelCatalogService, "_active_openrouter_fingerprint", fingerprint):
            ModelCatalogService.load(now=observed_at, lifecycle_ttl=timedelta(hours=1))

    status = ModelCatalogService.lifecycle_status()
    expected = "checked" if age_seconds < 3600 else "stale"
    assert status.state == (expected if fingerprint == "fingerprint-a" else "historical")
    assert status.key_verified_at == observed_at - timedelta(minutes=10)
    assert status.catalog_checked_at == observed_at - timedelta(seconds=age_seconds)
    from src.tui.model_catalog import ModelSuggestionProjection

    summary = ModelSuggestionProjection._catalog_status_summary()
    if fingerprint != "fingerprint-a":
        assert summary == "cached history; current key not checked"
    else:
        prefix = "catalog checked" if age_seconds < 3600 else "stale catalog"
        assert summary == f"{prefix} {status.catalog_checked_at.isoformat()}"
    ModelCatalogService.reset()


def test_cold_load_does_not_hydrate_future_cached_lifecycle_status() -> None:
    """Reject future persisted timestamps rather than presenting them as checked evidence."""
    observed_at = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint="fingerprint-a",
                key_verified_at=(observed_at + timedelta(seconds=1)).isoformat(),
                last_success_at=(observed_at + timedelta(seconds=1)).isoformat(),
            )
        ]
    )
    ModelCatalogService.reset()
    with (
        patch.object(ModelCatalogService, "_snapshot", None),
        patch.object(ModelCatalogStore, "load_provider_cache", return_value=cache),
        patch.object(ModelCatalogStore, "load_overrides", return_value=[]),
    ):
        ModelCatalogService.load(now=observed_at, lifecycle_ttl=timedelta(hours=1))

    assert ModelCatalogService.lifecycle_status().state == "unknown"


async def test_cold_load_inside_running_loop_uses_matching_lifecycle_provenance_without_io() -> None:
    """Expose only same-key cached rows without resolving credentials from an async projection."""
    seed = SeedModelCatalog.load()
    entry = seed.entries["gpt-5.4"].model_copy(
        update={"model_name": "openrouter:vendor/matching", "provider": ProviderName.OPENROUTER}
    )
    cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint="fingerprint-a",
                entries=[entry],
            )
        ]
    )
    with (
        patch.object(ModelCatalogService, "_snapshot", None),
        patch.object(ModelCatalogService, "_active_openrouter_fingerprint", "fingerprint-a"),
        patch.object(ModelCatalogStore, "load_provider_cache", return_value=cache),
        patch.object(ModelCatalogStore, "load_overrides", return_value=[]),
        patch.object(
            CredentialResolver, "resolve_with_source", side_effect=AssertionError("credential read")
        ),
        patch.object(OpenRouterAPIClient, "__init__", side_effect=AssertionError("client creation")),
        patch.object(httpx.AsyncClient, "send", side_effect=AssertionError("async network")),
    ):
        snapshot = ModelCatalogService.load()
        assert ModelCatalogService.entry_for_model(model_name=entry.model_name) == entry
        assert entry.model_name in ModelCatalogService.supported_models_by_provider()[ProviderName.OPENROUTER]
        assert snapshot.entries[entry.model_name] == entry
