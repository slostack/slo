"""Historical evidence parsing never promotes invalid timestamps to verification."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.agents.model_catalog.dao import ModelCatalogCacheDAO, ProviderCatalogCacheDAO
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.model_catalog.store import ModelCatalogStore
from src.auth.credential_dao import ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.tui.model_catalog import ModelSuggestionProjection


@pytest.mark.parametrize("value", [None, "invalid", "2026-10-01T12:00:00", "2026-10-01T12:00:01+00:00"])
def test_invalid_listing_preserves_only_historical_key_time(value: str | None) -> None:
    """Missing, malformed, naive and future listing times never become checked."""
    now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint="synthetic-a",
                key_verified_at=now.isoformat(),
                last_success_at=value,
            )
        ]
    )
    ModelCatalogService.reset()
    try:
        with (
            patch.object(ModelCatalogService, "_active_openrouter_fingerprint", "synthetic-a"),
            patch.object(ModelCatalogStore, "load_provider_cache", return_value=cache),
            patch.object(ModelCatalogStore, "load_overrides", return_value=[]),
            patch.object(CredentialResolver, "resolve_with_source", side_effect=AssertionError("I/O")),
        ):
            ModelCatalogService.load(now=now, lifecycle_ttl=timedelta(hours=1))
        status = ModelCatalogService.lifecycle_status()
        assert status.state == "stale"
        assert status.key_verified_at == now
        assert status.catalog_checked_at is None
        assert (
            ModelSuggestionProjection._catalog_status_summary() == "catalog status unknown; refresh required"
        )
    finally:
        ModelCatalogService.reset()
