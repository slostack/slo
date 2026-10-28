"""Local transport proof that catalog browsing never authorizes rejected credentials."""

import asyncio
from collections.abc import Callable
from typing import ParamSpec, TypeVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.agents.model_catalog.dao import ModelCatalogCacheDAO, ProviderCatalogCacheDAO
from src.agents.model_catalog.openrouter import OpenRouterCatalogConverter
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
from src.integrations.openrouter.client import OpenRouterAPIClient
from src.integrations.openrouter.dao import (
    OpenRouterKeyVerificationDAO,
    OpenRouterModelsResponseDAO,
    credential_fingerprint,
)
from src.integrations.openrouter.exceptions import OpenRouterAPIError

P = ParamSpec("P")
R = TypeVar("R")


@pytest.mark.parametrize("status", [401, 403, None])
@pytest.mark.parametrize("operation", ["prepare", "selection", "prompt"])
async def test_prepare_when_key_rejected_preserves_raw_cache(
    tmp_path: Path, status: int | None, operation: str
) -> None:
    """Expired verification must reach the real GET boundary, not admit cached membership."""
    cache_path = tmp_path / "catalog.json"
    assert cache_path.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic-admission-key"
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE)
    now = datetime.now(tz=timezone.utc)
    entries = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(
            data=[
                {
                    "id": "vendor/admission",
                    "context_length": 1000,
                    "supported_parameters": ["tools"],
                    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                }
            ]
        ),
        now=now,
    ).entries
    cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint=credential_fingerprint(access_token=credential.access_token),
                key_verified_at=(now - timedelta(hours=2)).isoformat(),
                last_success_at=now.isoformat(),
                entries=entries,
            )
        ]
    )
    ModelCatalogStore.write_provider_cache(cache=cache, override_path=cache_path)
    before = cache_path.read_bytes()
    requests: list[str] = []

    def reject(request: httpx.Request) -> httpx.Response:
        """Reject only metadata requests without permitting any external transport."""
        requests.append(request.url.path)
        assert request.headers["Authorization"] == "Bearer synthetic-admission-key"
        return httpx.Response(
            status_code=status or 500, json={"error": {"message": "private-upstream-marker"}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as http:
        with (
            patch.object(
                CredentialResolver,
                "resolve_with_source",
                return_value=resolved if status is not None else None,
            ),
            patch.object(ModelCatalogStore, "load_provider_cache", return_value=cache),
            patch(
                "src.agents.model_catalog.service.OpenRouterAPIClient",
                side_effect=lambda *, credential: OpenRouterAPIClient(
                    credential=credential, http_client=http
                ),
            ),
            patch.object(ModelCatalogStore, "refresh_lease", wraps=ModelCatalogStore.refresh_lease) as lease,
        ):
            # Route lease writes into this test's proven private directory.
            original_lease = lease._mock_wraps
            lease.side_effect = lambda *, cache_path=None: original_lease(
                cache_path=tmp_path / "catalog.json"
            )
            ModelCatalogService.reset()
            snapshot = ModelCatalogService.load()
            assert "openrouter:vendor/admission" in snapshot.entries
            from src.agents.slo_agent.sessions.dao import SessionConfigDAO
            from src.agents.slo_agent.sessions.service import SloAgentSession

            route = "openrouter:vendor/admission"
            session = SloAgentSession.build(
                config=SessionConfigDAO(
                    workdir=tmp_path,
                    model_name=route if operation == "prompt" else "gpt-5.4",
                    enable_history=False,
                ),
                catalog_snapshot=snapshot,
            )
            before_state = (
                session._config,
                session.catalog_snapshot,
                session.active_model_name,
                session.active_reasoning_level,
                session.usage_snapshot,
                session._agent,
            )
            if operation == "selection":
                message = await session.prepare_model_selection(model_name=route)
                assert "/auth" in message
                assert "private-upstream-marker" not in message
            else:
                with pytest.raises(ModelPreparationRequiredError, match="/auth") as failure:
                    if operation == "prompt":
                        async for _ in session.invoke(text="must not run"):
                            pytest.fail("Rejected admission emitted inference output")
                    else:
                        await ModelCatalogService.prepare_models(model_names=(route,))
                assert "private-upstream-marker" not in str(failure.value)
            assert (
                session._config,
                session.catalog_snapshot,
                session.active_model_name,
                session.active_reasoning_level,
                session.usage_snapshot,
                session._agent,
            ) == before_state
            assert requests == ([] if status is None else ["/api/v1/key"])
            assert ModelCatalogService.load() is snapshot
            assert cache_path.read_bytes() == before
            await ModelCatalogService.shutdown()
            ModelCatalogService.reset()


@pytest.mark.parametrize("verification_old", [False, True])
async def test_prepare_models_when_same_key_listing_is_stale_and_refresh_fails_admits_cached_route(
    tmp_path: Path,
    verification_old: bool,
) -> None:
    """Keep a same-key verified stale route admissible after one transient listing failure."""
    cache_path: Path = tmp_path / "catalog.json"
    assert cache_path.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-stale-admission-key",
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE)
    now = datetime.now(tz=timezone.utc)
    route = "openrouter:vendor/stale-admission"
    entries = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(
            data=[
                {
                    "id": "vendor/stale-admission",
                    "context_length": 1000,
                    "supported_parameters": ["tools"],
                    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                }
            ]
        ),
        now=now,
    ).entries
    cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint=credential_fingerprint(access_token=credential.access_token),
                key_verified_at=(now - timedelta(hours=2) if verification_old else now).isoformat(),
                last_success_at=(now - timedelta(hours=2)).isoformat(),
                entries=entries,
            )
        ]
    )
    ModelCatalogStore.write_provider_cache(cache=cache, override_path=cache_path)

    class ListingFailureClient:
        """Verify the captured key then fail only the stale listing request."""

        async def get_current_key(self) -> OpenRouterKeyVerificationDAO:
            """Return fresh matching key evidence without external I/O."""
            return OpenRouterKeyVerificationDAO(
                credential_fingerprint=credential_fingerprint(access_token=credential.access_token),
                verified_at=now,
            )

        async def list_user_models(self) -> OpenRouterModelsResponseDAO:
            """Model the transient catalog-list failure after successful verification."""
            raise OpenRouterAPIError()

    with (
        patch.object(CredentialResolver, "resolve_with_source", return_value=resolved),
        patch.object(ModelCatalogStore, "load_provider_cache", return_value=cache),
        patch("src.agents.model_catalog.service.OpenRouterAPIClient", return_value=ListingFailureClient()),
        patch.object(ModelCatalogStore, "refresh_lease", wraps=ModelCatalogStore.refresh_lease) as lease,
    ):
        original_lease = lease._mock_wraps
        lease.side_effect = lambda *, cache_path=None: original_lease(cache_path=tmp_path / "catalog.json")
        ModelCatalogService.reset()
        snapshot = ModelCatalogService.load()
        prepared = await ModelCatalogService.prepare_models(model_names=(route,))

    assert prepared.entries[route] == snapshot.entries[route]
    status = ModelCatalogService.lifecycle_status()
    assert status.state == "failed"
    assert status.key_verified_at == now
    assert status.catalog_checked_at != now
    assert ModelCatalogStore.load_provider_cache(override_path=cache_path) == cache
    await ModelCatalogService.shutdown()
    ModelCatalogService.reset()


async def test_prepare_models_rechecks_unchanged_initial_cache_after_newer_removal_publication(
    tmp_path: Path,
) -> None:
    """Reject an unpinned route when an unchanged first read returns after removal."""
    cache_path = tmp_path / "catalog.json"
    assert cache_path.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-initial-read-removal-key",
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE)
    now = datetime.now(tz=timezone.utc)
    route = "openrouter:vendor/initial-read-removal"
    entries = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(
            data=[
                {
                    "id": "vendor/initial-read-removal",
                    "context_length": 8_000,
                    "supported_parameters": ["tools"],
                    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                }
            ]
        ),
        now=now,
    ).entries
    initial = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint=credential_fingerprint(access_token=credential.access_token),
                key_verified_at=now.isoformat(),
                last_success_at=now.isoformat(),
                entries=entries,
            )
        ]
    )
    removed = initial.model_copy(
        update={"provider_slices": [initial.provider_slices[0].model_copy(update={"entries": ()})]}
    )
    first_read_complete = asyncio.Event()
    release_first_read = asyncio.Event()
    reads = 0
    original_thread = asyncio.to_thread

    async def delayed_first_read(
        function: Callable[P, R], *args: P.args, **kwargs: P.kwargs
    ) -> R | ModelCatalogCacheDAO:
        """Delay only the already-completed initial durable cache read."""
        nonlocal reads
        if function != ModelCatalogStore.load_provider_cache:
            return await original_thread(function, *args, **kwargs)
        reads += 1
        result = initial if reads == 1 else removed
        if reads == 1:
            first_read_complete.set()
            await release_first_read.wait()
        return result

    with (
        patch.object(CredentialResolver, "resolve_with_source", return_value=resolved),
        patch("src.agents.model_catalog.service.asyncio.to_thread", side_effect=delayed_first_read),
    ):
        ModelCatalogService.reset()
        with patch.object(ModelCatalogStore, "load_provider_cache", return_value=initial):
            ModelCatalogService.load()
        task = asyncio.create_task(ModelCatalogService.prepare_models(model_names=(route,)))
        await first_read_complete.wait()
        ModelCatalogService._active_openrouter_fingerprint = credential_fingerprint(
            access_token=credential.access_token
        )
        ModelCatalogService._publish_candidate(
            candidate=await ModelCatalogService._build_publication_candidate(cache=removed),
            fingerprint=credential_fingerprint(access_token=credential.access_token),
        )
        release_first_read.set()
        with pytest.raises(ModelPreparationRequiredError, match="/model refresh"):
            await task

    assert route not in ModelCatalogService.load().entries
    await ModelCatalogService.shutdown()
    ModelCatalogService.reset()


async def test_prepare_models_rechecks_unchanged_initial_cache_after_credential_rotation(
    tmp_path: Path,
) -> None:
    """Reject an equal first read when its credential assumption changes before return."""
    cache_path = tmp_path / "catalog.json"
    assert cache_path.resolve().is_relative_to(tmp_path.resolve())
    credential_a = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-initial-read-a-key",
    )
    credential_b = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-initial-read-b-key",
    )
    resolved_a = ResolvedCredentialDAO(credential=credential_a, source=CredentialSource.STORE)
    resolved_b = ResolvedCredentialDAO(credential=credential_b, source=CredentialSource.STORE)
    now = datetime.now(tz=timezone.utc)
    route = "openrouter:vendor/initial-read-rotation"
    entries = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(
            data=[
                {
                    "id": "vendor/initial-read-rotation",
                    "context_length": 8_000,
                    "supported_parameters": ["tools"],
                    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                }
            ]
        ),
        now=now,
    ).entries
    cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint=credential_fingerprint(access_token=credential_a.access_token),
                key_verified_at=now.isoformat(),
                last_success_at=now.isoformat(),
                entries=entries,
            )
        ]
    )
    first_read_complete = asyncio.Event()
    release_first_read = asyncio.Event()
    reads = 0
    effective = resolved_a
    original_thread = asyncio.to_thread

    def resolve_effective(*, provider: ProviderName) -> ResolvedCredentialDAO:
        """Provide one mutable credential source without a live resolver."""
        assert provider is ProviderName.OPENROUTER
        return effective

    async def delayed_first_read(
        function: Callable[P, R], *args: P.args, **kwargs: P.kwargs
    ) -> R | ModelCatalogCacheDAO:
        """Delay only the completed first durable read until the effective key rotates."""
        nonlocal reads
        if function != ModelCatalogStore.load_provider_cache:
            return await original_thread(function, *args, **kwargs)
        reads += 1
        if reads == 1:
            first_read_complete.set()
            await release_first_read.wait()
        return cache

    with (
        patch.object(CredentialResolver, "resolve_with_source", side_effect=resolve_effective),
        patch("src.agents.model_catalog.service.asyncio.to_thread", side_effect=delayed_first_read),
    ):
        ModelCatalogService.reset()
        with patch.object(ModelCatalogStore, "load_provider_cache", return_value=cache):
            ModelCatalogService.load()
        task = asyncio.create_task(ModelCatalogService.prepare_models(model_names=(route,)))
        await first_read_complete.wait()
        effective = resolved_b
        release_first_read.set()
        with pytest.raises(ModelPreparationRequiredError, match="credential changed"):
            await task

    await ModelCatalogService.shutdown()
    ModelCatalogService.reset()


async def test_adopt_current_openrouter_slice_does_not_overwrite_newer_generation_after_candidate_await(
    tmp_path: Path,
) -> None:
    """An older admission candidate retries rather than overwriting a newer publication."""
    cache_path = tmp_path / "catalog.json"
    assert cache_path.resolve().is_relative_to(tmp_path.resolve())
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-adoption-generation-key",
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE)
    now = datetime.now(tz=timezone.utc)
    route = "openrouter:vendor/adoption-generation"

    def cache_for_cap(cap: int) -> ModelCatalogCacheDAO:
        """Build a complete durable slice with one distinguishable output ceiling."""
        entries = OpenRouterCatalogConverter.invoke(
            response=OpenRouterModelsResponseDAO(
                data=[
                    {
                        "id": "vendor/adoption-generation",
                        "context_length": 8_000,
                        "supported_parameters": ["tools"],
                        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                        "top_provider": {"max_completion_tokens": cap},
                    }
                ]
            ),
            now=now,
        ).entries
        return ModelCatalogCacheDAO(
            provider_slices=[
                ProviderCatalogCacheDAO(
                    provider=ProviderName.OPENROUTER,
                    credential_fingerprint=credential_fingerprint(access_token=credential.access_token),
                    key_verified_at=now.isoformat(),
                    last_success_at=now.isoformat(),
                    entries=entries,
                )
            ]
        )

    initial = cache_for_cap(cap=3_000)
    older = cache_for_cap(cap=1_024)
    newer = cache_for_cap(cap=512)
    candidate_started = asyncio.Event()
    allow_candidate = asyncio.Event()
    original_build = ModelCatalogService._build_publication_candidate

    async def blocked_build(*, cache: ModelCatalogCacheDAO) -> object:
        """Pause the old candidate so a newer publication wins before it returns."""
        candidate_started.set()
        await allow_candidate.wait()
        return await original_build(cache=cache)

    with (
        patch.object(CredentialResolver, "resolve_with_source", return_value=resolved),
        patch.object(ModelCatalogService, "_build_publication_candidate", side_effect=blocked_build),
    ):
        ModelCatalogService.reset()
        ModelCatalogService._active_openrouter_fingerprint = credential_fingerprint(
            access_token=credential.access_token
        )
        with patch.object(ModelCatalogStore, "load_provider_cache", return_value=initial):
            warm_snapshot = ModelCatalogService.load()
        task = asyncio.create_task(
            ModelCatalogService._adopt_current_openrouter_slice(
                snapshot=warm_snapshot,
                cache=older,
                fingerprint=credential_fingerprint(access_token=credential.access_token),
            )
        )
        await candidate_started.wait()
        ModelCatalogService._publish_candidate(
            candidate=await original_build(cache=newer),
            fingerprint=credential_fingerprint(access_token=credential.access_token),
        )
        winning_generation = ModelCatalogService.load().generation
        with patch.object(ModelCatalogStore, "load_provider_cache", return_value=newer):
            allow_candidate.set()
            adopted = await task

    assert adopted.entries[route].runtime_profile.max_tokens == 512
    assert ModelCatalogService.load().generation == winning_generation
    await ModelCatalogService.shutdown()
    ModelCatalogService.reset()


async def test_adopt_current_openrouter_slice_rejects_rotation_after_candidate_await(tmp_path: Path) -> None:
    """Credential rotation after candidate construction rejects adoption without publication."""
    cache_path = tmp_path / "catalog.json"
    assert cache_path.resolve().is_relative_to(tmp_path.resolve())
    credential_a = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-adoption-a-key",
    )
    credential_b = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-adoption-b-key",
    )
    resolved_a = ResolvedCredentialDAO(credential=credential_a, source=CredentialSource.STORE)
    resolved_b = ResolvedCredentialDAO(credential=credential_b, source=CredentialSource.STORE)
    now = datetime.now(tz=timezone.utc)
    route = "openrouter:vendor/adoption-rotation"
    entries = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(
            data=[
                {
                    "id": "vendor/adoption-rotation",
                    "context_length": 8_000,
                    "supported_parameters": ["tools"],
                    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                }
            ]
        ),
        now=now,
    ).entries
    cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint=credential_fingerprint(access_token=credential_a.access_token),
                key_verified_at=now.isoformat(),
                last_success_at=now.isoformat(),
                entries=entries,
            )
        ]
    )
    candidate_started = asyncio.Event()
    allow_candidate = asyncio.Event()
    original_build = ModelCatalogService._build_publication_candidate

    async def blocked_build(*, cache: ModelCatalogCacheDAO) -> object:
        """Pause candidate completion until the resolver changes effective identity."""
        candidate_started.set()
        await allow_candidate.wait()
        return await original_build(cache=cache)

    effective_credential = resolved_a

    def resolve_effective_credential(*, provider: ProviderName) -> ResolvedCredentialDAO:
        """Return the mutable synthetic effective credential for the adoption race."""
        assert provider is ProviderName.OPENROUTER
        return effective_credential

    with (
        patch.object(CredentialResolver, "resolve_with_source", side_effect=resolve_effective_credential),
        patch.object(ModelCatalogService, "_build_publication_candidate", side_effect=blocked_build),
    ):
        ModelCatalogService.reset()
        ModelCatalogService._active_openrouter_fingerprint = credential_fingerprint(
            access_token=credential_a.access_token
        )
        snapshot = ModelCatalogService.load()
        generation_before = snapshot.generation
        task = asyncio.create_task(
            ModelCatalogService._adopt_current_openrouter_slice(
                snapshot=snapshot,
                cache=cache,
                fingerprint=credential_fingerprint(access_token=credential_a.access_token),
            )
        )
        await candidate_started.wait()
        effective_credential = resolved_b
        allow_candidate.set()
        with pytest.raises(ModelPreparationRequiredError, match="credential changed"):
            await task

    assert ModelCatalogService.load().generation == generation_before
    assert route not in ModelCatalogService.load().entries
    await ModelCatalogService.shutdown()
    ModelCatalogService.reset()


async def test_prepare_models_adopts_fresh_same_key_disk_removal_before_admission(tmp_path: Path) -> None:
    """A warm process rejects a route removed by another same-key publication."""
    cache_path = tmp_path / "catalog.json"
    root = tmp_path.resolve()
    assert cache_path.resolve().is_relative_to(root)
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-external-removal-key",
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE)
    now = datetime.now(tz=timezone.utc)
    route = "openrouter:vendor/external-removal"
    entries = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(
            data=[
                {
                    "id": "vendor/external-removal",
                    "context_length": 8_000,
                    "supported_parameters": ["tools"],
                    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                }
            ]
        ),
        now=now,
    ).entries
    initial = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint=credential_fingerprint(access_token=credential.access_token),
                key_verified_at=now.isoformat(),
                last_success_at=now.isoformat(),
                entries=entries,
            )
        ]
    )
    removed = initial.model_copy(
        update={"provider_slices": [initial.provider_slices[0].model_copy(update={"entries": ()})]}
    )

    with (
        patch.object(CredentialResolver, "resolve_with_source", return_value=resolved),
        patch.object(ModelCatalogStore, "load_provider_cache", return_value=removed) as load_cache,
    ):
        ModelCatalogService.reset()
        with patch.object(ModelCatalogStore, "load_provider_cache", return_value=initial):
            warm_snapshot = ModelCatalogService.load()
        assert route in warm_snapshot.entries
        with pytest.raises(ModelPreparationRequiredError, match="/model refresh"):
            await ModelCatalogService.prepare_models(model_names=(route,))

    assert load_cache.call_count >= 2
    assert route not in ModelCatalogService.load().entries
    await ModelCatalogService.shutdown()
    ModelCatalogService.reset()


async def test_prepare_models_adopts_fresh_same_key_disk_cap_before_admission(tmp_path: Path) -> None:
    """A warm process adopts a lower externally published same-key output cap."""
    cache_path = tmp_path / "catalog.json"
    root = tmp_path.resolve()
    assert cache_path.resolve().is_relative_to(root)
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-external-cap-key",
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE)
    now = datetime.now(tz=timezone.utc)
    route = "openrouter:vendor/external-cap"

    def cache_for_cap(cap: int) -> ModelCatalogCacheDAO:
        """Build one complete same-key durable publication with the requested cap."""
        entries = OpenRouterCatalogConverter.invoke(
            response=OpenRouterModelsResponseDAO(
                data=[
                    {
                        "id": "vendor/external-cap",
                        "context_length": 8_000,
                        "supported_parameters": ["tools"],
                        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                        "top_provider": {"max_completion_tokens": cap},
                    }
                ]
            ),
            now=now,
        ).entries
        return ModelCatalogCacheDAO(
            provider_slices=[
                ProviderCatalogCacheDAO(
                    provider=ProviderName.OPENROUTER,
                    credential_fingerprint=credential_fingerprint(access_token=credential.access_token),
                    key_verified_at=now.isoformat(),
                    last_success_at=now.isoformat(),
                    entries=entries,
                )
            ]
        )

    initial = cache_for_cap(cap=3_000)
    changed = cache_for_cap(cap=512)
    with patch.object(CredentialResolver, "resolve_with_source", return_value=resolved):
        ModelCatalogService.reset()
        with patch.object(ModelCatalogStore, "load_provider_cache", return_value=initial):
            warm_snapshot = ModelCatalogService.load()
        assert warm_snapshot.entries[route].runtime_profile.max_tokens == 3_000
        with patch.object(ModelCatalogStore, "load_provider_cache", return_value=changed) as load_cache:
            prepared = await ModelCatalogService.prepare_models(model_names=(route,))

    assert load_cache.call_count >= 1
    assert prepared.entries[route].runtime_profile.max_tokens == 512
    assert ModelCatalogService.load().entries[route].runtime_profile.max_tokens == 512
    await ModelCatalogService.shutdown()
    ModelCatalogService.reset()
