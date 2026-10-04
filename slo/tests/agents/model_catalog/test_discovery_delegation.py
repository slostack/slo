"""The legacy discovery entry must not own credentials, merging, or publication."""

from unittest.mock import AsyncMock, patch

from src.agents.model_catalog.dao import CatalogRefreshResultDAO
from src.agents.model_catalog.discovery import ProviderModelDiscoveryService
from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_dao import ProviderName
from src.auth.credential_resolver import CredentialResolver


async def test_discovery_delegates_explicit_provider_to_single_catalog_owner() -> None:
    """Compatibility discovery forwards to the async owner without a credential loop."""
    expected = CatalogRefreshResultDAO(status="refreshed", catalog_generation=3, safe_message="Checked.")
    refresh = AsyncMock(return_value=expected)
    with (
        patch.object(ModelCatalogService, "refresh", new=refresh),
        patch.object(CredentialResolver, "resolve", side_effect=AssertionError("credential loop")),
    ):
        result = await ProviderModelDiscoveryService.refresh(provider=ProviderName.OPENROUTER, force=True)
    assert result is expected
    refresh.assert_awaited_once_with(provider=ProviderName.OPENROUTER, force=True)


async def test_unsupported_direct_discovery_is_not_successful_empty_publication() -> None:
    """Unsupported direct adapters retain the snapshot and report unavailability."""
    with patch.object(ModelCatalogService, "_snapshot", None):
        result = await ProviderModelDiscoveryService.refresh(provider=ProviderName.ANTHROPIC)
        assert result.status == "failed"
        assert ModelCatalogService._snapshot is None
