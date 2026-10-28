"""Real retained-child ownership composed with mounted inbox shutdown cutoffs."""

import asyncio
from src.tui.components.chat_transcript.component import ChatTranscript

from pathlib import Path
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.inbox.dao import SessionInboxMessageDAO
from src.agents.slo_agent.history.inbox.store import SessionInboxStore
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from tests.state_isolation import FakeHerdrFixture
from tests.tui.test_herdr_activation_composed import eventually, native_factory
from tests.tui.test_herdr_inbox_disposition import inbox_file
from tests.tui.test_herdr_viewer_retention_composed import exercise_retained_viewer


@pytest.mark.parametrize("throwing_notice", [False, True])
@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize(
    "cutoff",
    [
        "claim_pending",
        "workflow_advance_pending",
        "before_chat_registration",
        "already_registered",
        "registered_abort",
        "registered_original_store",
        "registered_abort_original_store",
    ],
)
async def test_all_owner_claim_pending(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: object,
    monkeypatch: pytest.MonkeyPatch,
    cutoff: str,
    persistent: bool,
    throwing_notice: bool,
) -> None:
    """Keep the exact claimed bytes while actual current and retired owners drain."""
    observations: list[asyncio.Task[None]] = []
    viewers: list[asyncio.Task[None]] = []
    finalized = asyncio.Event()
    refused: list[tuple[SessionInboxMessageDAO, bytes, Path]] = []
    notices: list[str] = []
    owners: dict[str, MagicMock] = {}
    ownership = ExitStack()
    cleanup_notices: list[str] = []
    lease_arguments: dict[str, object] = {}
    retired_reporters: list[HerdrReporter] = []
    closed_reporters: list[HerdrReporter] = []
    original_close = HerdrReporter.close

    async def close_reporter(reporter: HerdrReporter) -> HerdrReporterCloseOutcomeDAO:
        """Record the actual reporter owner, delegating its complete close lifetime."""
        closed_reporters.append(reporter)
        return await original_close(reporter)

    monkeypatch.setattr(target=HerdrReporter, name="close", value=close_reporter)
    original_sink = ChatTranscript.write_transcript_line

    def diagnostic(app: SloTUI, *, content: str, classes: str) -> None:
        """Exercise the contained sink while genuine shutdown owners continue."""
        if content == "Session cleanup incomplete.":
            cleanup_notices.append(content)
            if throwing_notice:
                raise RuntimeError("synthetic cleanup diagnostic fault")
        original_sink(app, content=content, classes=classes)

    monkeypatch.setattr(target=ChatTranscript, name="write_transcript_line", value=diagnostic)

    async def prepare(app: SloTUI) -> None:
        """Pause the real claim until the public shutdown has sealed admission."""
        worker_entered = asyncio.Event()

        async def worker(*, parent_session_id: str, session: SloAgentSession) -> None:
            """Retain registry ownership until its cancellation acquires the real gate."""
            assert session is app._session and parent_session_id == "occupied-current"
            worker_entered.set()
            try:
                await asyncio.Future()
            finally:
                async with app._prompt_submission_lock:
                    finalized.set()

        with patch.object(app, "_run_visualizer_launch", side_effect=worker):
            app._schedule_visualizer_launch(parent_session_id="occupied-current")
            viewers.append(app._visualizer_launch_tasks["occupied-current"])
            await asyncio.wait_for(fut=worker_entered.wait(), timeout=5)
        current, retired = app._session, app._retired_herdr_session
        assert retired is not None
        for name, owner, method in (
            ("viewers", app, "_cancel_visualizer_launches"),
            ("preparation", app, "_cancel_session_preparation"),
            ("current_close", current, "close_external_reporting"),
            ("current_final", current, "finish_retired_reporting_cleanup"),
            ("retired_final", retired, "finish_retired_reporting_cleanup"),
            ("retired_drain", retired, "drain_retained_external_resources"),
            ("unsubscribe", current, "unsubscribe"),
        ):
            owners[name] = ownership.enter_context(patch.object(owner, method, wraps=getattr(owner, method)))
        original_preparation = app._cancel_session_preparation

        async def preparation_fault() -> None:
            """Delegate the real preparation drain before the original cleanup fault."""
            await original_preparation()
            raise RuntimeError("synthetic preparation cleanup fault")

        ownership.enter_context(
            patch.object(app, "_cancel_session_preparation", side_effect=preparation_fault)
        )
        reporter = retired._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        retired_reporters.append(reporter)
        owners["retired_reporter_drain"] = ownership.enter_context(
            patch.object(
                reporter,
                "drain_retained_external_resources",
                wraps=reporter.drain_retained_external_resources,
            )
        )
        lease_store = app._lease_store
        assert lease_store is not None
        lease_arguments.update(
            lease_store=lease_store, session_id=current.session_id, owner_id=app._session_owner_id
        )
        owners["captured_lease"] = ownership.enter_context(
            patch.object(app, "_release_captured_session_lease", wraps=app._release_captured_session_lease)
        )
        owners["lease"] = ownership.enter_context(
            patch.object(lease_store, "release", wraps=lease_store.release)
        )
        for name in ("_lease_timer", "_inbox_timer"):
            timer = getattr(app, name)
            assert timer is not None
            owners[name] = ownership.enter_context(patch.object(timer, "stop", wraps=timer.stop))
        store = app._inbox_store
        assert store is not None
        assert app._inbox_timer is not None
        app._inbox_timer.stop()
        # Exclude the fixture's polling pause: only shutdown may satisfy these spies.
        owners["_inbox_timer"].reset_mock()
        handles = app._workflow_handle_store
        assert handles is not None
        await handles.write(
            handle=WorkflowHandleDAO(
                workflow_id="wf-cutoff",
                owner_session_id=app._session.session_id,
                orchestrator_session_id="orch-cutoff",
                pid=4242,
                brief="bounded",
                cwd=str(tmp_path),
                state="running",
            )
        )
        message = SessionInboxMessageDAO(
            session_id=app._session.session_id,
            schedule_id="workflow:wf-cutoff",
            run_id="run",
            kind="workflow_completed",
            delivery_mode="chat_turn",
            text="retained cutoff",
            payload={"workflow_id": "wf-cutoff", "orchestrator_session_id": "orch-cutoff"},
        )
        await store.enqueue(message=message)
        before = inbox_file(root=tmp_path, message=message).read_bytes()
        entered = asyncio.Event()
        original = store.claim_next

        async def claim(*, session_id: str) -> SessionInboxMessageDAO | None:
            """Resume storage only after observing the monotonic shutdown prefix."""
            if cutoff == "claim_pending":
                entered.set()
                await eventually(predicate=lambda: app._app_closing)
            return await original(session_id=session_id)

        original_ack = store.ack
        original_run = app._run_prompt
        registered: list[asyncio.Task[None]] = []
        admitted = cutoff in {
            "already_registered",
            "registered_abort",
            "registered_original_store",
            "registered_abort_original_store",
        }
        operator_abort = cutoff in {"registered_abort", "registered_abort_original_store"}
        displace_store = cutoff in {"already_registered", "registered_abort"}
        streaming, stream_release = asyncio.Event(), asyncio.Event()
        session = app._session

        async def stream_barrier(event: AgentStreamEventDAO) -> None:
            """Hold a real Faux delta until the operator explicitly interrupts."""
            if operator_abort and event.kind == "text_delta":
                streaming.set()
                await stream_release.wait()

        session.subscribe(handler=stream_barrier)

        async def run(*, text: str) -> None:
            """Hold admitted execution until shutdown has sealed new admission."""
            await eventually(predicate=lambda: app._app_closing)
            await original_run(text=text)

        async def ack(*, session_id: str, message_id: str) -> bool:
            """Capture the admitted task and ack through the original storage owner."""
            if admitted:
                task = app._in_flight_task
                assert task is not None and not task.done()
                registered.append(task)
                entered.set()
                await eventually(predicate=lambda: app._app_closing)
                assert app._in_flight_task is task and task.cancelling() == 0
                if displace_store:
                    app._inbox_store = SessionInboxStore(history_root=tmp_path / "displaced")
            return await original_ack(session_id=session_id, message_id=message_id)

        original_advance = app._advance_workflow_handle_state
        original_write = app._chat_transcript.write_transcript_line

        async def advance(*, message: SessionInboxMessageDAO) -> None:
            """Hold only after actual durable workflow advancement."""
            await original_advance(message=message)
            if cutoff == "workflow_advance_pending":
                entered.set()
                await eventually(predicate=lambda: app._app_closing)

        def write(*, content: str, classes: str) -> None:
            """Seal the final synchronous registration boundary after its notice."""
            if content == "Inbox delivery deferred during shutdown; claimed item retained.":
                notices.append(content)
                if throwing_notice:
                    raise RuntimeError("synthetic diagnostic sink fault")
            original_write(content=content, classes=classes)
            if cutoff == "before_chat_registration" and content.startswith("[scheduled update]"):
                app._app_closing = True
                entered.set()

        async def observe() -> None:
            """Assert refused delivery independently of retained process finalization."""
            with (
                patch.object(session, "invoke", wraps=session.invoke) as invoke,
                patch.object(app._prompt_history, "record", wraps=app._prompt_history.record) as history,
                patch.object(store, "claim_next", side_effect=claim),
                patch.object(store, "ack", side_effect=ack) as ack_spy,
                patch.object(app, "_run_prompt", side_effect=run),
                patch.object(app, "_register_prompt_task", wraps=app._register_prompt_task) as register,
                patch.object(app, "_advance_workflow_handle_state", side_effect=advance),
                patch.object(app._chat_transcript, "write_transcript_line", side_effect=write),
            ):
                await app._poll_session_inbox()
                if admitted:
                    ack_spy.assert_awaited_once_with(
                        session_id=message.session_id, message_id=message.message_id
                    )
                    assert len(registered) == register.call_count == 1
                    if operator_abort:
                        await asyncio.wait_for(fut=streaming.wait(), timeout=5)
                        assert app._in_flight_task is registered[0]
                        await app.action_interrupt()
                        stream_release.set()
                    await asyncio.wait_for(fut=registered[0], timeout=5)
                    session.unsubscribe(handler=stream_barrier)
                    assert app._queued_prompt_text is None
                    assert not (tmp_path / "displaced").exists()
                else:
                    ack_spy.assert_not_called()
                    invoke.assert_not_called()
                    history.assert_not_called()
                    assert session.history_root is not None
                    events = await FilesystemSessionHistoryStore(root=session.history_root).load_events(
                        session_id=session.session_id
                    )
                    assert not any(event.kind in {"user_message", "tool_call"} for event in events)
                    assert register.call_count == int(cutoff == "before_chat_registration")
                assert app._in_flight_task is None
                path = inbox_file(root=tmp_path, message=message)
                assert path.parent.name == ("done" if registered else "claimed")
                assert path.read_bytes() == before
                if not admitted:
                    assert session.history_root is not None
                    refused.append((message, before, session.history_root))
                assert await original(session_id=message.session_id) is None
                handle = await handles.read(owner_session_id=message.session_id, workflow_id="wf-cutoff")
                assert handle is not None
                assert handle.state == ("running" if cutoff == "claim_pending" else "completed")

        observations.append(asyncio.create_task(coro=observe()))
        await asyncio.wait_for(fut=entered.wait(), timeout=5)

    async def exercise() -> None:
        """Run the same resource fixture for successful and persistent final drain."""
        await exercise_retained_viewer(
            root=tmp_path,
            fake=fake_herdr,
            monkeypatch=monkeypatch,
            persistent=persistent,
            before_shutdown=prepare,
            registry_fault=False,
        )

    with ownership:
        if persistent:
            with pytest.raises(asyncio.CancelledError):
                await exercise()
        else:
            await exercise()
    for name in ("viewers", "preparation", "current_final", "retired_final"):
        owners[name].assert_awaited_once()
    assert owners["current_close"].await_count == 2  # Shutdown plus idempotent final cleanup.
    owners["retired_drain"].assert_awaited()
    owners["unsubscribe"].assert_called()
    owners["captured_lease"].assert_awaited_once_with(**lease_arguments)
    owners["lease"].assert_awaited_once_with(
        session_id=lease_arguments["session_id"], owner_id=lease_arguments["owner_id"]
    )
    owners["retired_reporter_drain"].assert_awaited_once_with()
    assert len(retired_reporters) == 1
    assert closed_reporters == retired_reporters
    for name in ("_lease_timer", "_inbox_timer"):
        owners[name].assert_called_once_with()
    await asyncio.wait_for(fut=asyncio.gather(*observations), timeout=5)
    assert finalized.is_set() and all(task.done() for task in viewers)
    assert len(notices) == int(bool(refused))
    assert cleanup_notices == ["Session cleanup incomplete."]
    for message, original_bytes, history_root in refused:
        restored = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                history_root=history_root,
                session_id=message.session_id,
                model_name="gpt-5.4",
            )
        )
        restored_app = SloTUI(session=restored)
        with patch.object(restored, "invoke", wraps=restored.invoke) as invoke:
            async with restored_app.run_test():
                await restored_app._poll_session_inbox()
                invoke.assert_not_called()
                assert restored_app._in_flight_task is None
                assert restored_app._queued_prompt_text is None
                path = inbox_file(root=tmp_path, message=message)
                assert path.parent.name == "claimed"
                assert path.read_bytes() == original_bytes
