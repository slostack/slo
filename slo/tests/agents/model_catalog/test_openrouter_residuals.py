"""Offline protocol regression proofs for the third lifecycle iteration."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from src.agents.model_catalog.openrouter import OpenRouterCatalogConverter
from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_dao import (
    AuthType,
    CredentialDAO,
    CredentialSource,
    ProviderName,
    ResolvedCredentialDAO,
)
from src.integrations.openrouter.client import OpenRouterAPIClient
from src.integrations.openrouter.dao import (
    OpenRouterKeyVerificationDAO,
    OpenRouterModelsResponseDAO,
    credential_fingerprint,
)
from tests.agents.model_catalog.test_openrouter_lifecycle import FakeOpenRouterClient


@pytest.mark.parametrize("status", [401, 403], ids=["unauthorized", "forbidden"])
async def test_real_key_rejection_preserves_cache_and_redacts_body(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    """The real GET boundary rejects both auth statuses without exposing wire sentinels."""
    path = tmp_path / "cache.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture-secret"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE)
    ModelCatalogService.reset()
    await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
        cache_path=path,
    )
    before = path.read_bytes()
    snapshot = ModelCatalogService.load()
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Return a secret-bearing error only from the injected local transport."""
        requests.append(request.url.path)
        return httpx.Response(status_code=status, json={"error": "fixture-body-secret"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler=respond)) as http:
        result = await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            resolved_credential=resolved,
            key_verification=OpenRouterKeyVerificationDAO(
                credential_fingerprint=credential_fingerprint(access_token=credential.access_token),
                verified_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
            ),
            client_factory=lambda credential: OpenRouterAPIClient(credential=credential, http_client=http),
            cache_path=path,
        )
    assert result.status == "failed"
    assert requests == ["/api/v1/key"]
    assert path.read_bytes() == before
    assert ModelCatalogService.load() is snapshot
    assert "fixture-secret" not in repr(result) + caplog.text
    assert "fixture-body-secret" not in repr(result) + caplog.text


def test_identical_duplicate_rows_dedupe_in_first_seen_order() -> None:
    """Equal complete rows represent one exact route, not an incomplete listing."""
    first: dict[str, object] = {"id": "vendor/first", "context_length": 1000}
    second: dict[str, object] = {"id": "vendor/second", "context_length": 1000}
    result = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(data=[first, second, dict(first)]),
        now=datetime.now(tz=timezone.utc),
    )
    assert result.complete
    assert result.available_model_names == ["openrouter:vendor/first", "openrouter:vendor/second"]


async def test_refresh_reuses_persisted_fresh_key_verification_after_reset(
    tmp_path: Path,
) -> None:
    """A fresh matching schema-two key timestamp skips `/key` after process reload.

    The listing timestamp is made stale so this proves verification reuse rather
    than the independent fresh-listing early return.
    """
    from src.agents.model_catalog.dao import ModelCatalogCacheDAO
    from src.agents.model_catalog.store import ModelCatalogStore

    path: Path = tmp_path / "cache.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture-secret"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE)
    ModelCatalogService.reset()
    await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
        cache_path=path,
    )
    persisted = ModelCatalogStore.load_provider_cache(override_path=path)
    assert persisted is not None
    stale_slice = persisted.provider_slices[0].model_copy(
        update={"last_success_at": (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()}
    )
    ModelCatalogStore.write_provider_cache(
        cache=ModelCatalogCacheDAO(provider_slices=[stale_slice]), override_path=path
    )
    ModelCatalogService.reset()
    client = FakeOpenRouterClient(credential=credential)

    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        resolved_credential=resolved,
        client_factory=lambda credential: client,
        cache_path=path,
    )

    assert result.status == "refreshed"
    assert client.key_calls == 0
    assert client.model_calls == 1


async def test_refresh_offloads_cache_conversion_and_save_from_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real lifecycle leaves blocking JSON/conversion/fsync leaves to worker threads."""
    import threading
    from src.agents.model_catalog.store import ModelCatalogStore

    path = tmp_path / "cache.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    loop_thread = threading.get_ident()
    observed: list[str] = []

    def guard(owner: type, name: str) -> None:
        """Wrap a leaf without replacing its actual disk/conversion behavior."""
        original = getattr(owner, name)

        def checked(**kwargs: object) -> object:
            """Require the wrapped leaf to execute away from the event loop."""
            assert threading.get_ident() != loop_thread, name
            observed.append(name)
            return original(**kwargs)

        monkeypatch.setattr(owner, name, checked)

    guard(owner=ModelCatalogStore, name="load_provider_cache")
    guard(owner=ModelCatalogStore, name="write_provider_cache")
    guard(owner=OpenRouterCatalogConverter, name="invoke")
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture-secret"
    )
    ModelCatalogService.reset()
    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE),
        client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
        cache_path=path,
    )
    assert result.status == "refreshed"
    assert set(observed) == {"load_provider_cache", "write_provider_cache", "invoke"}


async def test_total_budget_covers_key_and_listing_and_releases_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Injected timeout expiration at listing cancels the whole leased operation."""
    import asyncio
    from contextlib import asynccontextmanager
    from src.agents.model_catalog.store import ModelCatalogStore

    path = tmp_path / "cache.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    original_timeout = asyncio.timeout
    budgets: list[float] = []
    deadlines: list[asyncio.Timeout] = []

    @asynccontextmanager
    async def controlled_timeout(delay: float):
        """Record the production budget without waiting thirty real seconds."""
        budgets.append(delay)
        async with original_timeout(None) as deadline:
            deadlines.append(deadline)
            yield

    class ExpiringClient(FakeOpenRouterClient):
        async def list_user_models(self) -> OpenRouterModelsResponseDAO:
            """Expire only after verification, while the production lease is held."""
            assert deadlines, "No total operation timeout surrounds the HTTP pair"
            deadlines[0].reschedule(asyncio.get_running_loop().time())
            await asyncio.Event().wait()
            raise AssertionError("deadline did not cancel listing")

    monkeypatch.setattr(asyncio, "timeout", controlled_timeout)
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture-secret"
    )
    ModelCatalogService.reset()
    result = await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE),
        client_factory=lambda credential: ExpiringClient(credential=credential),
        cache_path=path,
    )
    assert budgets == [30.0]
    assert result.status == "failed"
    assert result.safe_message == "OpenRouter catalog refresh is unavailable."
    assert not path.exists()
    async with ModelCatalogStore.refresh_lease(cache_path=path):
        pass


async def test_force_reuses_newer_same_key_cache_completed_while_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A forced contender rereads the winner instead of issuing duplicate HTTP."""
    import asyncio
    from contextlib import asynccontextmanager
    from datetime import timedelta
    from src.agents.model_catalog.dao import ModelCatalogCacheDAO
    from src.agents.model_catalog.store import ModelCatalogStore

    path = tmp_path / "cache.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture-secret"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE)
    ModelCatalogService.reset()
    await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
        cache_path=path,
    )
    cache = ModelCatalogStore.load_provider_cache(override_path=path)
    assert cache is not None
    old = cache.provider_slices[0].model_copy(
        update={"last_success_at": (datetime.now(tz=timezone.utc) - timedelta(minutes=5)).isoformat()}
    )
    ModelCatalogStore.write_provider_cache(
        cache=ModelCatalogCacheDAO(provider_slices=[old]), override_path=path
    )
    waiting = asyncio.Event()
    release = asyncio.Event()
    original_lease = ModelCatalogStore.refresh_lease

    @asynccontextmanager
    async def paused_lease(*, cache_path: Path):
        """Pause before acquiring the real lease to simulate a winning process."""
        waiting.set()
        await release.wait()
        async with original_lease(cache_path=cache_path):
            yield

    monkeypatch.setattr(ModelCatalogStore, "refresh_lease", paused_lease)
    from src.agents.model_catalog.seed import SeedModelCatalog

    ModelCatalogService._snapshot = SeedModelCatalog.load()
    client = FakeOpenRouterClient(credential=credential)
    contender = asyncio.create_task(
        ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            resolved_credential=resolved,
            client_factory=lambda credential: client,
            cache_path=path,
        )
    )
    await waiting.wait()
    ModelCatalogStore.write_provider_cache(cache=cache, override_path=path)
    release.set()
    result = await contender
    assert result.status == "fresh"
    assert client.key_calls == client.model_calls == 0
    winner_entry = cache.provider_slices[0].entries[0]
    assert ModelCatalogService.entry_for_model(model_name=winner_entry.model_name) == winner_entry
    assert result.catalog_generation == ModelCatalogService.load().generation


@pytest.mark.parametrize(
    "payload",
    [
        {
            "data": [
                {"id": "vendor/conflict", "context_length": 1000},
                {"id": "vendor/conflict", "context_length": 2000},
            ]
        },
        {"data": [{"id": ""}]},
        {"data": [{"id": 42}]},
        {"data": [{"id": "vendor/with space"}]},
        {"data": "fixture-body-secret"},
        {"data": [None]},
        {"data": [], "total_count": True},
        {"data": [], "total_count": 1, "next": "https://invalid.example/fixture-body-secret"},
    ],
    ids=[
        "conflicting-duplicate",
        "empty-id",
        "integer-id",
        "whitespace-id",
        "non-list-data",
        "non-record-row",
        "boolean-total",
        "unterminated-page",
    ],
)
async def test_raw_listing_protocol_failure_retains_complete_cache(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    """Actual wire-client/converter failures cannot replace a last-good complete list."""
    path = tmp_path / "cache.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture-secret"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE)
    ModelCatalogService.reset()
    await ModelCatalogService.refresh(
        provider=ProviderName.OPENROUTER,
        force=True,
        resolved_credential=resolved,
        client_factory=lambda credential: FakeOpenRouterClient(credential=credential),
        cache_path=path,
    )
    before = path.read_bytes()
    snapshot = ModelCatalogService.load()

    def respond(request: httpx.Request) -> httpx.Response:
        """Return malformed listing data after a successful local key check."""
        return httpx.Response(
            status_code=200, json={"data": {}} if request.url.path.endswith("/key") else payload
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler=respond)) as http:
        result = await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            resolved_credential=resolved,
            client_factory=lambda credential: OpenRouterAPIClient(credential=credential, http_client=http),
            cache_path=path,
        )
    assert result.status == "failed"
    assert path.read_bytes() == before
    assert ModelCatalogService.load() is snapshot
    assert "fixture-body-secret" not in repr(result)
