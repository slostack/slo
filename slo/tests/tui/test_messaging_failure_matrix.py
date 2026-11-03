"""DC09 failure and rollback guards; no provider or memory fallback is allowed."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.tui.app import SloTUI
from tests.tui.recording_prompt import RecordingPromptInput
from src.tui.components.prompt_input.component import PromptInputComponent
from tests.tui.test_prompt_component_protocol import build_session
from tests.tui.test_durable_composer import _wait_until, _transcript_notices
from tests.cli.test_app import compose_default_tui


async def test_legacy_host_refuses_session_with_durable_messages(tmp_path: Path) -> None:
    """Presence alone blocks rollback execution, even for an empty or unreadable store."""
    session = build_session(tmp_path=tmp_path)
    path = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    assert session.has_messaging_store() is False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a database")
    assert session.has_messaging_store() is True
    app = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=False)
    async with app.run_test() as pilot:
        prompt = app.query_one(RecordingPromptInput)
        prompt.load_text("kept draft")
        await pilot.press("enter")
        await _wait_until(
            predicate=lambda: any(
                "This session has durable messages; use a messaging-enabled Slo." in line
                for line in _transcript_notices(app)
            )
        )
        assert prompt.text == "kept draft"
        assert app._in_flight_task is None and app._queued_prompt_text is None
        assert session.history_store is not None
        assert await session.history_store.load_events(session_id=session.session_id) == []


async def test_messaging_session_refuses_legacy_scheduling_invariants(tmp_path: Path) -> None:
    """Invariant guards refuse both legacy consumers without registering work."""
    session = build_session(tmp_path=tmp_path)
    app = compose_default_tui(session=session)
    async with app.run_test() as pilot:
        await _wait_until(predicate=lambda: session.is_messaging_ready)
        with pytest.raises(RuntimeError, match="legacy scheduling in messaging session"):
            app._register_prompt_task(text="forbidden")
        with pytest.raises(RuntimeError, match="legacy scheduling in messaging session"):
            await app._queue_prompt(text="forbidden")
        assert app._in_flight_task is None and app._queued_prompt_text is None


@pytest.mark.parametrize(
    argnames="case",
    argvalues=["corrupt", "owned", "urgent", "ui_notice", "machine_recovery", "ephemeral", "storage"],
)
async def test_default_path_failures_refuse_safely(tmp_path: Path, case: str) -> None:
    """Messaging composition refuses startup/runtime failures, preserving its single consumer."""
    import sqlite3
    from uuid import uuid4
    from langchain_core.messages import AIMessage
    from src.agents.slo_agent.agent import SloAgent
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.agents.slo_agent.messaging.ownership import SessionExecutionOwnership
    from src.agents.slo_agent.messaging.dao import (
        MessageSubmissionDAO,
        MessageErrorDAO,
        MessageReceiptDAO,
        MessagePrincipalDAO,
    )
    from tests.tui.test_durable_composer import _build_factory_session
    from tests.agents.slo_agent.messaging.test_delivery import RecordingModel

    model = RecordingModel(responses=[AIMessage(content="done")])
    if case == "ephemeral":
        session = SloAgentSession(
            agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
            workdir=tmp_path,
            session_id=str(uuid4()),
            enable_history=False,
        )
    else:
        session = _build_factory_session(tmp_path=tmp_path, model=model)
    database = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
    assert database.resolve().is_relative_to(tmp_path.resolve())
    holder = None
    if case == "corrupt":
        database.parent.mkdir(parents=True, exist_ok=True)
        database.write_bytes(b"corrupt SQLite")
        database.chmod(mode=0o600)
    if case == "owned":
        holder = await SessionExecutionOwnership.acquire(
            root=tmp_path / "history", session_id=session.session_id
        )
    app = compose_default_tui(session=session)
    try:
        async with app.run_test() as pilot:
            prompt = app.query_one(RecordingPromptInput)
            if case in ("corrupt", "owned"):
                await _wait_until(
                    predicate=lambda: any(
                        "Durable messaging unavailable" in text for text in _transcript_notices(app)
                    )
                )
                prompt.load_text("kept")
                await pilot.press("enter")
                assert prompt.text == "kept"
                assert app._messaging_client is None and not model.requests
            else:
                await _wait_until(predicate=lambda: session.is_messaging_ready)
                target = session.messaging_target
                principal = session.messaging_owner_principal
                if case in ("urgent", "ui_notice"):
                    changes = {"priority": "urgent"} if case == "urgent" else {"kind": "ui_notice"}
                    request = MessageSubmissionDAO(
                        message_id=str(uuid4()), target=target, kind="agent_input", text="forbidden"
                    ).model_copy(update=changes)
                    assert app._messaging_client is not None
                    result = await app._messaging_client.submit(submission=request)
                    assert isinstance(result, MessageErrorDAO) and result.code == "unsupported"
                    assert result.message_id == request.message_id
                    receipt = await app._messaging_client.get_receipt(message_id=request.message_id)
                    assert isinstance(receipt, MessageErrorDAO) and receipt.code == "not_found"
                    assert session._message_store is not None
                    assert await session._message_store.find_identity(message_id=request.message_id) is None
                    assert session.history_store is not None
                    events = await session.history_store.load_events(session_id=session.session_id)
                    assert not [event for event in events if event.kind == "user_message"]
                    assert not model.requests
                elif case == "machine_recovery":
                    recovery = await session.list_retained_messages(
                        principal=MessagePrincipalDAO(principal_id="machine", kind="scheduler")
                    )
                    assert isinstance(recovery, MessageErrorDAO) and recovery.code == "unauthorized"
                    assert not model.requests
                elif case == "ephemeral":
                    await _wait_until(
                        predicate=lambda: any("not durable" in text for text in _transcript_notices(app))
                    )
                    prompt.load_text("ephemeral")
                    await pilot.press("enter")
                    await _wait_until(predicate=lambda: bool(prompt.outcomes))
                    receipt = prompt.outcomes[0].outcome
                    assert isinstance(receipt, MessageReceiptDAO) and receipt.durable is False
                    model.release.set()
                    await _wait_until(predicate=lambda: len(model.requests) == 1 and not session.is_running)
                    assert not database.exists()
                else:
                    with sqlite3.connect(database=database) as connection:
                        connection.execute("DROP TABLE identity")
                    prompt.load_text("failed draft")
                    await pilot.press("enter")
                    await _wait_until(predicate=lambda: bool(prompt.outcomes))
                    outcome = prompt.outcomes[-1].outcome
                    assert isinstance(outcome, MessageErrorDAO) and outcome.code == "storage_unavailable"
                    assert not model.requests
                    result = await session.admit_message(
                        submission=MessageSubmissionDAO(
                            message_id=str(uuid4()), target=target, kind="agent_input", text="next"
                        ),
                        principal=principal,
                    )
                    assert isinstance(result, MessageErrorDAO) and result.code == "storage_unavailable"
                    await _wait_until(
                        predicate=lambda: any(
                            "Message updates unavailable" in text for text in _transcript_notices(app)
                        )
                    )
            assert app._in_flight_task is None and app._queued_prompt_text is None
    finally:
        model.release.set()
        if holder is not None:
            await holder.release()
