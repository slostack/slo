"""Real capacity and manual summary transaction acceptance for direct GPT-6."""

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.agents.base import LLMFactory
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.compaction.constants import RESERVED_TOKEN_LIMIT
from src.agents.slo_agent.compaction.context_window import ContextWindowSnapshotService
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore
from tests.agents.providers.feature89_responses import answer_frames
from tests.agents.slo_agent.test_session_manual_compaction import _viable_events
from tests.integration.test_openrouter_full_flow import isolated_catalog


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol"])
@pytest.mark.parametrize("oauth", [False, True])
async def test_gpt6_summary_uses_reserved_cap_and_total_context(
    isolated_catalog: CredentialStore, tmp_path: Path, model_name: str, oauth: bool
) -> None:
    """Compact actual history once using real Platform SDK and verify its wire cap."""
    root = tmp_path.resolve()
    assert isolated_catalog.path.resolve().is_relative_to(root)
    isolated_catalog.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="fixture-capacity89"
        )
    )
    if oauth:
        from tests.agents.providers.test_openai_codex import _build_jwt, _oauth_cred

        token = _build_jwt(
            claims={"https://api.openai.com/auth": {"chatgpt_account_id": "fixture-summary89"}}
        )
        isolated_catalog.persist(cred=_oauth_cred(access_token=token))
    store = FilesystemSessionHistoryStore(root=root)
    await store.ensure_session(session_id="session", workdir=root, model_name=model_name)
    for event in _viable_events():
        await store.append_event(event=event)
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Return one complete synthetic summary stream to the owning compacter."""
        requests.append(request)
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=answer_frames(model_name=model_name),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        chat = LLMFactory.create(model_name=model_name, reasoning_level="off", http_async_client=client).llm
        session = SloAgentSession(
            agent=SloAgent(llm=chat, model_name=model_name, cwd=str(root), tools=[]),
            workdir=root,
            session_id="session",
            history_store=store,
            enable_history=True,
        )
        with patch.object(store, "compact_to_boundary", wraps=store.compact_to_boundary) as transaction:
            result = await session.compact_context()
        assert result.status == "compacted"
        transaction.assert_awaited_once()
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert str(requests[0].url) == (
        "https://chatgpt.com/backend-api/codex/responses" if oauth else "https://api.openai.com/v1/responses"
    )
    if oauth:
        assert not {"max_tokens", "max_completion_tokens", "max_output_tokens"}.intersection(body)
        assert body["instructions"]
    else:
        assert body["max_output_tokens"] == RESERVED_TOKEN_LIMIT != 128000
        assert "instructions" not in body
    events = await store.load_events(session_id="session")
    assert [event.payload.content for event in events if event.kind == "compaction_summary"] == [
        "complete-89"
    ]
    capacity = ContextWindowSnapshotService.build(events=events, model_name=model_name)
    assert capacity.context_window_tokens == 1050000
    assert capacity.available_tokens == 1050000 - capacity.estimated_used_tokens


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol"])
async def test_gpt6_large_estimate_is_advisory(
    isolated_catalog: CredentialStore, tmp_path: Path, model_name: str
) -> None:
    """An actual 500001-token estimate crosses the hint but still invokes the Faux graph."""
    from langchain_core.messages import AIMessage
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.sessions.service import _RATE_LIMIT_OUTPUT_ESTIMATE_TOKENS

    root = tmp_path.resolve()
    session = SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(responses=[AIMessage(content="admitted89")]),
            model_name=model_name,
            cwd=str(root),
            tools=[],
        ),
        config=SessionConfigDAO(workdir=root, model_name=model_name, enable_history=False),
        workdir=root,
        session_id="advisory89",
        enable_history=False,
    )
    text = "x" * ((500001 - _RATE_LIMIT_OUTPUT_ESTIMATE_TOKENS) * 4)
    assert session._estimated_request_tokens(text=text) == 500001
    events = [event async for event in session.invoke(text=text)]
    assert [event.content for event in events if event.kind == "run_completed"] == ["admitted89"]
    bypasses = [event for event in events if event.kind == "preflight_bypassed"]
    assert len(bypasses) == 1
    assert bypasses[0].metadata["estimated_tokens"] == 500001
    assert not any(event.kind in {"run_failed", "run_retrying"} for event in events)
