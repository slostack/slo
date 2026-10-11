"""Real session/agent/SDK commit barriers with synthetic in-memory SSE."""

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import patch

import httpx
import pytest
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from src.agents.base import LLMFactory
from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from tests.agents.providers.test_openrouter_transport import _prepared_snapshot, _OPENROUTER_MODEL_NAME


class FragmentStream(httpx.AsyncByteStream):
    """Pause after SDK consumption of a fragment, then fail or await cancellation."""

    def __init__(self, *, frame: dict[str, object], release: asyncio.Event) -> None:
        """Retain a synthetic frame and the test-owned failure barrier."""
        self.frame = frame
        self.release = release
        self.consumed = asyncio.Event()
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        """Yield one fragment before the barrier-controlled gateway failure."""
        yield f"data: {json.dumps(self.frame)}\n\n".encode()
        self.consumed.set()
        await self.release.wait()
        yield b'data: {"error":{"code":503,"message":"synthetic-private-error"}}\n\n'

    async def aclose(self) -> None:
        """Record SDK stream cleanup without external resources."""
        self.closed = True


FRAMES: list[dict[str, object]] = [
    {"choices": [{"index": 0, "delta": {"role": "assistant"}}]},
    {"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}},
    {"choices": [{"index": 0, "delta": {"content": "committed"}}]},
    {"choices": [{"index": 0, "delta": {"reasoning": "visible reasoning"}}]},
    {
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call-partial",
                            "type": "function",
                            "function": {"name": "echo", "arguments": "{"},
                        }
                    ]
                },
            }
        ]
    },
]


@pytest.mark.parametrize("frame", FRAMES, ids=["role", "usage", "text", "reasoning", "tool"])
@pytest.mark.parametrize("cancel", [False, True], ids=["failure", "cancel"])
async def test_session_committed_fragment_never_requests_again(
    tmp_path: Path, frame: dict[str, object], cancel: bool
) -> None:
    """Exercise actual retry/recovery/continuation owners, not policy helpers."""
    release = asyncio.Event()
    stream = FragmentStream(frame=frame, release=release)
    requests: list[str] = []
    events: list[AgentStreamEventDAO] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Count every inference lane and trip immediately on any extra attempt."""
        requests.append(str(request.url))
        assert len(requests) == 1, "postcommit retry, continuation or fallback"
        return httpx.Response(status_code=200, headers={"content-type": "text/event-stream"}, stream=stream)

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with patch("src.agents.base.CredentialResolver.require", return_value=credential):
            model = LLMFactory.create(
                model_name=_OPENROUTER_MODEL_NAME, snapshot=_prepared_snapshot(), http_async_client=client
            ).llm
        direct = ChatOpenAI(
            model="gpt-5.4",
            api_key=SecretStr("fixture"),
            max_retries=0,
            base_url="https://direct.invalid/v1",
            http_async_client=client,
        )
        pool = ModelPool(
            pool_dao=ModelPoolDAO(
                entries=[
                    ModelPoolEntryDAO(
                        model_name=_OPENROUTER_MODEL_NAME, provider=ProviderName.OPENROUTER, priority=0
                    ),
                    ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=1),
                ]
            ),
            models={_OPENROUTER_MODEL_NAME: model, "gpt-5.4": direct},
        )
        session = SloAgentSession(
            agent=SloAgent(llm=pool, tools=[], cwd=str(tmp_path), system_prompt="Answer."),
            workdir=tmp_path,
            session_id="commit-session",
            enable_history=False,
            catalog_snapshot=_prepared_snapshot(),
        )

        async def consume() -> None:
            """Drive the real session to its terminal outcome."""
            async for event in session.invoke(text="hello"):
                events.append(event)

        task = asyncio.create_task(consume())
        await asyncio.wait_for(stream.consumed.wait(), timeout=5)
        if cancel:
            task.cancel()
        else:
            release.set()
        outcomes = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=5)
        if cancel:
            # The session intentionally translates task cancellation to run_aborted.
            assert outcomes == [None]
            assert "run_aborted" in [event.kind for event in events]
        assert requests == ["https://openrouter.ai/api/v1/chat/completions"]
        assert stream.closed
        assert pool.active_model_name == _OPENROUTER_MODEL_NAME
        assert pool.drain_route_switch_log() == []
        assert not {"run_retrying", "recovery_started", "stream_reconnecting"}.intersection(
            event.kind for event in events
        )
        if not cancel:
            assert "run_failed" in [event.kind for event in events]
        assert "synthetic-private-error" not in "".join(event.model_dump_json() for event in events)
