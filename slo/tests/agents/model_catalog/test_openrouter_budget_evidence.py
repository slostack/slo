"""Strict reasoning-budget evidence survives canonical serialization without controls."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.agents.base import LLMFactory
from src.agents.model_catalog.dao import ModelCatalogCacheDAO, ProviderCatalogCacheDAO
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.model_catalog.store import ModelCatalogStore
from src.auth.credential_dao import (
    AuthType,
    CredentialDAO,
    ProviderName,
    CredentialSource,
    ResolvedCredentialDAO,
)
from src.auth.credential_resolver import CredentialResolver
from src.integrations.openrouter.dao import credential_fingerprint
from tests.agents.model_catalog.test_openrouter_converter_metadata import _entry


@pytest.mark.parametrize(
    "value,expected", [(True, True), (False, False), (None, None), (1, None), ("true", None), ({}, None)]
)
def test_budget_evidence_survives_real_cache(tmp_path: Path, value: object, expected: bool | None) -> None:
    """Retain strict optional evidence through the actual schema-2 disk boundary."""
    entry = _entry(reasoning={"supports_max_tokens": value})
    path = tmp_path / "catalog.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                entries=[entry],
            )
        ]
    )
    ModelCatalogStore.write_provider_cache(cache=cache, override_path=path)
    loaded = ModelCatalogStore.load_provider_cache(override_path=path)
    assert loaded is not None
    retained = loaded.provider_slices[0].entries[0]
    assert retained.capabilities is not None
    assert retained.capabilities.supports_max_tokens is expected
    assert retained.reasoning_profile.supported_levels == ("off",)


@pytest.mark.parametrize(
    "value,expected", [(True, True), (False, False), (None, None), (1, None), ("true", None), ({}, None)]
)
async def test_prepared_budget_evidence_never_adds_budget_request(
    tmp_path: Path,
    value: object,
    expected: bool | None,
) -> None:
    """Admit real schema-2 evidence and complete an SDK response without budget controls."""
    reasoning: dict[str, object] = {"supported_efforts": ["low"], "mandatory": False}
    if value is not None:
        reasoning["supports_max_tokens"] = value
    entry = _entry(reasoning=reasoning)
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Capture the local SDK request without contacting a provider."""
        import json

        requests.append(json.loads(request.content))
        return httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            json={
                "id": "fixture",
                "object": "chat.completion",
                "created": 1,
                "model": "vendor/model",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
                ],
            },
        )

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-budget-key",
    )
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.STORE)
    now = datetime.now(tz=timezone.utc).isoformat()
    cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(
                provider=ProviderName.OPENROUTER,
                credential_fingerprint=credential_fingerprint(access_token=credential.access_token),
                key_verified_at=now,
                last_success_at=now,
                entries=[entry],
            )
        ]
    )
    path = tmp_path / "model_catalog_cache.v2.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    ModelCatalogStore.write_provider_cache(cache=cache, override_path=path)
    with (
        patch("src.agents.model_catalog.store._global_dir", return_value=tmp_path),
        patch.object(CredentialResolver, "resolve_with_source", return_value=resolved),
        patch(
            "src.agents.model_catalog.service.OpenRouterAPIClient",
            side_effect=AssertionError("HTTP forbidden"),
        ),
    ):
        ModelCatalogService.reset()
        try:
            prepared = await ModelCatalogService.prepare_models(model_names=(entry.model_name,))
        finally:
            await ModelCatalogService.shutdown()
            ModelCatalogService.reset()
    assert prepared.entries[entry.model_name] == entry
    assert prepared.entries[entry.model_name].capabilities is not None
    assert prepared.entries[entry.model_name].capabilities.supports_max_tokens is expected

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=entry.model_name,
                snapshot=prepared,
                reasoning_level="low",
                streaming=False,
                http_async_client=client,
            ).llm
        response = await model.ainvoke(input="hello")
        assert response.content == "ok"

    assert len(requests) == 1
    assert requests[0]["reasoning"] == {"effort": "low"}
    assert "max_tokens" not in requests[0]["reasoning"]
    assert "reasoning_max_tokens" not in requests[0]
