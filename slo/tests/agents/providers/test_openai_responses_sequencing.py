"""Regression journeys through real OpenAI clients and synthetic provider SSE."""

import json
from typing import Literal, cast

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr
from src.agents.providers.openai_responses_sequencing import SequencedChatOpenAI

from src.agents.base import LLMFactory
from src.agents.providers.openai_codex import build_chatgpt_backed_chat_openai
from tests.agents.providers.feature89_responses import answer_frames, encode_frames, response_envelope
from tests.agents.providers.test_openai_codex import _build_jwt, _oauth_cred
from tests.auth.test_credential_resolver import _reload_cfg


def call_frames(*, order: Literal["sequential", "interleaved", "done-only"]) -> list[dict[str, object]]:
    """Build two function calls with the same fragments in different arrival orders.

    Args:
        order: Whether arguments follow their opening or interleave across calls.

    Returns:
        Provider events including authoritative completed calls and token usage.
    """
    starts = [
        {"type": "function_call", "id": "fc_a", "call_id": "call_a", "name": "read", "arguments": ""},
        {"type": "function_call", "id": "fc_b", "call_id": "call_b", "name": "find", "arguments": ""},
    ]
    arguments = ['{"path":"x.py"}', '{"pattern":"*.py"}']
    added = [
        {"type": "response.output_item.added", "output_index": i, "item": s} for i, s in enumerate(starts)
    ]
    deltas = [
        [
            {
                "type": "response.function_call_arguments.delta",
                "output_index": i,
                "item_id": s["id"],
                "delta": part,
            }
            for part in (arguments[i][:8], arguments[i][8:])
        ]
        for i, s in enumerate(starts)
    ]
    done: list[dict[str, object]] = [
        {**s, "arguments": arguments[i], "status": "completed"} for i, s in enumerate(starts)
    ]
    bodies = {
        "sequential": [added[0], *deltas[0], added[1], *deltas[1]],
        "interleaved": [*added, deltas[0][0], deltas[1][0], deltas[0][1], deltas[1][1]],
        "done-only": added,
    }
    return [
        {
            "type": "response.created",
            "response": response_envelope(model_name="gpt-5", output=[], completed=False),
        },
        *bodies[order],
        *[
            {"type": "response.output_item.done", "output_index": i, "item": item}
            for i, item in enumerate(done)
        ],
        {
            "type": "response.completed",
            "response": response_envelope(model_name="gpt-5", output=done, completed=True),
        },
    ]


@pytest.mark.parametrize("lane", ["codex", "platform", "legacy"])
@pytest.mark.parametrize("order", ["sequential", "interleaved", "done-only"])
async def test_calls_keep_arguments_and_replay_when_streams_interleave(
    lane: str, order: Literal["sequential", "interleaved", "done-only"], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Factory clients keep both call arguments through aggregation and next-turn replay."""
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Return only in-memory SSE; record the actual subsequent request."""
        requests.append(json.loads(request.content))
        body = (
            encode_frames(frames=call_frames(order=order))
            if len(requests) == 1
            else answer_frames(model_name="gpt-5")
        )
        return httpx.Response(status_code=200, headers={"content-type": "text/event-stream"}, content=body)

    monkeypatch.setenv(name="SLO_OPENAI_API_KEY", value="offline-sequencing")
    _reload_cfg()
    chat: BaseChatModel
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        if lane == "codex":
            token = _build_jwt(
                claims={"https://api.openai.com/auth": {"chatgpt_account_id": "offline-account"}}
            )
            chat = build_chatgpt_backed_chat_openai(
                model_name="gpt-5",
                cred=_oauth_cred(access_token=token),
                session_id="sequencing",
                http_async_client=client,
            )
        else:
            chat = LLMFactory.create(
                model_name="gpt-6-luna" if lane == "platform" else "gpt-5.6-sol",
                reasoning_level="medium",
                streaming=True,
                http_async_client=client,
            ).llm
        answer = await chat.ainvoke(input=[HumanMessage(content="Read and find")])
        assert isinstance(answer, AIMessage)
        assert [(c["name"], c["id"], c["args"]) for c in answer.tool_calls] == [
            ("read", "call_a", {"path": "x.py"}),
            ("find", "call_b", {"pattern": "*.py"}),
        ]
        assert not answer.invalid_tool_calls
        assert answer.usage_metadata is not None
        assert answer.usage_metadata["total_tokens"] == 14
        followup = await chat.ainvoke(
            input=[
                HumanMessage(content="Read and find"),
                answer,
                ToolMessage(content="file", tool_call_id="call_a"),
                ToolMessage(content="matches", tool_call_id="call_b"),
            ]
        )
    assert "complete-89" in str(followup.content)
    replay = [
        item
        for item in cast(list[dict[str, str]], requests[1]["input"])
        if item.get("type") == "function_call"
    ]
    assert [(item["name"], item["call_id"], json.loads(item["arguments"])) for item in replay] == [
        ("read", "call_a", {"path": "x.py"}),
        ("find", "call_b", {"pattern": "*.py"}),
    ]


@pytest.mark.parametrize("output_version", ["v0", "responses/v1"])
async def test_headers_and_content_format_survive_sequencing(
    output_version: Literal["v0", "responses/v1"],
) -> None:
    """Optional SDK headers and legacy content shapes survive the workaround."""

    def respond(request: httpx.Request) -> httpx.Response:
        """Return a complete response with identifiable HTTP metadata."""
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream", "x-request-id": "offline-id"},
            content=encode_frames(frames=call_frames(order="interleaved")),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        chat = SequencedChatOpenAI(
            model="gpt-5",
            api_key=SecretStr("offline"),
            use_responses_api=True,
            streaming=True,
            output_version=output_version,
            include_response_headers=True,
            http_async_client=client,
        )
        answer = await chat.ainvoke(input="read and find")
    assert isinstance(answer, AIMessage)
    assert answer.response_metadata["headers"]["x-request-id"] == "offline-id"
    assert [call["args"] for call in answer.tool_calls] == [{"path": "x.py"}, {"pattern": "*.py"}]
    if output_version == "v0":
        assert answer.content == []
    else:
        assert len(answer.content) == 2
