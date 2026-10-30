"""Offline SDK boundary regression tests; no filesystem or provider access."""

import httpx
import logging
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from src.agents.providers.openrouter import OpenRouterChatOpenAI
from src.integrations.openrouter.exceptions import OpenRouterAPIError


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("status_code", [401, 429, 503])
async def test_nonstream_http_errors_are_normalized(asynchronous: bool, status_code: int) -> None:
    """Both public invoke paths must discard raw SDK exception bodies before propagation."""
    sentinel = "private-response-sentinel"

    def respond(request: httpx.Request) -> httpx.Response:
        """Return a synthetic rejected request from the in-memory transport."""
        return httpx.Response(status_code=status_code, json={"error": {"message": sentinel}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as async_client:
            model = OpenRouterChatOpenAI(
                slo_model_name="openrouter:vendor/model",
                model="vendor/model",
                api_key="synthetic-only",
                base_url="https://openrouter.ai/api/v1",
                streaming=False,
                max_retries=0,
                http_client=client,
                http_async_client=async_client,
            )
            with pytest.raises(OpenRouterAPIError) as caught:
                if asynchronous:
                    await model.ainvoke(input="hello")
                else:
                    model.invoke(input="hello")
    assert caught.value.status_code == status_code
    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)


async def test_nonstream_reasoning_tool_continuation_strips_visible_reasoning_without_mutating_source() -> (
    None
):
    """Retain a private nonstream anchor while excluding its display-only thinking from wire input."""
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Return a raw reasoning tool call followed by a terminal local response."""
        requests.append(__import__("json").loads(request.content))
        if len(requests) == 1:
            return httpx.Response(
                status_code=200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "ordinary answer",
                                "reasoning": "visible nonstream reasoning",
                                "reasoning_details": [{"type": "encrypted", "data": "private-anchor"}],
                                "tool_calls": [
                                    {
                                        "id": "call-nonstream",
                                        "type": "function",
                                        "function": {"name": "echo", "arguments": "{}"},
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
            )
        return httpx.Response(
            status_code=200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = OpenRouterChatOpenAI(
            slo_model_name="openrouter:vendor/model",
            model="vendor/model",
            api_key="synthetic-only",
            base_url="https://openrouter.ai/api/v1",
            streaming=False,
            max_retries=0,
            http_async_client=client,
        )
        first_response = await model.ainvoke(input=[HumanMessage(content="call echo")])
        assert isinstance(first_response.content, list)
        original_content = list(first_response.content)
        await model.ainvoke(
            input=[
                HumanMessage(content="call echo"),
                first_response,
                ToolMessage(content="tool output", tool_call_id="call-nonstream"),
            ]
        )

    assert first_response.content == original_content
    messages = requests[1]["messages"]
    assert isinstance(messages, list)
    assistant = messages[1]
    assert isinstance(assistant, dict)
    assert assistant["content"] == [{"type": "text", "text": "ordinary answer"}]
    assert assistant["reasoning_details"] == [{"type": "encrypted", "data": "private-anchor"}]
    assert "visible nonstream reasoning" not in str(assistant)


def test_sync_stream_hides_private_request_options(caplog: pytest.LogCaptureFixture) -> None:
    """Sync streaming retains opaque wire metadata without logging the SDK request body."""
    sentinel = "private-sync-continuation"
    requests: list[bytes] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Capture a local continuation and return a minimal successful SSE frame."""
        requests.append(request.content)
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content='data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = OpenRouterChatOpenAI(
            slo_model_name="openrouter:vendor/model",
            model="vendor/model",
            api_key="synthetic-only",
            max_retries=0,
            http_client=client,
        )
        message = AIMessage(
            content="",
            additional_kwargs={
                "slo_provider_extension": {
                    "provider": "openrouter",
                    "source_model_name": "openrouter:vendor/model",
                    "reasoning_details": [{"type": "encrypted", "data": sentinel}],
                }
            },
        )
        with caplog.at_level(logging.DEBUG, logger="openai._base_client"):
            chunks = list(model.stream(input=[message]))
    assert chunks
    assert sentinel.encode() in requests[0]
    assert sentinel not in caplog.text
