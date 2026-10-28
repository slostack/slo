"""Mounted real-store disposition checks for C 7.9; no production substitutes."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from src.tui.components.chat_transcript.component import ChatTranscript

from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.inbox.dao import InboxDeliveryMode, SessionInboxMessageDAO
from src.agents.slo_agent.history.inbox.store import SessionInboxStore
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleDAO, WorkflowHandleStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI


@asynccontextmanager
async def mounted_inbox(*, root: Path, session_id: str | None = None) -> AsyncIterator[SloTUI]:
    """Mount a config-backed Faux session with storage confined to pytest's root."""
    assert root.resolve().is_dir()
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="delivered")]),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=root, history_root=root / "history", model_name="gpt-5.4", session_id=session_id
            )
        )
        app = SloTUI(
            session=session,
            workflow_handle_store=WorkflowHandleStore(
                history_root=root / "history", pid_alive=lambda pid: True
            ),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._inbox_timer is not None
            app._inbox_timer.stop()
            with ExitStack() as stack:
                cleanup_spies = [
                    stack.enter_context(patch.object(owner, name, wraps=getattr(owner, name)))
                    for owner, name in (
                        (app, "_cancel_session_preparation"),
                        (session, "close_external_reporting"),
                        (session._herdr_reporter, "close"),
                        (session._herdr_reporter, "close_transport"),
                        (session, "unsubscribe"),
                        (app, "_stop_delivery_timers"),
                        (app, "_release_replaced_session_lease"),
                        (session, "finish_retired_reporting_cleanup"),
                    )
                ]
                try:
                    yield app
                finally:
                    task = app._in_flight_task
                    if task is not None:
                        await asyncio.wait_for(task, timeout=5)
                    await asyncio.wait_for(app.on_unmount(), timeout=5)
                    for spy in cleanup_spies:
                        assert spy.call_count >= 1
                    assert session._herdr_visualizer is None
                    assert app._retired_herdr_session is None
                    assert app._app_closing and app._delivery_quiescing


def inbox_file(*, root: Path, message: SessionInboxMessageDAO) -> Path:
    """Require one regular contained message, independently of its storage lane."""
    paths = list(root.rglob(f"*{message.message_id}.json"))
    assert len(paths) == 1
    path = paths[0]
    assert not path.is_symlink()
    assert path.resolve().is_relative_to(root.resolve())
    assert path.is_file()
    return path


@pytest.mark.parametrize(
    "case",
    [
        "empty",
        "closed_entry",
        "claim_error",
        "advance_error",
        "handler_cancel",
        "chat_open",
        "notice_open",
        "note_open",
        "context_open",
        "ack_false",
        "ack_error",
    ],
)
async def test_inbox_delivery_disposition(tmp_path: Path, case: str) -> None:
    """Exercise real claim/dispatch/ack lanes, with faults only at the named boundary."""
    async with mounted_inbox(root=tmp_path) as app:
        store = app._inbox_store
        assert store is not None
        session = app._session
        modes: dict[str, InboxDeliveryMode] = {
            "notice_open": "ui_notice",
            "note_open": "transcript_note",
            "context_open": "context_note",
        }
        message = SessionInboxMessageDAO(
            session_id=session.session_id,
            schedule_id="schedule",
            run_id="run",
            kind="system_notice",
            delivery_mode=modes.get(case, "chat_turn"),
            text="bounded inbox text",
        )
        original_bytes = b""
        if case != "empty":
            await store.enqueue(message=message)
            original_bytes = inbox_file(root=tmp_path, message=message).read_bytes()
        original_claim = store.claim_next
        original_advance = app._advance_workflow_handle_state
        original_ack = store.ack

        async def claim(*, session_id: str) -> SessionInboxMessageDAO | None:
            """Inject a storage failure before the real atomic claim."""
            if case == "claim_error":
                raise OSError("claim sentinel")
            return await original_claim(session_id=session_id)

        async def advance(*, message: SessionInboxMessageDAO) -> None:
            """Inject pre-delivery failure or cancellation without replacing delivery."""
            if case == "advance_error":
                raise OSError("advance sentinel")
            if case == "handler_cancel":
                raise asyncio.CancelledError
            await original_advance(message=message)

        async def ack(*, session_id: str, message_id: str) -> bool:
            """Keep the real writer for success and isolate explicit storage failures."""
            if case == "ack_false":
                return False
            if case == "ack_error":
                raise OSError("ack sentinel")
            return await original_ack(session_id=session_id, message_id=message_id)

        app._app_closing = case == "closed_entry"
        with (
            patch.object(store, "claim_next", side_effect=claim),
            patch.object(store, "ack", side_effect=ack) as ack_spy,
            patch.object(app, "_advance_workflow_handle_state", side_effect=advance),
            patch.object(session, "invoke", wraps=session.invoke) as invoke,
            patch.object(app._chat_transcript, "echo_user", wraps=app._chat_transcript.echo_user) as echo,
            patch.object(app, "_queue_prompt", wraps=app._queue_prompt) as queue,
            patch.object(app._prompt_history, "record", wraps=app._prompt_history.record) as history,
        ):
            if case in {"claim_error", "advance_error", "ack_error"}:
                with pytest.raises(OSError, match="sentinel"):
                    await app._poll_session_inbox()
            elif case == "handler_cancel":
                with pytest.raises(asyncio.CancelledError):
                    await app._poll_session_inbox()
            else:
                await app._poll_session_inbox()
            task = app._in_flight_task
            if task is not None:
                await asyncio.wait_for(task, timeout=5)
            delivered = case in {
                "chat_open",
                "notice_open",
                "note_open",
                "context_open",
                "ack_false",
                "ack_error",
            }
            assert invoke.call_count == int(delivered and message.delivery_mode == "chat_turn")
            assert ack_spy.await_count == int(delivered)
            echo.assert_not_called()
            queue.assert_not_called()
            history.assert_not_called()
            assert app._queued_prompt_text is None
            if case == "empty":
                assert list(tmp_path.rglob(f"*{message.message_id}.json")) == []
                return
            path = inbox_file(root=tmp_path, message=message)
            expected_lane = "done" if delivered else "claimed"
            if case in {"closed_entry", "claim_error"}:
                expected_lane = "pending"
            if case in {"ack_false", "ack_error"}:
                expected_lane = "claimed"
            assert path.parent.name == expected_lane
            assert path.read_bytes() == original_bytes
            if expected_lane != "pending":
                fresh = SessionInboxStore(history_root=tmp_path / "history")
                assert await fresh.claim_next(session_id=session.session_id) is None
            if delivered:
                assert app._chat_transcript._adapter is not None
                prefixes = {
                    "ui_notice": "[scheduled notice]",
                    "transcript_note": "[scheduled update]",
                    "chat_turn": "[scheduled update]",
                    "context_note": "⊛",
                }
                assert any(
                    text.startswith(prefixes[message.delivery_mode]) and message.text in text
                    for text, _ in app._chat_transcript._adapter.lines
                )
            if case == "context_open":
                assert (
                    await session.record_workflow_update(
                        text=message.text, message_id=message.message_id, workflow_id="wf-unknown"
                    )
                    is False
                )


@pytest.mark.parametrize("boundary", ["claim", "advance"])
async def test_displaced_session_retains_claim(tmp_path: Path, boundary: str) -> None:
    """A captured message never enters the newly selected session after an await."""
    async with mounted_inbox(root=tmp_path) as app:
        session, store = app._session, app._inbox_store
        assert store is not None
        replacement = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                history_root=tmp_path / "replacement",
                model_name="gpt-5.4",
            )
        )
        message = SessionInboxMessageDAO(
            session_id=session.session_id,
            schedule_id="schedule",
            run_id="run",
            kind="system_notice",
            delivery_mode="chat_turn",
            text="old session only",
        )
        await store.enqueue(message=message)
        before = inbox_file(root=tmp_path, message=message).read_bytes()
        original_claim, original_advance = store.claim_next, app._advance_workflow_handle_state

        async def claim(*, session_id: str) -> SessionInboxMessageDAO | None:
            """Displace at return from actual claim, not before its captured ID."""
            result = await original_claim(session_id=session_id)
            if boundary == "claim":
                app._session = replacement
            return result

        async def advance(*, message: SessionInboxMessageDAO) -> None:
            """Displace after the real workflow handler's awaited boundary."""
            await original_advance(message=message)
            app._session = replacement

        try:
            with (
                patch.object(store, "claim_next", side_effect=claim),
                patch.object(app, "_advance_workflow_handle_state", side_effect=advance),
                patch.object(store, "ack", wraps=store.ack) as ack,
                patch.object(session, "invoke", wraps=session.invoke) as old_invoke,
                patch.object(replacement, "invoke", wraps=replacement.invoke) as new_invoke,
            ):
                await app._poll_session_inbox()
                ack.assert_not_called()
                old_invoke.assert_not_called()
                new_invoke.assert_not_called()
                assert app._in_flight_task is None
                path = inbox_file(root=tmp_path, message=message)
                assert path.parent.name == "claimed" and path.read_bytes() == before
                assert await original_claim(session_id=session.session_id) is None
        finally:
            app._session = session
            await replacement.dispose_unmounted_session()


async def test_context_pending_at_close(tmp_path: Path) -> None:
    """An admitted context write completes once and acknowledges the captured store."""
    async with mounted_inbox(root=tmp_path) as app:
        session, store = app._session, app._inbox_store
        assert store is not None
        message = SessionInboxMessageDAO(
            session_id=session.session_id,
            schedule_id="schedule",
            run_id="run",
            kind="system_notice",
            delivery_mode="context_note",
            text="durable context",
        )
        await store.enqueue(message=message)
        before = inbox_file(root=tmp_path, message=message).read_bytes()
        entered, release = asyncio.Event(), asyncio.Event()
        original = session.record_workflow_update

        async def record(*, text: str, message_id: str, workflow_id: str) -> bool:
            """Hold persistence after admission but before the real history writer."""
            entered.set()
            await release.wait()
            return await original(text=text, message_id=message_id, workflow_id=workflow_id)

        with (
            patch.object(session, "record_workflow_update", side_effect=record),
            patch.object(store, "ack", wraps=store.ack) as ack,
            patch.object(session, "invoke", wraps=session.invoke) as invoke,
        ):
            poll = asyncio.create_task(coro=app._poll_session_inbox())
            shutdown = None
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                shutdown = asyncio.create_task(coro=app.on_unmount())
                await asyncio.sleep(0)
                assert app._app_closing
                release.set()
                await asyncio.wait_for(poll, timeout=5)
                await asyncio.wait_for(shutdown, timeout=5)
                ack.assert_awaited_once_with(session_id=session.session_id, message_id=message.message_id)
                invoke.assert_not_called()
                path = inbox_file(root=tmp_path, message=message)
                assert path.parent.name == "done" and path.read_bytes() == before
                assert (
                    await original(text=message.text, message_id=message.message_id, workflow_id="wf-unknown")
                    is False
                )
            finally:
                release.set()
                await asyncio.wait_for(poll, timeout=5)
                if shutdown is not None:
                    await asyncio.wait_for(shutdown, timeout=5)


@pytest.mark.parametrize("cutoff", ["claim_pending", "workflow_advance_pending", "before_chat_registration"])
@pytest.mark.parametrize("throwing_notice", [False, True])
async def test_durable_advance_then_shutdown(tmp_path: Path, throwing_notice: bool, cutoff: str) -> None:
    """A real lifecycle commit survives refused delivery and a broken notice sink."""
    async with mounted_inbox(root=tmp_path) as app:
        store = app._inbox_store
        handles = app._workflow_handle_store
        assert store is not None and handles is not None
        session = app._session
        await handles.write(
            handle=WorkflowHandleDAO(
                workflow_id="wf-inbox",
                owner_session_id=session.session_id,
                orchestrator_session_id="orch-inbox",
                pid=4242,
                brief="bounded",
                cwd=str(tmp_path),
                state="running",
            )
        )
        message = SessionInboxMessageDAO(
            session_id=session.session_id,
            schedule_id="workflow:wf-inbox",
            run_id="run",
            kind="workflow_completed",
            delivery_mode="chat_turn",
            text="private lifecycle",
            payload={"workflow_id": "wf-inbox", "orchestrator_session_id": "orch-inbox"},
        )
        await store.enqueue(message=message)
        before = inbox_file(root=tmp_path, message=message).read_bytes()
        entered, release = asyncio.Event(), asyncio.Event()
        original = app._advance_workflow_handle_state
        original_claim = store.claim_next

        async def claim(*, session_id: str) -> SessionInboxMessageDAO | None:
            """Hold the original claim until the public shutdown prefix runs."""
            if cutoff == "claim_pending":
                entered.set()
                await release.wait()
            return await original_claim(session_id=session_id)

        async def advance(*, message: SessionInboxMessageDAO) -> None:
            """Pause only after the real service has committed its terminal handle."""
            await original(message=message)
            if cutoff == "workflow_advance_pending":
                entered.set()
                await release.wait()

        original_write = app._chat_transcript.write_transcript_line

        def write(*, content: str, classes: str) -> None:
            """Fault only the diagnostic, not the actual lifecycle service."""
            if (
                throwing_notice
                and content == "Inbox delivery deferred during shutdown; claimed item retained."
            ):
                raise RuntimeError("private diagnostic sentinel")
            original_write(content=content, classes=classes)
            if cutoff == "before_chat_registration" and content.startswith("[scheduled update]"):
                app._app_closing = True
                entered.set()

        with (
            patch.object(store, "claim_next", side_effect=claim),
            patch.object(app._prompt_history, "record", wraps=app._prompt_history.record) as history,
            patch.object(app._chat_transcript, "echo_user", wraps=app._chat_transcript.echo_user) as echo,
            patch.object(app, "_queue_prompt", wraps=app._queue_prompt) as queue,
            patch.object(app, "_advance_workflow_handle_state", side_effect=advance),
            patch.object(app._chat_transcript, "write_transcript_line", side_effect=write),
            patch.object(store, "ack", wraps=store.ack) as ack,
            patch.object(session, "invoke", wraps=session.invoke) as invoke,
        ):
            poll = asyncio.create_task(coro=app._poll_session_inbox())
            shutdown = None
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                handle = await handles.read(owner_session_id=session.session_id, workflow_id="wf-inbox")
                assert handle is not None
                assert handle.state == ("running" if cutoff == "claim_pending" else "completed")
                shutdown = asyncio.create_task(coro=app.on_unmount())
                await asyncio.sleep(0)
                assert app._app_closing
                release.set()
                await asyncio.wait_for(poll, timeout=5)
                await asyncio.wait_for(shutdown, timeout=5)
                ack.assert_not_called()
                invoke.assert_not_called()
                history.assert_not_called()
                echo.assert_not_called()
                queue.assert_not_called()
                assert app._in_flight_task is None
                path = inbox_file(root=tmp_path, message=message)
                assert path.parent.name == "claimed" and path.read_bytes() == before
                assert (
                    await SessionInboxStore(history_root=tmp_path / "history").claim_next(
                        session_id=session.session_id
                    )
                    is None
                )
                retained = await handles.read(owner_session_id=session.session_id, workflow_id="wf-inbox")
                assert retained == handle
                assert app._chat_transcript._adapter is not None
                if cutoff != "before_chat_registration":
                    assert not any(
                        "private lifecycle" in text for text, _ in app._chat_transcript._adapter.lines
                    )
                assert not any(
                    "private diagnostic sentinel" in text for text, _ in app._chat_transcript._adapter.lines
                )
            finally:
                release.set()
                await asyncio.wait_for(poll, timeout=5)
                if shutdown is not None:
                    await asyncio.wait_for(shutdown, timeout=5)

    await assert_restart_retains_claim(root=tmp_path, message=message, original_bytes=before)


async def assert_restart_retains_claim(
    *, root: Path, message: SessionInboxMessageDAO, original_bytes: bytes
) -> None:
    """Mount a fresh owner on the same history and require explicit user admission."""
    history = FilesystemSessionHistoryStore(root=root / "history")
    before_events = await history.load_events(session_id=message.session_id)
    assert not any(event.kind in {"user_message", "tool_call"} for event in before_events)
    async with mounted_inbox(root=root, session_id=message.session_id) as restarted:
        with patch.object(restarted._session, "invoke", wraps=restarted._session.invoke) as invoke:
            await restarted._poll_session_inbox()
            invoke.assert_not_called()
            assert restarted._in_flight_task is None
            assert restarted._prompt_history.older(current_buffer="") is None
            assert await history.load_events(session_id=message.session_id) == before_events
            path = inbox_file(root=root, message=message)
            assert path.parent.name == "claimed" and path.read_bytes() == original_bytes
            await restarted._submit_or_queue_prompt(text="explicit subsequent user prompt")
            task = restarted._in_flight_task
            assert task is not None
            await asyncio.wait_for(task, timeout=5)
            invoke.assert_called_once()
            events = await history.load_events(session_id=message.session_id)
            users = [event for event in events if event.kind == "user_message"]
            assert len(users) == 1
            assert users[0].payload.content == "explicit subsequent user prompt"
            assert not any(event.kind == "tool_call" for event in events)
            assert message.text not in " ".join(event.model_dump_json() for event in events)
            assert path.read_bytes() == original_bytes and path.parent.name == "claimed"


@pytest.mark.parametrize("operator_abort", [False, True])
@pytest.mark.parametrize("displace_store", [False, True])
async def test_already_registered_ack_pending_at_close(
    tmp_path: Path, operator_abort: bool, displace_store: bool
) -> None:
    """Closing preserves the exact admitted task and captured-store ack ownership."""
    async with mounted_inbox(root=tmp_path) as app:
        session = app._session
        store = app._inbox_store
        assert store is not None
        message = SessionInboxMessageDAO(
            session_id=session.session_id,
            schedule_id="schedule",
            run_id="run",
            kind="system_notice",
            delivery_mode="chat_turn",
            text="registered before closing",
        )
        await store.enqueue(message=message)
        before = inbox_file(root=tmp_path, message=message).read_bytes()
        entered, release, run_release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        streaming, stream_release = asyncio.Event(), asyncio.Event()

        async def stream_barrier(event: AgentStreamEventDAO) -> None:
            """Pause a real streamed delta inside the admitted session invocation."""
            if operator_abort and event.kind == "text_delta":
                streaming.set()
                await stream_release.wait()

        session.subscribe(handler=stream_barrier)
        original_ack = store.ack
        original_run = app._run_prompt

        async def ack(*, session_id: str, message_id: str) -> bool:
            """Keep the actual ack pending while shutdown seals new registration."""
            entered.set()
            await release.wait()
            return await original_ack(session_id=session_id, message_id=message_id)

        async def run(*, text: str) -> None:
            """Separate registration from coroutine entry without replacing execution."""
            await run_release.wait()
            await original_run(text=text)

        with (
            patch.object(store, "ack", side_effect=ack) as ack_spy,
            patch.object(app, "_run_prompt", side_effect=run),
            patch.object(app, "_register_prompt_task", wraps=app._register_prompt_task) as register,
            patch.object(session, "invoke", wraps=session.invoke) as invoke,
            patch.object(session, "abort", wraps=session.abort) as abort,
        ):
            poll = asyncio.create_task(coro=app._poll_session_inbox())
            shutdown = None
            task = None
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                task = app._in_flight_task
                assert task is not None and not task.done()
                assert register.call_count == 1
                invoke.assert_not_called()
                shutdown = asyncio.create_task(coro=app.on_unmount())
                await asyncio.sleep(0)
                assert app._app_closing and app._in_flight_task is task
                abort.assert_not_called()
                assert task.cancelling() == 0
                if displace_store:
                    app._inbox_store = SessionInboxStore(history_root=tmp_path / "replacement-store")
                release.set()
                await asyncio.wait_for(poll, timeout=5)
                run_release.set()
                if operator_abort:
                    await asyncio.wait_for(streaming.wait(), timeout=5)
                    assert invoke.call_count == 1 and app._in_flight_task is task
                    await app.action_interrupt()
                    abort.assert_called_once()
                    stream_release.set()
                await asyncio.wait_for(task, timeout=5)
                await asyncio.wait_for(shutdown, timeout=5)
                ack_spy.assert_awaited_once_with(session_id=session.session_id, message_id=message.message_id)
                assert register.call_count == 1 and invoke.call_count == 1
                assert abort.call_count == int(operator_abort)
                path = inbox_file(root=tmp_path, message=message)
                assert path.parent.name == "done" and path.read_bytes() == before
                assert app._queued_prompt_text is None
                assert not (tmp_path / "replacement-store").exists()
                assert await store.claim_next(session_id=session.session_id) is None
                events = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
                    session_id=session.session_id
                )
                assert sum(event.kind == "user_message" for event in events) == 1
                assert sum(event.kind == "run_aborted" for event in events) == int(operator_abort)
            finally:
                release.set()
                run_release.set()
                stream_release.set()
                session.unsubscribe(handler=stream_barrier)
                await asyncio.wait_for(poll, timeout=5)
                if task is not None:
                    await asyncio.wait_for(task, timeout=5)
                if shutdown is not None:
                    await asyncio.wait_for(shutdown, timeout=5)
