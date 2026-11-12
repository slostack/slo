"""Spec 107 A18 and compatibility gate 2 over real provider HTTP decoding.

These are synthetic SSE captures, not live-provider certification. The public
model stream is inspected before graph execution; no normalizer-built chunks
stand in for adapter evidence. HTTP is intercepted at the third-party transport.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import httpx
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.tools import tool
from pydantic import SecretStr

from src.agents.base import LLMFactory
from src.agents.model_catalog.dao import ModelCapabilitiesDAO
from src.agents.providers.anthropic_claude_code import (
    _ThinkingPatchedChatAnthropic,
    build_claude_code_backed_chat_anthropic,
)
from src.agents.providers.openrouter import OpenRouterChatOpenAI
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.agents.providers.openai_responses_sequencing import SequencedChatOpenAI
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.tui.components.chat_transcript.adapters.transcript_projector import TranscriptProjectionAdapter
from tests.agents.providers.feature89_responses import (
    answer_frames,
    tool_frames,
    encode_frames,
    response_envelope,
)
from tests.auth.test_credential_resolver import _reload_cfg
from tests.tui.test_transcript_projector import FakeHost


def chat_completion_frames(*, shape: str, answer: bool = False) -> bytes:
    """Encode fragmented Chat Completions calls or the terminal answer.

    Args:
        shape: Single, parallel, empty or late-name call sequence.
        answer: Emit a tool-free terminal response instead. Defaults to False.

    Returns:
        bytes: SDK-readable SSE with opaque Kimi-style call identifiers.
    """
    deltas: list[dict[str, object]] = []
    if answer:
        deltas = [{"role": "assistant", "content": "complete-107"}]
    else:
        count: int = 2 if shape == "parallel" else 1
        for slot in range(count):
            function: dict[str, object] = {"arguments": ""}
            if shape != "late-name":
                function["name"] = "echo"
            deltas.append(
                {
                    "tool_calls": [
                        {
                            "index": slot,
                            "id": f"functions.echo:{slot}",
                            "type": "function",
                            "function": function,
                        }
                    ]
                }
            )
        for piece in ("{", '"text":"wire"}') if shape != "empty" else ("{", "}"):
            for slot in range(count):
                deltas.append({"tool_calls": [{"index": slot, "function": {"arguments": piece}}]})
        if shape == "late-name":
            deltas.append({"tool_calls": [{"index": 0, "function": {"name": "echo", "arguments": ""}}]})
    frames: list[dict[str, object]] = [
        {
            "id": "chat107",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "offline",
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        }
        for delta in deltas
    ]
    frames.append(
        {
            "id": "chat107",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "offline",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop" if answer else "tool_calls"}],
        }
    )
    return ("".join(f"data: {json.dumps(frame)}\n\n" for frame in frames) + "data: [DONE]\n\n").encode()


class TestChatCompletionsToolCallWireJourney:
    """A18/gate2 for the OpenRouter adapter and factory-built stock Kimi."""

    @pytest.mark.parametrize("route", ["openrouter", "kimi"], ids=["A18-OpenRouter", "A18-Kimi"])
    @pytest.mark.parametrize("shape", ["single", "parallel", "empty", "late-name"])
    async def test_executes_once_and_continues_when_chat_completions_fragments_calls(
        self, *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str, shape: str
    ) -> None:
        """Inspect adapter chunks and retain original ids through graph and display.

        Args:
            tmp_path: Owned graph work directory.
            monkeypatch: Restores synthetic factory credential environment.
            route: Concrete production provider construction path.
            shape: Required wire-fragment scenario.
        """
        requests: list[dict[str, object]] = []
        executions: list[str] = []

        @tool
        def echo(*, text: str = "empty") -> str:
            """Return and record one local execution.

            Args:
                text: Tool argument, defaulting to empty's marker.

            Returns:
                str: Observably executed result rather than a validation error.
            """
            executions.append(text)
            return text

        async def respond(transport: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
            """Intercept the vendor HTTP boundary; forbid all unmatched traffic.

            Args:
                transport: Third-party transport selected by the factory (unused).
                request: Serialized SDK request.

            Returns:
                httpx.Response: Scripted SSE response without a socket.
            """
            del transport
            assert str(request.url) == (
                "https://api.kimi.com/coding/v1/chat/completions"
                if route == "kimi"
                else "https://openrouter.ai/api/v1/chat/completions"
            )
            requests.append(json.loads(request.content))
            assert len(requests) <= 3
            return httpx.Response(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                stream=httpx.ByteStream(chat_completion_frames(shape=shape, answer=len(requests) == 3)),
            )

        monkeypatch.setenv(name="SLO_KIMI_FOR_CODING_API_KEY", value="offline-107")
        _reload_cfg()
        with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", new=respond):
            model: BaseChatModel = (
                LLMFactory.create(model_name="kimi-for-coding", streaming=True, max_retries=0).llm
                if route == "kimi"
                else OpenRouterChatOpenAI(
                    slo_model_name="openrouter:vendor/offline",
                    model="vendor/offline",
                    slo_capabilities=ModelCapabilitiesDAO(
                        input_modalities=("text",),
                        output_modalities=("text",),
                        supported_parameters=("tools", "tool_choice", "parallel_tool_calls"),
                    ),
                    base_url="https://openrouter.ai/api/v1",
                    api_key=SecretStr("offline"),
                    streaming=True,
                    max_retries=0,
                )
            )
            chunks: list[AIMessageChunk] = []
            async for chunk in model.astream(input="Use echo"):
                assert isinstance(chunk, AIMessageChunk)
                chunks.append(chunk)
            assert any(chunk.tool_call_chunks for chunk in chunks)
            for chunk in chunks:
                assert_content_tool_chunks_agree(chunk=chunk)
            host: FakeHost = FakeHost()
            projector: TranscriptProjectionAdapter = TranscriptProjectionAdapter(host=host)
            agent: SloAgent = SloAgent(llm=model, tools=[echo], cwd=str(tmp_path), system_prompt="Use tools.")
            events: list[AgentStreamEventDAO] = []
            async for event in agent.invoke(query="Use echo"):
                events.append(event)
                await projector.handle(event=event)
        count: int = 2 if shape == "parallel" else 1
        expected_ids: list[str] = [f"functions.echo:{slot}" for slot in range(count)]
        expected_output: str = "empty" if shape == "empty" else "wire"
        assert_tool_lifecycle(events=events, expected_ids=expected_ids)
        assert executions == [expected_output] * count
        assert host.mount_order.count("tool") == count
        assert list(host.tool_blocks) == expected_ids
        assert [block.result_output for block in host.tool_blocks.values()] == [expected_output] * count
        assert Counter(
            event.tool_call_id for event in events if event.kind == "tool_result"
        ) == dict.fromkeys(expected_ids, 1)
        assert Counter(
            event.tool_call_id for event in events if event.kind == "tool_call_end"
        ) == dict.fromkeys(expected_ids, 1)
        assert events[-1].kind == "run_completed" and events[-1].content == "complete-107"
        messages = requests[-1]["messages"]
        assert isinstance(messages, list)
        assert [
            message["tool_call_id"] for message in messages if message.get("role") == "tool"
        ] == expected_ids


def anthropic_frames(*, tool_name: str, shape: str, answer: bool = False) -> bytes:
    """Encode valid Anthropic block starts, argument deltas and message closure.

    Anthropic names are required at content_block_start and have no name-delta
    event; a late-name scenario is not representable on this wire protocol.

    Args:
        tool_name: Wire name, including OAuth's canonical Read casing.
        shape: Single, parallel or empty argument calls.
        answer: Emit the terminal text message. Defaults to False.

    Returns:
        bytes: SSE decoded by the real Anthropic SDK.
    """
    frames: list[dict[str, object]] = [
        {
            "type": "message_start",
            "message": {
                "id": "msg107",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 0},
            },
        }
    ]
    if answer:
        frames.extend(
            [
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "complete-107"},
                },
                {"type": "content_block_stop", "index": 0},
            ]
        )
    else:
        for slot in range(2 if shape == "parallel" else 1):
            frames.append(
                {
                    "type": "content_block_start",
                    "index": slot,
                    "content_block": {
                        "type": "tool_use",
                        "id": f"toolu107_{slot}",
                        "name": tool_name,
                        "input": {},
                    },
                }
            )
            for piece in ("{", "}") if shape == "empty" else ('{"text":', '"wire"}'):
                frames.append(
                    {
                        "type": "content_block_delta",
                        "index": slot,
                        "delta": {"type": "input_json_delta", "partial_json": piece},
                    }
                )
            frames.append({"type": "content_block_stop", "index": slot})
    frames.extend(
        [
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn" if answer else "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 4},
            },
            {"type": "message_stop"},
        ]
    )
    return "".join(f"event: {frame['type']}\ndata: {json.dumps(frame)}\n\n" for frame in frames).encode()


class TestAnthropicToolCallWireJourney:
    """A18/gates1&2 through real API-key and Claude Code OAuth providers."""

    @pytest.mark.parametrize(
        "route,wire_name",
        [("api-key", "read"), ("oauth", "read"), ("oauth", "Read")],
        ids=["A18-api-key", "gate1-oauth-read", "gate1-oauth-Read"],
    )
    @pytest.mark.parametrize("shape", ["single", "parallel", "empty"])
    async def test_executes_registered_tool_and_continues_when_anthropic_streams_calls(
        self, *, tmp_path: Path, route: str, wire_name: str, shape: str
    ) -> None:
        """Check both chunk sources before running the same wire through the graph.

        Args:
            tmp_path: Owned work directory.
            route: API-key subclass or OAuth builder.
            wire_name: Actual returned name, never rewritten in the test.
            shape: Required representable Anthropic call shape.
        """
        requests: list[dict[str, object]] = []
        executions: list[str] = []

        @tool(name_or_callable="read")
        def read(*, text: str = "empty") -> str:
            """Record execution under the real registered Slo tool name.

            Args:
                text: Synthetic tool argument; defaults to empty's marker.

            Returns:
                str: Successful execution marker sent back to the provider.
            """
            executions.append(text)
            return text

        async def respond(transport: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
            """Forbid unmatched traffic at the Anthropic SDK HTTP boundary.

            Args:
                transport: SDK transport, unused because no socket is opened.
                request: Actual vendor request for capture.

            Returns:
                httpx.Response: Scripted tool or final-answer stream.
            """
            del transport
            assert request.url.host == "api.anthropic.com" and request.url.path == "/v1/messages"
            requests.append(json.loads(request.content))
            assert len(requests) <= 3
            return httpx.Response(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                stream=httpx.ByteStream(
                    anthropic_frames(tool_name=wire_name, shape=shape, answer=len(requests) == 3)
                ),
            )

        with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", new=respond):
            model: BaseChatModel = (
                build_claude_code_backed_chat_anthropic(
                    model_name="claude-sonnet-4-6",
                    cred=CredentialDAO(
                        provider=ProviderName.ANTHROPIC, auth_type=AuthType.OAUTH, access_token="offline107"
                    ),
                    max_retries=0,
                )
                if route == "oauth"
                else _ThinkingPatchedChatAnthropic(
                    model_name="claude-sonnet-4-6",
                    api_key=SecretStr("offline107"),
                    streaming=True,
                    max_retries=0,
                    timeout=None,
                    stop=None,
                )
            )
            chunks: list[AIMessageChunk] = []
            async for chunk in model.bind_tools(tools=[read]).astream(input="Read"):
                assert isinstance(chunk, AIMessageChunk)
                chunks.append(chunk)
            assert any(chunk.tool_call_chunks and chunk.content for chunk in chunks)
            for chunk in chunks:
                assert_content_tool_chunks_agree(chunk=chunk)
            host: FakeHost = FakeHost()
            projector: TranscriptProjectionAdapter = TranscriptProjectionAdapter(host=host)
            agent: SloAgent = SloAgent(llm=model, tools=[read], cwd=str(tmp_path), system_prompt="Read.")
            events: list[AgentStreamEventDAO] = []
            async for event in agent.invoke(query="Read"):
                events.append(event)
                await projector.handle(event=event)
        count: int = 2 if shape == "parallel" else 1
        expected_ids: list[str] = [f"toolu107_{slot}" for slot in range(count)]
        expected_output: str = "empty" if shape == "empty" else "wire"
        assert_tool_lifecycle(events=events, expected_ids=expected_ids)
        assert (
            executions == [expected_output] * count
        ), "gate1: streamed wire name must execute registered read"
        assert host.mount_order.count("tool") == count
        assert list(host.tool_blocks) == expected_ids
        assert [block.result_output for block in host.tool_blocks.values()] == [expected_output] * count
        assert Counter(
            event.tool_call_id for event in events if event.kind == "tool_result"
        ) == dict.fromkeys(expected_ids, 1)
        assert Counter(
            event.tool_call_id for event in events if event.kind == "tool_call_end"
        ) == dict.fromkeys(expected_ids, 1)
        assert events[-1].kind == "run_completed" and events[-1].content == "complete-107"
        messages: object = requests[-1]["messages"]
        assert isinstance(messages, list)
        outbound_ids: list[str] = [
            block["tool_use_id"]
            for message in messages
            if isinstance(message.get("content"), list)
            for block in message["content"]
            if block.get("type") == "tool_result"
        ]
        assert outbound_ids == expected_ids
        outbound_results: list[dict[str, object]] = [
            block
            for message in messages
            if isinstance(message.get("content"), list)
            for block in message["content"]
            if block.get("type") == "tool_result"
        ]
        assert all(not block.get("is_error", False) for block in outbound_results)
        assert [block["content"] for block in outbound_results] == [expected_output] * count


def responses_frames(*, shape: str) -> bytes:
    """Build authoritative Responses calls with interleaved argument fragments.

    Responses requires name at output_item.added; the production sequencing
    adapter rejects a different completion name. No name-delta wire event exists.

    Args:
        shape: Single uses feature89 verbatim; parallel or empty extends it.

    Returns:
        bytes: Complete SDK-validated SSE for the first response.
    """
    if shape == "single":
        return tool_frames(model_name="gpt-5")
    starts: list[dict[str, object]] = [
        {
            "type": "function_call",
            "id": f"fc107_{slot}",
            "call_id": f"call107_{slot}",
            "name": "echo",
            "arguments": "",
            "status": "in_progress",
        }
        for slot in range(2 if shape == "parallel" else 1)
    ]
    arguments: str = "{}" if shape == "empty" else '{"text":"echo-89"}'
    completed: list[dict[str, object]] = [
        {**start, "arguments": arguments, "status": "completed"} for start in starts
    ]
    frames: list[dict[str, object]] = [
        {
            "type": "response.created",
            "response": response_envelope(model_name="gpt-5", output=[], completed=False),
        }
    ]
    frames.extend(
        {"type": "response.output_item.added", "output_index": slot, "item": start}
        for slot, start in enumerate(starts)
    )
    for piece in (arguments[:1], arguments[1:]):
        frames.extend(
            {
                "type": "response.function_call_arguments.delta",
                "output_index": slot,
                "item_id": start["id"],
                "delta": piece,
            }
            for slot, start in enumerate(starts)
        )
    frames.extend(
        {"type": "response.output_item.done", "output_index": slot, "item": done}
        for slot, done in enumerate(completed)
    )
    frames.append(
        {
            "type": "response.completed",
            "response": response_envelope(model_name="gpt-5", output=completed, completed=True),
        }
    )
    return encode_frames(frames=frames)


class TestProviderToolCallWireJourney:
    """Exercise A18 execution, display and original result-id continuation."""

    @pytest.mark.parametrize("output_version", ["v0", "responses/v1"], ids=["A18-v0", "A18-v1"])
    @pytest.mark.parametrize("shape", ["single", "parallel", "empty"])
    async def test_attaches_one_result_when_responses_streams_a_call(
        self, *, tmp_path: Path, output_version: Literal["v0", "responses/v1"], shape: str
    ) -> None:
        """A18/gate2: decode actual chunks, then execute once and continue.

        Args:
            tmp_path: Owned work directory; the tool makes no filesystem writes.
            output_version: Production Responses output representation.
            shape: Required representable Responses call shape.
        """
        requests: list[dict[str, object]] = []
        executions: list[str] = []

        @tool
        def echo(*, text: str = "empty") -> str:
            """Record one graph execution and return its argument.

            Args:
                text: Provider-requested text.

            Returns:
                str: The same text for the next provider request.
            """
            executions.append(text)
            return text

        def respond(request: httpx.Request) -> httpx.Response:
            """Serve only the expected Responses endpoint without network access.

            Args:
                request: Actual SDK request, including serialized tool results.

            Returns:
                httpx.Response: First tool stream or terminal answer stream.
            """
            assert request.url.path == "/v1/responses"
            requests.append(json.loads(request.content))
            assert len(requests) <= 3
            return httpx.Response(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                content=(
                    responses_frames(shape=shape) if len(requests) <= 2 else answer_frames(model_name="gpt-5")
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler=respond)) as client:
            model: BaseChatModel = SequencedChatOpenAI(
                model="gpt-5",
                api_key=SecretStr("offline"),
                streaming=True,
                use_responses_api=True,
                output_version=output_version,
                max_retries=0,
                http_async_client=client,
            )
            chunks: list[AIMessageChunk] = []
            async for chunk in model.astream(input="Use echo"):
                assert isinstance(chunk, AIMessageChunk)
                chunks.append(chunk)
            assert any(chunk.tool_call_chunks for chunk in chunks)
            if output_version == "responses/v1":
                assert any(chunk.tool_call_chunks and chunk.content for chunk in chunks)
            for chunk in chunks:
                assert_content_tool_chunks_agree(chunk=chunk)
            host: FakeHost = FakeHost()
            projector: TranscriptProjectionAdapter = TranscriptProjectionAdapter(host=host)
            agent: SloAgent = SloAgent(llm=model, tools=[echo], cwd=str(tmp_path), system_prompt="Use tools.")
            events: list[AgentStreamEventDAO] = []
            async for event in agent.invoke(query="Use echo"):
                events.append(event)
                await projector.handle(event=event)

        count: int = 2 if shape == "parallel" else 1
        expected_ids: list[str] = (
            ["call_89"] if shape == "single" else [f"call107_{slot}" for slot in range(count)]
        )
        expected_output: str = "empty" if shape == "empty" else "echo-89"
        assert_tool_lifecycle(events=events, expected_ids=expected_ids)
        assert executions == [expected_output] * count
        assert host.mount_order.count("tool") == count
        assert list(host.tool_blocks) == expected_ids
        assert [block.result_output for block in host.tool_blocks.values()] == [expected_output] * count
        assert Counter(
            event.tool_call_id for event in events if event.kind == "tool_result"
        ) == dict.fromkeys(expected_ids, 1)
        assert Counter(
            event.tool_call_id for event in events if event.kind == "tool_call_end"
        ) == dict.fromkeys(expected_ids, 1)
        assert events[-1].kind == "run_completed"
        assert "complete-89" in (events[-1].content or "")
        outbound = requests[-1]["input"]
        assert isinstance(outbound, list)
        assert [
            block["call_id"] for block in outbound if block.get("type") == "function_call_output"
        ] == expected_ids


def assert_tool_lifecycle(*, events: list[AgentStreamEventDAO], expected_ids: list[str]) -> None:
    """Assert A18's exactly-once request/result lifecycle through the real graph.

    Starts must precede deltas and ends, ends must precede results, and finished
    ids remain terminal for this invocation. Called after the graph is drained.

    Args:
        events: Ordered events emitted by the production SloAgent invocation.
        expected_ids: Original provider call ids, not generated display ids.

    Raises:
        AssertionError: Any call is missing, duplicated or updated after its result.
    """
    for call_id in expected_ids:
        call_events: list[AgentStreamEventDAO] = [event for event in events if event.tool_call_id == call_id]
        kinds: list[str] = [event.kind for event in call_events]
        assert kinds.count("tool_call_start") == 1
        assert kinds.count("tool_call_end") == 1
        assert kinds.count("tool_result") == 1
        assert kinds[0] == "tool_call_start"
        assert kinds[-1] == "tool_result"
        assert kinds.index("tool_call_end") < kinds.index("tool_result")


def assert_content_tool_chunks_agree(*, chunk: AIMessageChunk) -> None:
    """Reject a gate2 counterexample in an actual adapter-produced chunk.

    Args:
        chunk: Unmodified public model-stream chunk before normalizer absorption.

    Raises:
        AssertionError: Nonempty tool chunks omit or contradict a local content call.
    """
    if not chunk.tool_call_chunks or not isinstance(chunk.content, list):
        return
    for block in chunk.content:
        if not isinstance(block, dict) or block.get("type") not in {
            "function_call",
            "tool_use",
            "input_json_delta",
            "tool_call_chunk",
        }:
            continue
        content_index: object = block.get("index")
        fragments = [
            fragment for fragment in chunk.tool_call_chunks if fragment.get("index") == content_index
        ]
        assert len(fragments) == 1, f"gate2 missing local call: {chunk!r}"
        fragment = fragments[0]
        call_id: object = block.get("call_id") if block["type"] == "function_call" else block.get("id")
        if call_id:
            assert fragment.get("id") == call_id, f"gate2 identity mismatch: {chunk!r}"
        if block.get("name"):
            assert fragment.get("name") == block["name"], f"gate2 name mismatch: {chunk!r}"
        arguments: object = block.get("arguments", block.get("args", block.get("partial_json", "")))
        if block["type"] == "tool_use":
            tool_input: object = block.get("input")
            arguments = json.dumps(tool_input) if tool_input else ""
        assert (fragment.get("args") or "") == arguments, f"gate2 argument mismatch: {chunk!r}"


class TestClaudeCodeCanonicalNames:
    """Resolve bound names at public streaming and assembled-message boundaries."""

    @pytest.mark.parametrize("mode", ["stream", "astream", "invoke", "ainvoke"])
    @pytest.mark.parametrize(
        "bound_names,wire_name,expected_name",
        [
            (["read"], "Read", "read"),
            (["Read"], "read", "Read"),
            (["read", "Read"], "Read", "Read"),
            (["read", "Read"], "READ", "READ"),
            (["customAlias"], "CUSTOMALIAS", "customAlias"),
            (["customAlias"], "unknown", "unknown"),
            ([], "Read", "read"),
        ],
        ids=["canonical", "bound-spelling", "exact", "ambiguous", "alias", "unknown", "unbound"],
    )
    async def test_preserves_bound_identity_when_wire_names_need_resolution(
        self, *, mode: str, bound_names: list[str], wire_name: str, expected_name: str
    ) -> None:
        """Use real SDK decoding and LangChain aggregation without provider traffic.

        Args:
            mode: Public sync/async streaming or assembled invocation.
            bound_names: Original registry spellings forwarded by RunnableBinding.
            wire_name: Synthetic provider name.
            expected_name: Safe resolved spelling, or unchanged ambiguous name.
        """

        def respond(transport: httpx.HTTPTransport | None, request: httpx.Request) -> httpx.Response:
            """Serve a synthetic SSE response at the vendor HTTP boundary.

            Args:
                transport: Unused vendor transport.
                request: Vendor request, constrained to the expected endpoint.

            Returns:
                httpx.Response: An empty-argument tool call with its original ID.
            """
            del transport
            assert request.url.host == "api.anthropic.com" and request.url.path == "/v1/messages"
            return httpx.Response(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                content=anthropic_frames(tool_name=wire_name, shape="empty"),
            )

        async def arespond(transport: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
            """Serve the same external fixture to the asynchronous SDK.

            Args:
                transport: Unused vendor transport.
                request: Vendor request for the expected endpoint.

            Returns:
                httpx.Response: The shared synthetic SSE response.
            """
            del transport
            return respond(transport=None, request=request)

        model: BaseChatModel = build_claude_code_backed_chat_anthropic(
            model_name="claude-sonnet-4-6",
            cred=CredentialDAO(
                provider=ProviderName.ANTHROPIC, auth_type=AuthType.OAUTH, access_token="offline107"
            ),
            max_retries=0,
        )
        bound = model.bind_tools(
            tools=[
                {"name": name, "description": "Synthetic tool", "input_schema": {"type": "object"}}
                for name in bound_names
            ]
        )
        with (
            patch.object(httpx.HTTPTransport, "handle_request", new=respond),
            patch.object(httpx.AsyncHTTPTransport, "handle_async_request", new=arespond),
        ):
            messages: list[BaseMessage] = []
            if mode == "stream":
                messages = list(bound.stream(input="Read"))
            elif mode == "astream":
                messages = [chunk async for chunk in bound.astream(input="Read")]
            elif mode == "invoke":
                messages = [bound.invoke(input="Read")]
            else:
                messages = [await bound.ainvoke(input="Read")]
        completed: BaseMessage = messages[0]
        if isinstance(completed, AIMessageChunk):
            for message in messages[1:]:
                assert isinstance(message, AIMessageChunk)
                completed = completed + message
        assert isinstance(completed, AIMessage)
        calls = completed.tool_calls
        assert calls == [{"name": expected_name, "args": {}, "id": "toolu107_0", "type": "tool_call"}]
        blocks = [
            block
            for message in messages
            if isinstance(message.content, list)
            for block in message.content
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]
        assert [block["name"] for block in blocks] == [expected_name]
        for message in messages:
            if isinstance(message, AIMessageChunk):
                assert_content_tool_chunks_agree(chunk=message)
        fragments = [
            fragment
            for message in messages
            if isinstance(message, AIMessageChunk)
            for fragment in message.tool_call_chunks
            if fragment.get("name")
        ]
        if mode in {"stream", "astream"}:
            assert [fragment["name"] for fragment in fragments] == [expected_name]
            assert fragments[0]["index"] == 0
            assert fragments[0]["id"] == "toolu107_0"


class TestClaudeCodeDecodedPayloadPreservation:
    """Exercise real JSON/SSE decoding without changing opaque call fields."""

    @pytest.mark.parametrize("mode", ["invoke", "ainvoke"])
    @pytest.mark.parametrize(
        "bound_names,wire_names,expected_names",
        [
            (["read", "customAlias"], ["Read", "CUSTOMALIAS"], ["read", "customAlias"]),
            (["read", "Read"], ["Read", "READ"], ["Read", "READ"]),
            (["customAlias"], ["unknown", "Read"], ["unknown", "read"]),
        ],
        ids=["unique-and-alias", "exact-and-ambiguous", "unknown-and-retained-alias"],
    )
    async def test_preserves_json_response_when_nonstream_names_are_resolved(
        self, *, mode: str, bound_names: list[str], wire_names: list[str], expected_names: list[str]
    ) -> None:
        """OEF-01: public nonstream calls preserve mixed content, args and metadata.

        Args:
            mode: Public synchronous or asynchronous invocation.
            bound_names: Original tool registry spellings.
            wire_names: Two provider tool names in response order.
            expected_names: Safely resolved names in the same order.
        """
        arguments: list[dict[str, object]] = [{"path": "a/β.py", "nested": [True, 2, None]}, {}]
        blocks: list[dict[str, object]] = [
            {"type": "text", "text": "before", "citations": []},
            {"type": "tool_use", "id": "functions.read:0", "name": wire_names[0], "input": arguments[0]},
            {"type": "text", "text": "between", "citations": []},
            {"type": "tool_use", "id": "opaque:β/second", "name": wire_names[1], "input": arguments[1]},
        ]
        requests: list[dict[str, object]] = []

        def respond(transport: httpx.HTTPTransport | None, request: httpx.Request) -> httpx.Response:
            """Return genuine message JSON, refusing any streaming request.

            Args:
                transport: Unused external HTTP transport.
                request: SDK message request.

            Returns:
                httpx.Response: Synthetic nonstream Anthropic message.
            """
            del transport
            assert request.url.host == "api.anthropic.com" and request.url.path == "/v1/messages"
            payload: dict[str, object] = json.loads(request.content)
            assert payload.get("stream", False) is False
            requests.append(payload)
            return httpx.Response(
                status_code=200,
                json={
                    "id": "msg-json107",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                    "content": blocks,
                    "stop_reason": "tool_use",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 13, "output_tokens": 7},
                },
            )

        async def arespond(transport: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
            """Serve the JSON fixture at the asynchronous vendor boundary."""
            del transport
            return respond(transport=None, request=request)

        model = build_claude_code_backed_chat_anthropic(
            model_name="claude-sonnet-4-6",
            cred=CredentialDAO(
                provider=ProviderName.ANTHROPIC, auth_type=AuthType.OAUTH, access_token="offline107"
            ),
            streaming=False,
            max_retries=0,
        )
        bound = model.bind_tools(
            tools=[
                {"name": name, "description": "Synthetic tool", "input_schema": {"type": "object"}}
                for name in bound_names
            ]
        )
        with (
            patch.object(httpx.HTTPTransport, "handle_request", new=respond),
            patch.object(httpx.AsyncHTTPTransport, "handle_async_request", new=arespond),
        ):
            message = bound.invoke(input="Read") if mode == "invoke" else await bound.ainvoke(input="Read")
        assert len(requests) == 1
        assert isinstance(message, AIMessage)
        assert message.tool_calls == [
            {"name": expected_names[0], "args": arguments[0], "id": "functions.read:0", "type": "tool_call"},
            {"name": expected_names[1], "args": arguments[1], "id": "opaque:β/second", "type": "tool_call"},
        ]
        assert message.content == [
            blocks[0],
            {**blocks[1], "name": expected_names[0], "caller": None},
            blocks[2],
            {**blocks[3], "name": expected_names[1], "caller": None},
        ]
        assert message.invalid_tool_calls == []
        assert message.usage_metadata == {
            "input_tokens": 13,
            "output_tokens": 7,
            "total_tokens": 20,
            "input_token_details": {},
        }
        assert message.response_metadata["id"] == "msg-json107"
        assert message.response_metadata["model_name"] == "claude-sonnet-4-6"
        assert message.response_metadata["stop_reason"] == "tool_use"
        assert message.response_metadata["stop_sequence"] is None

    @pytest.mark.parametrize("mode", ["stream", "astream"])
    @pytest.mark.parametrize("malformed", [False, True], ids=["valid", "invalid-json"])
    async def test_preserves_fragments_when_names_are_absent_on_argument_deltas(
        self, *, mode: str, malformed: bool
    ) -> None:
        """OEF-02: no invented name/ID, unchanged slots, JSON text, order and usage.

        Args:
            mode: Public synchronous or asynchronous stream.
            malformed: Emit representable invalid JSON instead of an object.
        """
        pieces: list[str] = ['{"path":', '"a/β.py","nested":[true,2,null]}']
        if malformed:
            pieces = ["not-json", "!"]
        frames: list[dict[str, object]] = [
            {
                "type": "message_start",
                "message": {
                    "id": "msg-stream107",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 13, "output_tokens": 0},
                },
            },
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "before"}},
            {"type": "content_block_stop", "index": 0},
        ]
        for slot, call_id in [(2, "functions.read:0"), (5, "opaque:β/second")]:
            frames.append(
                {
                    "type": "content_block_start",
                    "index": slot,
                    "content_block": {
                        "type": "tool_use",
                        "id": call_id,
                        "name": "Read",
                        "input": {},
                    },
                }
            )
            for piece in pieces:
                frames.append(
                    {
                        "type": "content_block_delta",
                        "index": slot,
                        "delta": {"type": "input_json_delta", "partial_json": piece},
                    }
                )
            frames.append({"type": "content_block_stop", "index": slot})
        frames.extend(
            [
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                    "usage": {"input_tokens": 13, "output_tokens": 7},
                },
                {"type": "message_stop"},
            ]
        )
        wire: bytes = "".join(
            f"event: {frame['type']}\ndata: {json.dumps(frame)}\n\n" for frame in frames
        ).encode()

        def respond(transport: httpx.HTTPTransport | None, request: httpx.Request) -> httpx.Response:
            """Serve supported Anthropic events through real SDK decoding."""
            del transport
            assert request.url.host == "api.anthropic.com" and request.url.path == "/v1/messages"
            assert json.loads(request.content)["stream"] is True
            return httpx.Response(
                status_code=200, headers={"content-type": "text/event-stream"}, content=wire
            )

        async def arespond(transport: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
            """Serve the identical wire sequence asynchronously."""
            del transport
            return respond(transport=None, request=request)

        model = build_claude_code_backed_chat_anthropic(
            model_name="claude-sonnet-4-6",
            cred=CredentialDAO(
                provider=ProviderName.ANTHROPIC, auth_type=AuthType.OAUTH, access_token="offline107"
            ),
            max_retries=0,
        )
        bound = model.bind_tools(
            tools=[{"name": "read", "description": "Synthetic tool", "input_schema": {"type": "object"}}]
        )
        with (
            patch.object(httpx.HTTPTransport, "handle_request", new=respond),
            patch.object(httpx.AsyncHTTPTransport, "handle_async_request", new=arespond),
        ):
            chunks = (
                list(bound.stream(input="Read"))
                if mode == "stream"
                else [chunk async for chunk in bound.astream(input="Read")]
            )
        decoded_chunks: list[AIMessageChunk] = []
        for chunk in chunks:
            assert isinstance(chunk, AIMessageChunk)
            decoded_chunks.append(chunk)
        fragments = [fragment for chunk in decoded_chunks for fragment in chunk.tool_call_chunks]
        assert fragments == [
            fragment
            for slot, call_id in [(2, "functions.read:0"), (5, "opaque:β/second")]
            for fragment in [
                {"name": "read", "args": "", "id": call_id, "index": slot, "type": "tool_call_chunk"},
                *[
                    {"name": None, "args": piece, "id": None, "index": slot, "type": "tool_call_chunk"}
                    for piece in pieces
                ],
            ]
        ]
        content = [
            block for chunk in decoded_chunks if isinstance(chunk.content, list) for block in chunk.content
        ]
        assert content == [
            {"type": "text", "text": "before", "index": 0},
            *[
                block
                for slot, call_id in [(2, "functions.read:0"), (5, "opaque:β/second")]
                for block in [
                    {
                        "type": "tool_use",
                        "id": call_id,
                        "name": "read",
                        "input": {},
                        "caller": None,
                        "index": slot,
                    },
                    *[{"type": "input_json_delta", "partial_json": piece, "index": slot} for piece in pieces],
                ]
            ],
        ]
        for chunk in decoded_chunks:
            assert_content_tool_chunks_agree(chunk=chunk)
        completed: AIMessageChunk = decoded_chunks[0]
        for chunk in decoded_chunks[1:]:
            merged_chunk = completed + chunk
            assert isinstance(merged_chunk, AIMessageChunk)
            completed = merged_chunk
        assert completed.response_metadata == {
            "model_name": "claude-sonnet-4-6",
            "stop_reason": "tool_use",
            "stop_sequence": None,
        }
        assert completed.usage_metadata == {
            "input_tokens": 13,
            "output_tokens": 7,
            "total_tokens": 20,
            "input_token_details": {},
        }
        if malformed:
            assert completed.tool_calls == []
            assert completed.invalid_tool_calls == [
                {
                    "name": "read",
                    "args": "".join(pieces),
                    "id": call_id,
                    "error": None,
                    "type": "invalid_tool_call",
                }
                for call_id in ["functions.read:0", "opaque:β/second"]
            ]
        else:
            assert completed.invalid_tool_calls == []
            assert completed.tool_calls == [
                {
                    "name": "read",
                    "args": {"path": "a/β.py", "nested": [True, 2, None]},
                    "id": call_id,
                    "type": "tool_call",
                }
                for call_id in ["functions.read:0", "opaque:β/second"]
            ]
