"""Catalog-to-SDK reasoning and successful truncation acceptance; synthetic only."""

import json
from datetime import datetime, timezone
from unittest.mock import patch

import httpx
import pytest

from src.agents.base import LLMFactory
from src.agents.model_catalog.openrouter import OpenRouterCatalogConverter
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.reasoning_capabilities import resolve_reasoning_config
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.integrations.openrouter.dao import OpenRouterModelsResponseDAO
from tests.agents.model_catalog.test_openrouter_converter_metadata import _record


@pytest.mark.parametrize(
    ("reasoning", "advertised", "active", "wire"),
    [
        ({}, True, "off", None),
        ({"mandatory": False}, True, "off", None),
        ({"supported_efforts": [], "mandatory": False}, True, "off", {"enabled": False}),
        ({"supported_efforts": ["unknown"], "mandatory": True}, True, "off", None),
        ({"supported_efforts": ["low"], "mandatory": "false"}, True, "off", None),
        ({"supported_efforts": ["low"]}, True, "off", None),
        ({"supported_efforts": ["low"], "mandatory": False}, False, "off", None),
        ({"supported_efforts": None, "mandatory": False}, True, "off", {"enabled": False}),
        ({"supported_efforts": ["none"], "mandatory": False}, True, "off", {"enabled": False}),
        ({"supported_efforts": ["none"], "mandatory": True}, False, "off", None),
        ({"supported_efforts": ["none", "low"], "mandatory": False}, True, "off", {"enabled": False}),
        (
            {"supported_efforts": ["low", "unknown"], "mandatory": False, "default_enabled": False},
            True,
            "off",
            {"enabled": False},
        ),
        (
            {"supported_efforts": ["low", "high"], "mandatory": True, "default_effort": "high"},
            True,
            "low",
            {"effort": "low"},
        ),
        (
            {"supported_efforts": ["low", "high"], "default_effort": "high"},
            True,
            "off",
            None,
        ),
        (
            {"supported_efforts": None, "mandatory": True, "default_enabled": False},
            True,
            "minimal",
            {"effort": "minimal"},
        ),
    ],
)
async def test_off_canonical_display_and_actual_wire(
    reasoning: dict[str, object], advertised: bool, active: str, wire: object
) -> None:
    """Resolve canonical off honestly and transmit only established gateway controls."""
    entry = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(
            data=[
                _record(
                    reasoning=reasoning,
                    supported_parameters=["tools", "reasoning"] if advertised else ["tools"],
                )
            ]
        ),
        now=datetime(2026, 10, 1, tzinfo=timezone.utc),
    ).entries[0]
    snapshot = SeedModelCatalog.load().model_copy(update={"entries": {entry.model_name: entry}})
    resolved = resolve_reasoning_config(model_name=entry.model_name, requested_level="off", snapshot=snapshot)
    assert resolved.active_level == active
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Capture the actual SDK request, never contact a provider."""
        requests.append(json.loads(request.content))
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content='data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        )

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic-reasoning-key"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=entry.model_name,
                snapshot=snapshot,
                reasoning_level="off",
                http_async_client=client,
            ).llm
        await model.ainvoke(input="hello")
    assert len(requests) == 1
    assert requests[0].get("reasoning") == wire


async def test_default_effort_without_disable_permission_transmits_advertised_effort() -> None:
    """Use advertised enabled defaults without inventing permission to disable them."""
    entry = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(
            data=[
                _record(
                    reasoning={"supported_efforts": ["low", "high"], "default_effort": "high"},
                    supported_parameters=["tools", "reasoning"],
                )
            ]
        ),
        now=datetime(2026, 10, 1, tzinfo=timezone.utc),
    ).entries[0]
    snapshot = SeedModelCatalog.load().model_copy(update={"entries": {entry.model_name: entry}})
    resolved = resolve_reasoning_config(
        model_name=entry.model_name,
        requested_level=entry.reasoning_profile.default_level,
        snapshot=snapshot,
    )
    assert resolved.active_level == "high"
    assert resolved.provider_effort == "high"
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Capture the default effort after the real factory and SDK serialize it."""
        requests.append(json.loads(request.content))
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content='data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        )

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic-default-key"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=entry.model_name, snapshot=snapshot, http_async_client=client,
                reasoning_level=entry.reasoning_profile.default_level,
            ).llm
        await model.ainvoke(input="hello")
    assert len(requests) == 1
    assert requests[0].get("reasoning") == {"effort": "high"}


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("answer", ["", "partial answer"])
async def test_length_is_visible_success_without_adapter_retry(streaming: bool, answer: str) -> None:
    """Reasoning-only and mixed truncation retain output and label one successful request."""
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Return the same successful length outcome in JSON or split SSE frames."""
        requests.append(json.loads(request.content))
        message = {"role": "assistant", "content": answer, "reasoning": "visible thought"}
        if not streaming:
            return httpx.Response(
                status_code=200,
                json={
                    "id": "fixture",
                    "model": "vendor/model",
                    "choices": [{"index": 0, "message": message, "finish_reason": "length"}],
                },
            )
        frames = [
            {"choices": [{"index": 0, "delta": message, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "length"}]},
        ]
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames) + "data: [DONE]\n\n",
        )

    from tests.agents.providers.test_openrouter_capability_recovery import _MODEL, _snapshot

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic-length-key"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_MODEL, snapshot=_snapshot(), streaming=streaming, http_async_client=client
            ).llm
        response = await model.ainvoke(input="hello")
    assert "Output limit reached" in response.text()
    assert answer in response.text()
    assert "visible thought" in str(response.content)
    assert response.response_metadata["finish_reason"] == "length"
    assert len(requests) == 1
