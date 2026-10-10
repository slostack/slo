"""Authenticated synthetic Jev admission through real GET, resolver and store owners."""

import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.agents.model_catalog.service import ModelCatalogService, ModelPreparationRequiredError
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore
from src.integrations.openrouter.client import OpenRouterAPIClient
from tests.integration.test_openrouter_full_flow import isolated_catalog

ROUTE = "openrouter:typesafe/jev-router"
NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


@pytest.fixture
async def jev_transport(
    isolated_catalog: CredentialStore, request: pytest.FixtureRequest
) -> AsyncIterator[list[httpx.Request]]:
    """Inject only the real GET client's transport and clock for each admission test."""
    requests: list[httpx.Request] = []
    outcome: str = getattr(request, "param", "available")
    record = json.loads(Path(__file__).with_name("feature89_jev.json").read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        """Serve the full row only on authenticated user listing, never public listing."""
        assert request.method == "GET"
        assert request.url.host == "openrouter.ai"
        assert request.headers["authorization"] in {"Bearer fixture-jev-A", "Bearer fixture-jev-B"}
        requests.append(request)
        if request.headers["authorization"] == "Bearer fixture-jev-B":
            return httpx.Response(status_code=401, json={"error": {"message": "rejected"}})
        if request.url.path == "/api/v1/key":
            return httpx.Response(status_code=200, json={"data": {}})
        assert request.url.path == "/api/v1/models/user"
        if len(requests) > 2:
            if outcome == "transient":
                return httpx.Response(status_code=503, json={"error": {"message": "unavailable"}})
            if outcome == "removed":
                return httpx.Response(status_code=200, json={"data": []})
            if outcome == "incomplete":
                return httpx.Response(status_code=200, json={"data": [record], "total_count": 2})
            if outcome == "expired":
                return httpx.Response(
                    status_code=200, json={"data": [{**record, "expiration_date": "2026-10-09"}]}
                )
        return httpx.Response(status_code=200, json={"data": [record]})

    assert isolated_catalog.additional_providers_path.resolve().is_relative_to(
        isolated_catalog.path.parent.resolve()
    )
    isolated_catalog.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture-jev-A"
        )
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:

        def factory(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Keep production parsing/verification with caller-owned HTTP lifetime."""
            return OpenRouterAPIClient(credential=credential, http_client=client)

        with (
            patch("src.agents.model_catalog.service.OpenRouterAPIClient", side_effect=factory),
            patch("src.agents.model_catalog.service.datetime", wraps=datetime) as clock,
            patch("src.integrations.openrouter.client.verification_now", return_value=NOW),
        ):
            clock.now.return_value = NOW
            yield requests


@pytest.mark.parametrize("jev_transport", ["transient"], indirect=True)
async def test_jev_stale_listing_requires_fresh_same_key_verification(
    isolated_catalog: CredentialStore, jev_transport: list[httpx.Request]
) -> None:
    """After TTL, real re-verification permits only the retained same-key listing."""
    from datetime import timedelta

    admitted = await ModelCatalogService.prepare_models(model_names=(ROUTE,), now=NOW)
    cache = isolated_catalog.path.parent / "global/model_catalog_cache.v2.json"
    before = cache.read_bytes()
    later = NOW + timedelta(hours=2)
    with (
        patch("src.agents.model_catalog.service.datetime", wraps=datetime) as clock,
        patch("src.integrations.openrouter.client.verification_now", return_value=later),
    ):
        clock.now.return_value = later
        retained = await ModelCatalogService.prepare_models(model_names=(ROUTE,), now=later)
    assert [request.url.path for request in jev_transport] == [
        "/api/v1/key",
        "/api/v1/models/user",
        "/api/v1/key",
        "/api/v1/models/user",
    ]
    assert cache.read_bytes() == before
    assert retained.entries[ROUTE] == admitted.entries[ROUTE]
    assert retained.entries[ROUTE].runtime_profile.max_tokens == 4096


async def test_jev_router_unknown_controls_use_provider_default(
    isolated_catalog: CredentialStore, jev_transport: list[httpx.Request]
) -> None:
    """Actual admission supplies the router's unknown-controls evidence."""
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.tui.slash_router import SlashRouter
    from src.agents.slo_agent.preferences.service import UserPreferencesStore

    snapshot = await ModelCatalogService.prepare_models(model_names=(ROUTE,), now=NOW)
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=isolated_catalog.path.parent,
            model_name=ROUTE,
            enable_history=False,
        ),
        catalog_snapshot=snapshot,
    )
    with patch.object(UserPreferencesStore, "upsert", side_effect=AssertionError("must not save")):
        for line in ("/reasoning", "/reasoning off", "/reasoning on"):
            result = await SlashRouter.dispatch(line=line, session=session)
            assert result.rendered is not None
            assert "provider default; controls unavailable" in result.rendered
            assert "unsupported" not in result.rendered
            assert "disabled" not in result.rendered


async def test_jev_authenticated_admission(
    isolated_catalog: CredentialStore, jev_transport: list[httpx.Request]
) -> None:
    """Admission obtains real authenticated metadata and publishes the conservative cap."""
    snapshot = await ModelCatalogService.prepare_models(model_names=(ROUTE,), now=NOW)
    entry = snapshot.entries[ROUTE]
    assert entry.runtime_profile.max_tokens == 4096
    assert entry.capabilities is not None
    assert entry.capabilities.reported_output_ceiling is None
    assert entry.capabilities.reasoning_controls_available is False
    assert [request.url.path for request in jev_transport] == ["/api/v1/key", "/api/v1/models/user"]


@pytest.mark.parametrize("change", ["rotation", "removal"])
async def test_jev_new_admission_rejects_changed_credentials(
    isolated_catalog: CredentialStore, jev_transport: list[httpx.Request], change: str
) -> None:
    """New admission cannot borrow A's listing; already admitted A remains immutable."""
    admitted = await ModelCatalogService.prepare_models(model_names=(ROUTE,), now=NOW)
    cache = isolated_catalog.path.parent / "global/model_catalog_cache.v2.json"
    before = cache.read_bytes()
    if change == "removal":
        isolated_catalog.remove(provider=ProviderName.OPENROUTER)
    else:
        isolated_catalog.persist(
            cred=CredentialDAO(
                provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture-jev-B"
            )
        )
    with pytest.raises(ModelPreparationRequiredError):
        await ModelCatalogService.prepare_models(model_names=(ROUTE,), now=NOW)
    assert cache.read_bytes() == before
    assert admitted.entries[ROUTE].availability == "available"
    assert admitted.entries[ROUTE].runtime_profile.max_tokens == 4096
    assert len(jev_transport) == (2 if change == "removal" else 3)
    assert "fixture-jev" not in admitted.model_dump_json()


@pytest.mark.parametrize("jev_transport", ["removed", "incomplete", "expired"], indirect=True)
async def test_jev_listing_refresh_preserves_admission_boundaries(
    isolated_catalog: CredentialStore, jev_transport: list[httpx.Request], request: pytest.FixtureRequest
) -> None:
    """Complete removal/expiry revokes membership; incomplete listing retains good bytes."""
    admitted = await ModelCatalogService.prepare_models(model_names=(ROUTE,), now=NOW)
    cache = isolated_catalog.path.parent / "global/model_catalog_cache.v2.json"
    before = cache.read_bytes()
    outcome = request.node.callspec.params["jev_transport"]
    refreshed = await ModelCatalogService.refresh(provider=ProviderName.OPENROUTER, force=True)
    assert admitted.entries[ROUTE].availability == "available"
    if outcome == "incomplete":
        assert refreshed.status == "failed"
        assert cache.read_bytes() == before
        retained = await ModelCatalogService.prepare_models(model_names=(ROUTE,), now=NOW)
        assert retained.entries[ROUTE].runtime_profile.max_tokens == 4096
    else:
        assert refreshed.status == "refreshed"
        assert cache.read_bytes() != before
        with pytest.raises(ModelPreparationRequiredError):
            await ModelCatalogService.prepare_models(model_names=(ROUTE,), now=NOW)
