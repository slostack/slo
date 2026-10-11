"""Deterministic local lifecycle ordering and invalidation regressions."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.model_catalog.dao import ModelCatalogCacheDAO
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
from src.integrations.openrouter.dao import (
    OpenRouterKeyVerificationDAO,
    OpenRouterModelsResponseDAO,
    credential_fingerprint,
)
from src.integrations.openrouter.exceptions import OpenRouterAuthenticationError
from tests.agents.model_catalog.test_openrouter_lifecycle import FakeOpenRouterClient


def _credential(*, label: str) -> ResolvedCredentialDAO:
    """Build a synthetic store capture with no external credential lookup."""
    return ResolvedCredentialDAO(
        credential=CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=f"synthetic-takeover-{label}",
        ),
        source=CredentialSource.STORE,
    )


@pytest.mark.parametrize("removed", [False, True])
async def test_key_response_after_rotation_never_publishes_verification(
    tmp_path: Path, removed: bool
) -> None:
    """Observe public status at the next actual endpoint after a key-boundary rotation."""
    first, second = _credential(label="publication-A"), _credential(label="publication-B")
    assert (tmp_path / "cache.json").resolve().is_relative_to(tmp_path.resolve())
    ModelCatalogService.reset()
    with (
        patch.object(CredentialResolver, "resolve_with_source", return_value=first) as resolver,
        patch.object(ModelCatalogStore, "overrides_path", return_value=tmp_path / "overrides.json"),
    ):

        class RotatingClient(FakeOpenRouterClient):
            """Rotate effective identity after verification without changing the client capture."""

            async def get_current_key(self) -> OpenRouterKeyVerificationDAO:
                """Return A's evidence after resolver identity changes."""
                evidence = await super().get_current_key()
                resolver.return_value = None if removed else second
                return evidence

            async def list_user_models(self) -> OpenRouterModelsResponseDAO:
                """Assert no A verification is published for B or missing credentials."""
                status = ModelCatalogService.lifecycle_status()
                assert status.key_verified_at is None
                assert status.state == ("requires_auth" if removed else "credential_changed")
                public = status.model_dump_json() + repr(status)
                for capture in (first, second):
                    assert capture.credential.access_token not in public
                    assert credential_fingerprint(access_token=capture.credential.access_token) not in public
                assert self.credential == first.credential
                return await super().list_user_models()

        try:
            result = await ModelCatalogService.refresh(
                provider=ProviderName.OPENROUTER,
                force=True,
                cache_path=tmp_path / "cache.json",
                client_factory=lambda credential: RotatingClient(credential=credential),
            )
            assert result.status == "credential_changed"
        finally:
            await ModelCatalogService.shutdown()
            ModelCatalogService.reset()


@pytest.mark.parametrize("late_failure", [False, True])
@pytest.mark.parametrize("cancel_joiner", [False, True])
@pytest.mark.parametrize("late_joiner", [False, True])
async def test_old_operation_cannot_overwrite_new_status(
    tmp_path: Path, late_failure: bool, cancel_joiner: bool, late_joiner: bool
) -> None:
    """Release A's key response only after B publishes its complete checked status."""
    entered, release = asyncio.Event(), asyncio.Event()
    first, second = _credential(label="A"), _credential(label="B")
    for name in ("a/cache.json", "b/cache.json", "overrides.json"):
        assert (tmp_path / name).resolve().is_relative_to(tmp_path.resolve())

    class DelayedClient(FakeOpenRouterClient):
        """Hold the old operation at the key boundary without sleeps."""

        async def get_current_key(self) -> OpenRouterKeyVerificationDAO:
            """Await B then return old verification or a safe failure."""
            entered.set()
            await release.wait()
            if late_failure:
                raise OpenRouterAuthenticationError()
            return await super().get_current_key()

    ModelCatalogService.reset()
    with (
        patch.object(CredentialResolver, "resolve_with_source", return_value=first) as resolver,
        patch.object(ModelCatalogStore, "overrides_path", return_value=tmp_path / "overrides.json"),
    ):
        older = asyncio.create_task(
            ModelCatalogService.refresh(
                provider=ProviderName.OPENROUTER,
                force=True,
                cache_path=tmp_path / "a" / "cache.json",
                client_factory=lambda credential: DelayedClient(credential=credential),
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            joiner = asyncio.create_task(
                ModelCatalogService.refresh(
                    provider=ProviderName.OPENROUTER,
                    force=True,
                    cache_path=tmp_path / "a" / "cache.json",
                    client_factory=lambda credential: DelayedClient(credential=credential),
                )
            )
            # Wait for the coalesced subscriber, not a clock-based ordering guess.
            while sum(ModelCatalogService._refresh_waiters.values()) < 2:
                await asyncio.sleep(0)
            resolver.return_value = second
            result = await ModelCatalogService.refresh(
                provider=ProviderName.OPENROUTER,
                force=True,
                cache_path=tmp_path / "b" / "cache.json",
                client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
            )
            assert result.status == "refreshed"
            winner = ModelCatalogService.lifecycle_status()
            assert winner.state == "checked"
            if late_joiner:
                late = asyncio.create_task(
                    ModelCatalogService.refresh(
                        provider=ProviderName.OPENROUTER,
                        force=True,
                        resolved_credential=first,
                        cache_path=tmp_path / "a" / "cache.json",
                        client_factory=lambda credential: DelayedClient(credential=credential),
                    )
                )
                while sum(ModelCatalogService._refresh_waiters.values()) < 3:
                    await asyncio.sleep(0)
                try:
                    assert ModelCatalogService.lifecycle_status() == winner
                finally:
                    late.cancel()
                    await asyncio.gather(late, return_exceptions=True)
            if cancel_joiner:
                joiner.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await joiner
            release.set()
            await older
            if not cancel_joiner:
                await joiner
            assert ModelCatalogService.lifecycle_status() == winner
        finally:
            release.set()
            await ModelCatalogService.shutdown()
            ModelCatalogService.reset()


async def test_admission_rotation_clears_status_before_cache_read(tmp_path: Path) -> None:
    """Admission reconciles identity before awaiting I/O without mutating its prior snapshot."""
    first, second = _credential(label="admit-A"), _credential(label="admit-B")
    assert (tmp_path / "model_catalog_cache.v2.json").resolve().is_relative_to(tmp_path.resolve())
    ModelCatalogService.reset()
    with (
        patch.object(CredentialResolver, "resolve_with_source", return_value=first) as resolver,
        patch("src.agents.model_catalog.store._global_dir", return_value=tmp_path),
        patch.object(ModelCatalogStore, "overrides_path", return_value=tmp_path / "overrides.json"),
    ):
        try:
            await ModelCatalogService.refresh(
                provider=ProviderName.OPENROUTER,
                force=True,
                client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
            )
            admitted = await ModelCatalogService.prepare_models(
                model_names=("openrouter:vendor/unseeded-tool-model",)
            )
            original = admitted.model_dump_json()
            resolver.return_value = second
            original_load = ModelCatalogStore.load_provider_cache

            def observe_cache(*, override_path: Path | None = None) -> ModelCatalogCacheDAO | None:
                """Observe status at the first asynchronous admission boundary."""
                assert ModelCatalogService.lifecycle_status().key_verified_at is None
                assert ModelCatalogService.lifecycle_status().state == "credential_changed"
                return original_load(override_path=override_path)

            with (
                patch.object(ModelCatalogStore, "load_provider_cache", side_effect=observe_cache),
                patch(
                    "src.agents.model_catalog.service.OpenRouterAPIClient",
                    side_effect=lambda *, credential: FakeOpenRouterClient(credential=credential),
                ),
            ):
                await ModelCatalogService.prepare_models(
                    model_names=("openrouter:vendor/unseeded-tool-model",)
                )
            assert admitted.model_dump_json() == original
        finally:
            await ModelCatalogService.shutdown()
            ModelCatalogService.reset()


async def test_public_status_reconciles_rotation_before_fresh_cache_status_publish(tmp_path: Path) -> None:
    """A rotated resolver identity prevents an older fresh slice from claiming checked."""
    first, second = _credential(label="fresh-A"), _credential(label="fresh-B")
    cache_path = tmp_path / "cache.json"
    assert cache_path.resolve().is_relative_to(tmp_path.resolve())
    ModelCatalogService.reset()
    with (
        patch.object(CredentialResolver, "resolve_with_source", return_value=first) as resolver,
        patch.object(ModelCatalogStore, "overrides_path", return_value=tmp_path / "overrides.json"),
    ):
        await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
            cache_path=cache_path,
        )
        resolver.return_value = second
        result = await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=False,
            resolved_credential=first,
            client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
            cache_path=cache_path,
        )

    status = ModelCatalogService.lifecycle_status()
    assert result.status == "credential_changed"
    assert status.state == "credential_changed"
    assert status.key_verified_at is None
    assert status.catalog_checked_at is None
    public = status.model_dump_json() + repr(status)
    for credential in (first, second):
        assert credential.credential.access_token not in public
        assert credential_fingerprint(access_token=credential.credential.access_token) not in public
    await ModelCatalogService.shutdown()
    ModelCatalogService.reset()


async def test_reset_identity_is_not_reused_by_new_refresh(tmp_path: Path) -> None:
    """Reset fences retiring owners even when a new refresh starts immediately."""
    assert (tmp_path / "cache.json").resolve().is_relative_to(tmp_path.resolve())
    resolved = _credential(label="reset")
    ModelCatalogService.reset()
    old_identity = ModelCatalogService._current_openrouter_operation
    ModelCatalogService.reset()
    assert ModelCatalogService._current_openrouter_operation > old_identity
    with (
        patch.object(CredentialResolver, "resolve_with_source", return_value=resolved),
        patch.object(ModelCatalogStore, "overrides_path", return_value=tmp_path / "overrides.json"),
    ):
        try:
            await ModelCatalogService.refresh(
                provider=ProviderName.OPENROUTER,
                force=True,
                cache_path=tmp_path / "cache.json",
                client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
            )
            assert ModelCatalogService._current_openrouter_operation > old_identity
        finally:
            await ModelCatalogService.shutdown()
            ModelCatalogService.reset()


@pytest.mark.parametrize("rejection_status", [401, 403, None])
async def test_rejection_or_removal_clears_public_verification(
    tmp_path: Path, rejection_status: int | None
) -> None:
    """Previously successful verification cannot remain public after invalidation."""
    path = tmp_path / "cache.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    resolved = _credential(label="prior-success")
    ModelCatalogService.reset()
    with (
        patch.object(CredentialResolver, "resolve_with_source", return_value=resolved) as resolver,
        patch("src.agents.model_catalog.store._global_dir", return_value=tmp_path),
        patch.object(ModelCatalogStore, "overrides_path", return_value=tmp_path / "overrides.json"),
    ):
        await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
        )
        assert ModelCatalogService.lifecycle_status().key_verified_at is not None
        if rejection_status is None:
            resolver.return_value = None
            with pytest.raises(ModelPreparationRequiredError):
                await ModelCatalogService.prepare_models(
                    model_names=("openrouter:vendor/unseeded-tool-model",)
                )
        else:
            with patch.object(
                FakeOpenRouterClient,
                "get_current_key",
                side_effect=OpenRouterAuthenticationError(status_code=rejection_status),
            ):
                await ModelCatalogService.refresh(
                    provider=ProviderName.OPENROUTER,
                    force=True,
                    client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
                )
        assert ModelCatalogService.lifecycle_status().key_verified_at is None
        assert ModelCatalogService.lifecycle_status().state in {"failed", "requires_auth"}
    await ModelCatalogService.shutdown()
    ModelCatalogService.reset()


@pytest.mark.parametrize("status_code", [401, 403])
async def test_listing_rejection_clears_public_verification_and_preserves_raw_cache(
    status_code: int,
    tmp_path: Path,
) -> None:
    """Treat listing authorization rejection as key rejection without deleting last-good bytes."""
    cache_path = tmp_path / "cache.json"
    assert cache_path.resolve().is_relative_to(tmp_path.resolve())
    resolved = _credential(label="listing-rejection")
    client = FakeOpenRouterClient(credential=resolved.credential)
    ModelCatalogService.reset()
    with (
        patch.object(CredentialResolver, "resolve_with_source", return_value=resolved),
        patch.object(ModelCatalogStore, "overrides_path", return_value=tmp_path / "overrides.json"),
    ):
        await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            client_factory=lambda credential: client,
            cache_path=cache_path,
        )
        raw_bytes = cache_path.read_bytes()

        class ListingRejectionClient(FakeOpenRouterClient):
            """Return fresh matching key evidence then reject the listing."""

            async def list_user_models(self) -> OpenRouterModelsResponseDAO:
                """Reject the authenticated listing without exposing an upstream body."""
                self.model_calls += 1
                raise OpenRouterAuthenticationError(status_code=status_code)

        result = await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            client_factory=lambda credential: ListingRejectionClient(credential=credential),
            cache_path=cache_path,
        )

    status = ModelCatalogService.lifecycle_status()
    assert result.status == "failed"
    assert status.state == "failed"
    assert status.key_verified_at is None
    assert status.catalog_checked_at is None
    assert cache_path.read_bytes() == raw_bytes
    await ModelCatalogService.shutdown()
    ModelCatalogService.reset()


@pytest.mark.parametrize("discovered", [False, True])
async def test_pool_requires_every_exact_route(tmp_path: Path, discovered: bool) -> None:
    """A fresh present member never short-circuits discovery of a missing pool member."""
    assert tmp_path.resolve().is_relative_to(tmp_path.resolve())
    resolved = _credential(label="pool")
    client = FakeOpenRouterClient(credential=resolved.credential)
    ModelCatalogService.reset()
    with (
        patch.object(CredentialResolver, "resolve_with_source", return_value=resolved),
        patch("src.agents.model_catalog.store._global_dir", return_value=tmp_path),
        patch.object(ModelCatalogStore, "overrides_path", return_value=tmp_path / "overrides.json"),
        patch("src.agents.model_catalog.service.OpenRouterAPIClient", return_value=client),
    ):
        await ModelCatalogService.refresh(provider=ProviderName.OPENROUTER, force=True)
        original = await client.list_user_models()
        rows = list(original.data)
        if discovered:
            rows.append({**rows[0], "id": "vendor/missing"})
        with patch.object(
            client, "list_user_models", return_value=OpenRouterModelsResponseDAO(data=rows)
        ) as listing:
            names = ("gpt-5.4", "openrouter:vendor/unseeded-tool-model", "openrouter:vendor/missing")
            if discovered:
                prepared = await ModelCatalogService.prepare_models(model_names=names)
                assert all(name in prepared.entries for name in names)
            else:
                with pytest.raises(ModelPreparationRequiredError):
                    await ModelCatalogService.prepare_models(model_names=names)
            assert listing.await_count == 1
    await ModelCatalogService.shutdown()
    ModelCatalogService.reset()
