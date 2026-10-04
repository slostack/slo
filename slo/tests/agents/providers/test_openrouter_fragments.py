"""Real factory/SDK SSE contracts for private continuation fragments."""

import json
import logging
from unittest.mock import patch

import httpx
import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage, message_chunk_to_message

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.base import LLMFactory
from src.agents.providers.message_extension import PROVIDER_MESSAGE_EXTENSION_KEY
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.integrations.openrouter.exceptions import OpenRouterAPIError
from tests.agents.providers.test_openrouter_transport import _prepared_snapshot, _OPENROUTER_MODEL_NAME


def _sse(deltas: list[dict[str, object]]) -> httpx.Response:
    """Encode local assistant deltas as SDK-readable SSE frames."""
    frames = [
        {
            "id": "local",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "vendor/exact-model",
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        }
        for delta in deltas
    ]
    return httpx.Response(
        status_code=200,
        headers={"content-type": "text/event-stream"},
        content="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames) + "data: [DONE]\n\n",
    )


@pytest.mark.parametrize("same_route", [True, False])
async def test_fragmented_tool_response_continues_without_metadata_duplication(same_route: bool) -> None:
    """Public streaming API assembles fragments once and sends them on request two."""
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Return fragmented private metadata then a clean answer."""
        requests.append(json.loads(request.content))
        if len(requests) > 1:
            return _sse([{"content": "done"}])
        return _sse(
            [
                {"reasoning_details": [{"index": 2, "type": "encrypted", "id": "r", "data": "abc"}]},
                {"reasoning_details": [{"index": 0, "type": "summary", "summary": "first"}]},
                {
                    "reasoning_details": [{"index": 2, "type": "encrypted", "id": "r", "data": "def"}],
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "echo", "arguments": "{}"},
                        }
                    ],
                },
            ]
        )

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_OPENROUTER_MODEL_NAME, snapshot=_prepared_snapshot(), http_async_client=client
            ).llm
        bound = model.bind_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "echo",
                        "description": "Local echo",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]
        )
        chunks = [chunk async for chunk in bound.astream([HumanMessage(content="echo")])]
        assert sum(PROVIDER_MESSAGE_EXTENSION_KEY in chunk.additional_kwargs for chunk in chunks) == 1
        combined = chunks[0]
        assert isinstance(combined, AIMessageChunk)
        for chunk in chunks[1:]:
            assert isinstance(chunk, AIMessageChunk)
            combined = combined + chunk
        assert isinstance(combined, AIMessageChunk)
        assistant = message_chunk_to_message(combined)
        agent = object.__new__(SloAgent)
        agent._current_iteration = 1
        trace = agent._trace_events_from_message(message=assistant)[0]
        event = SessionHistoryEventDAO(
            session_id="local",
            turn_id="turn",
            kind="tool_call",
            payload=SessionHistoryEventPayloadDAO(
                content=trace.payload.content,
                tool_calls=trace.payload.tool_calls,
                tool_call_id=trace.payload.tool_call_id,
                provider_message_extension=trace.payload.provider_message_extension,
            ),
        )
        restored = SessionHistoryEventDAO.model_validate_json(event.model_dump_json())
        replayed = SessionHistoryProjector._event_to_message(event=restored)
        assert replayed is not None
        assistant = replayed
        if not same_route:
            snapshot = _prepared_snapshot()
            other_name = "openrouter:vendor/other-model"
            entry = snapshot.entries[_OPENROUTER_MODEL_NAME].model_copy(
                update={"model_name": other_name, "api_model_name": "vendor/other-model"}
            )
            snapshot = snapshot.model_copy(update={"entries": {**snapshot.entries, other_name: entry}})
            with patch("src.agents.base.CredentialResolver.require", return_value=credential):
                model = LLMFactory.create(
                    model_name=other_name, snapshot=snapshot, http_async_client=client
                ).llm
        second = [
            chunk
            async for chunk in model.astream(
                [HumanMessage(content="echo"), assistant, ToolMessage(content="ok", tool_call_id="call-1")]
            )
        ]
    assert len(requests) == 2
    assert all(PROVIDER_MESSAGE_EXTENSION_KEY not in chunk.additional_kwargs for chunk in second)
    messages = requests[1]["messages"]
    assert isinstance(messages, list)
    assert requests[0]["tools"]
    assert messages[1]["tool_calls"][0]["function"]["name"] == "echo"
    if not same_route:
        assert "reasoning_details" not in messages[1]
        assert requests[1]["model"] == "vendor/other-model"
        return
    assert messages[1]["reasoning_details"] == [
        {"index": 2, "type": "encrypted", "id": "r", "data": "abcdef"},
        {"index": 0, "type": "summary", "summary": "first"},
    ]
    assert messages[2]["tool_call_id"] == "call-1"


@pytest.mark.parametrize(
    "details",
    [
        [{"index": 0, "type": "changed", "data": "RAW_SENTINEL"}],
        [{"index": 0, "data": float("nan")}],
        [{"data": "x" * (8 * 1024 * 1024)}],
    ],
)
async def test_invalid_fragments_fail_safely_through_sdk(details: list[dict[str, object]]) -> None:
    """Conflict, non-JSON numbers and oversized continuations are terminal, never truncated."""

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve invalid continuation data without external I/O."""
        return _sse(
            [
                {"reasoning_details": [{"index": 0, "type": "encrypted", "data": "start"}]},
                {"reasoning_details": details},
            ]
        )

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_OPENROUTER_MODEL_NAME, snapshot=_prepared_snapshot(), http_async_client=client
            ).llm
        with pytest.raises(OpenRouterAPIError) as caught:
            _ = [chunk async for chunk in model.astream([HumanMessage(content="echo")])]
    assert "RAW_SENTINEL" not in str(caught.value)
    assert caught.value.error_type == "invalid_request"


async def test_sdk_debug_redacts_opaque_continuation_only_during_openrouter_request() -> None:
    """Keep opaque continuation data on the exact request but out of SDK DEBUG records."""
    opaque_sentinel = "OPAQUE_SDK_DEBUG_SENTINEL"
    unrelated_sentinel = "UNRELATED_SDK_DEBUG_SENTINEL"
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Capture the exact outbound request and return a local terminal SSE response."""
        requests.append(json.loads(request.content))
        return _sse([{"content": "done"}])

    extension = {
        "provider": "openrouter",
        "source_model_name": _OPENROUTER_MODEL_NAME,
        "reasoning_details": [{"type": "encrypted", "data": opaque_sentinel}],
    }
    assistant = AIMessageChunk(content="", additional_kwargs={PROVIDER_MESSAGE_EXTENSION_KEY: extension})
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture"
    )
    sdk_logger = logging.getLogger("openai._base_client")
    handler = _InMemoryLogHandler()
    previous_level = sdk_logger.level
    previous_propagate = sdk_logger.propagate
    sdk_logger.addHandler(handler)
    sdk_logger.setLevel(logging.DEBUG)
    sdk_logger.propagate = False
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch("src.agents.base.CredentialResolver.require", return_value=credential):
                model = LLMFactory.create(
                    model_name=_OPENROUTER_MODEL_NAME,
                    snapshot=_prepared_snapshot(),
                    http_async_client=client,
                ).llm
            _ = [
                chunk
                async for chunk in model.astream(
                    [
                        HumanMessage(content="echo"),
                        assistant,
                        ToolMessage(content="ok", tool_call_id="call-1"),
                    ]
                )
            ]
        sdk_logger.debug("unrelated diagnostic %s", unrelated_sentinel)
    finally:
        sdk_logger.removeHandler(handler)
        sdk_logger.setLevel(previous_level)
        sdk_logger.propagate = previous_propagate

    captured = "\n".join(record.getMessage() for record in handler.records)
    assert len(requests) == 1
    messages = requests[0]["messages"]
    assert isinstance(messages, list)
    assert messages[1]["reasoning_details"][0]["data"] == opaque_sentinel
    assert opaque_sentinel not in captured
    assert unrelated_sentinel in captured


class _InMemoryLogHandler(logging.Handler):
    """Keep SDK DEBUG records in memory for the scoped redaction integration test."""

    def __init__(self) -> None:
        """Initialize the empty owned in-memory record buffer."""
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Retain one captured record without writing a file or terminal stream."""
        self.records.append(record)


@pytest.mark.parametrize("status", [401, 429, 503])
async def test_http200_numeric_error_code_is_safe_and_classifiable(status: int) -> None:
    """A gateway HTTP-200 error preserves numeric status, not its raw nested message."""

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve an SDK SSE error envelope."""
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content="data: " + json.dumps({"error": {"code": status, "message": "RAW_SENTINEL"}}) + "\n\n",
        )

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_OPENROUTER_MODEL_NAME, snapshot=_prepared_snapshot(), http_async_client=client
            ).llm
        with pytest.raises(OpenRouterAPIError) as caught:
            _ = [chunk async for chunk in model.astream([HumanMessage(content="echo")])]
    assert caught.value.status_code == status
    assert "RAW_SENTINEL" not in repr(caught.value)
