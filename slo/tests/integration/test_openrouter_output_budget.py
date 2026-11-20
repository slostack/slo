"""Bug 112 journeys: reported OpenRouter output ceilings raise the default request budget.

Real refresh, converter, catalog store/service, session admission and LLMFactory run
end to end; only OpenRouter HTTP transport is mocked (third-party boundary). Every
persistent target stays inside the pytest-owned temporary root via the shared
``isolated_catalog`` fixture.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import httpx
import pytest
from langchain_core.messages import HumanMessage

from src.agents.base import LLMFactory
from src.agents.model_catalog.dao import (
    ModelCapabilitiesDAO,
    ModelCatalogCacheDAO,
    ModelCatalogEntryDAO,
    ModelRuntimeProfileDAO,
    ProviderCatalogCacheDAO,
)
from src.agents.model_catalog.openrouter import (
    OPENROUTER_UNREPORTED_OUTPUT_BUDGET_TOKENS,
    OpenRouterCatalogConverter,
)
from src.agents.model_catalog.service import (
    ModelCatalogService,
    OpenRouterCatalogClientProtocol,
)
from src.agents.model_catalog.store import ModelCatalogStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore
from src.integrations.openrouter.dao import OpenRouterModelsResponseDAO, credential_fingerprint
from tests.integration.test_openrouter_full_flow import isolated_catalog

__all__ = ["isolated_catalog"]

SYNTHETIC_OPENROUTER_KEY: str = "bug112-synthetic-key"
GLM_ROUTE: str = "openrouter:z-ai/glm-5.3-flash"
GLM_RECORD: dict[str, object] = {
    "id": "z-ai/glm-5.3-flash",
    "name": "Z.AI: GLM 5.3 Flash",
    "context_length": 1_048_576,
    "top_provider": {"context_length": 1_048_576, "max_completion_tokens": 131_072},
    "supported_parameters": ["tools", "reasoning"],
    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
    "reasoning": {
        "supported_efforts": ["low", "high", "max"],
        "default_effort": "max",
        "mandatory": True,
    },
}
LARGE_CEILING_ROUTE: str = "openrouter:vendor/huge-output"
LARGE_CEILING_RECORD: dict[str, object] = {
    "id": "vendor/huge-output",
    "name": "Huge Output",
    "context_length": 10_000_000,
    "top_provider": {"context_length": 10_000_000, "max_completion_tokens": 1_000_001},
    "supported_parameters": ["tools"],
    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
}
UNREPORTED_ROUTE: str = "openrouter:vendor/unreported-coder"
UNREPORTED_RECORD: dict[str, object] = {
    "id": "vendor/unreported-coder",
    "name": "Unreported Coder",
    "context_length": 64000,
    "top_provider": {"context_length": 64000, "max_completion_tokens": None},
    "supported_parameters": ["tools"],
    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
}


def _sse_response(*, model_id: str) -> httpx.Response:
    """Answer one chat completion with a single synthetic SSE frame."""
    chunk = {
        "id": "bug112",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": model_id,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
    }
    return httpx.Response(
        status_code=200,
        headers={"content-type": "text/event-stream"},
        content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
    )


def _catalog_client_factory(
    *, http_client: httpx.AsyncClient
) -> Callable[[CredentialDAO], OpenRouterCatalogClientProtocol]:
    """Keep the real metadata client while replacing only its network transport."""
    from src.integrations.openrouter.client import OpenRouterAPIClient

    def client_factory(credential: CredentialDAO) -> OpenRouterCatalogClientProtocol:
        """Inject the mocked transport into the real OpenRouter metadata client."""
        return OpenRouterAPIClient(credential=credential, http_client=http_client)

    return client_factory


def _persist_openrouter_cache(
    *,
    store: CredentialStore,
    entries: list[ModelCatalogEntryDAO],
) -> Path:
    """Persist prepared entries under the synthetic credential fingerprint."""
    now = datetime.now(tz=timezone.utc)
    cache_path: Path = store.path.parent / "global/model_catalog_cache.v2.json"
    assert cache_path.parent.resolve().is_relative_to(store.path.parent.resolve())
    ModelCatalogStore.write_provider_cache(
        cache=ModelCatalogCacheDAO(
            provider_slices=[
                ProviderCatalogCacheDAO(
                    provider=ProviderName.OPENROUTER,
                    credential_fingerprint=credential_fingerprint(access_token=SYNTHETIC_OPENROUTER_KEY),
                    key_verified_at=now.isoformat(),
                    last_success_at=now.isoformat(),
                    entries=list(entries),
                )
            ]
        ),
        override_path=cache_path,
    )
    return cache_path


def _stale_converted_glm_entry() -> ModelCatalogEntryDAO:
    """Convert GLM exactly as pre-fix code persisted it: budget clamped to 4,096."""
    entry = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(data=[GLM_RECORD]),
        now=datetime.now(tz=timezone.utc),
    ).entries[0]
    return entry.model_copy(
        update={"runtime_profile": entry.runtime_profile.model_copy(update={"max_tokens": 4096})}
    )


STALE_UNREPORTED_RECORD: dict[str, object] = {
    "id": "vendor/stale-unreported",
    "name": "Stale Unreported",
    "context_length": 64000,
    "top_provider": {"context_length": 64000, "max_completion_tokens": None},
    "supported_parameters": ["tools"],
    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
}
STALE_UNREPORTED_ROUTE: str = "openrouter:vendor/stale-unreported"


def _stale_converted_unreported_entry() -> ModelCatalogEntryDAO:
    """Convert the unreported route exactly as pre-fix code persisted it: budget 4,096."""
    entry = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(data=[STALE_UNREPORTED_RECORD]),
        now=datetime.now(tz=timezone.utc),
    ).entries[0]
    return entry.model_copy(
        update={"runtime_profile": entry.runtime_profile.model_copy(update={"max_tokens": 4096})}
    )


def _seed_derived_glm_entry() -> ModelCatalogEntryDAO:
    """Rebuild a stale GLM cache row from seed fields like the offline read fixtures."""
    from src.agents.model_catalog.seed import SeedModelCatalog

    seed_entry: ModelCatalogEntryDAO = SeedModelCatalog.load().entries["gpt-5.4"]
    return seed_entry.model_copy(
        update={
            "model_name": GLM_ROUTE,
            "api_model_name": "z-ai/glm-5.3-flash",
            "provider": ProviderName.OPENROUTER,
            "runtime_profile": seed_entry.runtime_profile.model_copy(
                update={"max_tokens": 4096, "context_window": 1_048_576}
            ),
            "capabilities": ModelCapabilitiesDAO(
                input_modalities=("text",),
                output_modalities=("text",),
                supported_parameters=("tools",),
                reported_output_ceiling=131_072,
            ),
        }
    )


async def _capture_glm_request(
    *,
    isolated_catalog: CredentialStore,
) -> tuple[list[dict[str, object]], int]:
    """Run admission, session selection, factory and one captured streaming request."""
    completions: list[dict[str, object]] = []

    def capture(request: httpx.Request) -> httpx.Response:
        """Capture the exact SDK request body at the third-party HTTP boundary."""
        assert request.url == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {SYNTHETIC_OPENROUTER_KEY}"
        completions.append(json.loads(request.content))
        return _sse_response(model_id="z-ai/glm-5.3-flash")

    snapshot = await ModelCatalogService.prepare_models(model_names=(GLM_ROUTE,))
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=isolated_catalog.path.parent,
            model_name="gpt-5.4",
            enable_history=False,
        )
    )
    notice: str = await session.prepare_model_selection(model_name=GLM_ROUTE)
    assert session.active_model_name == GLM_ROUTE, notice

    async with httpx.AsyncClient(transport=httpx.MockTransport(capture)) as http_client:
        model = LLMFactory.create(
            model_name=session.active_model_name,
            snapshot=snapshot,
            http_async_client=http_client,
        ).llm
        chunks = [chunk async for chunk in model.astream(input=[HumanMessage(content="Say hello")])]
    assert "".join(str(chunk.content) for chunk in chunks) == "ok"
    assert len(completions) == 1
    return completions, snapshot.entries[GLM_ROUTE].runtime_profile.max_tokens


@pytest.mark.asyncio
async def test_fresh_glm_record_defaults_request_budget_to_agent_cap(
    isolated_catalog: CredentialStore,
) -> None:
    """A fresh /models/user GLM record requests the 64,000 default budget end to end."""
    catalog_requests: list[httpx.Request] = []

    def catalog_handler(request: httpx.Request) -> httpx.Response:
        """Serve key verification and the GLM model record without external I/O."""
        catalog_requests.append(request)
        if request.url.path == "/api/v1/key":
            return httpx.Response(status_code=200, json={"data": {}})
        assert request.url.path == "/api/v1/models/user"
        assert request.headers["authorization"] == f"Bearer {SYNTHETIC_OPENROUTER_KEY}"
        return httpx.Response(status_code=200, json={"data": [GLM_RECORD]})

    isolated_catalog.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=SYNTHETIC_OPENROUTER_KEY,
        )
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(catalog_handler)) as http_client:
        result = await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            client_factory=_catalog_client_factory(http_client=http_client),
        )
    assert result.status == "refreshed"
    assert [request.url.path for request in catalog_requests] == [
        "/api/v1/key",
        "/api/v1/models/user",
    ]

    completions, catalog_max_tokens = await _capture_glm_request(isolated_catalog=isolated_catalog)

    assert catalog_max_tokens == 64000
    wire_budget = completions[0].get("max_tokens", completions[0].get("max_completion_tokens"))
    assert wire_budget == 64000

    # Pin the fresh persisted budget so Change 1 cannot hide behind the
    # read-merge recomputation of Change 2.
    cache = ModelCatalogStore.load_provider_cache(
        override_path=isolated_catalog.path.parent / "global/model_catalog_cache.v2.json"
    )
    assert cache is not None
    persisted = cache.provider_slices[0].entries[0]
    assert persisted.runtime_profile.max_tokens == 64000
    assert persisted.capabilities is not None
    assert persisted.capabilities.reported_output_ceiling == 131_072


@pytest.mark.asyncio
async def test_reported_ceiling_above_one_million_defaults_to_agent_cap(
    isolated_catalog: CredentialStore,
) -> None:
    """A fresh record reporting 1,000,001 requests the 64,000 default budget."""
    completions: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Serve the model record and capture the chat completion body."""
        if request.url.path == "/api/v1/key":
            return httpx.Response(status_code=200, json={"data": {}})
        if request.url.path == "/api/v1/models/user":
            return httpx.Response(status_code=200, json={"data": [LARGE_CEILING_RECORD]})
        assert request.url.path == "/api/v1/chat/completions"
        completions.append(json.loads(request.content))
        return _sse_response(model_id="vendor/huge-output")

    isolated_catalog.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=SYNTHETIC_OPENROUTER_KEY,
        )
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            force=True,
            client_factory=_catalog_client_factory(http_client=http_client),
        )
        assert result.status == "refreshed"
        snapshot = await ModelCatalogService.prepare_models(model_names=(LARGE_CEILING_ROUTE,))
        model = LLMFactory.create(
            model_name=LARGE_CEILING_ROUTE,
            snapshot=snapshot,
            http_async_client=http_client,
        ).llm
        chunks = [chunk async for chunk in model.astream(input=[HumanMessage(content="hi")])]
    assert "".join(str(chunk.content) for chunk in chunks) == "ok"
    assert snapshot.entries[LARGE_CEILING_ROUTE].runtime_profile.max_tokens == 64000
    assert len(completions) == 1
    wire_budget = completions[0].get("max_tokens", completions[0].get("max_completion_tokens"))
    assert wire_budget == 64000


@pytest.mark.asyncio
async def test_stale_cached_glm_record_defaults_to_agent_cap_without_refresh(
    isolated_catalog: CredentialStore,
) -> None:
    """An old cache entry with budget 4,096 requests 64,000 with no refresh."""
    isolated_catalog.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=SYNTHETIC_OPENROUTER_KEY,
        )
    )
    cache_path = _persist_openrouter_cache(store=isolated_catalog, entries=[_stale_converted_glm_entry()])
    before: bytes = cache_path.read_bytes()
    with patch(
        "src.agents.model_catalog.service.OpenRouterAPIClient",
        side_effect=AssertionError("HTTP forbidden: cached evidence must be reused"),
    ):
        completions, catalog_max_tokens = await _capture_glm_request(isolated_catalog=isolated_catalog)

    assert catalog_max_tokens == 64000
    assert completions[0]["model"] == "z-ai/glm-5.3-flash"
    wire_budget = completions[0].get("max_tokens", completions[0].get("max_completion_tokens"))
    assert wire_budget == 64000
    assert cache_path.read_bytes() == before


@pytest.mark.asyncio
async def test_unreported_ceiling_uses_openrouter_unreported_fallback(
    isolated_catalog: CredentialStore,
) -> None:
    """A route with no reported ceiling requests the 8,192 fallback with an 8,192 ceiling."""
    isolated_catalog.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=SYNTHETIC_OPENROUTER_KEY,
        )
    )
    converted = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(data=[UNREPORTED_RECORD]),
        now=datetime.now(tz=timezone.utc),
    ).entries
    cache_path = _persist_openrouter_cache(store=isolated_catalog, entries=list(converted))
    before: bytes = cache_path.read_bytes()
    captured: list[dict[str, object]] = []

    def capture(request: httpx.Request) -> httpx.Response:
        """Capture the exact SDK request body for the unreported route."""
        assert request.headers["authorization"] == f"Bearer {SYNTHETIC_OPENROUTER_KEY}"
        captured.append(json.loads(request.content))
        return _sse_response(model_id="vendor/unreported-coder")

    with patch(
        "src.agents.model_catalog.service.OpenRouterAPIClient",
        side_effect=AssertionError("HTTP forbidden: cached evidence must be reused"),
    ):
        snapshot = await ModelCatalogService.prepare_models(model_names=(UNREPORTED_ROUTE,))
        async with httpx.AsyncClient(transport=httpx.MockTransport(capture)) as http_client:
            model = LLMFactory.create(
                model_name=UNREPORTED_ROUTE,
                snapshot=snapshot,
                http_async_client=http_client,
            ).llm
            chunks = [chunk async for chunk in model.astream(input=[HumanMessage(content="hi")])]
        assert "".join(str(chunk.content) for chunk in chunks) == "ok"

    entry = snapshot.entries[UNREPORTED_ROUTE]
    assert entry.runtime_profile.max_tokens == 8192
    assert len(captured) == 1
    wire_budget = captured[0].get("max_tokens", captured[0].get("max_completion_tokens"))
    assert wire_budget == 8192
    assert cache_path.read_bytes() == before

    # Enforcement pin: the adapter exposes an 8,192 ceiling for this entry, and
    # the adapter-level invocation guard rejects a request above it before HTTP.
    from src.integrations.openrouter.exceptions import OpenRouterAPIError

    assert model.slo_output_ceiling == 8192  # type: ignore[attr-defined]
    with pytest.raises(OpenRouterAPIError):
        await model.ainvoke(input=[HumanMessage(content="hi")], max_tokens=8193)
    assert len(captured) == 1  # the rejected cap never reached the wire


def test_openrouter_unreported_fallback_constant_is_public_and_fixed() -> None:
    """The OpenRouter unreported fallback is a fixed public constant (8192)."""
    assert OPENROUTER_UNREPORTED_OUTPUT_BUDGET_TOKENS == 8_192


@pytest.mark.asyncio
async def test_operator_override_applies_after_recomputed_budget(
    isolated_catalog: CredentialStore,
) -> None:
    """A persisted operator override still lowers the re-derived 64,000 budget."""
    isolated_catalog.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=SYNTHETIC_OPENROUTER_KEY,
        )
    )
    cache_path = _persist_openrouter_cache(store=isolated_catalog, entries=[_stale_converted_glm_entry()])
    overrides_path: Path = isolated_catalog.path.parent / "global/model_catalog_overrides.json"
    overrides_path.write_text(
        data=json.dumps(
            [
                {
                    "model_name": GLM_ROUTE,
                    "runtime_profile": ModelRuntimeProfileDAO(
                        max_tokens=8192,
                        context_window=1_048_576,
                        streaming=True,
                        requests_per_minute=20,
                        tokens_per_minute=None,
                        automatic_retry_attempts=2,
                        local_retry_wait_cap_seconds=60,
                    ).model_dump(),
                }
            ]
        ),
        encoding="utf-8",
    )
    before: bytes = cache_path.read_bytes()
    with patch(
        "src.agents.model_catalog.service.OpenRouterAPIClient",
        side_effect=AssertionError("HTTP forbidden: cached evidence must be reused"),
    ):
        completions, catalog_max_tokens = await _capture_glm_request(isolated_catalog=isolated_catalog)

    assert catalog_max_tokens == 8192
    wire_budget = completions[0].get("max_tokens", completions[0].get("max_completion_tokens"))
    assert wire_budget == 8192
    assert cache_path.read_bytes() == before


@pytest.mark.asyncio
async def test_repeated_old_cache_admissions_hold_generation_and_effective_entries_stable(
    isolated_catalog: CredentialStore,
) -> None:
    """Repeated admissions over pre-fix cache rows republish only on real change.

    WHAT: Two stale rows (reported 131,072 and unreported, both persisted with the
        pre-fix 4,096 budget) admit three times with no refresh; no admission
        republishes at all, so generation stays at zero and the effective entries
        stay identical. Persisted bytes never change.
    WHY: Bug 112 F1 — raw durable 4,096 budgets must not be compared against
        normalized in-memory budgets, or every admission would republish.
    """
    isolated_catalog.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=SYNTHETIC_OPENROUTER_KEY,
        )
    )
    cache_path = _persist_openrouter_cache(
        store=isolated_catalog,
        entries=[_stale_converted_glm_entry(), _stale_converted_unreported_entry()],
    )
    before: bytes = cache_path.read_bytes()
    with patch(
        "src.agents.model_catalog.service.OpenRouterAPIClient",
        side_effect=AssertionError("HTTP forbidden: cached evidence must be reused"),
    ):
        snapshots = [
            await ModelCatalogService.prepare_models(
                model_names=(GLM_ROUTE, STALE_UNREPORTED_ROUTE),
            )
            for _ in range(3)
        ]

    generations: list[int] = [snapshot.generation for snapshot in snapshots]
    assert generations == [
        0,
        0,
        0,
    ], f"stale cache must never republish while its effective entries are unchanged, got {generations}"
    assert snapshots[0].entries == snapshots[1].entries == snapshots[2].entries
    glm_budgets: list[int] = [
        snapshot.entries[GLM_ROUTE].runtime_profile.max_tokens for snapshot in snapshots
    ]
    unreported_budgets: list[int] = [
        snapshot.entries[STALE_UNREPORTED_ROUTE].runtime_profile.max_tokens for snapshot in snapshots
    ]
    assert glm_budgets == [64000, 64000, 64000]
    assert unreported_budgets == [8192, 8192, 8192]
    assert cache_path.read_bytes() == before


@pytest.mark.asyncio
async def test_meaningful_changed_state_still_republishes_once_then_stays_stable(
    isolated_catalog: CredentialStore,
) -> None:
    """A real durable change (newer reported ceiling) republishes once, then stabilizes.

    WHAT: A seed-derived stale GLM row (raw budget 4,096, ceiling 131,072) admits
        twice at one unchanged generation; persisting a row whose reported ceiling
        changed to 200,000 republishes exactly once, and the next admission holds
        the new generation. The derivation is deterministic, so equality is
        coherent and one publication is sufficient.
    """
    isolated_catalog.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENROUTER,
            auth_type=AuthType.API_KEY,
            access_token=SYNTHETIC_OPENROUTER_KEY,
        )
    )
    cache_path = _persist_openrouter_cache(store=isolated_catalog, entries=[_seed_derived_glm_entry()])
    with patch(
        "src.agents.model_catalog.service.OpenRouterAPIClient",
        side_effect=AssertionError("HTTP forbidden: cached evidence must be reused"),
    ):
        initial = await ModelCatalogService.prepare_models(model_names=(GLM_ROUTE,))
        repeated = await ModelCatalogService.prepare_models(model_names=(GLM_ROUTE,))
        assert repeated.generation == initial.generation == 0
        assert repeated.entries[GLM_ROUTE].runtime_profile.max_tokens == 64000

        changed_entry = _seed_derived_glm_entry().model_copy(
            update={
                "capabilities": ModelCapabilitiesDAO(
                    input_modalities=("text",),
                    output_modalities=("text",),
                    supported_parameters=("tools",),
                    reported_output_ceiling=200_000,
                )
            }
        )
        _persist_openrouter_cache(store=isolated_catalog, entries=[changed_entry])
        adopted = await ModelCatalogService.prepare_models(model_names=(GLM_ROUTE,))
        assert adopted.generation == 1
        adopted_capabilities = adopted.entries[GLM_ROUTE].capabilities
        assert adopted_capabilities is not None
        assert adopted_capabilities.reported_output_ceiling == 200_000
        assert adopted.entries[GLM_ROUTE].runtime_profile.max_tokens == 64000
        settled = await ModelCatalogService.prepare_models(model_names=(GLM_ROUTE,))
        assert settled.generation == 1
        assert settled.entries == adopted.entries
