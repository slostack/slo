"""Synthetic provider cache shared by namespace and mixed-version tests."""

from src.agents.model_catalog.dao import ModelCatalogCacheDAO, ProviderCatalogCacheDAO
from src.agents.model_catalog.seed import SeedModelCatalog
from src.auth.credential_dao import ProviderName


def openrouter_cache_sample() -> ModelCatalogCacheDAO:
    """Return a fresh one-entry OpenRouter cache for persistence tests.

    Catalog separation and compatibility tests call this before writing their
    owned cache files. The exact route, API identifier and provider agree.

    Returns:
        ModelCatalogCacheDAO: Synthetic provider metadata, never a real key.
    """
    entry = (
        SeedModelCatalog.load()
        .entries["gpt-5.5"]
        .model_copy(
            update={
                "model_name": "openrouter:vendor/compat",
                "api_model_name": "vendor/compat",
                "provider": ProviderName.OPENROUTER,
                "aliases": (),
                "support_tier": "auto_discovered",
            }
        )
    )
    return ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER, credential_fingerprint="fingerprint", entries=[entry]
            )
        ]
    )
