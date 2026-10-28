"""Shutdown admission regressions for the app-owned prompt registration boundary."""

import asyncio
from src.tui.components.chat_transcript.component import ChatTranscript

from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.history.inbox.dao import InboxDeliveryMode, SessionInboxMessageDAO

from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI


@pytest.mark.parametrize("mode", ["chat_turn", "ui_notice", "transcript_note", "context_note"])
@pytest.mark.parametrize("closing", [False, True])
async def test_inbox_handler_explicit_admission(
    tmp_path: Path, mode: InboxDeliveryMode, closing: bool
) -> None:
    """Every mode returns literal admission, including final registration refusal."""
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="delivered")]),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
        )
        app = SloTUI(session=session)
        message = SessionInboxMessageDAO(
            session_id=session.session_id,
            schedule_id="schedule",
            run_id="run",
            kind="system_notice",
            delivery_mode=mode,
            text="inbox text",
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app._app_closing = closing
            async with app._prompt_submission_lock:
                admitted = await app._handle_inbox_message(message=message)
            task = app._in_flight_task
            if task is not None:
                await asyncio.wait_for(task, timeout=5)
            assert admitted is (not closing)
            if closing:
                assert task is None


@pytest.mark.parametrize("cutoff", ["claim", "advance", "registration"])
async def test_claim_retained_on_shutdown(tmp_path: Path, cutoff: str) -> None:
    """Real inbox bytes stay claimed when shutdown overtakes admission."""
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="must not run")]),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
        )
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._inbox_timer is not None
            app._inbox_timer.stop()
            store = app._inbox_store
            assert store is not None
            message = SessionInboxMessageDAO(
                session_id=session.session_id,
                schedule_id="schedule",
                run_id="run",
                kind="system_notice",
                delivery_mode="chat_turn",
                text="private retained text",
            )
            await store.enqueue(message=message)
            pending = list(tmp_path.rglob(f"*{message.message_id}.json"))
            assert len(pending) == 1
            assert pending[0].resolve().is_relative_to(tmp_path.resolve())
            original_bytes = pending[0].read_bytes()
            entered = asyncio.Event()
            release = asyncio.Event()
            original_claim = store.claim_next
            original_advance = app._advance_workflow_handle_state
            original_write = app._chat_transcript.write_transcript_line

            async def claim(*, session_id: str) -> SessionInboxMessageDAO | None:
                """Pause the real claim before its original storage call."""
                if cutoff == "claim":
                    entered.set()
                    await release.wait()
                return await original_claim(session_id=session_id)

            async def advance(*, message: SessionInboxMessageDAO) -> None:
                """Retain original advancement before its continuation barrier."""
                await original_advance(message=message)
                if cutoff == "advance":
                    entered.set()
                    await release.wait()

            def write(*, content: str, classes: str) -> None:
                """Set the synchronous closing prefix at the final notice seam."""
                original_write(content=content, classes=classes)
                if cutoff == "registration" and content.startswith("[scheduled update]"):
                    app._app_closing = True

            with (
                patch.object(store, "claim_next", side_effect=claim),
                patch.object(app, "_advance_workflow_handle_state", side_effect=advance),
                patch.object(app._chat_transcript, "write_transcript_line", side_effect=write),
                patch.object(session, "invoke", wraps=session.invoke) as invoke,
            ):
                poll = asyncio.create_task(coro=app._poll_session_inbox())
                shutdown = None
                try:
                    if cutoff != "registration":
                        await asyncio.wait_for(entered.wait(), timeout=5)
                        shutdown = asyncio.create_task(coro=app.on_unmount())
                        await asyncio.sleep(0)
                        assert app._app_closing
                    release.set()
                    await asyncio.wait_for(poll, timeout=5)
                    assert app._in_flight_task is None
                    invoke.assert_not_called()
                    files = list(tmp_path.rglob(f"*{message.message_id}.json"))
                    assert len(files) == 1
                    assert files[0].parent.name == "claimed"
                    assert files[0].read_bytes() == original_bytes
                    assert await store.claim_next(session_id=session.session_id) is None
                finally:
                    release.set()
                    await asyncio.wait_for(poll, timeout=5)
                    if app._in_flight_task is not None:
                        await asyncio.wait_for(app._in_flight_task, timeout=5)
                    if shutdown is not None:
                        await asyncio.wait_for(shutdown, timeout=5)


async def test_prompt_registration_shutdown_local_echo_pending(tmp_path: Path) -> None:
    """Public shutdown during the real echo must refuse final task registration."""
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="must not execute")]),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
        )
        app = SloTUI(session=session)
        entered = asyncio.Event()
        release = asyncio.Event()
        original_echo = app._chat_transcript.echo_user

        async def echo(*, text: str) -> None:
            """Pause the actual echo while retaining the real submission lock."""
            await original_echo(text=text)
            entered.set()
            await release.wait()

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch.object(app._chat_transcript, "echo_user", side_effect=echo):
                submission = asyncio.create_task(coro=app._submit_or_queue_prompt(text="late prompt"))
                shutdown = None
                registered = None
                try:
                    await asyncio.wait_for(entered.wait(), timeout=5)
                    shutdown = asyncio.create_task(coro=app.on_unmount())
                    # The public shutdown prefix runs before its first suspension.
                    await asyncio.sleep(0)
                    assert app._app_closing
                    assert app._prompt_submission_lock.locked()
                    release.set()
                    await asyncio.wait_for(submission, timeout=5)
                    registered = app._in_flight_task
                    assert registered is None
                finally:
                    release.set()
                    await asyncio.wait_for(submission, timeout=5)
                    # Baseline may have registered a task: drain outside the gate.
                    registered = registered or app._in_flight_task
                    if registered is not None:
                        await asyncio.wait_for(registered, timeout=5)
                    if shutdown is not None:
                        await asyncio.wait_for(shutdown, timeout=5)
