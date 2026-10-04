"""Offline persistence/publication contracts for the bounded Feature 86 unit."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.agents.model_catalog import store as catalog_store
from src.agents.model_catalog.dao import (
    CatalogRefreshResultDAO,
    ModelCatalogCacheDAO,
    ModelCatalogSnapshotDAO,
)
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.model_catalog.store import ModelCatalogStore
from src.agents.slo_agent.history.atomic_io import AtomicFileWriter, AtomicWriteOutcomeDAO
from src.auth.credential_dao import (
    AuthType,
    CredentialDAO,
    CredentialSource,
    ProviderName,
    ResolvedCredentialDAO,
)
from src.auth.credential_resolver import CredentialResolver
from src.integrations.openrouter.dao import OpenRouterModelsResponseDAO
from tests.agents.model_catalog.test_openrouter_refresh_credential_contract import RecordingOpenRouterClient


@pytest.fixture(autouse=True)
def isolated_catalog(tmp_path: Path) -> Iterator[Path]:
    """Confine real store/lease/writer destinations and forbid default HTTP."""
    root = tmp_path.resolve(strict=True)
    original_write = AtomicFileWriter.write_text_with_outcome
    original_write_text = Path.write_text

    def checked_write_text(
        self: Path, data: str, encoding: str = "utf-8", errors: str = "strict", newline: str | None = None
    ) -> int:
        """Guard direct fixture writes before delegating to pathlib."""
        assert self.resolve().is_relative_to(root)
        return original_write_text(self, data=data, encoding=encoding, errors=errors, newline=newline)

    def checked_write(*, path: Path, text: str, private: bool = True) -> AtomicWriteOutcomeDAO:
        """Check ancestry before the real atomic writer creates sibling files."""
        assert path.resolve().is_relative_to(root)
        return original_write(path=path, text=text, private=private)

    with (
        patch.object(catalog_store, "_global_dir", return_value=root),
        patch.object(Path, "write_text", new=checked_write_text),
        patch.object(CredentialResolver, "resolve_with_source", return_value=captured_key()),
        patch.object(ModelCatalogStore, "overrides_path", return_value=root / "overrides.json"),
        patch.object(AtomicFileWriter, "write_text_with_outcome", side_effect=checked_write),
        patch.object(httpx.AsyncClient, "send", side_effect=AssertionError("Default HTTP forbidden")),
        patch.object(httpx.Client, "send", side_effect=AssertionError("Default HTTP forbidden")),
    ):
        ModelCatalogService.reset()
        yield root
        ModelCatalogService.reset()


def captured_key(*, token: str = "synthetic-publication-a") -> ResolvedCredentialDAO:
    """Build private synthetic evidence without reading the host credential store."""
    return ResolvedCredentialDAO(
        credential=CredentialDAO(
            provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token=token
        ),
        source=CredentialSource.STORE,
    )


async def test_owned_refresh_when_lease_is_held_delegates_lifecycle_decisions_to_existing_helpers(
    isolated_catalog: Path,
) -> None:
    """The lease owner delegates freshness through publication without re-owning branch logic."""
    effective = captured_key()
    expected = CatalogRefreshResultDAO(
        status="fresh",
        catalog_generation=0,
        safe_message="OpenRouter catalog is current.",
    )
    delegated = AsyncMock(return_value=expected)

    client_factory = lambda credential: RecordingOpenRouterClient(credential=credential)
    with patch.object(ModelCatalogService, "_refresh_openrouter_under_lease", new=delegated):
        result = await ModelCatalogService._refresh_openrouter_owned(
            effective=effective,
            fingerprint="synthetic-fingerprint",
            force=False,
            credential_was_supplied=False,
            supplied_effective_fingerprint=None,
            key_verification=None,
            client_factory=client_factory,
            cache_path=isolated_catalog / "model_catalog_cache.v2.json",
            operation_token=1,
        )

    assert result is expected
    delegated.assert_awaited_once_with(
        observed_cache=None,
        effective=effective,
        fingerprint="synthetic-fingerprint",
        force=False,
        credential_was_supplied=False,
        supplied_effective_fingerprint=None,
        key_verification=None,
        client_factory=client_factory,
        cache_path=isolated_catalog / "model_catalog_cache.v2.json",
        operation_token=1,
    )


async def test_rotation_failure_hides_rows_without_discarding_publication(isolated_catalog: Path) -> None:
    """Retain A while B fails, then admit B only after a monotonic publication."""
    current = captured_key()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def failed_listing() -> OpenRouterModelsResponseDAO:
        """Hold the failed replacement so offline readers can inspect the boundary."""
        entered.set()
        await asyncio.wait_for(release.wait(), timeout=5)
        raise RuntimeError("synthetic listing failure")

    with patch.object(CredentialResolver, "resolve_with_source", side_effect=lambda **kwargs: current):
        client = RecordingOpenRouterClient(credential=current.credential)
        await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER, force=True, client_factory=lambda credential: client
        )
        before = ModelCatalogService.load()
        cache_path = isolated_catalog / "model_catalog_cache.v2.json"
        disk_before = cache_path.read_bytes()
        current = captured_key(token="synthetic-publication-b")
        client = RecordingOpenRouterClient(credential=current.credential)
        with patch.object(client, "list_user_models", side_effect=failed_listing):
            task = asyncio.create_task(
                ModelCatalogService.refresh(
                    provider=ProviderName.OPENROUTER, force=True, client_factory=lambda credential: client
                )
            )
            await asyncio.wait_for(entered.wait(), timeout=5)
            try:
                with patch.object(
                    CredentialResolver, "resolve_with_source", side_effect=AssertionError("read")
                ):
                    hidden = ModelCatalogService.load()
                    assert "openrouter:vendor/captured-model" not in hidden.entries
                    assert ModelCatalogService._snapshot is before
                    assert hidden.generation == before.generation
            finally:
                release.set()
                result = await asyncio.wait_for(task, timeout=5)
        assert result.status == "failed"
        assert result.catalog_generation == before.generation
        assert ModelCatalogService._snapshot is before
        assert cache_path.read_bytes() == disk_before
        await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER, force=True, client_factory=lambda credential: client
        )
        admitted = await ModelCatalogService.prepare_models(model_names=("openrouter:vendor/captured-model",))
        assert admitted is ModelCatalogService.load()
        assert admitted.generation == before.generation + 1
        assert "openrouter:vendor/captured-model" in admitted.entries


async def test_invalid_override_preserves_disk_and_snapshot(isolated_catalog: Path) -> None:
    """A rejected full merged candidate must not persist even its valid raw slice."""
    import json

    resolved = captured_key()
    client = RecordingOpenRouterClient(credential=resolved.credential)
    with patch.object(CredentialResolver, "resolve_with_source", return_value=resolved):
        first = await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER, force=True, client_factory=lambda credential: client
        )
        assert first.status == "refreshed"
        before = ModelCatalogService.load()
        cache_path = isolated_catalog / "model_catalog_cache.v2.json"
        disk_before = cache_path.read_bytes()
        profile = before.entries["openrouter:vendor/captured-model"].runtime_profile.model_dump()
        profile["context_window"] = 2000
        override_path = isolated_catalog / "overrides.json"
        assert override_path.resolve().is_relative_to(isolated_catalog)
        override_path.write_text(
            json.dumps([{"model_name": "openrouter:vendor/captured-model", "runtime_profile": profile}]),
            encoding="utf-8",
        )
        result = await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER, force=True, client_factory=lambda credential: client
        )
        assert result.status == "failed"
        unchanged = cache_path.read_bytes() == disk_before
        assert unchanged, "Invalid override persisted raw candidate"
        assert ModelCatalogService.load() is before
        assert result.catalog_generation == before.generation


@pytest.mark.parametrize("force", [True, False])
async def test_supplied_auth_rotation_during_overrides_rejects_publication(
    isolated_catalog: Path, force: bool
) -> None:
    """Both fetched and fresh-cache paths reject rotation across the override await."""
    current = captured_key()
    client = RecordingOpenRouterClient(credential=current.credential)
    entered = asyncio.Event()
    release = asyncio.Event()
    original = ModelCatalogService._build_publication_candidate

    async def paused_candidate(*, cache: ModelCatalogCacheDAO) -> ModelCatalogSnapshotDAO:
        """Finish real override validation, then hold its awaited return at a barrier."""
        candidate = await original(cache=cache)
        entered.set()
        await asyncio.wait_for(release.wait(), timeout=5)
        return candidate

    def resolve(*, provider: ProviderName) -> ResolvedCredentialDAO:
        """Expose only the synthetic current effective identity."""
        return current

    with patch.object(CredentialResolver, "resolve_with_source", side_effect=resolve):
        await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER, force=True, client_factory=lambda credential: client
        )
        before = ModelCatalogService.load()
        cache_path = isolated_catalog / "model_catalog_cache.v2.json"
        disk_before = cache_path.read_bytes()
        evidence = await client.get_current_key()
        key_calls = client.key_calls
        models_calls = client.models_calls
        with patch.object(ModelCatalogService, "_build_publication_candidate", side_effect=paused_candidate):
            task = asyncio.create_task(
                ModelCatalogService.refresh(
                    provider=ProviderName.OPENROUTER,
                    force=force,
                    resolved_credential=current,
                    key_verification=evidence,
                    client_factory=lambda credential: client,
                )
            )
            await asyncio.wait_for(entered.wait(), timeout=5)
            current = captured_key(token="synthetic-publication-b")
            release.set()
            result = await asyncio.wait_for(task, timeout=5)
        assert result.status == "credential_changed"
        unchanged = cache_path.read_bytes() == disk_before
        assert unchanged, "Override race persisted stale candidate"
        assert ModelCatalogService.load() is before
        assert result.catalog_generation == before.generation
        assert client.key_calls == key_calls
        assert client.models_calls == models_calls + int(force)


@pytest.mark.parametrize("rotate", [True, False])
async def test_equal_entries_publish_new_provenance_and_generation(
    isolated_catalog: Path, rotate: bool
) -> None:
    """Real raw-cache replacement advances identity/freshness even with equal entries."""
    from src.integrations.openrouter.dao import credential_fingerprint

    current = captured_key()

    def resolve(*, provider: ProviderName) -> ResolvedCredentialDAO:
        """Expose the synthetic credential selected for this operation."""
        return current

    with patch.object(CredentialResolver, "resolve_with_source", side_effect=resolve):
        client = RecordingOpenRouterClient(credential=current.credential)
        await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER, force=True, client_factory=lambda credential: client
        )
        before = ModelCatalogService.load()
        cache_before = ModelCatalogStore.load_provider_cache()
        assert cache_before is not None
        if rotate:
            current = captured_key(token="synthetic-publication-b")
        client = RecordingOpenRouterClient(credential=current.credential)
        result = await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER, force=True, client_factory=lambda credential: client
        )
        after = ModelCatalogService.load()
        cache_after = ModelCatalogStore.load_provider_cache()
        assert cache_after is not None
        assert result.status == "refreshed"
        assert after.entries == before.entries
        assert after is not before
        assert after.generation == before.generation + 1
        provenance_changed = (
            cache_after.provider_slices[0].credential_fingerprint
            != cache_before.provider_slices[0].credential_fingerprint
        )
        assert provenance_changed is rotate
        assert (
            cache_after.provider_slices[0].last_success_at != cache_before.provider_slices[0].last_success_at
        )
        public = after.model_dump(mode="json")
        public["entries"].clear()
        assert ModelCatalogService.load().entries == before.entries
        exposed = after.model_dump_json() + result.model_dump_json() + repr(after) + repr(result)
        for token in ("synthetic-publication-a", "synthetic-publication-b"):
            assert token not in exposed
            assert credential_fingerprint(access_token=token) not in exposed
