"""Public lifecycle evidence is independent of catalog entry equality."""

from unittest.mock import patch
from pathlib import Path

from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_dao import ProviderName
from src.auth.credential_resolver import CredentialResolver


def test_missing_credential_publishes_safe_status_without_snapshot() -> None:
    """Offline reads expose no credential material and do not resolve credentials."""
    ModelCatalogService.reset()
    with patch.object(CredentialResolver, "resolve", side_effect=AssertionError("read I/O")):
        status = ModelCatalogService.lifecycle_status()
    assert status.revision >= 0
    assert status.key_verified_at is None
    assert status.catalog_checked_at is None
    assert set(status.model_dump()) == {"revision", "state", "key_verified_at", "catalog_checked_at"}


async def test_missing_refresh_advances_status_revision() -> None:
    """A failed no-key refresh publishes a requires-auth fact without entry changes."""
    ModelCatalogService.reset()
    before = ModelCatalogService.lifecycle_status()
    with patch.object(CredentialResolver, "resolve_with_source", return_value=None):
        result = await ModelCatalogService.refresh(provider=ProviderName.OPENROUTER)
    after = ModelCatalogService.lifecycle_status()
    assert result.status == "failed"
    assert after.revision > before.revision
    assert after.state == "requires_auth"
    assert after.catalog_checked_at is None


async def test_success_and_failure_publish_actual_cache_evidence(tmp_path: Path) -> None:
    """Listing failure retains real checked time and advances status without new entries."""
    from tests.agents.model_catalog.test_openrouter_lifecycle import FakeOpenRouterClient
    from src.auth.credential_dao import AuthType, CredentialDAO, CredentialSource, ResolvedCredentialDAO

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE)
    path = tmp_path / "cache.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    ModelCatalogService.reset()
    with patch.object(CredentialResolver, "resolve_with_source", return_value=resolved):
        await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
            cache_path=path,
        )
        checked = ModelCatalogService.lifecycle_status()
        assert checked.state == "checked"
        assert checked.key_verified_at is not None
        assert checked.catalog_checked_at is not None
        with patch.object(FakeOpenRouterClient, "list_user_models", side_effect=RuntimeError("private")):
            await ModelCatalogService.refresh(
                provider=ProviderName.OPENROUTER,
                force=True,
                client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
                cache_path=path,
            )
        failed = ModelCatalogService.lifecycle_status()
        assert failed.state == "failed"
        assert failed.revision > checked.revision
        assert failed.catalog_checked_at == checked.catalog_checked_at
        assert "private" not in failed.model_dump_json()
    ModelCatalogService.reset()
