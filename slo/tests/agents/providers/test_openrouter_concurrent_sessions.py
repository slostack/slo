"""Concurrent real sessions share an adapter, never a continuation accumulator."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import httpx

from src.agents.base import LLMFactory
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from tests.agents.providers.test_openrouter_session_commit import FragmentStream
from tests.agents.providers.test_openrouter_transport import _prepared_snapshot, _OPENROUTER_MODEL_NAME
from tests.agents.providers.test_openrouter_fragments import _sse


async def test_cancelled_session_does_not_poison_concurrent_private_anchor(tmp_path: Path) -> None:
    """Cancel an overlapping real run while its sibling completes and persists its own anchor."""
    release = asyncio.Event()
    blocked = FragmentStream(
        frame={
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "reasoning_details": [{"type": "encrypted", "data": "cancelled-private"}],
                        "content": "partial",
                    },
                }
            ]
        },
        release=release,
    )
    sibling_entered = asyncio.Event()
    sibling_release = asyncio.Event()
    requests: list[str] = []
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())

    async def respond(request: httpx.Request) -> httpx.Response:
        """Hold both invocations inside the shared adapter before cancelling one."""
        body = json.loads(request.content)
        prompt = body["messages"][-1]["content"]
        requests.append(prompt)
        assert len(requests) <= 2, "unexpected retry or continuation"
        if prompt == "cancel":
            return httpx.Response(
                status_code=200, headers={"content-type": "text/event-stream"}, stream=blocked
            )
        sibling_entered.set()
        await sibling_release.wait()
        return _sse(
            [
                {
                    "content": "sibling complete",
                    "reasoning_details": [{"type": "encrypted", "data": "sibling-private"}],
                }
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
        store = FilesystemSessionHistoryStore(root=root)
        sessions = [
            SloAgentSession(
                agent=SloAgent(llm=model, tools=[], cwd=str(tmp_path), system_prompt="Answer."),
                workdir=tmp_path,
                session_id=name,
                history_store=store,
                enable_history=True,
                catalog_snapshot=_prepared_snapshot(),
            )
            for name in ("cancel", "sibling")
        ]

        async def consume(session: SloAgentSession, prompt: str) -> list[AgentStreamEventDAO]:
            """Drive a session with its own run and persistence state."""
            return [event async for event in session.invoke(text=prompt)]

        cancelled = asyncio.create_task(consume(session=sessions[0], prompt="cancel"))
        await asyncio.wait_for(blocked.consumed.wait(), timeout=5)
        sibling = asyncio.create_task(consume(session=sessions[1], prompt="sibling"))
        await asyncio.wait_for(sibling_entered.wait(), timeout=5)
        cancelled.cancel()
        await asyncio.wait_for(asyncio.gather(cancelled, return_exceptions=True), timeout=5)
        assert blocked.closed
        sibling_release.set()
        events = await asyncio.wait_for(sibling, timeout=5)
        assert events[-1].kind == "run_completed"
        assert requests == ["cancel", "sibling"]
        assert "private" not in "".join(event.model_dump_json() for event in events)
        persisted = await store.load_events(session_id="sibling")
        anchors = [
            event.payload.provider_message_extension
            for event in persisted
            if event.payload.provider_message_extension is not None
        ]
        assert len(anchors) == 1
        assert anchors[0].reasoning_details == [{"type": "encrypted", "data": "sibling-private"}]
