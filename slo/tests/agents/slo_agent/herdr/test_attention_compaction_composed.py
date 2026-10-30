"""Persisted manual-compaction attention through the real session pipeline."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.herdr.dao import HerdrPublicationDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.agents.slo_agent.test_session_manual_compaction import _viable_events


@pytest.mark.parametrize("outcome", ["failure", "cancel", "busy"])
async def test_persisted_manual_attention(tmp_path: Path, outcome: str) -> None:
    """Real history survives refusal/cancellation; only a failure persists an audit."""
    assert tmp_path.resolve() == tmp_path and not tmp_path.is_symlink()
    session_id = "11111111-1111-4111-8111-111111111111"
    store = FilesystemSessionHistoryStore(root=tmp_path)
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    for event in _viable_events():
        await store.append_event(event=event.model_copy(update={"session_id": session_id}))
    agent = SloAgent(llm=FauxChatModel(responses=[AIMessage(content="summary")]), tools=[], cwd=str(tmp_path))
    session = SloAgentSession(
        agent=agent, workdir=tmp_path, session_id=session_id, history_store=store, enable_history=True
    )
    before = await store.load_events(session_id=session_id)
    states: list[str] = []
    session._herdr_reporting_started = True
    original_usage = session.refresh_usage_snapshot

    def observe_usage() -> None:
        """Spy on the shared owner without introducing alternate accounting."""
        assert session._reporting_state().state == "working"
        states.append("usage")
        original_usage()

    def observe_publication(*, publication: HerdrPublicationDAO) -> None:
        """Capture ordering at the real reporter handoff, without spawning Herdr."""
        states.append(publication.snapshot.state)

    error = asyncio.CancelledError() if outcome == "cancel" else RuntimeError("summary failed")
    with (
        patch.object(FauxChatModel, "ainvoke", side_effect=error) as summary,
        patch.object(session, "refresh_usage_snapshot", side_effect=observe_usage) as usage,
        patch.object(session._herdr_reporter, "publish", side_effect=observe_publication),
    ):
        if outcome == "busy":
            async with session._lock:
                result = await session.compact_context()
            assert result.status == "unavailable"
            summary.assert_not_called()
            usage.assert_not_called()
        elif outcome == "cancel":
            with pytest.raises(asyncio.CancelledError) as caught:
                await session.compact_context()
            assert caught.value is error
        else:
            assert (await session.compact_context()).status == "failed"
        if outcome != "busy":
            summary.assert_called_once()
            assert usage.called
    after = await store.load_events(session_id=session_id)
    assert after[: len(before)] == before
    assert [event.kind for event in after[len(before) :]] == (["run_failed"] if outcome == "failure" else [])
    assert session._reporting_state().state == ("blocked" if outcome == "failure" else "idle")
    assert not session._reporting_operations and not session._lock.locked()
    if outcome == "busy":
        assert states == [] and session._operation_serial == 0
    else:
        assert session._operation_serial == 1
        assert states[-1] == ("blocked" if outcome == "failure" else "idle")
        assert "usage" in states[:-1]
        assert set(states[:-1]) <= {"working", "usage"}
