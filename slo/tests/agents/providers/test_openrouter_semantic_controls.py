"""Synthetic local SDK acceptance for the bounded advertised control surface."""

import json
from unittest.mock import patch

import httpx
import pytest

from src.agents.base import LLMFactory
from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.integrations.openrouter.exceptions import OpenRouterAPIError
from tests.agents.providers.test_openrouter_capability_recovery import _MODEL, _snapshot

_TOOL: dict[str, object] = {
    "type": "function",
    "function": {"name": "echo", "parameters": {"type": "object", "properties": {}}},
}
_CONTROLS = (
    "tools",
    "stop",
    "temperature",
    "top_p",
    "tool_choice",
    "parallel_tool_calls",
    "strict",
    "seed",
    "frequency_penalty",
    "presence_penalty",
    "logprobs",
    "top_logprobs",
)


def control_snapshot(*, supported: tuple[str, ...]) -> ModelCatalogSnapshotDAO:
    """Return detached capability evidence without resolver or persistence I/O."""
    snapshot = _snapshot()
    entry = snapshot.entries[_MODEL]
    assert entry.capabilities is not None
    entry = entry.model_copy(
        update={"capabilities": entry.capabilities.model_copy(update={"supported_parameters": supported})}
    )
    return snapshot.model_copy(update={"entries": {**snapshot.entries, _MODEL: entry}})


async def invoke_controls(
    *,
    options: dict[str, object],
    supported: tuple[str, ...],
    requests: list[dict[str, object]],
    constructor: bool = False,
) -> None:
    """Drive the real factory and async SDK solely through an in-memory transport."""

    def respond(request: httpx.Request) -> httpx.Response:
        """Record the actual wire request and return one successful terminal chunk."""
        requests.append(json.loads(request.content))
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content='data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        )

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic-controls-key"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_MODEL,
                snapshot=control_snapshot(supported=supported),
                http_async_client=client,
                model_kwargs=options if constructor else None,
            ).llm
        await model.bind(**({} if constructor else options)).ainvoke(input="hello")


@pytest.mark.parametrize(
    "options",
    [
        {"stop": "END"},
        {"stop": ["END", "DONE"]},
        {"temperature": 0},
        {"temperature": 2.0},
        {"top_p": 0.0},
        {"top_p": 1},
        {"seed": 0},
        {"frequency_penalty": -2},
        {"frequency_penalty": 2},
        {"presence_penalty": -2},
        {"presence_penalty": 2},
        {"logprobs": True},
        {"logprobs": False},
        {"logprobs": True, "top_logprobs": 0},
        {"logprobs": True, "top_logprobs": 20},
        {"tools": [_TOOL], "tool_choice": "auto"},
        {"tools": [_TOOL], "tool_choice": "none"},
        {"tools": [_TOOL], "tool_choice": "required"},
        {"tools": [_TOOL], "tool_choice": {"type": "function", "function": {"name": "echo"}}},
        {"tools": [_TOOL], "parallel_tool_calls": True},
        {"tools": [_TOOL], "parallel_tool_calls": False},
        {"tools": [{"type": "function", "function": {"name": "echo", "strict": True}}]},
        {"tools": [{"type": "function", "function": {"name": "echo", "strict": False}}]},
    ],
)
async def test_advertised_valid_controls_reach_actual_wire(options: dict[str, object]) -> None:
    """Preserve only requested advertised controls and fixed gateway requirements."""
    requests: list[dict[str, object]] = []
    await invoke_controls(options=options, supported=_CONTROLS, requests=requests)
    assert len(requests) == 1
    for name, value in options.items():
        assert requests[0][name] == value
    assert requests[0]["provider"] == {"require_parameters": True}
    assert not (set(_CONTROLS) - options.keys()) & requests[0].keys()


@pytest.mark.parametrize(
    "options",
    [
        {"stop": []},
        {"stop": ["ok", 1]},
        {"stop": ""},
        {"stop": 1},
        {"temperature": True},
        {"temperature": -0.1},
        {"temperature": 2.1},
        {"temperature": float("nan")},
        {"top_p": float("inf")},
        {"top_p": "0.5"},
        {"top_p": -0.1},
        {"top_p": 1.1},
        {"seed": True},
        {"seed": -1},
        {"frequency_penalty": True},
        {"frequency_penalty": -2.1},
        {"presence_penalty": "0"},
        {"presence_penalty": 2.1},
        {"logprobs": 1},
        {"top_logprobs": 1},
        {"logprobs": True, "top_logprobs": 21},
        {"parallel_tool_calls": "true"},
        {"parallel_tool_calls": 1},
        {"tool_choice": "bogus"},
        {"tool_choice": True},
        {"tool_choice": {"type": "function", "function": {"name": "missing"}}},
        {"tool_choice": {"type": "function", "function": {"name": "echo", "extra": 1}}},
        {"tool_choice": {"type": "other", "function": {"name": "echo"}}},
        {"tools": [{"type": "function", "function": {"name": "", "parameters": {}}}]},
        {"tools": [{"type": "function", "function": {"name": "echo", "parameters": []}}]},
        {"tool_choice": "required"},
        {"tools": [{"type": "function", "function": {"name": "echo", "strict": "yes"}}]},
        {"strict": True},
        {"provider": {}},
    ],
)
async def test_malformed_controls_make_zero_http_requests(options: dict[str, object]) -> None:
    """Reject malformed controls before SDK serialization, not by remote rejection."""
    requests: list[dict[str, object]] = []
    with pytest.raises((OpenRouterAPIError, ValueError)):
        await invoke_controls(options=options, supported=_CONTROLS, requests=requests)
    assert requests == []


@pytest.mark.parametrize(
    "options",
    [
        {"stop": ["END"]},
        {"temperature": 1},
        {"top_p": 0.5},
        {"seed": 1},
        {"frequency_penalty": 0.5},
        {"presence_penalty": 0.5},
        {"logprobs": True},
        {"tool_choice": "auto"},
        {"parallel_tool_calls": False},
        {"tools": [{"type": "function", "function": {"name": "echo", "strict": False}}]},
    ],
)
async def test_unadvertised_controls_make_zero_http_requests(options: dict[str, object]) -> None:
    """Explicit false values still require advertised support."""
    requests: list[dict[str, object]] = []
    with pytest.raises((OpenRouterAPIError, ValueError)):
        await invoke_controls(options=options, supported=("tools",), requests=requests)
    assert requests == []


@pytest.mark.parametrize(
    "options",
    [
        {"stop": ["END"]},
        {"temperature": 0.5, "top_p": 0.7},
        {"tools": [_TOOL], "tool_choice": "required", "parallel_tool_calls": False},
        {"tools": [{"type": "function", "function": {"name": "echo", "strict": True}}]},
    ],
)
async def test_constructor_controls_reach_wire(options: dict[str, object]) -> None:
    """Constructor inputs obey the same advertised policy as invocation inputs."""
    requests: list[dict[str, object]] = []
    await invoke_controls(options=options, supported=_CONTROLS, requests=requests, constructor=True)
    assert len(requests) == 1
    for name, value in options.items():
        assert requests[0][name] == value
