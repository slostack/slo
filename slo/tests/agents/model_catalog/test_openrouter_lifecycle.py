"""Focused async lifecycle tests for OpenRouter catalog publication."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import asyncio
import multiprocessing
from pathlib import Path

import pytest

from src.agents.model_catalog.dao import (
    ModelCatalogCacheDAO,
    ProviderCatalogCacheDAO,
    ProviderCatalogTombstoneDAO,
)
from src.agents.model_catalog.service import ModelCatalogService
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


def _hold_refresh_lease(
    cache_path: str,
    acquired: multiprocessing.synchronize.Event,
    release: multiprocessing.synchronize.Event,
) -> None:
    """Hold the process lease until the parent releases a deterministic barrier.

    WHAT: Acquires the real POSIX lock under a pytest tmp-path and reports readiness.
    WHO: Called only by the lease-contention regression child process.
    WHEN: Runs before the parent attempts a conflicting lease acquisition.
    """
    asyncio.run(_hold_refresh_lease_async(cache_path=Path(cache_path), acquired=acquired, release=release))


async def _hold_refresh_lease_async(
    *,
    cache_path: Path,
    acquired: multiprocessing.synchronize.Event,
    release: multiprocessing.synchronize.Event,
) -> None:
    """Hold the async lease across the parent-controlled release event.

    WHAT: Enters the production lease and waits without a timing-based test gate.
    WHO: Called by the child-process target above.
    WHEN: Exists only for the deterministic process-contention test.
    """
    async with ModelCatalogStore.refresh_lease(cache_path=cache_path):
        acquired.set()
        await asyncio.to_thread(release.wait)


class FakeOpenRouterClient:
    """Injected authenticated metadata client with observable calls."""

    def __init__(self, *, credential: CredentialDAO) -> None:
        """Retain the captured credential for assertions."""
        self.credential = credential
        self.key_calls = 0
        self.model_calls = 0

    async def get_current_key(self) -> OpenRouterKeyVerificationDAO:
        """Return matching private verification evidence."""
        self.key_calls += 1
        return OpenRouterKeyVerificationDAO(
            credential_fingerprint=credential_fingerprint(access_token=self.credential.access_token),
            verified_at=datetime.now(tz=timezone.utc),
        )

    async def list_user_models(self) -> OpenRouterModelsResponseDAO:
        """Return one complete, suitable unseeded record."""
        self.model_calls += 1
        return OpenRouterModelsResponseDAO(
            data=[
                {
                    "id": "vendor/unseeded-tool-model",
                    "context_length": 1000,
                    "supported_parameters": ["tools"],
                    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                }
            ]
        )


class RecordsOpenRouterClient(FakeOpenRouterClient):
    """Supply explicit complete listings without assigning over typed methods."""

    def __init__(self, *, credential: CredentialDAO, records: list[dict[str, object]]) -> None:
        """Capture synthetic rows for reconciliation and malformed-list tests.

        Args:
            credential: Synthetic captured credential, never resolved externally.
            records: Complete fixture rows returned at the listing boundary.
        """
        super().__init__(credential=credential)
        self.records = records

    async def list_user_models(self) -> OpenRouterModelsResponseDAO:
        """Return the fixture response when the refresh owner requests its listing."""
        self.model_calls += 1
        return OpenRouterModelsResponseDAO(data=self.records)


@pytest.mark.asyncio
async def test_refresh_when_internally_created_client_fails_closes_client(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Close the service-created GET client before returning its safe failure outcome."""
    import src.agents.model_catalog.service as service_module
    from src.integrations.openrouter.exceptions import OpenRouterAPIError

    cache_path = tmp_path / "model_catalog_cache.v2.json"
    assert cache_path.parent.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-owned-client-key",
    )
    entered = asyncio.Event()
    closed = asyncio.Event()

    class FailingOwnedClient:
        """Instrument the production default-client construction seam without HTTP."""

        def __init__(self, *, credential: CredentialDAO) -> None:
            """Accept the production captured credential without exposing it."""

        async def __aenter__(self) -> "FailingOwnedClient":
            """Record that the service entered the internally created client context."""
            entered.set()
            return self

        async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
            """Record teardown after the local verification failure."""
            closed.set()

        async def get_current_key(self) -> OpenRouterKeyVerificationDAO:
            """Raise the fixed safe failure used by the catalog boundary."""
            raise OpenRouterAPIError()

        async def list_user_models(self) -> OpenRouterModelsResponseDAO:
            """Reject unexpected listing after verification failure."""
            raise AssertionError("listing must not run after verification failure")

    monkeypatch.setattr(service_module, "OpenRouterAPIClient", FailingOwnedClient)
    ModelCatalogService.reset()

    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=ResolvedCredentialDAO(
            credential=credential,
            source=CredentialSource.ENVIRONMENT,
        ),
        cache_path=cache_path,
    )

    assert result.status == "failed"
    assert entered.is_set()
    assert closed.is_set()


@pytest.mark.asyncio
async def test_refresh_when_internally_created_client_is_cancelled_closes_before_propagating(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drain internally owned client teardown before refresh cancellation reaches its caller."""
    import src.agents.model_catalog.service as service_module

    cache_path = tmp_path / "model_catalog_cache.v2.json"
    assert cache_path.parent.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-owned-client-key",
    )
    entered = asyncio.Event()
    cancellation_seen = asyncio.Event()
    closed = asyncio.Event()

    class BlockingOwnedClient:
        """Hold the default client branch at an event barrier until cancellation."""

        def __init__(self, *, credential: CredentialDAO) -> None:
            """Accept the production captured credential without exposing it."""

        async def __aenter__(self) -> "BlockingOwnedClient":
            """Record production-owned client entry before the request begins."""
            entered.set()
            return self

        async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
            """Complete teardown after the request observes cancellation."""
            assert cancellation_seen.is_set()
            closed.set()

        async def get_current_key(self) -> OpenRouterKeyVerificationDAO:
            """Wait deterministically until the service-owned refresh is cancelled."""
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_seen.set()
                raise
            raise AssertionError("blocked request unexpectedly completed")

        async def list_user_models(self) -> OpenRouterModelsResponseDAO:
            """Reject unexpected listing after cancelled verification."""
            raise AssertionError("listing must not run after cancelled verification")

    monkeypatch.setattr(service_module, "OpenRouterAPIClient", BlockingOwnedClient)
    ModelCatalogService.reset()
    refresh = asyncio.create_task(
        ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            resolved_credential=ResolvedCredentialDAO(
                credential=credential,
                source=CredentialSource.ENVIRONMENT,
            ),
            cache_path=cache_path,
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=1)

    refresh.cancel()
    with pytest.raises(asyncio.CancelledError):
        await refresh

    assert cancellation_seen.is_set()
    assert closed.is_set()


@pytest.mark.asyncio
async def test_refresh_persists_then_publishes_unseeded_same_key_entry(tmp_path) -> None:
    """A complete injected discovery becomes visible through canonical catalog reads."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    client = FakeOpenRouterClient(credential=credential)
    ModelCatalogService.reset()

    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: client,
        cache_path=cache_path,
    )

    saved: ModelCatalogCacheDAO | None = ModelCatalogStore.load_provider_cache(override_path=cache_path)
    entry = ModelCatalogService.entry_for_model(model_name="openrouter:vendor/unseeded-tool-model")
    assert result.status == "refreshed"
    assert saved is not None
    assert saved.provider_slices[0].credential_fingerprint == credential_fingerprint(access_token="key-a")
    assert entry.visible_in_picker is True
    assert client.key_calls == 1
    assert client.model_calls == 1


@pytest.mark.asyncio
async def test_refresh_when_key_authentication_is_rejected_preserves_same_fingerprint_last_good_state(
    tmp_path,
) -> None:
    """A 401/403 key rejection neither publishes nor relabels a same-key last-good slice."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    assert cache_path.parent.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="secret-key-that-must-not-leak",
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    successful_client = FakeOpenRouterClient(credential=credential)
    ModelCatalogService.reset()
    await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: successful_client,
        cache_path=cache_path,
    )
    cache_before = ModelCatalogStore.load_provider_cache(override_path=cache_path)
    generation_before = ModelCatalogService.load().generation

    class RejectingKeyClient(FakeOpenRouterClient):
        """Return a sanitized authentication failure from the fixed GET boundary."""

        async def get_current_key(self) -> OpenRouterKeyVerificationDAO:
            """Reject the captured key without exposing provider response content."""
            self.key_calls += 1
            raise OpenRouterAuthenticationError(status_code=401)

    rejected_client = RejectingKeyClient(credential=credential)
    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: rejected_client,
        cache_path=cache_path,
    )

    cache_after = ModelCatalogStore.load_provider_cache(override_path=cache_path)
    assert result.status == "failed"
    assert result.catalog_generation == generation_before
    assert result.safe_message == "OpenRouter catalog refresh is unavailable."
    assert "secret-key-that-must-not-leak" not in repr(result)
    assert rejected_client.key_calls == 1
    assert rejected_client.model_calls == 0
    assert cache_after == cache_before


@pytest.mark.asyncio
async def test_refresh_when_listing_fails_after_key_verification_preserves_listing_timestamp_only(
    tmp_path,
) -> None:
    """A successful key check cannot manufacture a successful catalog listing timestamp."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="key-a",
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    ModelCatalogService.reset()

    class ListingFailureClient(FakeOpenRouterClient):
        """Return verification evidence then fail the authenticated model listing."""

        async def list_user_models(self) -> OpenRouterModelsResponseDAO:
            """Fail after the completed `/key` request without returning partial rows."""
            self.model_calls += 1
            raise RuntimeError("listing unavailable")

    client = ListingFailureClient(credential=credential)
    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: client,
        cache_path=cache_path,
    )

    assert result.status == "failed"
    assert client.key_calls == 1
    assert client.model_calls == 1
    assert ModelCatalogStore.load_provider_cache(override_path=cache_path) is None


@pytest.mark.asyncio
async def test_provider_slice_freshness_rejects_missing_future_and_exact_ttl_timestamps() -> None:
    """Only a matching listing timestamp strictly inside the one-hour TTL is fresh."""
    fingerprint = credential_fingerprint(access_token="key-a")
    now = datetime.now(tz=timezone.utc)
    missing = ProviderCatalogCacheDAO(
        provider=ProviderName.OPENROUTER,
        credential_fingerprint=fingerprint,
    )
    future = ProviderCatalogCacheDAO(
        provider=ProviderName.OPENROUTER,
        credential_fingerprint=fingerprint,
        last_success_at=(now + timedelta(seconds=1)).isoformat(),
    )
    exact_ttl = ProviderCatalogCacheDAO(
        provider=ProviderName.OPENROUTER,
        credential_fingerprint=fingerprint,
        last_success_at=(now - timedelta(seconds=3_600)).isoformat(),
    )

    assert ModelCatalogService._provider_slice_is_fresh(slice=missing, fingerprint=fingerprint) is False
    assert ModelCatalogService._provider_slice_is_fresh(slice=future, fingerprint=fingerprint) is False
    assert ModelCatalogService._provider_slice_is_fresh(slice=exact_ttl, fingerprint=fingerprint) is False


@pytest.mark.asyncio
async def test_refresh_complete_listing_records_expired_and_ineligible_tombstone_reasons(tmp_path) -> None:
    """A complete listing preserves prior unsuitable entries as reasoned reconciliation evidence."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="key-a",
    )
    prior_expired = _catalog_entry(model_name="openrouter:vendor/expired")
    prior_expired = prior_expired.model_copy(update={"availability": "expired", "visible_in_picker": False})
    prior_ineligible = _catalog_entry(model_name="openrouter:vendor/ineligible")
    prior_ineligible = prior_ineligible.model_copy(
        update={"availability": "ineligible", "visible_in_picker": False}
    )
    seed_cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint=credential_fingerprint(access_token=credential.access_token),
                entries=[prior_expired, prior_ineligible],
            )
        ]
    )
    ModelCatalogStore.write_provider_cache(cache=seed_cache, override_path=cache_path)
    empty_client = RecordsOpenRouterClient(credential=credential, records=[])
    ModelCatalogService.reset()

    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT),
        client_factory=lambda credential: empty_client,
        cache_path=cache_path,
    )

    saved = ModelCatalogStore.load_provider_cache(override_path=cache_path)
    assert result.status == "refreshed"
    assert saved is not None
    assert {item.model_name: item.reason for item in saved.provider_slices[0].tombstones} == {
        "openrouter:vendor/expired": "expired",
        "openrouter:vendor/ineligible": "ineligible",
    }


@pytest.mark.asyncio
async def test_refresh_complete_empty_list_reconciles_entries_and_writes_tombstone(tmp_path) -> None:
    """A complete empty listing removes the prior route instead of retaining stale membership."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    assert cache_path.parent.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    initial_client = FakeOpenRouterClient(credential=credential)
    empty_client = RecordsOpenRouterClient(credential=credential, records=[])
    ModelCatalogService.reset()

    await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: initial_client,
        cache_path=cache_path,
    )
    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: empty_client,
        cache_path=cache_path,
    )

    cache = ModelCatalogStore.load_provider_cache(override_path=cache_path)
    assert result.status == "refreshed"
    assert cache is not None
    assert cache.provider_slices[0].entries == []
    assert cache.provider_slices[0].tombstones[0].model_name == "openrouter:vendor/unseeded-tool-model"
    with pytest.raises(ValueError, match="openrouter:vendor/unseeded-tool-model"):
        ModelCatalogService.entry_for_model(model_name="openrouter:vendor/unseeded-tool-model")


@pytest.mark.asyncio
async def test_refresh_when_ordinary_capture_rotates_before_persistence_preserves_prior_cache(
    tmp_path, monkeypatch
) -> None:
    """An ordinary resolver capture cannot persist after its effective key rotates."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    assert cache_path.parent.resolve().is_relative_to(tmp_path.resolve())
    key_a = CredentialDAO(provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a")
    key_b = CredentialDAO(provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-b")
    resolved_a = ResolvedCredentialDAO(credential=key_a, source=CredentialSource.ENVIRONMENT)
    ModelCatalogService.reset()
    await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved_a,
        client_factory=lambda credential: FakeOpenRouterClient(credential=key_a),
        cache_path=cache_path,
    )
    before = ModelCatalogStore.load_provider_cache(override_path=cache_path)
    resolver_calls = 0

    def resolve_rotating_credential(*, provider: ProviderName) -> ResolvedCredentialDAO:
        """Return A at admission and B at the ordinary final consistency check."""
        nonlocal resolver_calls
        resolver_calls += 1
        credential = key_a if resolver_calls == 1 else key_b
        return ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)

    monkeypatch.setattr(CredentialResolver, "resolve_with_source", resolve_rotating_credential)

    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        client_factory=lambda credential: FakeOpenRouterClient(credential=key_a),
        cache_path=cache_path,
    )

    after = ModelCatalogStore.load_provider_cache(override_path=cache_path)
    assert result.status == "credential_changed"
    assert after == before


@pytest.mark.asyncio
async def test_refresh_prunes_tombstones_older_than_thirty_days_only_after_successful_publication(
    tmp_path,
) -> None:
    """A successful replacement retains recent removals but prunes expired diagnostic evidence."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    assert cache_path.parent.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a"
    )
    old_entry = _catalog_entry(model_name="openrouter:vendor/old")
    retained_tombstone = ProviderCatalogTombstoneDAO(
        model_name="openrouter:vendor/recent",
        api_model_name="vendor/recent",
        reason="removed",
        last_seen_at=(datetime.now(tz=timezone.utc) - timedelta(days=29)).isoformat(),
    )
    expired_tombstone = ProviderCatalogTombstoneDAO(
        model_name="openrouter:vendor/expired",
        api_model_name="vendor/expired",
        reason="removed",
        last_seen_at=(datetime.now(tz=timezone.utc) - timedelta(days=31)).isoformat(),
    )
    seed_cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint=credential_fingerprint(access_token="key-a"),
                entries=[old_entry],
                tombstones=[retained_tombstone, expired_tombstone],
            )
        ]
    )
    ModelCatalogStore.write_provider_cache(cache=seed_cache, override_path=cache_path)
    empty_client = RecordsOpenRouterClient(credential=credential, records=[])
    ModelCatalogService.reset()

    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT),
        client_factory=lambda credential: empty_client,
        cache_path=cache_path,
    )

    saved = ModelCatalogStore.load_provider_cache(override_path=cache_path)
    assert result.status == "refreshed"
    assert saved is not None
    assert {item.model_name for item in saved.provider_slices[0].tombstones} == {
        "openrouter:vendor/recent",
        "openrouter:vendor/old",
    }


@pytest.mark.asyncio
async def test_refresh_incomplete_duplicate_or_malformed_results_preserve_last_good_slice(tmp_path) -> None:
    """Each non-complete candidate fails closed without reconciling the last complete listing."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    assert cache_path.parent.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    ModelCatalogService.reset()
    await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
        cache_path=cache_path,
    )
    before = ModelCatalogStore.load_provider_cache(override_path=cache_path)
    assert before is not None

    for records in (
        [
            {
                "id": "vendor/duplicate",
                "context_length": 1000,
                "supported_parameters": ["tools"],
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            },
            {"id": "vendor/duplicate", "context_length": 2000},
        ],
        [
            {
                "id": "",
                "context_length": 1000,
                "supported_parameters": ["tools"],
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            }
        ],
    ):
        client = RecordsOpenRouterClient(credential=credential, records=records)
        result = await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            resolved_credential=resolved,
            client_factory=lambda credential: client,
            cache_path=cache_path,
        )
        assert result.status == "failed"
        assert ModelCatalogStore.load_provider_cache(override_path=cache_path) == before


@pytest.mark.asyncio
async def test_refresh_save_failure_does_not_publish_candidate(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-replace persistence failure leaves both cache and published generation unchanged."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    ModelCatalogService.reset()
    await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
        cache_path=cache_path,
    )
    before_cache = ModelCatalogStore.load_provider_cache(override_path=cache_path)
    before_generation = ModelCatalogService.load().generation

    def fail_save(*, cache: ModelCatalogCacheDAO, override_path: Path | None = None):
        """Simulate the store's precommit failure without touching disk."""
        raise OSError("precommit failure")

    monkeypatch.setattr(ModelCatalogStore, "write_provider_cache", fail_save)
    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
        cache_path=cache_path,
    )

    assert result.status == "failed"
    assert ModelCatalogStore.load_provider_cache(override_path=cache_path) == before_cache
    assert ModelCatalogService.load().generation == before_generation


@pytest.mark.asyncio
async def test_refresh_publishes_after_committed_durability_warning(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A committed replacement with uncertain directory sync still publishes the durable state."""
    from src.agents.slo_agent.history.atomic_io import AtomicWriteOutcomeDAO

    cache_path = tmp_path / "model_catalog_cache.v2.json"
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    original_write = ModelCatalogStore.write_provider_cache

    def committed_warning(
        *, cache: ModelCatalogCacheDAO, override_path: Path | None = None
    ) -> AtomicWriteOutcomeDAO:
        """Commit the real replacement and report only post-replace durability uncertainty."""
        original_write(cache=cache, override_path=override_path)
        return AtomicWriteOutcomeDAO(committed=True, durability_warning=True)

    monkeypatch.setattr(ModelCatalogStore, "write_provider_cache", committed_warning)
    ModelCatalogService.reset()
    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
        cache_path=cache_path,
    )

    assert result.status == "refreshed"
    assert ModelCatalogStore.load_provider_cache(override_path=cache_path) is not None
    assert ModelCatalogService.load().generation == result.catalog_generation


@pytest.mark.asyncio
async def test_refresh_lease_times_out_while_another_process_holds_it(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contention returns a bounded timeout after a child confirms it owns the real POSIX lock."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    assert cache_path.parent.resolve().is_relative_to(tmp_path.resolve())
    context = multiprocessing.get_context("fork")
    acquired = context.Event()
    release = context.Event()
    child = context.Process(target=_hold_refresh_lease, args=(str(cache_path), acquired, release))
    child.start()
    assert acquired.wait(timeout=5)
    monkeypatch.setattr("src.agents.model_catalog.store._REFRESH_LEASE_TIMEOUT_SECONDS", 0.0)
    try:
        with pytest.raises(TimeoutError, match="unavailable"):
            async with ModelCatalogStore.refresh_lease(cache_path=cache_path):
                pytest.fail("conflicting process acquired the lease")
    finally:
        release.set()
        child.join(timeout=5)
    assert child.exitcode == 0


@pytest.mark.asyncio
async def test_refresh_returns_safe_failure_when_posix_locking_is_unsupported(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unsupported locking fails the explicit refresh without changing last-good cache state."""
    import fcntl

    cache_path = tmp_path / "model_catalog_cache.v2.json"
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    ModelCatalogService.reset()
    await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
        cache_path=cache_path,
    )
    before = ModelCatalogStore.load_provider_cache(override_path=cache_path)

    def unsupported_lock(descriptor: int, operation: int) -> None:
        """Model an unsupported POSIX flock implementation."""
        raise OSError("flock unsupported")

    monkeypatch.setattr(fcntl, "flock", unsupported_lock)
    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
        cache_path=cache_path,
    )

    assert result.status == "failed"
    assert ModelCatalogStore.load_provider_cache(override_path=cache_path) == before


def _catalog_entry(*, model_name: str):
    """Build a valid OpenRouter catalog entry for raw-slice lifecycle fixtures."""
    return (
        ModelCatalogService._merge_seed_and_provider_cache(
            seed_snapshot=__import__(
                "src.agents.model_catalog.seed", fromlist=["SeedModelCatalog"]
            ).SeedModelCatalog.load(),
            provider_cache=None,
        )
        .entries["gpt-5.5"]
        .model_copy(
            update={"model_name": model_name, "api_model_name": model_name.removeprefix("openrouter:")}
        )
    )


def _model_record(*, model_id: str) -> dict[str, object]:
    """Build one complete eligible model record for deterministic lifecycle races."""
    return {
        "id": model_id,
        "context_length": 1000,
        "supported_parameters": ["tools"],
        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
    }


@pytest.mark.asyncio
async def test_refresh_same_key_fresh_slice_avoids_network_and_publishes_freshness_generation(
    tmp_path,
) -> None:
    """A same-fingerprint fresh listing republishes provenance without another metadata request."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    client = FakeOpenRouterClient(credential=credential)
    ModelCatalogService.reset()
    await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: client,
        cache_path=cache_path,
    )
    published_generation = ModelCatalogService.load().generation

    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        resolved_credential=resolved,
        client_factory=lambda credential: client,
        cache_path=cache_path,
    )

    assert result.status == "fresh"
    assert result.catalog_generation == published_generation + 1
    assert client.key_calls == 1
    assert client.model_calls == 1


@pytest.mark.asyncio
async def test_refresh_changed_credential_does_not_select_prior_key_slice(tmp_path) -> None:
    """A new credential cannot report an old key's cached discovery as fresh."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    key_a = CredentialDAO(provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a")
    key_b = CredentialDAO(provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-b")
    client_a = FakeOpenRouterClient(credential=key_a)
    client_b = FakeOpenRouterClient(credential=key_b)
    ModelCatalogService.reset()
    await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=ResolvedCredentialDAO(credential=key_a, source=CredentialSource.ENVIRONMENT),
        client_factory=lambda credential: client_a,
        cache_path=cache_path,
    )

    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        resolved_credential=ResolvedCredentialDAO(credential=key_b, source=CredentialSource.ENVIRONMENT),
        client_factory=lambda credential: client_b,
        cache_path=cache_path,
    )

    saved = ModelCatalogStore.load_provider_cache(override_path=cache_path)
    assert result.status == "refreshed"
    assert client_b.key_calls == 1
    assert saved is not None
    assert saved.provider_slices[0].credential_fingerprint == credential_fingerprint(access_token="key-b")


@pytest.mark.asyncio
async def test_reset_cancels_owned_refresh_task_and_removes_task_registry_entry(tmp_path) -> None:
    """The test cleanup seam cancels an in-flight shared owner without retaining stale tasks."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="key-a",
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingClient(FakeOpenRouterClient):
        """Block verification until the reset assertion has observed the owned task."""

        async def get_current_key(self) -> OpenRouterKeyVerificationDAO:
            """Wait at the client boundary so cancellation reaches the shared owner."""
            self.key_calls += 1
            started.set()
            await release.wait()
            return await super().get_current_key()

    ModelCatalogService.reset()
    refresh_task = asyncio.create_task(
        ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            resolved_credential=resolved,
            client_factory=lambda credential: BlockingClient(credential=credential),
            cache_path=cache_path,
        )
    )
    await started.wait()

    ModelCatalogService.reset()

    with pytest.raises(asyncio.CancelledError):
        await refresh_task
    assert ModelCatalogService._refresh_tasks == {}


@pytest.mark.asyncio
async def test_force_refresh_joins_existing_same_key_flight_without_duplicate_client_calls(tmp_path) -> None:
    """A forced caller joins an already-owned same-key refresh rather than opening another client lane."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    verification_started = asyncio.Event()
    allow_verification = asyncio.Event()

    class BarrierClient(FakeOpenRouterClient):
        """Hold key verification until both public callers have joined the flight."""

        async def get_current_key(self) -> OpenRouterKeyVerificationDAO:
            """Block at the client seam to make duplicate-call detection deterministic."""
            self.key_calls += 1
            verification_started.set()
            await allow_verification.wait()
            return OpenRouterKeyVerificationDAO(
                credential_fingerprint=credential_fingerprint(access_token=self.credential.access_token),
                verified_at=datetime.now(tz=timezone.utc),
            )

    client = BarrierClient(credential=credential)
    ModelCatalogService.reset()
    ordinary = asyncio.create_task(
        ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=False,
            resolved_credential=resolved,
            client_factory=lambda credential: client,
            cache_path=cache_path,
        )
    )
    await verification_started.wait()
    forced = asyncio.create_task(
        ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            resolved_credential=resolved,
            client_factory=lambda credential: client,
            cache_path=cache_path,
        )
    )
    await asyncio.sleep(0)

    assert client.key_calls == 1
    assert client.model_calls == 0
    allow_verification.set()

    ordinary_result, forced_result = await asyncio.gather(ordinary, forced)
    assert ordinary_result.status == forced_result.status == "refreshed"
    assert client.key_calls == 1
    assert client.model_calls == 1


@pytest.mark.asyncio
async def test_reset_replacement_callback_cannot_remove_new_same_loop_refresh_flight(tmp_path) -> None:
    """A cancelled retired task cannot erase a replacement flight from the shared registry."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    first_started = asyncio.Event()
    replacement_started = asyncio.Event()
    release_replacement = asyncio.Event()

    class FirstClient(FakeOpenRouterClient):
        """Block the original owner until reset requests cancellation."""

        async def get_current_key(self) -> OpenRouterKeyVerificationDAO:
            """Yield a cancellable blocked refresh owner."""
            self.key_calls += 1
            first_started.set()
            await asyncio.Event().wait()
            raise AssertionError("cancelled owner unexpectedly resumed")

    class ReplacementClient(FakeOpenRouterClient):
        """Keep the replacement flight observable after the retired callback runs."""

        async def get_current_key(self) -> OpenRouterKeyVerificationDAO:
            """Wait until the registry assertion completes."""
            self.key_calls += 1
            replacement_started.set()
            await release_replacement.wait()
            return await super().get_current_key()

    ModelCatalogService.reset()
    original = asyncio.create_task(
        ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            resolved_credential=resolved,
            client_factory=lambda credential: FirstClient(credential=credential),
            cache_path=cache_path,
        )
    )
    await first_started.wait()
    ModelCatalogService.reset()
    replacement = asyncio.create_task(
        ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            resolved_credential=resolved,
            client_factory=lambda credential: ReplacementClient(credential=credential),
            cache_path=cache_path,
        )
    )
    await replacement_started.wait()
    await asyncio.sleep(0)

    assert len(ModelCatalogService._refresh_tasks) == 1
    release_replacement.set()
    with pytest.raises(asyncio.CancelledError):
        await original
    replacement_result = await replacement
    assert replacement_result.status == "refreshed"


@pytest.mark.asyncio
async def test_shutdown_waits_for_cancelled_refresh_owner_before_releasing_refresh_lease(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shutdown retains the production lease until the cancelled owner has drained its persistence worker."""
    cache_path = tmp_path / "model_catalog_cache.v2.json"
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    write_started = asyncio.Event()
    import threading

    allow_write_completion = threading.Event()
    write_completed = threading.Event()
    lease_released = asyncio.Event()
    original_write = ModelCatalogStore.write_provider_cache
    original_lease = ModelCatalogStore.refresh_lease

    def blocking_write(*, cache: ModelCatalogCacheDAO, override_path: Path | None = None):
        """Block a worker-thread persistence operation after the owner has acquired the lease."""
        write_started.set()
        allow_write_completion.wait()
        outcome = original_write(cache=cache, override_path=override_path)
        write_completed.set()
        return outcome

    @asynccontextmanager
    async def observing_lease(*, cache_path: Path):
        """Record release only after the production lease context fully exits."""
        async with original_lease(cache_path=cache_path):
            try:
                yield
            finally:
                lease_released.set()

    monkeypatch.setattr(ModelCatalogStore, "write_provider_cache", blocking_write)
    monkeypatch.setattr(ModelCatalogStore, "refresh_lease", observing_lease)
    ModelCatalogService.reset()
    refresh = asyncio.create_task(
        ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            resolved_credential=resolved,
            client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
            cache_path=cache_path,
        )
    )
    await asyncio.wait_for(write_started.wait(), timeout=1.0)
    shutdown = asyncio.create_task(ModelCatalogService.shutdown())
    await asyncio.sleep(0)

    assert not shutdown.done()
    assert not write_completed.is_set()
    assert not lease_released.is_set()
    allow_write_completion.set()
    await shutdown
    with pytest.raises(asyncio.CancelledError):
        await refresh
    assert write_completed.is_set()
    assert lease_released.is_set()


@pytest.mark.asyncio
async def test_refresh_coalesces_cancelling_waiter_without_cancelling_shared_work(tmp_path) -> None:
    """Cancelling one caller must not cancel the shared provider publication."""
    import asyncio

    cache_path = tmp_path / "model_catalog_cache.v2.json"
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="key-a"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    client = FakeOpenRouterClient(credential=credential)
    ModelCatalogService.reset()
    first = asyncio.create_task(
        ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            resolved_credential=resolved,
            client_factory=lambda credential: client,
            cache_path=cache_path,
        )
    )
    second = asyncio.create_task(
        ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            resolved_credential=resolved,
            client_factory=lambda credential: client,
            cache_path=cache_path,
        )
    )
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second

    result = await first

    assert result.status == "refreshed"
    assert client.key_calls == 1
    assert client.model_calls == 1
