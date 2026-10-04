"""Prepared capability rejection contracts at the real OpenRouter factory."""

import json
from unittest.mock import patch

import httpx
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from src.agents.providers.openrouter import OpenRouterChatOpenAI
from src.integrations.openrouter.exceptions import OpenRouterAPIError

import pytest

from src.agents.base import LLMFactory
from src.agents.model_catalog.dao import ModelCapabilitiesDAO, ModelCatalogSnapshotDAO
from src.agents.model_catalog.seed import SeedModelCatalog
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.agents.providers.openrouter import OpenRouterRequestPolicy, OpenRouterReasoningPolicy

_MODEL = "openrouter:fixture/capabilities"


def _snapshot() -> ModelCatalogSnapshotDAO:
    """Build detached synthetic metadata without catalog or credential I/O."""
    seed = SeedModelCatalog.load()
    template = seed.entries["gpt-5.4"]
    entry = template.model_copy(
        update={
            "model_name": _MODEL,
            "api_model_name": "fixture/capabilities",
            "provider": ProviderName.OPENROUTER,
            "runtime_profile": template.runtime_profile.model_copy(update={"max_tokens": 321}),
            "capabilities": ModelCapabilitiesDAO(
                input_modalities=("text",),
                output_modalities=("text",),
                supported_parameters=("tools",),
                reported_output_ceiling=500,
            ),
        }
    )
    return seed.model_copy(update={"entries": {**seed.entries, _MODEL: entry}})


@pytest.mark.parametrize("extras", [{"models": ["other"]}, {"extra_body": {}}, {"temperature": True}])
def test_constructor_extras_rejected_before_credentials(extras: dict[str, object]) -> None:
    """Explicit unsupported constructor inputs must not be silently discarded."""
    with patch("src.agents.base.CredentialResolver.require") as credential:
        with patch("src.agents.base.OpenRouterChatOpenAI") as client:
            with pytest.raises(ValueError):
                LLMFactory.create(model_name=_MODEL, snapshot=_snapshot(), model_kwargs=extras)
    credential.assert_not_called()
    client.assert_not_called()


@pytest.mark.parametrize("cap", [0, -1, True, 501])
def test_invalid_output_cap_rejected_before_credentials_or_client(cap: int) -> None:
    """Reject invalid or above-policy explicit caps before private client setup."""
    with patch("src.agents.base.CredentialResolver.require") as credential:
        with patch("src.agents.base.OpenRouterChatOpenAI") as client:
            with pytest.raises(ValueError, match="output cap"):
                LLMFactory.create(model_name=_MODEL, snapshot=_snapshot(), max_tokens=cap)
    credential.assert_not_called()
    client.assert_not_called()


@pytest.mark.parametrize(
    ("available", "effort", "expected"),
    [
        (False, None, {}),
        (False, "low", {}),
        (True, None, {"reasoning": {"enabled": False}}),
        (True, "low", {"reasoning": {"effort": "low"}}),
    ],
)
def test_reasoning_control_distinguishes_unknown_from_disabled(
    available: bool, effort: str | None, expected: dict[str, object]
) -> None:
    """Send explicit disable only when the prepared catalog establishes controls."""
    assert OpenRouterReasoningPolicy.build(
        controls_available=available, reasoning_effort=effort, disable_available=True
    ) == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"temperature": True},
        {"parallel_tool_calls": True},
    ],
)
async def test_invocation_overrides_reject_before_http(overrides: dict[str, object]) -> None:
    """The real factory adapter rejects invocation-time bypasses before transport."""

    def reject_http(request: httpx.Request) -> httpx.Response:
        """Tripwire: rejected requests must never reach the SDK transport."""
        pytest.fail("rejected request reached HTTP")

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic-key"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(reject_http)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(model_name=_MODEL, snapshot=_snapshot(), http_async_client=client).llm
        with pytest.raises(OpenRouterAPIError):
            await model.ainvoke(input=[HumanMessage(content="hello")], config=None, stop=None, **overrides)


async def test_invocation_sampling_advertised_only_for_factory_rejects_before_http() -> None:
    """Reject an advertised sampling control when its value is outside the gateway range."""

    def reject_http(request: httpx.Request) -> httpx.Response:
        """Tripwire: invalid sampling must never reach the SDK transport."""
        pytest.fail("invalid sampling request reached HTTP")

    base_snapshot = _snapshot()
    base_entry = base_snapshot.entries[_MODEL]
    assert base_entry.capabilities is not None
    snapshot = base_snapshot.model_copy(
        update={
            "entries": {
                **base_snapshot.entries,
                _MODEL: base_entry.model_copy(
                    update={
                        "capabilities": base_entry.capabilities.model_copy(
                            update={"supported_parameters": ("tools", "temperature")}
                        )
                    }
                ),
            }
        }
    )
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic-key"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(reject_http)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(model_name=_MODEL, snapshot=snapshot, http_async_client=client).llm
        with pytest.raises(OpenRouterAPIError):
            await model.ainvoke(input=[HumanMessage(content="hello")], temperature=2.1)


@pytest.mark.parametrize("role", ["user", "assistant", "tool"])
def test_text_only_rejects_images_in_every_history_role(role: str) -> None:
    """Validate original blocks before base conversion can drop or stringify images."""
    content: list[str | dict[str, object]] = [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
    ]
    messages = {
        "user": HumanMessage(content=content),
        "assistant": AIMessage(content=content),
        "tool": ToolMessage(content=content, tool_call_id="call-1"),
    }
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic-key"
    )
    with patch("src.agents.base.CredentialResolver.require", return_value=credential):
        model = LLMFactory.create(model_name=_MODEL, snapshot=_snapshot()).llm
    assert isinstance(model, OpenRouterChatOpenAI)
    with pytest.raises(OpenRouterAPIError):
        model._get_request_payload(input_=[messages[role]])


async def test_image_capable_route_reaches_local_sdk_with_preserved_image_block() -> None:
    """Send an explicitly supported image block through the factory and local Chat Completions wire.

    The factory supplies capability evidence; the adapter must preserve that
    image block rather than reject it through the text-only guard or flatten it
    before the real SDK payload builder receives it.
    """
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Capture the local SDK payload and return one terminal SSE answer."""
        requests.append(json.loads(request.content))
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=(
                'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":"ok"},'
                '"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            ),
        )

    base_snapshot = _snapshot()
    base_entry = base_snapshot.entries[_MODEL]
    assert base_entry.capabilities is not None
    image_snapshot = base_snapshot.model_copy(
        update={
            "entries": {
                **base_snapshot.entries,
                _MODEL: base_entry.model_copy(
                    update={
                        "capabilities": base_entry.capabilities.model_copy(
                            update={"input_modalities": ("text", "image")}
                        )
                    }
                ),
            }
        }
    )
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic-key"
    )
    image_block: dict[str, object] = {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,AAAA"},
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_MODEL,
                snapshot=image_snapshot,
                http_async_client=client,
            ).llm
        response = await model.ainvoke(input=[HumanMessage(content=[image_block])])

    assert response.content == "ok"
    assert len(requests) == 1
    messages = requests[0]["messages"]
    assert isinstance(messages, list)
    assert messages[0]["content"] == [image_block]


async def test_effective_output_ceiling_bounds_constructor_and_invocation_caps() -> None:
    """Send the conservative default and reject caps above the effective context-bounded ceiling."""
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Capture each accepted local SDK request and return a terminal SSE answer."""
        requests.append(json.loads(request.content))
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content='data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        )

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic-key"
    )
    base_snapshot = _snapshot()
    base_entry = base_snapshot.entries[_MODEL]
    snapshot = base_snapshot.model_copy(
        update={
            "entries": {
                **base_snapshot.entries,
                _MODEL: base_entry.model_copy(
                    update={
                        "runtime_profile": base_entry.runtime_profile.model_copy(
                            update={"max_tokens": 321, "context_window": 500}
                        ),
                        "capabilities": (
                            base_entry.capabilities.model_copy(update={"reported_output_ceiling": 500})
                            if base_entry.capabilities is not None
                            else None
                        ),
                    }
                ),
            }
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            default_model = LLMFactory.create(
                model_name=_MODEL,
                snapshot=snapshot,
                http_async_client=client,
            ).llm
            explicit_model = LLMFactory.create(
                model_name=_MODEL,
                snapshot=snapshot,
                max_tokens=250,
                http_async_client=client,
            ).llm
        await default_model.ainvoke(input=[HumanMessage(content="default")])
        await explicit_model.ainvoke(input=[HumanMessage(content="explicit")])
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            with pytest.raises(ValueError, match="output cap"):
                LLMFactory.create(
                    model_name=_MODEL,
                    snapshot=snapshot,
                    max_tokens=251,
                    http_async_client=client,
                )

    assert [request.get("max_tokens", request.get("max_completion_tokens")) for request in requests] == [
        250,
        250,
    ]
    with pytest.raises(OpenRouterAPIError):
        await default_model.ainvoke(input=[HumanMessage(content="overflow")], max_tokens=251)
    assert len(requests) == 2


def test_fractional_output_cap_rejected() -> None:
    """Reject a fractional untyped input at the factory's validation seam."""
    with pytest.raises(ValueError, match="output cap"):
        OpenRouterRequestPolicy.validate_output_cap(max_tokens=1.5, ceiling=321)


@pytest.mark.parametrize("cap", [None, 1, 321])
def test_valid_output_cap_preserved(cap: int | None) -> None:
    """Keep the prepared default and explicit lower caps without network access."""
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic-key"
    )
    with patch("src.agents.base.CredentialResolver.require", return_value=credential):
        with patch("src.agents.base.OpenRouterChatOpenAI") as client:
            LLMFactory.create(model_name=_MODEL, snapshot=_snapshot(), max_tokens=cap)
    assert client.call_args.kwargs["max_tokens"] == (321 if cap is None else cap)
