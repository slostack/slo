"""Real GET completeness failure must not reconcile last-good membership."""

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore
from src.integrations.openrouter.client import OpenRouterAPIClient
from tests.integration.test_openrouter_full_flow import isolated_catalog


@pytest.mark.parametrize("failure", ["repeat", "http", "partial"])
async def test_failed_pagination_preserves_committed_catalog(
    isolated_catalog: CredentialStore, tmp_path: Path, failure: str
) -> None:
    """Keep bytes, generation, last-success evidence and prior selectable model."""
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic-retention-key"
    )
    isolated_catalog.persist(cred=credential)
    failing = False
    row = {
        "id": "vendor/retained",
        "context_length": 64000,
        "supported_parameters": ["tools"],
        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
    }

    def respond(request: httpx.Request) -> httpx.Response:
        """Seed complete membership, then serve a controlled incomplete refresh."""
        if request.url.path.endswith("/key"):
            return httpx.Response(status_code=200, json={"data": {}})
        if not failing:
            return httpx.Response(status_code=200, json={"data": [row]})
        offset = request.url.params.get("offset")
        if offset is None:
            return httpx.Response(status_code=200, json={"data": [], "next": "ignored"})
        if offset == "500" and failure == "http":
            return httpx.Response(status_code=503)
        if offset == "500" and failure == "partial":
            return httpx.Response(status_code=200, json={"data": [], "next": "still-more"})
        rows = [{**row, "id": f"vendor/new-{index}"} for index in range(500)]
        return httpx.Response(status_code=200, json={"data": [] if offset == "1000" else rows})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:

        def client(*, credential: CredentialDAO) -> OpenRouterAPIClient:
            """Inject local transport without replacing lifecycle/publication owners."""
            return OpenRouterAPIClient(credential=credential, http_client=http)

        with patch("src.agents.model_catalog.service.OpenRouterAPIClient", side_effect=client):
            assert (
                await ModelCatalogService.refresh(provider=ProviderName.OPENROUTER, force=True)
            ).status == "refreshed"
            snapshot = ModelCatalogService.load()
            paths = list(tmp_path.rglob("model_catalog_cache.v2.json"))
            assert len(paths) == 1 and paths[0].resolve().is_relative_to(tmp_path.resolve())
            before = paths[0].read_bytes()
            failing = True
            result = await ModelCatalogService.refresh(provider=ProviderName.OPENROUTER, force=True)
            assert result.status == "failed"
            assert ModelCatalogService.load() == snapshot
            assert paths[0].read_bytes() == before
            assert "openrouter:vendor/retained" in before.decode()
