"""Messaging application identity across replay and presentation lifetimes (DC03)."""

from pathlib import Path
from tests.tui.recording_prompt import RecordingPromptInput
from uuid import UUID, uuid4, uuid5

from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.agents.slo_agent.messaging.dao import MessageSubmissionDAO, MessageReceiptDAO, MessageErrorDAO

import pytest

from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.transcript import ReplayEntryProjector
from src.agents.slo_agent.messaging.dao import MessageApplicationMetadataDAO, MessagePrincipalDAO
from src.tui.components.chat_transcript.adapters.transcript_projector import TranscriptProjectionAdapter
from src.tui.components.chat_transcript.commands import ProjectReplayEntryDAO
from tests.tui.test_transcript_projector import FakeHost


def application_event(*, sender_kind: str = "human", kind: str = "agent_input") -> SessionHistoryEventDAO:
    """Construct canonical provenance independently of the transcript implementation."""
    session_id = str(uuid4())
    metadata = MessageApplicationMetadataDAO(
        message_id=str(uuid4()),
        kind=kind,  # type: ignore[arg-type]
        sender=MessagePrincipalDAO(principal_id="owner", kind=sender_kind),  # type: ignore[arg-type]
        sequence=1,
        run_id=str(uuid4()),
        execution_generation=str(uuid4()),
    )
    return SessionHistoryEventDAO(
        session_id=session_id,
        event_id=str(uuid5(namespace=UUID(session_id), name="message:" + metadata.message_id)),
        turn_id=metadata.run_id,
        kind="workflow_update",
        payload=SessionHistoryEventPayloadDAO(
            content="exact input", metadata={"messaging_v1": metadata.model_dump(mode="json")}
        ),
    )


@pytest.mark.asyncio
async def test_reset_and_clear_preserve_binding_identity() -> None:
    """Per-run reset suppresses a repeated application; binding retirement permits rebuilding."""
    from src.tui.components.chat_transcript.commands import RetireHistoryBindingDAO

    host = FakeHost()
    adapter = TranscriptProjectionAdapter.register(host=host)
    entry = ReplayEntryProjector.build_entries(events=[application_event()])[0]
    await adapter.handle(event=ProjectReplayEntryDAO(entry=entry))
    await adapter.reset()
    await adapter.handle(event=ProjectReplayEntryDAO(entry=entry))
    assert len(host.user_blocks) == 1
    await adapter.handle(event=RetireHistoryBindingDAO())
    await adapter.handle(event=ProjectReplayEntryDAO(entry=entry))
    assert len(host.user_blocks) == 2
    await adapter.close()


@pytest.mark.asyncio
async def test_conflicting_same_id_evidence_fails_safely() -> None:
    """Conflicting content never creates another echo or repeated recovery notice."""
    host = FakeHost()
    adapter = TranscriptProjectionAdapter.register(host=host)
    event = application_event()
    changed = event.model_copy(update={"payload": event.payload.model_copy(update={"content": "changed"})})
    for item in (event, changed, changed, event):
        entry = ReplayEntryProjector.build_entries(events=[item])[0]
        await adapter.handle(event=ProjectReplayEntryDAO(entry=entry))
    assert len(host.user_blocks) == 1
    assert host.lines == [
        ("Conflicting history for one message; resume the session to recover.", "tool-result")
    ]
    await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(argnames="kind", argvalues=["context_note", "agent_input", "transcript_note"])
async def test_machine_applications_keep_machine_styling(kind: str) -> None:
    """Non-human applications use the existing machine notice path, never user styling."""
    host = FakeHost()
    adapter = TranscriptProjectionAdapter.register(host=host)
    entry = ReplayEntryProjector.build_entries(
        events=[application_event(sender_kind="scheduler", kind=kind)]
    )[0]
    await adapter.handle(event=ProjectReplayEntryDAO(entry=entry))
    assert host.user_blocks == []
    assert host.lines == [("⊛ exact input", "sub-agent-notice")]
    assert entry.application is not None
    await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(argnames="layout", argvalues=["flat", "tree"])
async def test_live_echo_once_per_id_with_band(tmp_path: Path, layout: str) -> None:
    """Real mounted Enter → SQLite/history → provider → transcript, followed by replay."""
    from pathlib import Path
    from langchain_core.messages import AIMessage
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
    from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.tui.app import SloTUI
    from src.tui.components.prompt_input.component import PromptInputComponent
    from src.tui.components.chat_transcript.component import ChatTranscriptComponent
    from src.tui.widgets.user_message_block import UserMessageBlock
    from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
    from tests.agents.slo_agent.messaging.test_delivery import RecordingModel, RealAgentFactory
    from tests.tui.test_durable_composer import _wait_until

    root: Path = tmp_path / "history"
    store = (
        FilesystemSessionHistoryStore(root=root)
        if layout == "flat"
        else TreeBasedFilesystemSessionHistoryStore(root=root)
    )
    model = RecordingModel(responses=[AIMessage(content=f"answer {index}") for index in range(3)])
    session_id = str(uuid4())
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, session_id=session_id, history_root=root, model_name="gpt-5.4"
        ),
        history_store=store,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path, stop_hook=None),
    )
    app = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    texts = ["one", "two", "three"]
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await _wait_until(
                predicate=lambda: app._messaging_session is session
                and app._messaging_observation_task is not None
            )
            prompt = app.query_one(RecordingPromptInput)
            for index, text in enumerate(texts):
                prompt.load_text(text)
                await pilot.press("enter")
                await _wait_until(predicate=lambda: len(prompt.outcomes) == index + 1)
                if index == 0:
                    await _wait_until(predicate=model.entered.is_set)
            await _wait_until(predicate=lambda: app._queued_prompt_block is not None)
            assert app._queued_prompt_block is not None
            assert app._queued_prompt_block.queued_text == "two"
            assert app._spinner is not None
            model.release.set()
            await _wait_until(predicate=lambda: len(model.requests) == 3 and not session.is_running)
            await _wait_until(
                predicate=lambda: len(app.query(UserMessageBlock)) == 3 and app._spinner is None
            )
            transcript = app.query_one(ChatTranscriptComponent)
            children = list(transcript.query_one("#transcript-content").children)
            order = [
                ("user", child.text) if isinstance(child, UserMessageBlock) else ("answer", child.answer_text)
                for child in children
                if isinstance(child, (UserMessageBlock, AssistantStreamBlock))
            ]
            assert order == [
                (kind, text)
                for index in range(3)
                for kind, text in (("user", texts[index]), ("answer", f"answer {index}"))
            ]
            assert app._queued_prompt_block is None
            assert prompt._prompt_history._entries == texts
            assert app._messaging_run_presented is False
    finally:
        model.release.set()
        await session.close_messaging()
    # Fresh owner generation, same real flat/tree history. Replay must not add recall.
    replay = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, session_id=session_id, history_root=root, model_name="gpt-5.4"
        ),
        history_store=store,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path, stop_hook=None),
    )
    replay_app = SloTUI(prompt_factory=RecordingPromptInput, session=replay, messaging_enabled=True)
    async with replay_app.run_test(size=(120, 40)) as pilot:
        await _wait_until(predicate=lambda: replay_app._messaging_observation_task is not None)
        await pilot.pause()
        assert [child.text for child in replay_app.query(UserMessageBlock)] == texts
        assert replay_app.query_one(RecordingPromptInput)._prompt_history._entries == []
        assert len(model.requests) == 3


@pytest.mark.asyncio
async def test_component_clear_preserves_identity_until_history_rebind(tmp_path: Path) -> None:
    """Public component clear and begin-run routes preserve ID/hash; rebind rebuilds it."""
    from src.tui.app import SloTUI
    from src.tui.components.chat_transcript.component import ChatTranscriptComponent
    from src.tui.components.chat_transcript.commands import (
        PresentMessageApplicationDAO,
        BeginTranscriptRunDAO,
        ClearTranscriptDAO,
        BindHistoryDAO,
    )
    from src.tui.widgets.user_message_block import UserMessageBlock
    from tests.tui.test_prompt_component_protocol import build_session

    app = SloTUI(prompt_factory=RecordingPromptInput, session=build_session(tmp_path=tmp_path))
    entry = ReplayEntryProjector.build_entries(events=[application_event()])[0]
    async with app.run_test() as pilot:
        await pilot.pause()
        transcript = app.query_one(ChatTranscriptComponent)
        await transcript.handle(command=PresentMessageApplicationDAO(entry=entry))
        await transcript.handle(command=BeginTranscriptRunDAO())
        await transcript.handle(command=PresentMessageApplicationDAO(entry=entry))
        assert len(transcript.query(UserMessageBlock)) == 1
        await transcript.handle(command=ClearTranscriptDAO())
        await transcript.handle(command=PresentMessageApplicationDAO(entry=entry))
        assert len(transcript.query(UserMessageBlock)) == 0
        await transcript.handle(
            command=BindHistoryDAO(history_reader=app._session.hydrate_transcript_entries)
        )
        await transcript.handle(command=PresentMessageApplicationDAO(entry=entry))
        assert len(transcript.query(UserMessageBlock)) == 1


@pytest.mark.asyncio
async def test_application_before_receipt_records_recall_once(tmp_path: Path) -> None:
    """A delayed real-client response lets canonical application win the recall race."""
    import asyncio
    from langchain_core.messages import AIMessage
    from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
    from src.tui.app import SloTUI
    from src.tui.components.prompt_input.component import PromptInputComponent
    from src.tui.widgets.user_message_block import UserMessageBlock
    from tests.agents.slo_agent.messaging.test_delivery import RecordingModel
    from tests.tui.test_durable_composer import _build_factory_session, _wait_until

    class DelayedReceiptClient(LocalSessionMessagingClient):
        """Inject response delay only; admission and execution remain real."""

        def __init__(self, *, session: SloAgentSession) -> None:
            """Bind real authority and a test-owned response gate."""
            super().__init__(
                session=session, target=session.messaging_target, principal=session.messaging_owner_principal
            )
            self.release_response = asyncio.Event()

        async def submit(self, *, submission: MessageSubmissionDAO) -> MessageReceiptDAO | MessageErrorDAO:
            """Admit durably before holding the response, never the transaction."""
            receipt = await super().submit(submission=submission)
            await self.release_response.wait()
            return receipt

    model = RecordingModel(responses=[AIMessage(content="answer")])
    session = _build_factory_session(tmp_path=tmp_path, model=model)
    clients = []

    def client_factory(session: SloAgentSession) -> DelayedReceiptClient:
        """Retain the injected real-client response gate."""
        client = DelayedReceiptClient(session=session)
        clients.append(client)
        return client

    app = SloTUI(
        prompt_factory=RecordingPromptInput,
        session=session,
        messaging_enabled=True,
        messaging_client_factory=client_factory,
    )
    try:
        async with app.run_test() as pilot:
            await _wait_until(predicate=lambda: app._messaging_session is session)
            prompt = app.query_one(RecordingPromptInput)
            prompt.load_text("recall race")
            await pilot.press("enter")
            await _wait_until(predicate=lambda: len(app.query(UserMessageBlock)) == 1)
            assert prompt.outcomes == []
            assert prompt._prompt_history._entries == ["recall race"]
            clients[0].release_response.set()
            await _wait_until(predicate=lambda: len(prompt.outcomes) == 1)
            assert prompt._prompt_history._entries == ["recall race"]
            assert len(app.query(UserMessageBlock)) == 1
            model.release.set()
            await _wait_until(predicate=lambda: not session.is_running)
    finally:
        for client in clients:
            client.release_response.set()
        model.release.set()
        await session.close_messaging()


@pytest.mark.asyncio
@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_compacted_messages_are_not_fabricated_on_replay(tmp_path: Path, tree: bool) -> None:
    """Existing real compaction owner commits coverage; remount shows summary, not old echoes."""
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
    from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.tui.app import SloTUI
    from src.tui.components.chat_transcript.component import ChatTranscriptComponent
    from src.tui.widgets.user_message_block import UserMessageBlock
    from tests.agents.slo_agent.messaging.test_delivery import (
        test_session_compaction_commits_exact_coverage_through_existing_owner,
    )
    from tests.tui.test_durable_composer import _wait_until

    # Reuse the specification's real SQLite/flat+tree compaction setup unchanged.
    await test_session_compaction_commits_exact_coverage_through_existing_owner(tmp_path=tmp_path, tree=tree)
    root = tmp_path / "history"
    session_id = next(root.iterdir()).name
    store = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, session_id=session_id, history_root=root, model_name="gpt-5.4"
        ),
        history_store=store,
    )
    app = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    async with app.run_test() as pilot:
        await _wait_until(predicate=lambda: app._messaging_observation_task is not None)
        await pilot.pause()
        # This existing setup compacts instructions 0/1 and retains the exact
        # four-body tail. Only that tail may echo; coverage cannot invent 0/1.
        assert [child.text for child in app.query(UserMessageBlock)] == [
            f"Applied instruction {index} " + "x" * 20000 for index in range(2, 6)
        ]
        transcript = app.query_one(ChatTranscriptComponent)
        assert "A verified conversation summary" in transcript.logical_copy_text()
        entries = await session.hydrate_transcript_entries()
        assert len([entry for entry in entries if entry.application is not None]) == 4


@pytest.mark.asyncio
async def test_run_presentation_follows_session_execution(tmp_path: Path) -> None:
    """A second real run remounts spinner/reset and terminal refreshes usage/context."""
    from langchain_core.messages import AIMessage
    from src.tui.app import SloTUI
    from src.tui.components.prompt_input.component import PromptInputComponent
    from src.tui.widgets.user_message_block import UserMessageBlock
    from tests.agents.slo_agent.messaging.test_delivery import RecordingModel
    from tests.tui.test_durable_composer import _build_factory_session, _wait_until

    class RecordingPresentationApp(SloTUI):
        """Observe real presentation gateways without replacing session execution."""

        from pathlib import Path

        CSS_PATH = str(Path(__file__).resolve().parents[2] / "src/tui/app.tcss")

        def __init__(self, *, session: SloAgentSession) -> None:
            """Retain terminal refresh counts."""
            super().__init__(session=session, messaging_enabled=True, prompt_factory=RecordingPromptInput)
            self.context_refreshes = 0
            self.usage_refreshes = 0

        async def _refresh_context_window_after_prompt(self) -> None:
            """Record, then run the production context refresh."""
            self.context_refreshes += 1
            await super()._refresh_context_window_after_prompt()

        def _refresh_usage_status_bar(self) -> None:
            """Record, then render the real usage status."""
            self.usage_refreshes += 1
            super()._refresh_usage_status_bar()

    model = RecordingModel(responses=[AIMessage(content="first"), AIMessage(content="second")])
    session = _build_factory_session(tmp_path=tmp_path, model=model)
    app = RecordingPresentationApp(session=session)
    try:
        async with app.run_test() as pilot:
            await _wait_until(predicate=lambda: app._messaging_session is session)
            prompt = app.query_one(RecordingPromptInput)
            for index in range(2):
                usage_before = app.usage_refreshes
                prompt.load_text(f"run {index}")
                await pilot.press("enter")
                await _wait_until(predicate=lambda: len(model.requests) == index + 1)
                assert app._messaging_run_presented and app._spinner is not None
                model.release.set()
                await _wait_until(
                    predicate=lambda: not session.is_running and not app._messaging_run_presented
                )
                assert app._spinner is None
                assert app.context_refreshes == index + 1
                assert app.usage_refreshes > usage_before
                model.release.clear()
            assert [block.text for block in app.query(UserMessageBlock)] == ["run 0", "run 1"]
    finally:
        model.release.set()
        await session.close_messaging()


@pytest.mark.asyncio
async def test_overflow_raises_replay_gap_and_host_rebuilds(tmp_path: Path) -> None:
    """Two real overflows during barrier replay force two subscribed rebuilds, never silent loss."""
    import asyncio
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.messaging.dao import MessageSubmissionDAO, MessageReceiptDAO
    from src.tui.app import SloTUI
    from src.tui.components.chat_transcript.component import ChatTranscriptComponent
    from src.tui.components.chat_transcript.commands import LoadOlderHistoryDAO
    from tests.tui.test_durable_composer import _wait_until

    class HeldReplaySession(SloAgentSession):
        """Hold the real replay result, leaving real observation registered and bounded."""

        def __init__(
            self,
            *,
            workdir: Path,
            session_id: str,
            config: SessionConfigDAO,
            history_store: FilesystemSessionHistoryStore,
        ) -> None:
            """Create deterministic gates while retaining the real session/store construction."""
            super().__init__(
                workdir=workdir, session_id=session_id, config=config, history_store=history_store
            )
            self.reads = 0
            self.snapshots = [asyncio.Event(), asyncio.Event()]
            self.releases = [asyncio.Event(), asyncio.Event()]

        async def hydrate_transcript_entries(self) -> list[TranscriptEntryDAO]:
            """Read through the real barrier before holding delivery, not persistence."""
            entries = await super().hydrate_transcript_entries()
            if self.is_messaging_ready:
                index = self.reads
                self.reads += 1
                if index < 2:
                    self.snapshots[index].set()
                    await self.releases[index].wait()
            return entries

    session_id = str(uuid4())
    root = tmp_path / "history"
    session = HeldReplaySession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, session_id=session_id, history_root=root, model_name="gpt-5.4"
        ),
        history_store=FilesystemSessionHistoryStore(root=root),
    )
    app = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    ids = set()
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            for batch in range(2):
                await asyncio.wait_for(session.snapshots[batch].wait(), timeout=5)
                for index in range(257):
                    submission = MessageSubmissionDAO(
                        message_id=str(uuid4()),
                        target=session.messaging_target,
                        kind="transcript_note",
                        text=f"batch {batch} note {index}",
                    )
                    ids.add(submission.message_id)
                    receipt = await session.admit_message(
                        submission=submission, principal=session.messaging_owner_principal
                    )
                    assert isinstance(receipt, MessageReceiptDAO)
                    async with asyncio.timeout(5):
                        while True:
                            receipt = await session.get_message_receipt(
                                message_id=submission.message_id,
                                target=session.messaging_target,
                                principal=session.messaging_owner_principal,
                            )
                            if isinstance(receipt, MessageReceiptDAO) and receipt.state == "applied":
                                break
                            await asyncio.sleep(0.001)
                session.releases[batch].set()
            await _wait_until(predicate=lambda: session.reads >= 3, timeout_seconds=10)
            transcript = app.query_one(ChatTranscriptComponent)
            # _hydrated seals partial-failure retry before mounting the tail;
            # joining the public command also joins the active hydration lock.
            from src.tui.components.chat_transcript.commands import HydrateTranscriptDAO

            await transcript.handle(command=HydrateTranscriptDAO())
            while transcript._load_older_cursor:
                await transcript.handle(command=LoadOlderHistoryDAO())
            assert set(transcript._projector._message_application_hashes) == ids
            assert transcript._projector._message_application_conflicts == set()
            assert app._messaging_observation_task is not None
            assert not app._messaging_observation_task.done()
            assert "Message updates unavailable." not in transcript.logical_copy_text()
    finally:
        for gate in session.releases:
            gate.set()
        await session.close_messaging()


@pytest.mark.asyncio
async def test_recall_identity_is_bounded_and_uses_submitted_slash_text(tmp_path: Path) -> None:
    """Receipt adoption uses actual submitted text, not an already-cleared slash editor."""
    from src.tui.app import SloTUI
    from src.tui.components.prompt_input.component import PromptInputComponent
    from src.tui.components.prompt_input.commands import RecordAcceptedPromptDAO, SubmitDraftDAO
    from src.agents.slo_agent.messaging.dao import MessageAddressDAO, utcnow
    from tests.tui.test_durable_composer import ScriptedMessagingClient, _wait_until
    from tests.tui.test_prompt_component_protocol import build_session

    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))

    def accepted(submission: MessageSubmissionDAO) -> MessageReceiptDAO:
        """Return a deterministic receipt at the injected internal-client boundary."""
        return MessageReceiptDAO(
            message_id=submission.message_id,
            target=target,
            sequence=1,
            state="accepted",
            durable=True,
            admitted_at=utcnow(),
        )

    app = SloTUI(prompt_factory=RecordingPromptInput, session=build_session(tmp_path=tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one(RecordingPromptInput)
        await prompt.replace_submission_binding(
            client=ScriptedMessagingClient(always=accepted), address=target
        )
        prompt.load_text("")
        draft = prompt.build_draft_submission(text="steer instruction", intent_revision=None)
        assert draft is not None
        await prompt.handle(command=SubmitDraftDAO(draft_submission=draft))
        await _wait_until(predicate=lambda: len(prompt.outcomes) == 1)
        await prompt.handle(
            command=RecordAcceptedPromptDAO(
                text="steer instruction", message_id=draft.message_submission.message_id
            )
        )
        assert prompt._prompt_history._entries == ["steer instruction"]
        for index in range(4097):
            await prompt.handle(
                command=RecordAcceptedPromptDAO(text=f"recall {index}", message_id=str(uuid4()))
            )
        assert len(prompt._recorded_message_ids) == 4096
        assert len(prompt._recorded_message_order) == 4096
        assert draft.message_submission.message_id not in prompt._recorded_message_ids


@pytest.mark.asyncio
async def test_fast_provider_echo_precedes_answer(tmp_path: Path) -> None:
    """Already-released provider must not outrun the canonical echo or leave a stale spinner."""
    from langchain_core.messages import AIMessage
    from src.tui.app import SloTUI
    from src.tui.components.prompt_input.component import PromptInputComponent
    from src.tui.components.chat_transcript.component import ChatTranscriptComponent
    from src.tui.widgets.user_message_block import UserMessageBlock
    from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
    from tests.agents.slo_agent.messaging.test_delivery import RecordingModel
    from tests.tui.test_durable_composer import _build_factory_session, _wait_until

    model = RecordingModel(responses=[AIMessage(content="fast answer")])
    model.release.set()
    session = _build_factory_session(tmp_path=tmp_path, model=model)
    app = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    async with app.run_test() as pilot:
        await _wait_until(predicate=lambda: app._messaging_observation_task is not None)
        prompt = app.query_one(RecordingPromptInput)
        prompt.load_text("fast input")
        await pilot.press("enter")
        await _wait_until(predicate=lambda: len(model.requests) == 1 and not session.is_running)
        await pilot.pause()
        transcript = app.query_one(ChatTranscriptComponent)
        children = list(transcript.query_one("#transcript-content").children)
        assert [
            type(child) for child in children if isinstance(child, (UserMessageBlock, AssistantStreamBlock))
        ] == [UserMessageBlock, AssistantStreamBlock]
        assert app._spinner is None and not app._messaging_run_presented


@pytest.mark.asyncio
async def test_machine_application_component_route_never_records_recall(tmp_path: Path) -> None:
    """Actual mounted component routes machine context/input to semantic notice widgets only."""
    from src.tui.app import SloTUI
    from src.tui.components.prompt_input.component import PromptInputComponent
    from src.tui.components.chat_transcript.component import ChatTranscriptComponent
    from src.tui.components.chat_transcript.commands import PresentMessageApplicationDAO
    from src.tui.widgets.user_message_block import UserMessageBlock
    from tests.tui.test_prompt_component_protocol import build_session

    app = SloTUI(prompt_factory=RecordingPromptInput, session=build_session(tmp_path=tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        transcript = app.query_one(ChatTranscriptComponent)
        for kind in ("context_note", "agent_input"):
            entry = ReplayEntryProjector.build_entries(
                events=[application_event(sender_kind="scheduler", kind=kind)]
            )[0]
            await transcript.handle(command=PresentMessageApplicationDAO(entry=entry))
        assert len(transcript.query(".sub-agent-notice")) == 2
        assert len(transcript.query(UserMessageBlock)) == 0
        assert app.query_one(RecordingPromptInput)._prompt_history._entries == []
