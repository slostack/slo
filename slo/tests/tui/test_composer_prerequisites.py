"""Cutover prerequisite journeys through real admission and contained SQLite."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tests.tui.recording_prompt import RecordingPromptInput
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.messaging.dao import MessagingLimitsDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.cli.test_app import compose_default_tui
from src.tui.components.prompt_input.component import PromptInputComponent
from tests.agents.slo_agent.messaging.test_delivery import RealAgentFactory, RecordingModel
from tests.agents.slo_agent.messaging.test_queue_closure import CompletionGate
from tests.tui.test_durable_composer import _wait_until, _transcript_notices
from tests.integration.test_session_messaging import read_closed_message_rows


def gated_session(
    *, tmp_path: Path, model: RecordingModel, gate: CompletionGate, limits: MessagingLimitsDAO
) -> SloAgentSession:
    """Inject only worker timing and provider responses into the real session."""
    history = tmp_path / "history"
    assert history.resolve().is_relative_to(tmp_path.resolve())
    session_id = str(uuid4())
    return SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path,
            session_id=session_id,
            history_root=history,
            model_name="gpt-5.4",
            messaging_limits=limits,
        ),
        history_store=FilesystemSessionHistoryStore(root=history),
        messaging_executor_factory=lambda: gate,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )


@pytest.mark.parametrize(argnames="limit_code", argvalues=["sender_limit", "queue_full"])
@pytest.mark.parametrize(argnames="newer_typing", argvalues=[False, True])
async def test_real_sender_limit_preserves_or_restores_draft(
    tmp_path: Path, newer_typing: bool, limit_code: str
) -> None:
    """DC02 A2/A3: worker-held refusal keeps B recoverable or restores its untouched editor."""
    gate = CompletionGate(hold_before=True)
    model = RecordingModel(responses=[AIMessage(content="first"), AIMessage(content="pending")])
    session = gated_session(
        tmp_path=tmp_path,
        model=model,
        gate=gate,
        limits=(
            MessagingLimitsDAO(pending_per_sender=1)
            if limit_code == "sender_limit"
            else MessagingLimitsDAO(pending_inputs=1)
        ),
    )
    app = compose_default_tui(session=session)
    async with app.run_test() as pilot:
        try:
            await _wait_until(predicate=lambda: session.is_messaging_ready)
            prompt = app.query_one(RecordingPromptInput)
            prompt.load_text("first")
            await pilot.press("enter")
            await asyncio.wait_for(model.entered.wait(), timeout=3)
            prompt.load_text("pending")
            await pilot.press("enter")
            adapter = prompt._submission_adapter
            assert adapter is not None
            await _wait_until(
                predicate=lambda: prompt.text == "" and all(task.done() for task in adapter._tasks)
            )
            gate.armed = True
            prompt.load_text("B")
            await pilot.press("enter")
            await _wait_until(predicate=gate.started.is_set)
            assert prompt.text == ""
            if newer_typing:
                await pilot.press("C")
            gate.release.set()
            await _wait_until(predicate=lambda: len(prompt.outcomes) == 3)
            from src.agents.slo_agent.messaging.dao import MessageErrorDAO

            refusal = prompt.outcomes[-1].outcome
            assert isinstance(refusal, MessageErrorDAO) and refusal.code == limit_code
            assert prompt.text == ("C" if newer_typing else "B")
            if newer_typing:
                prompt.load_text("/messages drafts")
                await pilot.press("enter")
                await _wait_until(predicate=lambda: any("B" in line for line in _transcript_notices(app)))
                drafts = prompt.list_recoverable_drafts()
                assert len(drafts) == 1 and drafts[0].draft_submission.message_submission.text == "B"
            else:
                assert prompt.cursor_location == (0, 1)
                assert prompt.list_recoverable_drafts() == ()
            model.release.set()
            await _wait_until(predicate=lambda: len(model.requests) == 2 and not session.is_running)
            assert all(
                message.content != "B"
                for request in model.requests
                for message in request
                if isinstance(message, HumanMessage)
            )
        finally:
            gate.release.set()
            model.release.set()
    rows = read_closed_message_rows(
        database_path=tmp_path / "history" / session.session_id / "messaging.v1.sqlite3",
        temporary_root=tmp_path,
    )
    assert len(rows) == 2 and all(state == "applied" for _, _, state in rows)


async def test_real_unknown_outcome_retry_observes_single_committed_identity(tmp_path: Path) -> None:
    """DC02 A4: both deadlines expire before commit; slash retry reads the original ID."""
    gate = CompletionGate(hold_before=True)
    model = RecordingModel(responses=[AIMessage(content="once")])
    session = gated_session(
        tmp_path=tmp_path, model=model, gate=gate, limits=MessagingLimitsDAO(admission_seconds=0.05)
    )
    app = compose_default_tui(session=session)
    async with app.run_test() as pilot:
        try:
            await _wait_until(predicate=lambda: session.is_messaging_ready)
            prompt = app.query_one(RecordingPromptInput)
            gate.armed = True
            prompt.load_text("uncertain")
            await pilot.press("enter")
            await _wait_until(
                predicate=lambda: any("delivery uncertain" in line for line in _transcript_notices(app))
            )
            drafts = prompt.list_recoverable_drafts()
            assert len(drafts) == 1 and drafts[0].last_error_code == "unknown_outcome"
            message_id = drafts[0].draft_submission.message_submission.message_id
            gate.release.set()
            await asyncio.wait_for(model.entered.wait(), timeout=3)
            prompt.load_text(f"/messages retry {message_id[:8]}")
            await pilot.press("enter")
            await _wait_until(predicate=lambda: prompt.list_recoverable_drafts() == ())
            model.release.set()
            await _wait_until(predicate=lambda: not session.is_running)
            assert [
                [message.content for message in request if isinstance(message, HumanMessage)]
                for request in model.requests
            ] == [["uncertain"]]
        finally:
            gate.release.set()
            model.release.set()
    assert read_closed_message_rows(
        database_path=tmp_path / "history" / session.session_id / "messaging.v1.sqlite3",
        temporary_root=tmp_path,
    ) == ((message_id, 0, "applied"),)
