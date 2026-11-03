"""DC06 mounted controls over the real scheduler, SQLite and history."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from textual.pilot import Pilot

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.messaging.dao import MessageErrorDAO, MessageReceiptDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from tests.tui.recording_prompt import RecordingPromptInput
from src.tui.components.chat_transcript.commands import PresentMessageApplicationDAO
from src.tui.components.chat_transcript.component import ChatTranscriptComponent
from src.tui.components.prompt_input.component import PromptInputComponent
from src.tui.widgets.user_message_block import UserMessageBlock
from tests.agents.slo_agent.messaging.test_delivery import RecordingModel, RealAgentFactory
from tests.integration.test_session_messaging import read_closed_message_rows
from tests.tui.test_durable_composer import _wait_until
from tests.tui.test_messages_command import slash, notices


class ControlProbeTUI(SloTUI):
    """Record any accidental app-owned abort escalation without replacing behavior."""

    CSS_PATH = str(Path(__file__).resolve().parents[2] / "src/tui/app.tcss")
    escalation_calls: int = 0

    def _escalate_abort(self) -> None:
        """Expose the forbidden messaging control branch while preserving legacy behavior."""
        self.escalation_calls += 1
        super()._escalate_abort()


def controlled_session(
    *, root: Path, session_type: type[SloAgentSession] = SloAgentSession
) -> tuple[SloAgentSession, RecordingModel]:
    """Compose existing real session and held vendor fixture under the test root."""
    model = RecordingModel(responses=[AIMessage(content=f"answer {i}") for i in range(8)])
    session_id = str(uuid4())
    history_root = root / "history"
    session = session_type(
        workdir=root,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=root, session_id=session_id, history_root=history_root, model_name="gpt-5.4"
        ),
        history_store=FilesystemSessionHistoryStore(root=history_root),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=root),
    )
    return session, model


@asynccontextmanager
async def mounted(*, app: SloTUI, model: RecordingModel) -> AsyncIterator[Pilot]:
    """Always release the vendor gate before joined app teardown, including assertion failures."""
    async with app.run_test(size=(120, 40)) as pilot:
        try:
            yield pilot
        finally:
            model.release.set()


async def enter(*, app: SloTUI, pilot: Pilot, text: str) -> str:
    """Submit through Enter and wait for its exact durable receipt."""
    prompt = app.query_one(RecordingPromptInput)
    before = len(prompt.outcomes)
    prompt.load_text(text=text)
    await pilot.press("enter")
    await _wait_until(predicate=lambda: len(prompt.outcomes) == before + 1)
    return prompt.outcomes[-1].draft_submission.message_submission.message_id


@pytest.mark.parametrize(argnames="resume", argvalues=[False, True])
async def test_abort_pauses_and_keeps_pending(tmp_path: Path, resume: bool) -> None:
    """Slash abort preserves accepted input; an ordinary submit resumes exact order once."""
    session, model = controlled_session(root=tmp_path)
    app = ControlProbeTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    async with mounted(app=app, model=model) as pilot:
        first = await enter(app=app, pilot=pilot, text="first")
        await _wait_until(predicate=model.entered.is_set)
        pending = [await enter(app=app, pilot=pilot, text=text) for text in ("second", "third")]
        await slash(app=app, pilot=pilot, line="/abort")
        assert "Pending messages are kept; send a new prompt or use /messages continue to resume." in notices(
            app=app
        )
        assert app._in_flight_task is None and app.escalation_calls == 0
        model.release.set()
        await _wait_until(predicate=lambda: not session.is_running)
        await pilot.pause()
        assert len(model.requests) == 1
        assert not app._exit
        assert session.history_store is not None
        events = await session.history_store.load_events(session_id=session.session_id)
        assert any(event.kind == "run_aborted" for event in events)
        assert app._messaging_client is not None
        for message_id in pending:
            receipt = await app._messaging_client.get_receipt(message_id=message_id)
            assert isinstance(receipt, MessageReceiptDAO)
            assert receipt.state == "accepted" and not receipt.retained_for_recovery
        note_id = str(uuid4())
        from src.agents.slo_agent.messaging.dao import MessageSubmissionDAO

        note = await app._messaging_client.submit(
            submission=MessageSubmissionDAO(
                message_id=note_id, target=session.messaging_target, kind="context_note", text="note alone"
            )
        )
        assert isinstance(note, MessageReceiptDAO)
        await pilot.pause()
        assert len(model.requests) == 1
        if resume:
            last = await enter(app=app, pilot=pilot, text="next")
            await _wait_until(predicate=lambda: len(model.requests) == 4 and not session.is_running)
            events = await session.history_store.load_events(session_id=session.session_id)
            applications = [
                event
                for event in events
                if event.payload.metadata.get("messaging_v1", {}).get("kind") == "agent_input"
            ]
            assert [event.payload.content for event in applications] == ["first", "second", "third", "next"]
            assert [event.payload.metadata["messaging_v1"]["message_id"] for event in applications] == [
                first,
                *pending,
                last,
            ]
            assert [
                [message.content for message in request if isinstance(message, HumanMessage)]
                for request in model.requests
            ] == [
                ["first"],
                ["first", "note alone", "second"],
                ["first", "note alone", "second", "third"],
                ["first", "note alone", "second", "third", "next"],
            ]
    rows = read_closed_message_rows(
        database_path=tmp_path / "history" / session.session_id / "messaging.v1.sqlite3",
        temporary_root=tmp_path,
    )
    rows = tuple(row for row in rows if row[0] != note_id)
    assert rows == tuple(
        (message_id, 0 if resume or index == 0 else 1, "applied" if resume or index == 0 else "accepted")
        for index, message_id in enumerate([first, *pending, *([last] if resume else [])])
    )


@pytest.mark.parametrize(argnames="control", argvalues=["/clear", "ctrl+l"])
async def test_clear_never_cancels_or_reechoes(tmp_path: Path, control: str) -> None:
    """Display clear keeps the observed band, identity, recall and newer editor draft."""
    session, model = controlled_session(root=tmp_path)
    app = ControlProbeTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    async with mounted(app=app, model=model) as pilot:
        await enter(app=app, pilot=pilot, text="applied")
        await _wait_until(predicate=model.entered.is_set)
        pending = await enter(app=app, pilot=pilot, text="pending")
        await _wait_until(predicate=lambda: app._queued_prompt_block is not None)
        prompt = app.query_one(RecordingPromptInput)
        recall = tuple(prompt._prompt_history._entries)
        if control == "/clear":
            await slash(app=app, pilot=pilot, line=control)
        else:
            prompt.load_text(text="newer draft")
            await pilot.press(control)
            assert prompt.text == "newer draft"
        assert tuple(prompt._prompt_history._entries) == recall
        assert not app.query(UserMessageBlock)
        assert app._queued_prompt_block is not None and app._queued_prompt_block.queued_text == "pending"
        assert session.history_store is not None
        from src.agents.slo_agent.history.transcript import ReplayEntryProjector

        events = await session.history_store.load_events(session_id=session.session_id)
        entry = next(
            entry
            for entry in ReplayEntryProjector.build_entries(events=events)
            if entry.application is not None
        )
        await app.query_one(ChatTranscriptComponent).handle(command=PresentMessageApplicationDAO(entry=entry))
        assert not app.query(UserMessageBlock)
        model.release.set()
        await _wait_until(predicate=lambda: len(model.requests) == 2 and not session.is_running)
        await pilot.pause()
        assert [block.text for block in app.query(UserMessageBlock)] == ["pending"]
    rows = read_closed_message_rows(
        database_path=tmp_path / "history" / session.session_id / "messaging.v1.sqlite3",
        temporary_root=tmp_path,
    )
    assert len(rows) == 2 and rows[1] == (pending, 0, "applied")


class SuccessorFactory:
    """Inject a real held-model successor through the existing replacement seam."""

    def __init__(self) -> None:
        """Record candidates without mutating selected app state."""
        self.sessions: list[SloAgentSession] = []
        self.models: list[RecordingModel] = []

    def __call__(self, *, config: SessionConfigDAO, allow_pending_preparation: bool) -> SloAgentSession:
        """Build a prepared real session using the predecessor's history root."""
        model = RecordingModel(responses=[AIMessage(content="successor answer")])
        model.release.set()
        session = SloAgentSession(
            workdir=config.workdir,
            session_id=str(uuid4()),
            config=config,
            history_store=FilesystemSessionHistoryStore(root=config.history_root),
            messaging_agent_factory=RealAgentFactory(model=model, workdir=config.workdir),
        )
        self.sessions.append(session)
        self.models.append(model)
        return session


async def test_new_retires_binding_closes_old_and_never_redirects(tmp_path: Path) -> None:
    """Old accepted input and rejected drafts stay old; close releases lease before adoption."""
    from tests.tui.test_composer_retirement import bind_script, submit, refusal
    from tests.tui.test_durable_composer import ScriptedMessagingClient
    from src.agents.slo_agent.messaging.ownership import SessionExecutionOwnership

    old, model = controlled_session(root=tmp_path)
    factory = SuccessorFactory()
    app = SloTUI(
        prompt_factory=RecordingPromptInput, session=old, messaging_enabled=True, session_factory=factory
    )
    async with mounted(app=app, model=model) as pilot:
        await enter(app=app, pilot=pilot, text="first")
        await _wait_until(predicate=model.entered.is_set)
        pending = await enter(app=app, pilot=pilot, text="old pending")
        await slash(app=app, pilot=pilot, line="/abort")
        model.release.set()
        await _wait_until(predicate=lambda: not old.is_running)
        old_client = app._messaging_client
        observation = app._messaging_observation_task
        target = old.messaging_target
        scripted = ScriptedMessagingClient(always=refusal)
        prompt = await bind_script(app=app, client=scripted)
        draft = await submit(prompt=prompt, text="old recoverable")
        adapter = prompt._submission_adapter
        assert adapter is not None
        await adapter.reset()
        await slash(app=app, pilot=pilot, line="/new")
        successor = app._session
        assert successor is not old and successor is factory.sessions[0]
        await _wait_until(predicate=lambda: app._messaging_session is successor)
        assert not old.is_messaging_ready
        assert observation is not None and observation.done()
        assert adapter._closed and adapter._client is None
        assert old_client is not None
        assert await old_client.get_receipt(message_id=pending) == MessageErrorDAO(
            code="completing", message_id=pending
        )
        assert successor.messaging_target != target
        assert prompt._submission_adapter is not adapter and not prompt._submission_sealed
        held = app.list_retained_drafts()
        assert len(held) == 1 and held[0].draft_submission == draft
        assert held[0].draft_submission.message_submission.target == target
        assert read_closed_message_rows(
            database_path=tmp_path / "history" / old.session_id / "messaging.v1.sqlite3",
            temporary_root=tmp_path,
        )[1] == (pending, 1, "accepted")
        lease = await SessionExecutionOwnership.acquire(root=tmp_path / "history", session_id=old.session_id)
        await lease.release()
        await slash(app=app, pilot=pilot, line=f"/messages retry {draft.message_submission.message_id}")
        assert "Draft belongs to a previous session" in notices(app=app)
        fresh = await enter(app=app, pilot=pilot, text="fresh successor input")
        await _wait_until(predicate=lambda: len(factory.models[0].requests) == 1 and not successor.is_running)
        assert app._lease_store is not None
        assert await app._lease_store.read(session_id=old.session_id) is None
        lease_row = await app._lease_store.read(session_id=successor.session_id)
        assert lease_row is not None and lease_row.owner_id == app._session_owner_id
    assert read_closed_message_rows(
        database_path=tmp_path / "history" / successor.session_id / "messaging.v1.sqlite3",
        temporary_root=tmp_path,
    ) == ((fresh, 0, "applied"),)


async def test_new_refused_while_running(tmp_path: Path) -> None:
    """A held real provider refuses /new before any candidate or owner close."""
    old, model = controlled_session(root=tmp_path)
    factory = SuccessorFactory()
    app = SloTUI(
        prompt_factory=RecordingPromptInput, session=old, messaging_enabled=True, session_factory=factory
    )
    async with mounted(app=app, model=model) as pilot:
        await enter(app=app, pilot=pilot, text="running")
        await _wait_until(predicate=model.entered.is_set)
        client = app._messaging_client
        observation = app._messaging_observation_task
        await slash(app=app, pilot=pilot, line="/new")
        assert "cannot start a new session while a prompt is in flight" in notices(app=app)
        assert not factory.sessions and old.is_messaging_ready
        assert app._session is old and app._messaging_client is client
        assert (
            app._messaging_observation_task is observation
            and observation is not None
            and not observation.done()
        )


async def test_new_refused_when_drafts_cannot_be_kept(tmp_path: Path) -> None:
    """Full host handoff discards only the candidate and leaves old binding usable."""
    from tests.tui.test_composer_retirement import bind_script, submit, refusal
    from tests.tui.test_durable_composer import ScriptedMessagingClient
    from src.tui.components.prompt_input.submission import (
        DraftSubmissionDAO,
        DraftHandoffDAO,
        RetrySubmissionDAO,
    )
    from src.agents.slo_agent.messaging.dao import MessageSubmissionDAO

    old, model = controlled_session(root=tmp_path)
    factory = SuccessorFactory()
    app = SloTUI(
        prompt_factory=RecordingPromptInput, session=old, messaging_enabled=True, session_factory=factory
    )
    async with mounted(app=app, model=model) as pilot:
        scripted = ScriptedMessagingClient(always=refusal)
        prompt = await bind_script(app=app, client=scripted)
        draft = await submit(prompt=prompt, text="keep component draft")
        adapter = prompt._submission_adapter
        assert adapter is not None
        await adapter.reset()
        target = old.messaging_target
        held = tuple(
            DraftSubmissionDAO(
                message_submission=MessageSubmissionDAO(
                    message_id=str(uuid4()), target=target, kind="agent_input", text=f"held {i}"
                ),
                draft_revision=0,
                binding_version=0,
            )
            for i in range(16)
        )
        ack = await app.retain_unresolved_drafts(
            handoff=DraftHandoffDAO(handoff_id=str(uuid4()), target=target, binding_version=0, drafts=held)
        )
        assert ack.accepted
        client = app._messaging_client
        observation = app._messaging_observation_task
        await slash(app=app, pilot=pilot, line="/new")
        assert "Cannot start a new session: unsent drafts could not be kept." in notices(app=app)
        assert len(factory.sessions) == 1 and not factory.sessions[0].is_messaging_ready
        assert (
            factory.sessions[0]._herdr_close_task is not None and factory.sessions[0]._herdr_close_task.done()
        )
        assert app._session is old and old.is_messaging_ready and not old._herdr_closing
        assert app._messaging_client is client and app._messaging_observation_task is observation
        assert prompt._submission_adapter is adapter and not adapter._closed and not prompt._submission_sealed
        assert prompt.list_recoverable_drafts()[0].draft_submission == draft
        scripted._outcomes[draft.message_submission.message_id] = MessageErrorDAO(
            code="not_found", message_id=draft.message_submission.message_id
        )
        await prompt.handle(command=RetrySubmissionDAO(message_id=draft.message_submission.message_id))
        await adapter.reset()
        assert scripted.submit_calls == [draft.message_submission] * 2
        assert scripted.receipt_calls == [draft.message_submission.message_id]


@pytest.mark.parametrize(argnames="running", argvalues=[False, True])
async def test_ctrl_c_distinguishes_idle_and_running(tmp_path: Path, running: bool) -> None:
    """Actual Ctrl+C pauses session-owned work, or warns once and exits when idle."""
    from tests.tui.test_composer_retirement import bind_script, submit, refusal
    from tests.tui.test_durable_composer import ScriptedMessagingClient

    session, model = controlled_session(root=tmp_path)
    app = ControlProbeTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    async with mounted(app=app, model=model) as pilot:
        if running:
            await enter(app=app, pilot=pilot, text="running")
            await _wait_until(predicate=model.entered.is_set)
            pending = await enter(app=app, pilot=pilot, text="pending")
        else:
            prompt = await bind_script(app=app, client=ScriptedMessagingClient(always=refusal))
            await submit(prompt=prompt, text="unsent")
            assert prompt._submission_adapter is not None
            await prompt._submission_adapter.reset()
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert not app._exit
        assert app.escalation_calls == 0
        if running:
            assert "(aborting…)" in notices(app=app) and "Pending messages are kept" in notices(app=app)
            model.release.set()
            await _wait_until(predicate=lambda: not session.is_running)
            await pilot.pause()
            assert len(model.requests) == 1
            assert app._messaging_client is not None
            receipt = await app._messaging_client.get_receipt(message_id=pending)
            assert isinstance(receipt, MessageReceiptDAO) and receipt.state == "accepted"
        else:
            assert "1 unsent drafts will be lost" in notices(app=app)
            await pilot.press("ctrl+c")
    if not running:
        assert app._messaging_client is None and app._messaging_session is None


class HeldCloseSession(SloAgentSession):
    """Injected session gateway holds actual predecessor cleanup, then optionally loses its reply."""

    def __init__(
        self,
        *,
        workdir: Path,
        session_id: str,
        config: SessionConfigDAO,
        history_store: FilesystemSessionHistoryStore,
        messaging_agent_factory: RealAgentFactory,
    ) -> None:
        """Keep close gates local to this disposable owner."""
        super().__init__(
            workdir=workdir,
            session_id=session_id,
            config=config,
            history_store=history_store,
            messaging_agent_factory=messaging_agent_factory,
        )
        self.close_entered = asyncio.Event()
        self.close_release = asyncio.Event()
        self.fail_after_close = False

    async def close_messaging(self) -> None:
        """Hold the owner close boundary; actual cleanup still uses the real session."""
        self.close_entered.set()
        await self.close_release.wait()
        await super().close_messaging()
        if self.fail_after_close:
            self.fail_after_close = False
            raise OSError("simulated close response loss")


@pytest.mark.parametrize(argnames="failure", argvalues=[False, True])
async def test_new_joins_predecessor_cleanup_before_adopting(tmp_path: Path, failure: bool) -> None:
    """Caller cancellation joins committed replacement; cleanup faults suppress delivery, not adoption."""
    old, model = controlled_session(root=tmp_path, session_type=HeldCloseSession)
    assert isinstance(old, HeldCloseSession)
    factory = SuccessorFactory()
    app = SloTUI(
        prompt_factory=RecordingPromptInput, session=old, messaging_enabled=True, session_factory=factory
    )
    async with mounted(app=app, model=model) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: app._messaging_session is old)
        prompt = app.query_one(RecordingPromptInput)
        adapter = prompt._submission_adapter
        observation = app._messaging_observation_task
        client = app._messaging_client
        old.fail_after_close = failure
        replacement = asyncio.create_task(coro=app._dispatch_slash_command(line="/new"))
        try:
            await _wait_until(predicate=old.close_entered.is_set)
            assert app._session is old and not replacement.done()
            assert adapter is not None and adapter._closed and adapter._client is None
            assert observation is not None and observation.done()
            assert client is not None
            message_id = str(uuid4())
            assert await client.get_receipt(message_id=message_id) == MessageErrorDAO(
                code="completing", message_id=message_id
            )
            assert not factory.sessions[0].is_messaging_ready
            if not failure:
                replacement.cancel()
                await asyncio.sleep(0)
                replacement.cancel()
                await asyncio.sleep(0)
                assert not replacement.done()
            old.close_release.set()
            if failure:
                await replacement
                assert not app._replacement_delivery_safe
                assert "Previous session messaging cleanup incomplete." in notices(app=app)
            else:
                with pytest.raises(asyncio.CancelledError):
                    await replacement
            assert app._session is factory.sessions[0] and app._messaging_session is app._session
            assert not old.is_messaging_ready
        finally:
            old.close_release.set()
            await asyncio.gather(replacement, return_exceptions=True)


async def test_clear_preserves_recoverable_drafts_and_abort_without_pending_is_quiet(tmp_path: Path) -> None:
    """Clear never retires unsent snapshots; no observed pending input means no survival hint."""
    from tests.tui.test_composer_retirement import bind_script, submit, refusal
    from tests.tui.test_durable_composer import ScriptedMessagingClient

    session, model = controlled_session(root=tmp_path)
    app = ControlProbeTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    async with mounted(app=app, model=model) as pilot:
        prompt = await bind_script(app=app, client=ScriptedMessagingClient(always=refusal))
        draft = await submit(prompt=prompt, text="recoverable")
        adapter = prompt._submission_adapter
        assert adapter is not None
        await adapter.reset()
        await slash(app=app, pilot=pilot, line="/clear")
        assert prompt.list_recoverable_drafts()[0].draft_submission == draft
        assert prompt._submission_adapter is adapter and not adapter._closed
        await slash(app=app, pilot=pilot, line="/abort")
        assert "Pending messages are kept" not in notices(app=app)
        assert app.escalation_calls == 0
        assert not model.requests
