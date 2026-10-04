"""Synthetic local Chat Completions transport proof; no live provider evidence."""

import json
import pytest
from unittest.mock import patch

import httpx
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.base import LLMFactory
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.providers.message_extension import PROVIDER_MESSAGE_EXTENSION_KEY, ProviderMessageExtensionDAO
from src.agents.providers.openrouter import OpenRouterChatOpenAI
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName

_OPENROUTER_MODEL_NAME = "openrouter:vendor/exact-model"


def _prepared_snapshot():
    """Build one local prepared exact-route snapshot for transport-only tests."""
    seed = SeedModelCatalog.load()
    template = seed.entries["gpt-5.4"]
    from src.agents.model_catalog.dao import ModelCapabilitiesDAO

    entry = template.model_copy(
        update={
            "model_name": _OPENROUTER_MODEL_NAME,
            "api_model_name": "vendor/exact-model",
            "provider": ProviderName.OPENROUTER,
            "capabilities": ModelCapabilitiesDAO(
                input_modalities=("text",),
                output_modalities=("text",),
                supported_parameters=("tools",),
            ),
        }
    )
    return seed.model_copy(update={"entries": {**seed.entries, entry.model_name: entry}})


async def test_two_request_tool_continuation_strips_visible_reasoning_without_mutating_source() -> None:
    """Send a detached assistant continuation that retains its private anchor and tool call."""
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Return an initial tool response followed by a terminal local SSE response."""
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            first_chunk: dict[str, object] = {
                "id": "first-response",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "vendor/exact-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": None,
                            "reasoning": "visible local reasoning",
                            "reasoning_details": [{"type": "encrypted", "data": "inbound-opaque"}],
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-inbound-1",
                                    "type": "function",
                                    "function": {"name": "echo", "arguments": '{"text":"from-inbound"}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }
            return httpx.Response(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                content=f"data: {json.dumps(first_chunk)}\n\ndata: [DONE]\n\n",
            )
        second_chunk: dict[str, object] = {
            "id": "second-response",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "vendor/exact-model",
            "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": "completed"}, "finish_reason": "stop"}
            ],
        }
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=f"data: {json.dumps(second_chunk)}\n\ndata: [DONE]\n\n",
        )

    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="fixture",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_OPENROUTER_MODEL_NAME,
                http_async_client=client,
                snapshot=_prepared_snapshot(),
            ).llm
        assert isinstance(model, OpenRouterChatOpenAI)
        first_response = await model.ainvoke(input=[HumanMessage(content="Use echo")])
        assert isinstance(first_response, AIMessage)
        continuation_chunks = [
            chunk
            async for chunk in model.astream(
                input=[
                    HumanMessage(content="Use echo"),
                    first_response,
                    ToolMessage(content="from-inbound", tool_call_id="call-inbound-1"),
                ]
            )
        ]

    assert isinstance(first_response.content, list)
    assert first_response.content[0] == {"type": "reasoning", "text": "visible local reasoning"}
    original_content = list(first_response.content)

    assert first_response.tool_calls == [
        {"name": "echo", "args": {"text": "from-inbound"}, "id": "call-inbound-1", "type": "tool_call"}
    ]
    assert "".join(str(chunk.content) for chunk in continuation_chunks) == "completed"
    assert len(requests) == 2
    assert first_response.content == original_content
    continuation_messages = requests[1]["messages"]
    assert isinstance(continuation_messages, list)
    assert continuation_messages[1]["reasoning_details"] == [{"type": "encrypted", "data": "inbound-opaque"}]
    assert continuation_messages[1]["content"] in (None, "")
    assert "visible local reasoning" not in json.dumps(continuation_messages[1])
    assert continuation_messages[1]["tool_calls"][0]["id"] == "call-inbound-1"
    assert json.loads(continuation_messages[1]["tool_calls"][0]["function"]["arguments"]) == {
        "text": "from-inbound"
    }
    assert continuation_messages[2] == {
        "role": "tool",
        "content": "from-inbound",
        "tool_call_id": "call-inbound-1",
    }


@pytest.mark.parametrize("streaming", [False, True])
async def test_refusal_is_visible_through_real_sdk(streaming: bool) -> None:
    """A successful refusal remains a terminal visible answer, not an empty response."""

    def respond(request: httpx.Request) -> httpx.Response:
        """Return a synthetic refusal in either documented transport shape."""
        message = {"role": "assistant", "content": None, "refusal": "Cannot help with that."}
        if streaming:
            frame = {"choices": [{"index": 0, "delta": message, "finish_reason": "stop"}]}
            return httpx.Response(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                content=f"data: {json.dumps(frame)}\n\ndata: [DONE]\n\n",
            )
        return httpx.Response(
            status_code=200, json={"choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}
        )

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="synthetic"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_OPENROUTER_MODEL_NAME,
                snapshot=_prepared_snapshot(),
                http_async_client=client,
                streaming=streaming,
            ).llm
        response = await model.ainvoke(input="hello")
    assert isinstance(response, AIMessage)
    assert response.content == "Cannot help with that."
    assert response.usage_metadata is None


async def test_reasoning_only_length_response_projects_plaintext_without_exposing_opaque_details() -> None:
    """Project visible reasoning and report an empty length completion without retrying the local SDK."""
    requests: list[dict[str, object]] = []
    opaque_sentinel = "OPAQUE_REASONING_SENTINEL"

    def respond(request: httpx.Request) -> httpx.Response:
        """Return one reasoning-only truncated Chat Completions response."""
        requests.append(json.loads(request.content))
        return httpx.Response(
            status_code=200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning": "plain reasoning",
                            "reasoning_details": [{"type": "encrypted", "data": opaque_sentinel}],
                        },
                        "finish_reason": "length",
                    }
                ]
            },
        )

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_OPENROUTER_MODEL_NAME,
                snapshot=_prepared_snapshot(),
                streaming=False,
                http_async_client=client,
            ).llm
        response = await model.ainvoke(input=[HumanMessage(content="continue")])

    assert response.text() == "Output limit reached"
    assert response.additional_kwargs[PROVIDER_MESSAGE_EXTENSION_KEY]["reasoning"] == "plain reasoning"
    assert opaque_sentinel not in response.text()
    assert len(requests) == 1


async def test_nonstream_response_preserves_inbound_reasoning_details() -> None:
    """Retain an ordinary Chat Completions reasoning field before a future continuation."""
    credential: CredentialDAO = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="fixture",
    )
    response: dict[str, object] = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "nonstream answer",
                    "reasoning_content": "gateway reasoning",
                },
                "finish_reason": "stop",
            }
        ]
    }
    with patch("src.agents.base.CredentialResolver.require", return_value=credential):
        model = LLMFactory.create(model_name=_OPENROUTER_MODEL_NAME, snapshot=_prepared_snapshot()).llm

    assert isinstance(model, OpenRouterChatOpenAI)
    result = model._create_chat_result(response=response)
    message = result.generations[0].message

    assert message.additional_kwargs[PROVIDER_MESSAGE_EXTENSION_KEY] == {
        "provider": "openrouter",
        "source_model_name": "openrouter:vendor/exact-model",
        "reasoning": "gateway reasoning",
        "reasoning_details": [],
    }


async def test_second_tool_request_preserves_same_route_extension_through_sdk() -> None:
    """Send a tool continuation through the public API and inspect the actual HTTP body."""
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Capture the SDK body and return one documented-shape synthetic SSE response."""
        assert request.url.path == "/api/v1/chat/completions"
        requests.append(json.loads(request.content))
        chunk = {
            "id": "fixture",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "vendor/exact-model",
            "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": "Done"}, "finish_reason": "stop"}
            ],
        }
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
        )

    extension = ProviderMessageExtensionDAO(
        provider=ProviderName.OPENROUTER,
        source_model_name=_OPENROUTER_MODEL_NAME,
        reasoning_details=[{"type": "encrypted", "data": "synthetic-opaque"}],
    )
    assistant = AIMessage(
        content="",
        tool_calls=[{"name": "echo", "args": {"text": "hello"}, "id": "call-1", "type": "tool_call"}],
        additional_kwargs={PROVIDER_MESSAGE_EXTENSION_KEY: extension.model_dump(mode="json")},
    )
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_OPENROUTER_MODEL_NAME, http_async_client=client, snapshot=_prepared_snapshot()
            ).llm
        chunks = [
            chunk
            async for chunk in model.astream(
                input=[
                    HumanMessage(content="Echo hello"),
                    assistant,
                    ToolMessage(content="hello", tool_call_id="call-1"),
                ]
            )
        ]
    assert "".join(str(chunk.content) for chunk in chunks) == "Done"
    assert len(requests) == 1
    assert requests[0]["provider"] == {"require_parameters": True}
    assert requests[0]["model"] == "vendor/exact-model"
    messages = requests[0]["messages"]
    assert isinstance(messages, list)
    assert messages[1]["reasoning_details"] == extension.reasoning_details
    assert messages[1]["tool_calls"][0]["id"] == "call-1"
    assert json.loads(messages[1]["tool_calls"][0]["function"]["arguments"]) == {"text": "hello"}
    assert messages[2] == {"role": "tool", "content": "hello", "tool_call_id": "call-1"}
