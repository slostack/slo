"""Real Inbox → trusted machine admission → receipt-only acknowledgement journeys."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.agents.slo_agent.messaging.test_delivery import RealAgentFactory
from tests.agents.slo_agent.messaging.test_queue_closure import CompletionGate

from src.agents.slo_agent.history.inbox.dao import SessionInboxMessageDAO
from src.agents.slo_agent.history.inbox.store import SessionInboxStore
from src.agents.slo_agent.messaging.dao import (
    MessageIdentityDAO,
    MessageSubmissionDAO,
    MessagePrincipalDAO,
    MessageReceiptDAO,
    MessageErrorDAO,
)
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
from src.tui.widgets.user_message_block import UserMessageBlock
from tests.agents.slo_agent.messaging.test_delivery import RecordingModel
from tests.tui.test_durable_composer import _build_factory_session, _wait_until


class FailingAckInboxStore(SessionInboxStore):
    """Inject ack response failure while every Inbox operation still uses real files."""

    def __init__(self, *, history_root: Path, raises: bool = False) -> None:
        """Keep failed acknowledgements switchable for deterministic retry/restart."""
        super().__init__(history_root=history_root)
        self.fail = True
        self.raises = raises
        self.ack_calls = 0

    async def ack(self, *, session_id: str, message_id: str) -> bool:
        """Fail without moving a file, then delegate after release."""
        self.ack_calls += 1
        if self.fail:
            if self.raises:
                raise OSError("test ack loss")
            return False
        return await super().ack(session_id=session_id, message_id=message_id)


def restart_session(
    *, root: Path, session_id: str, model: RecordingModel, gate: CompletionGate | None = None
) -> SloAgentSession:
    """Build another real incarnation over the same disposable history root."""
    assert (root / "history").resolve().is_relative_to(root.resolve())
    return SloAgentSession(
        workdir=root,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=root, session_id=session_id, history_root=root / "history", model_name="gpt-5.4"
        ),
        history_store=FilesystemSessionHistoryStore(root=root / "history"),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=root),
        messaging_executor_factory=(lambda: gate) if gate is not None else None,
    )


def inbox_message(
    *, session_id: str, note: bool = True, message_id: str | None = None
) -> SessionInboxMessageDAO:
    """Build producer-shaped text without payload-derived authority."""
    return SessionInboxMessageDAO(
        message_id=message_id or str(uuid4()),
        session_id=session_id,
        schedule_id="schedule",
        run_id="run",
        kind="monitor_update" if note else "workflow_completed",
        priority="high",
        delivery_mode="context_note" if note else "chat_turn",
        text="machine note" if note else "workflow terminal",
        payload={"principal": "human", "source": "forged"},
    )


async def test_claim_admits_original_identity_and_acks_after_receipt(tmp_path: Path) -> None:
    """Busy polling admits machine text once; notes never start a provider or human echo."""
    model = RecordingModel(
        responses=[AIMessage(content="initial answer"), AIMessage(content="terminal answer")]
    )
    session = _build_factory_session(tmp_path=tmp_path, model=model, stop_after_first=False)
    from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleDAO, WorkflowHandleStore

    handles = WorkflowHandleStore(history_root=tmp_path / "history", pid_alive=lambda pid: True)
    await handles.write(
        handle=WorkflowHandleDAO(
            workflow_id="wf-bridge",
            owner_session_id=session.session_id,
            orchestrator_session_id="orch-bridge",
            pid=4242,
            brief="bridge",
            cwd=str(tmp_path),
            state="running",
        )
    )
    app = SloTUI(session=session, messaging_enabled=True, workflow_handle_store=handles)
    async with app.run_test() as pilot:
        try:
            await _wait_until(
                predicate=lambda: app._inbox_timer is not None and app._messaging_session is session
            )
            assert app._inbox_timer is not None
            app._inbox_timer.stop()
            store = app._inbox_store
            assert store is not None
            note = inbox_message(session_id=session.session_id)
            await store.enqueue(message=note)
            await app._poll_session_inbox()
            assert await store.list_done(session_id=session.session_id) == [note]
            await pilot.pause()
            assert model.requests == []
            prompt = app.query_one(PromptInputComponent)
            prompt.load_text("initial")
            await pilot.press("enter")
            await asyncio.wait_for(model.entered.wait(), timeout=3)
            terminal = inbox_message(session_id=session.session_id, note=False).model_copy(
                update={"payload": {"workflow_id": "wf-bridge", "orchestrator_session_id": "orch-bridge"}}
            )
            await store.enqueue(message=terminal)
            await app._poll_session_inbox()
            assert {item.message_id for item in await store.list_done(session_id=session.session_id)} == {
                note.message_id,
                terminal.message_id,
            }
            assert app._legacy_inbox_clients is not None
            for message in (note, terminal):
                client = app._legacy_inbox_clients["scheduler" if message is note else "workflow"]
                from src.agents.slo_agent.messaging.dao import LegacyInboxAdmissionDAO

                proof = await session.get_legacy_inbox_admission(
                    owner=session.messaging_owner_principal,
                    client=client,
                    admission=LegacyInboxAdmissionDAO(
                        message_id=message.message_id,
                        kind="context_note" if message is note else "agent_input",
                        text=message.text,
                    ),
                )
                assert isinstance(proof, MessageIdentityDAO)
                assert proof.sender.kind == ("scheduler" if message is note else "workflow")
            model.release.set()
            await _wait_until(predicate=lambda: len(model.requests) == 2 and not session.is_running)
            await pilot.pause()
            assert [block.text for block in app.query(UserMessageBlock)] == ["initial"]
            handle = await handles.read(workflow_id="wf-bridge", owner_session_id=session.session_id)
            assert handle is not None and handle.state == "completed"
            assert app._in_flight_task is None
            assert prompt._prompt_history._entries == ["initial"]
            assert len(app.query(".sub-agent-notice")) == 2
        finally:
            model.release.set()
    import sqlite3

    database = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
    assert database.resolve().is_relative_to(tmp_path.resolve())
    with sqlite3.connect(database=database) as connection:
        rows = connection.execute("SELECT submission_json FROM messages ORDER BY sequence").fetchall()
    submissions = [MessageSubmissionDAO.model_validate_json(row[0]) for row in rows]
    for message in (note, terminal):
        admitted = next(item for item in submissions if item.message_id == message.message_id)
        assert admitted.source_event_id == "legacy-inbox:" + message.message_id
        assert admitted.priority == "normal" and admitted.text == message.text
        assert admitted.payload.type == "text" and admitted.workflow_id is None


async def test_noncanonical_inbox_id_is_refused_without_replacement(tmp_path: Path) -> None:
    """Invalid transport identity stays claimed rather than acquiring a random UUID."""
    model = RecordingModel(responses=[])
    session = _build_factory_session(tmp_path=tmp_path, model=model)
    app = SloTUI(session=session, messaging_enabled=True)
    async with app.run_test() as pilot:
        await _wait_until(
            predicate=lambda: app._inbox_timer is not None and app._messaging_session is session
        )
        assert app._inbox_timer is not None
        app._inbox_timer.stop()
        store = app._inbox_store
        assert store is not None
        message = inbox_message(session_id=session.session_id, message_id="invalid-id")
        await store.enqueue(message=message)
        await app._poll_session_inbox()
        assert await store.list_done(session_id=session.session_id) == []
        assert await store.list_pending(session_id=session.session_id) == []
        assert (
            len(list((tmp_path / "history" / session.session_id / "inbox" / "claimed").glob("*.json"))) == 1
        )
        assert not model.requests
        assert session._message_store is not None
        assert await session._message_store.read_identities() == ()


@pytest.mark.parametrize(argnames="raises", argvalues=[False, True])
async def test_ack_failure_repeats_verification_not_execution(tmp_path: Path, raises: bool) -> None:
    """Failed ack is retried with original proof; one SQLite identity and application."""
    store = FailingAckInboxStore(history_root=tmp_path / "history", raises=raises)
    model = RecordingModel(responses=[])
    session = _build_factory_session(tmp_path=tmp_path, model=model)
    app = SloTUI(session=session, inbox_store=store, messaging_enabled=True)
    async with app.run_test() as pilot:
        await _wait_until(
            predicate=lambda: app._inbox_timer is not None and app._messaging_session is session
        )
        assert app._inbox_timer is not None
        app._inbox_timer.stop()
        message = inbox_message(session_id=session.session_id)
        await store.enqueue(message=message)
        await app._poll_session_inbox()
        assert await store.list_done(session_id=session.session_id) == []
        assert len(app._unacked_inbox_claims) == 1
        store.fail = False
        await app._poll_session_inbox()
        assert await store.list_done(session_id=session.session_id) == [message]
        assert app._unacked_inbox_claims == {}
        assert store.ack_calls == 2
        assert session._message_store is not None
        assert len(await session._message_store.read_identities()) == 1
        await pilot.pause()
        assert not model.requests


@pytest.mark.parametrize(argnames="edit", argvalues=[None, "text", "kind", "source", "unknown", "retained"])
async def test_restart_scan_acks_matching_admission_after_generation_change(
    tmp_path: Path, edit: str | None
) -> None:
    """Restart verifies saved target after body pruning; changed or unknown claims stay."""
    from datetime import timedelta
    from src.agents.slo_agent.messaging.dao import utcnow

    store = FailingAckInboxStore(history_root=tmp_path / "history")
    first_model = RecordingModel(responses=[])
    first = _build_factory_session(tmp_path=tmp_path, model=first_model)
    message = inbox_message(session_id=first.session_id)
    first_app = SloTUI(session=first, inbox_store=store, messaging_enabled=True)
    async with first_app.run_test() as pilot:
        await _wait_until(
            predicate=lambda: first_app._inbox_timer is not None and first_app._messaging_session is first
        )
        assert first_app._inbox_timer is not None
        first_app._inbox_timer.stop()
        original_target = first.messaging_target
        await store.enqueue(message=message)
        if edit == "unknown":
            await store.claim_next(session_id=first.session_id)
        elif edit == "retained":
            from src.agents.slo_agent.messaging.dao import LegacyInboxAdmissionDAO

            assert first_app._legacy_inbox_clients is not None
            await store.claim_next(session_id=first.session_id)
            await first._lock.acquire()
            try:
                result = await first_app._legacy_inbox_clients["scheduler"].submit(
                    submission=MessageSubmissionDAO(
                        message_id=message.message_id,
                        target=first.messaging_target,
                        kind="context_note",
                        text=message.text,
                        source_event_id="legacy-inbox:" + message.message_id,
                    )
                )
                assert isinstance(result, MessageReceiptDAO)
                assert first._message_queue is not None
                await first._message_queue.retain_pending()
            finally:
                first._lock.release()
        else:
            await first_app._poll_session_inbox()
            assert first._message_store is not None
            async with asyncio.timeout(3):
                while True:
                    identity = await first._message_store.find_identity(message_id=message.message_id)
                    assert identity is not None
                    if identity.receipt.state == "applied":
                        break
                    await asyncio.sleep(0.01)
            await first._message_store.maintain(now=utcnow() + timedelta(days=9))
    if edit not in ("unknown", "retained"):
        import sqlite3

        database = tmp_path / "history" / first.session_id / "messaging.v1.sqlite3"
        assert database.resolve().is_relative_to(tmp_path.resolve())
        with sqlite3.connect(database=database) as connection:
            assert connection.execute("SELECT count(*) FROM messages").fetchone() == (0,)
    if edit in ("text", "kind", "source"):
        changes = {
            "text": {"text": "edited"},
            "kind": {"delivery_mode": "transcript_note"},
            "source": {"kind": "workflow_started"},
        }[edit]
        changed = message.model_copy(update=changes)
        path = next((tmp_path / "history" / first.session_id / "inbox" / "claimed").glob("*.json"))
        assert path.resolve().is_relative_to(tmp_path.resolve())
        path.write_text(changed.model_dump_json(), encoding="utf-8")
    store.fail = False
    model = RecordingModel(responses=[])
    second = restart_session(root=tmp_path, session_id=first.session_id, model=model)
    app = SloTUI(session=second, inbox_store=store, messaging_enabled=True)
    async with app.run_test() as pilot:
        await _wait_until(predicate=lambda: app._inbox_timer is not None and app._messaging_session is second)
        assert app._inbox_timer is not None
        app._inbox_timer.stop()
        await pilot.pause()
        done = await store.list_done(session_id=second.session_id)
        assert done == ([message] if edit in (None, "retained") else [])
        claims = await store.read_claimed(session_id=second.session_id)
        assert len(claims) == (0 if edit in (None, "retained") else 1)
        assert second.messaging_target != original_target
        assert not model.requests
        assert second._message_store is not None
        identities = await second._message_store.read_identities()
        assert len(identities) == (0 if edit == "unknown" else 1)
        if identities:
            assert identities[0].receipt.target == original_target
            if edit == "retained":
                assert (
                    identities[0].receipt.retained_for_recovery and identities[0].receipt.state == "accepted"
                )


async def test_machine_clients_close_before_session_and_successor_rejects_old_client(tmp_path: Path) -> None:
    """Real app teardown joins all capabilities; restart never accepts a previous client."""
    from src.agents.slo_agent.messaging.dao import LegacyInboxAdmissionDAO, MessageErrorDAO

    class CheckingCloseSession(SloAgentSession):
        """Record the observable client-close cutoff before delegating real cleanup."""

        closed_clients: tuple = ()

        async def close_messaging(self) -> None:
            """Probe bound client refusal without sealing or substituting persistence."""
            for client in self.closed_clients:
                result = await client.get_receipt(message_id=message_id)
                assert isinstance(result, MessageErrorDAO) and result.code == "completing"
            await super().close_messaging()

    message_id = str(uuid4())
    session_id = str(uuid4())
    model = RecordingModel(responses=[])
    session = CheckingCloseSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, session_id=session_id, history_root=tmp_path / "history", model_name="gpt-5.4"
        ),
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    app = SloTUI(session=session, messaging_enabled=True)
    async with app.run_test() as pilot:
        await _wait_until(predicate=lambda: app._legacy_inbox_clients is not None)
        assert app._legacy_inbox_clients is not None and app._messaging_client is not None
        old_client = app._legacy_inbox_clients["scheduler"]
        session.closed_clients = (*app._legacy_inbox_clients.values(), app._messaging_client)
    successor = restart_session(root=tmp_path, session_id=session_id, model=model)
    await successor.start_messaging()
    try:
        successor.register_legacy_inbox_client(owner=successor.messaging_owner_principal, source="scheduler")
        result = await successor.get_legacy_inbox_admission(
            owner=successor.messaging_owner_principal,
            client=old_client,
            admission=LegacyInboxAdmissionDAO(message_id=message_id, kind="context_note", text="unknown"),
        )
        assert isinstance(result, MessageErrorDAO) and result.code == "unauthorized"
    finally:
        await successor.close_messaging()


async def test_startup_scan_continues_after_malformed_claim(tmp_path: Path) -> None:
    """Corrupt selected claims are reported once and later UUIDs are still verified."""
    from uuid import UUID
    from src.tui.components.chat_transcript.component import ChatTranscriptComponent

    model = RecordingModel(responses=[])
    session = _build_factory_session(tmp_path=tmp_path, model=model)
    store = SessionInboxStore(history_root=tmp_path / "history")
    messages = [
        inbox_message(session_id=session.session_id, message_id=str(UUID(int=index)))
        for index in range(1, 21)
    ]
    for message in messages:
        await store.enqueue(message=message)
        await store.claim_next(session_id=session.session_id)
    corrupt = next(
        (tmp_path / "history" / session.session_id / "inbox" / "claimed").glob(
            f"*-{messages[3].message_id}.json"
        )
    )
    assert corrupt.resolve().is_relative_to(tmp_path.resolve())
    corrupt.write_text("{broken", encoding="utf-8")
    app = SloTUI(session=session, inbox_store=store, messaging_enabled=True)
    async with app.run_test() as pilot:
        await _wait_until(
            predicate=lambda: app._messaging_session is session and app._inbox_timer is not None
        )
        assert app._inbox_timer is not None
        app._inbox_timer.stop()
        await pilot.pause()
        lines = app.query_one(ChatTranscriptComponent)._adapter.lines
        assert sum("could not be read" in text for text, _ in lines) == 1
        assert sum("was not resent" in text for text, _ in lines) == 19
        assert await store.list_done(session_id=session.session_id) == []
        assert not model.requests
        assert session._message_store is not None
        assert await session._message_store.read_identities() == ()


async def test_response_loss_retries_same_id_then_acks(tmp_path: Path) -> None:
    """A real worker result held beyond both client deadlines commits once and later verifies."""

    class LostSubmitSession(SloAgentSession):
        """Gate only the first real machine admission, after verification has finished."""

        async def admit_message(
            self, *, submission: MessageSubmissionDAO, principal: MessagePrincipalDAO
        ) -> MessageReceiptDAO | MessageErrorDAO:
            """Hold the persistence worker at the public submission boundary."""
            if submission.source_event_id and submission.source_event_id.startswith("legacy-inbox:"):
                gate.armed = True
            return await super().admit_message(submission=submission, principal=principal)

    gate = CompletionGate(hold_before=True)
    model = RecordingModel(responses=[AIMessage(content="one machine answer")])
    session_id = str(uuid4())
    from src.agents.slo_agent.messaging.dao import MessagingLimitsDAO

    session = LostSubmitSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path,
            session_id=session_id,
            history_root=tmp_path / "history",
            model_name="gpt-5.4",
            messaging_limits=MessagingLimitsDAO(admission_seconds=0.02),
        ),
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        messaging_executor_factory=lambda: gate,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    app = SloTUI(session=session, messaging_enabled=True)
    async with app.run_test() as pilot:
        try:
            await _wait_until(
                predicate=lambda: app._inbox_timer is not None and app._messaging_session is session
            )
            assert app._inbox_timer is not None
            app._inbox_timer.stop()
            store = app._inbox_store
            assert store is not None
            message = inbox_message(session_id=session_id, note=False)
            await store.enqueue(message=message)
            await app._poll_session_inbox()
            assert gate.started.is_set()
            assert await store.list_done(session_id=session_id) == []
            gate.release.set()
            await app._poll_session_inbox()
            assert await store.list_done(session_id=session_id) == [message]
            assert session._message_store is not None
            assert len(await session._message_store.read_identities()) == 1
            model.release.set()
            await _wait_until(predicate=lambda: len(model.requests) == 1 and not session.is_running)
            identity = await session._message_store.find_identity(message_id=message.message_id)
            assert identity is not None and identity.receipt.state == "applied"
            assert await session._message_store.load_application_event(message_id=message.message_id)
        finally:
            model.release.set()
            gate.release.set()


class HeldClaimInboxStore(FailingAckInboxStore):
    """Hold a real startup page after reading it, without substituting its contents."""

    def __init__(self, *, history_root: Path) -> None:
        """Expose test-owned page and release events through constructor injection."""
        super().__init__(history_root=history_root)
        self.entered = asyncio.Event()
        self.release_page = asyncio.Event()
        self.armed = False

    async def read_claimed(
        self, *, session_id: str, after_message_id: str | None = None, limit: int = 16
    ) -> tuple[SessionInboxMessageDAO, ...]:
        """Return the actual page only after the mount's captured authority can change."""
        page = await super().read_claimed(
            session_id=session_id, after_message_id=after_message_id, limit=limit
        )
        if self.armed:
            self.armed = False
            self.entered.set()
            await self.release_page.wait()
        return page


@pytest.mark.parametrize(argnames="cutoff", argvalues=["displace", "shutdown"])
async def test_mounted_startup_scan_does_not_ack_after_cutoff(tmp_path: Path, cutoff: str) -> None:
    """DC08 critical cutoff: a held page cannot acknowledge or paint a displaced binding."""
    from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO
    from src.tui.components.chat_transcript.component import ChatTranscriptComponent

    store = HeldClaimInboxStore(history_root=tmp_path / "history")
    model = RecordingModel(responses=[])
    session = _build_factory_session(tmp_path=tmp_path, model=model)
    message = inbox_message(session_id=session.session_id)
    candidate = _build_factory_session(tmp_path=tmp_path, model=model)
    app = SloTUI(session=session, inbox_store=store, messaging_enabled=True)
    async with app.run_test() as pilot:
        await _wait_until(
            predicate=lambda: app._inbox_timer is not None and app._messaging_session is session
        )
        assert app._inbox_timer is not None
        app._inbox_timer.stop()
        await store.enqueue(message=message)
        await app._poll_session_inbox()
        assert await store.list_done(session_id=session.session_id) == []
        assert session._message_store is not None
        async with asyncio.timeout(3):
            while True:
                identity = await session._message_store.find_identity(message_id=message.message_id)
                if identity is not None and identity.receipt.state == "applied":
                    break
                await asyncio.sleep(0.01)
        await pilot.pause()
        store.fail = False
        ack_calls_before = store.ack_calls
        store.armed = True
        scan = asyncio.create_task(app._scan_recovered_inbox_claims(session=session))
        try:
            await asyncio.wait_for(store.entered.wait(), timeout=3)
            assert app.query_one(PromptInputComponent).is_mounted
            lines_before = tuple(app.query_one(ChatTranscriptComponent)._adapter.lines)
            if cutoff == "displace":
                app._adopt_replacement_session(
                    old_session=session,
                    candidate=candidate,
                    outcome=HerdrReporterCloseOutcomeDAO(replacement="safe"),
                )
            else:
                app._app_closing = True
            store.release_page.set()
            await asyncio.wait_for(scan, timeout=3)
            await pilot.pause()
            assert await store.list_done(session_id=session.session_id) == []
            assert len(await store.read_claimed(session_id=session.session_id)) == 1
            assert tuple(app.query_one(ChatTranscriptComponent)._adapter.lines) == lines_before
            assert not model.requests
            assert session._message_store is not None
            assert len(await session._message_store.read_identities()) == 1
            assert store.ack_calls == ack_calls_before
        finally:
            store.release_page.set()
            await asyncio.gather(scan, return_exceptions=True)
            await app._close_session_messaging(session=session)
            await candidate.close_messaging()


async def test_machine_verification_storage_failure_keeps_claim_and_refuses_next_input(
    tmp_path: Path,
) -> None:
    """DC08 critical failure: real SQLite damage during machine verification never acknowledges."""
    import sqlite3
    from src.tui.components.chat_transcript.component import ChatTranscriptComponent

    model = RecordingModel(responses=[])
    session = _build_factory_session(tmp_path=tmp_path, model=model)
    app = SloTUI(session=session, messaging_enabled=True)
    async with app.run_test() as pilot:
        await _wait_until(
            predicate=lambda: app._inbox_timer is not None and app._messaging_session is session
        )
        assert app._inbox_timer is not None and app._inbox_store is not None
        app._inbox_timer.stop()
        database = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
        assert database.resolve().is_relative_to(tmp_path.resolve())
        target = session.messaging_target
        principal = session.messaging_owner_principal
        with sqlite3.connect(database=database) as connection:
            connection.execute("DROP TABLE identity")
        message = inbox_message(session_id=session.session_id)
        await app._inbox_store.enqueue(message=message)
        await app._poll_session_inbox()
        await pilot.pause()
        assert await app._inbox_store.list_done(session_id=session.session_id) == []
        assert len(await app._inbox_store.read_claimed(session_id=session.session_id)) == 1
        lines = app.query_one(ChatTranscriptComponent)._adapter.lines
        assert any("storage_unavailable" in text for text, _ in lines)
        result = await session.admit_message(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=target, kind="agent_input", text="forbidden"
            ),
            principal=principal,
        )
        assert isinstance(result, MessageErrorDAO) and result.code == "storage_unavailable"
        assert not model.requests and app._in_flight_task is None
