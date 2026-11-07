"""Real local-client → session → history → agent context → SQLite acknowledgement."""

from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from pathlib import Path
from typing import BinaryIO, Optional
from uuid import uuid4

import asyncio
import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import BaseTool
from pydantic import Field

from src.agents.providers.faux import FauxChatModel
from src.agents.hooks import Hook, ShouldStopAfterTurnHook, ShouldStopAfterTurnHookContextDAO
from src.agents.slo_agent.compaction.compacter import CompactionResult
from src.agents.slo_agent.messaging.ownership import SessionExecutionOwnership
from src.agents.slo_agent.messaging.dao import SessionAlreadyOwnedError
from src.agents.tools.echo import echo_tool
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
    MessageHistoryEvidenceDAO,
)
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
from src.agents.slo_agent.messaging.dao import (
    MessageAdmissionError,
    BoundaryDAO,
    BoundaryDeliveryDAO,
    MessageIdentityDAO,
    CompactionLedgerDAO,
    MessageAddressDAO,
    MessagePrincipalDAO,
    MessageDeliveryDAO,
    MessageStoreError,
    MessagingLimitsDAO,
    MessageReceiptDAO,
    MessageErrorDAO,
    MessageSubmissionDAO,
)
from src.agents.slo_agent.messaging.store import MessageStore
from src.agents.slo_agent.rate_limit.dao import RateLimitRetryPlanDAO
from tests.agents.slo_agent.messaging.test_store_journey import application_event
from src.agents.slo_agent.messaging.delivery import MessageRunState
from src.agents.slo_agent.messaging.delivery import AgentMessageSource
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import (
    SloAgentSession,
    PreparedPromptAttemptDAO,
    PromptAttemptPlanDAO,
)


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
@pytest.mark.parametrize(
    argnames="stage",
    argvalues=[
        "accepted",
        "claimed",
        "prepared",
        "history",
        "applied",
        "missing",
        "cancelled",
        "corrupt",
        "mismatch",
    ],
)
async def test_startup_reconciles_recipient_evidence_without_provider(
    tmp_path: Path, tree: bool, stage: str
) -> None:
    """Restart repairs prepared delivery, retains unprepared input and rejects lost applied proof."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id: str = str(uuid4())
    target: MessageAddressDAO = MessageAddressDAO(
        kind="agent_session", session_id=session_id, generation=str(uuid4())
    )
    history: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    await history.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    store: MessageStore = await MessageStore.open(
        path=root / session_id / "messaging.v1.sqlite3", limits=MessagingLimitsDAO(), target=target
    )
    submission: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()), target=target, kind="agent_input", text="Recover exact input"
    )
    await store.set_lifecycle(accepting=True)
    await store.admit(
        submission=submission, principal=MessagePrincipalDAO(principal_id="original", kind="human")
    )
    if stage not in ("accepted", "cancelled"):
        delivery: Optional[MessageDeliveryDAO] = await store.claim_one(
            boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0)
        )
        assert delivery is not None
        if stage != "claimed":
            event: SessionHistoryEventDAO = application_event(delivery=delivery, generation=target.generation)
            await store.prepare_application(delivery=delivery, event=event)
            if stage in ("history", "applied", "corrupt", "mismatch"):
                await history.append_message_application_once(event=event)
            if stage in ("history", "applied", "missing", "corrupt", "mismatch"):
                await store.mark_history_committed(message_id=submission.message_id)
            if stage in ("applied", "missing", "corrupt", "mismatch"):
                await store.mark_applied(message_id=submission.message_id)
    if stage == "cancelled":
        await store.retain_pending()
        await store.cancel_retained(message_ids=(submission.message_id,))
    if stage == "corrupt":
        path: Path = root / session_id / "events.jsonl"
        assert path.resolve().is_relative_to(tmp_path.resolve())
        path.write_text(data="invalid terminated record\n", encoding="utf-8")
    if stage == "mismatch":
        path = root / session_id / "events.jsonl"
        assert path.resolve().is_relative_to(tmp_path.resolve())
        active: SessionHistoryEventDAO = (await history.application_evidence(session_id=session_id)).events[0]
        altered: SessionHistoryEventDAO = active.model_copy(
            update={"payload": active.payload.model_copy(update={"content": "Changed persisted instruction"})}
        )
        path.write_text(data=altered.model_dump_json() + "\n", encoding="utf-8")
    await store.close()
    model: RecordingModel = RecordingModel(responses=[])
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    try:
        if stage in ("missing", "corrupt", "mismatch"):
            with pytest.raises(expected_exception=MessageStoreError):
                await session.start_messaging()
            assert not session._messaging_accepting
        else:
            await session.start_messaging()
            assert session._message_store is not None
            identities: tuple[MessageIdentityDAO, ...] = await session._message_store.read_identities()
            receipt: MessageReceiptDAO = identities[0].receipt
            evidence: MessageHistoryEvidenceDAO = await history.application_evidence(session_id=session_id)
            if stage == "cancelled":
                assert receipt.state == "cancelled" and not evidence.events
            elif stage in ("accepted", "claimed"):
                assert receipt.state == "accepted" and receipt.retained_for_recovery
                assert receipt.run_id is None and not evidence.events
            else:
                assert receipt.state == "applied"
                assert len(evidence.events) == 1
                assert evidence.events[0].payload.content == submission.text
            assert not model.requests and not session.is_running
    finally:
        await session.close_messaging()


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
@pytest.mark.parametrize(
    argnames="activation",
    argvalues=["prepared", "activated", "committed", "pruned", "lost", "duplicate", "archive", "empty"],
)
async def test_startup_reconciles_exact_compaction_membership(
    tmp_path: Path, tree: bool, activation: str
) -> None:
    """Only active summary UUID or all originals settles preparation; committed coverage survives."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id: str = str(uuid4())
    target: MessageAddressDAO = MessageAddressDAO(
        kind="agent_session", session_id=session_id, generation=str(uuid4())
    )
    history: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    await history.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    store: MessageStore = await MessageStore.open(
        path=root / session_id / "messaging.v1.sqlite3", limits=MessagingLimitsDAO(), target=target
    )
    await store.set_lifecycle(accepting=True)
    submission: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()), target=target, kind="agent_input", text="Already applied"
    )
    await store.admit(
        submission=submission, principal=MessagePrincipalDAO(principal_id="original", kind="human")
    )
    delivery: Optional[MessageDeliveryDAO] = await store.claim_one(
        boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0)
    )
    assert delivery is not None
    event: SessionHistoryEventDAO = application_event(delivery=delivery, generation=target.generation)
    await store.prepare_application(delivery=delivery, event=event)
    await history.append_message_application_once(event=event)
    await store.mark_history_committed(message_id=submission.message_id)
    await store.mark_applied(message_id=submission.message_id)
    retained: SessionHistoryEventDAO = await history.append_event(
        event=SessionHistoryEventDAO(session_id=session_id, kind="run_completed")
    )
    events: list[SessionHistoryEventDAO] = list(
        (await history.application_evidence(session_id=session_id)).events
    )
    result: CompactionResult = CompactionResult(
        summary_text="Covered earlier input",
        first_kept_entry_id=retained.event_id,
        cut_point_entry_id=event.event_id,
        tokens_before=100,
        tokens_after=10,
    )
    compaction_id: str = str(uuid4())
    await store.prepare_compaction(
        compaction_id=compaction_id,
        message_ids=() if activation == "empty" else (submission.message_id,),
        observation_ids=(),
    )
    with pytest.raises(expected_exception=MessageStoreError):
        await store.prepare_compaction(compaction_id=str(uuid4()), message_ids=(), observation_ids=())
    if activation == "archive":
        active_path: Path = root / session_id / "events.jsonl"
        assert active_path.resolve().is_relative_to(tmp_path.resolve())
        archive_path: Path = root / session_id / "events.pre-compaction-1.jsonl"
        assert archive_path.resolve().is_relative_to(tmp_path.resolve())
        active_path.rename(target=archive_path)
    if activation not in ("prepared", "archive", "empty"):
        summary: SessionHistoryEventDAO = await history.compact_to_boundary(
            session_id=session_id,
            events=events,
            result=result,
            turn_id=str(uuid4()),
            messaging_compaction_id=compaction_id,
        )
        if activation == "duplicate":
            await history.append_event(
                event=SessionHistoryEventDAO(
                    session_id=session_id,
                    kind="compaction_summary",
                    payload=SessionHistoryEventPayloadDAO(
                        content="Conflicting summary", metadata={"messaging_compaction_id": compaction_id}
                    ),
                )
            )
        if activation in ("committed", "pruned"):
            await store.finish_compaction(compaction_id=compaction_id, summary_event_id=summary.event_id)
        if activation == "pruned":
            from datetime import timedelta

            await store.maintain(now=delivery.envelope.admitted_at + timedelta(days=9))
        if activation in ("committed", "pruned", "lost"):
            pruned_path: Path = root / session_id / "events.jsonl"
            assert pruned_path.resolve().is_relative_to(tmp_path.resolve())
            pruned_path.write_text(data=retained.model_dump_json() + "\n", encoding="utf-8")
    await store.close()
    model: RecordingModel = RecordingModel(responses=[])
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    try:
        if activation in ("lost", "duplicate"):
            with pytest.raises(expected_exception=MessageStoreError):
                await session.start_messaging()
        else:
            await session.start_messaging()
            assert session._message_store is not None
            ledger: tuple[CompactionLedgerDAO, ...] = await session._message_store.read_compactions()
            assert ledger[0].state == (
                "rolled_back" if activation in ("prepared", "archive", "empty") else "committed"
            )
            identities: tuple[MessageIdentityDAO, ...] = await session._message_store.read_identities()
            assert identities[0].receipt.state == "applied"
            active: MessageHistoryEvidenceDAO = await history.application_evidence(session_id=session_id)
            assert sum(item.event_id == event.event_id for item in active.events) == (
                1 if activation in ("prepared", "archive", "empty") else 0
            )
        assert not model.requests
    finally:
        await session.close_messaging()


async def test_workflow_history_write_waits_for_common_history_barrier(tmp_path: Path) -> None:
    """Legacy workflow writes cannot race messaging application or compaction activation."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id: str = str(uuid4())
    history: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=root)
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        history_store=history,
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, session_id=session_id),
    )
    await session._history_barrier.acquire()
    writer: asyncio.Task[bool] = asyncio.create_task(
        coro=session.record_workflow_update(
            text="Workflow note", message_id=str(uuid4()), workflow_id=str(uuid4())
        )
    )
    try:
        with pytest.raises(expected_exception=TimeoutError):
            async with asyncio.timeout(delay=0.1):
                await asyncio.shield(arg=writer)
        assert not writer.done()
    finally:
        session._history_barrier.release()
        await writer
    assert len((await history.application_evidence(session_id=session_id)).events) == 1


@pytest.mark.parametrize(argnames="tamper", argvalues=[False, True])
async def test_attempt_rebuild_verifies_raw_proof_before_borrowing_cursor(
    tmp_path: Path, tamper: bool
) -> None:
    """A rebuilt real attempt retains cursor/cache and cannot call provider after lost proof."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id: str = str(uuid4())
    history: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=root)
    model: RecordingModel = RecordingModel(responses=[])
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    submission: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()),
        target=session.messaging_target,
        kind="agent_input",
        text="Retain one insertion",
    )
    try:
        async with session._session_run_scope():
            await client.submit(submission=submission)
            run: MessageRunState = MessageRunState(run_id=str(uuid4()))
            session._message_run = run
            await session._ensure_history_session()
            selected: BoundaryDeliveryDAO = await session.take_one(
                boundary=BoundaryDAO(run_id=run.run_id, boundary_index=0)
            )
            assert selected.instruction is not None
            run.applied_message_ids = frozenset({submission.message_id})
            await session.commit_applied(delivery=selected.instruction)
            if tamper:
                path: Path = root / session_id / "events.jsonl"
                assert path.resolve().is_relative_to(tmp_path.resolve())
                path.write_text(data="", encoding="utf-8")
            if tamper:
                with pytest.raises(expected_exception=MessageStoreError):
                    await session._prepare_attempt_context(plan=session._build_initial_attempt_plan(text=""))
            else:
                first: PreparedPromptAttemptDAO = await session._prepare_attempt_context(
                    plan=session._build_initial_attempt_plan(text="")
                )
                second: PreparedPromptAttemptDAO = await session._prepare_attempt_context(
                    plan=session._build_initial_attempt_plan(text="")
                )
                assert first.turn_id != second.turn_id
                assert first.message_history == second.message_history
                assert [item.content for item in first.message_history] == [submission.text]
                assert session._message_run is run and run.delivery is selected
                assert run.boundary_index == 0 and run.applied_message_ids == {submission.message_id}
            assert not model.requests
            session._message_run = None
    finally:
        await client.close()
        await session.close_messaging()


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_session_compaction_commits_exact_coverage_through_existing_owner(
    tmp_path: Path, tree: bool
) -> None:
    """Real compacter summary activates through the session barrier and SQLite ledger."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id: str = str(uuid4())
    history: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    model: RecordingModel = RecordingModel(
        responses=[FauxChatModel.assistant_message(content="A verified conversation summary")]
    )
    model.release.set()
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    try:
        async with session._session_run_scope():
            await session._ensure_history_session()
            session._message_run = MessageRunState(run_id=str(uuid4()))
            for index in range(6):
                submission: MessageSubmissionDAO = MessageSubmissionDAO(
                    message_id=str(uuid4()),
                    target=session.messaging_target,
                    kind="agent_input",
                    text=f"Applied instruction {index} " + "x" * 20000,
                )
                await client.submit(submission=submission)
                selected: BoundaryDeliveryDAO = await session.take_one(
                    boundary=BoundaryDAO(run_id=session._message_run.run_id, boundary_index=index)
                )
                assert selected.instruction is not None
                session._message_run.applied_message_ids |= {submission.message_id}
                await session.commit_applied(delivery=selected.instruction)
                session._message_run.boundary_index += 1
                session._message_run.delivery = None
            await session._ensure_agent_ready()
            assert await session._run_compaction_if_needed(turn_id=str(uuid4()), force=True)
            assert session._message_store is not None
            ledgers: tuple[CompactionLedgerDAO, ...] = await session._message_store.read_compactions()
            assert len(ledgers) == 1 and ledgers[0].state == "committed"
            evidence: MessageHistoryEvidenceDAO = await history.application_evidence(session_id=session_id)
            summaries: list[SessionHistoryEventDAO] = [
                event for event in evidence.events if event.kind == "compaction_summary"
            ]
            assert len(summaries) == 1
            assert summaries[0].payload.metadata["messaging_compaction_id"] == ledgers[0].compaction_id
            await session._verify_borrowed_message_run()
            session._message_run = None
    finally:
        await client.close()
        await session.close_messaging()


class RecordingModel(FauxChatModel):
    """Injected external model records real graph requests, without replacing durability."""

    requests: list[list[BaseMessage]] = Field(
        default_factory=list,
        description="Ordered real graph requests observed at the external model boundary.",
    )
    entered: asyncio.Event = Field(
        default_factory=asyncio.Event, description="Signals that an external model request has begun."
    )
    release: asyncio.Event = Field(
        default_factory=asyncio.Event,
        description="Test-owned gate allowing the held external request to finish.",
    )

    def __init__(
        self,
        *,
        responses: Sequence[AIMessage],
        chunk_scripts: Optional[Sequence[Sequence[AIMessageChunk]]] = None,
    ) -> None:
        """Initialize the external script with explicitly typed construction inputs."""
        super().__init__(responses=responses, chunk_scripts=chunk_scripts)

    def bind_tools(
        self, tools: Sequence[object], *, tool_choice: Optional[str] = None, **kwargs: object
    ) -> "RecordingModel":
        """Record the real tools while retaining this external model's request recorder."""
        bound: list[BaseTool] = []
        for candidate in tools:
            if not isinstance(candidate, BaseTool):
                raise ValueError("This deterministic fixture requires actual tools")
            bound.append(candidate)
        self.bound_tools = list(bound)
        return self

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Capture context only after the real source has acknowledged its insertion."""
        self.requests.append(list(messages))
        self.entered.set()
        await self.release.wait()
        async for chunk in super()._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


class RealAgentFactory:
    """Compose the real agent with the session source and an injected external model."""

    def __init__(
        self,
        *,
        model: RecordingModel,
        workdir: Path,
        tools: Optional[list[BaseTool]] = None,
        stop_hook: Optional[ShouldStopAfterTurnHook] = None,
    ) -> None:
        """Retain only external-model construction inputs."""
        self.model: RecordingModel = model
        self.workdir: Path = workdir
        self.tools: list[BaseTool] = list(tools or [])
        self.stop_hook: Optional[ShouldStopAfterTurnHook] = stop_hook

    def __call__(self, *, message_source: AgentMessageSource) -> SloAgent:
        """Bind the real session source at real agent construction, never by mutation."""
        return SloAgent(
            llm=self.model,
            tools=self.tools,
            cwd=str(self.workdir),
            system_prompt="Test system",
            message_source=message_source,
            should_stop_after_turn_hook=self.stop_hook or Hook.should_stop_after_turn_hook,
        )


def stop_after_turn(context: ShouldStopAfterTurnHookContextDAO) -> bool:
    """External operator policy stops even when durable input remains queued."""
    return True


@pytest.mark.parametrize(argnames="mode", argvalues=["continue", "stop", "abort"])
async def test_pending_input_continues_same_run_unless_hard_control_pauses(tmp_path: Path, mode: str) -> None:
    """Three tool-free inputs share one cursor; stop/abort never starts the waiting inputs."""
    history_root: Path = tmp_path / "history"
    assert history_root.resolve().is_relative_to(tmp_path.resolve())
    history: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=history_root)
    model: RecordingModel = RecordingModel(
        responses=[FauxChatModel.assistant_message(content="Answer.") for _ in range(4)]
    )
    session_id: str = str(uuid4())
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=history_root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(
            model=model, workdir=tmp_path, stop_hook=stop_after_turn if mode == "stop" else None
        ),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    submissions: list[MessageSubmissionDAO] = [
        MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text=f"Input {index}",
        )
        for index in range(3)
    ]
    try:
        assert isinstance(await client.submit(submission=submissions[0]), MessageReceiptDAO)
        async with asyncio.timeout(delay=5):
            await model.entered.wait()
        for submission in submissions[1:]:
            assert isinstance(await client.submit(submission=submission), MessageReceiptDAO)
        if mode == "abort":
            session.abort()
        model.release.set()
        async with asyncio.timeout(delay=5):
            while session.is_running:
                await asyncio.sleep(delay=0)
        evidence: MessageHistoryEvidenceDAO = await history.application_evidence(session_id=session_id)
        applications: list[SessionHistoryEventDAO] = [
            event for event in evidence.events if "messaging_v1" in event.payload.metadata
        ]
        if mode == "continue":
            if session._messaging_failure is not None:
                raise session._messaging_failure
            assert len(model.requests) == 3
            assert [event.payload.content for event in applications] == [item.text for item in submissions]
            assert len({event.turn_id for event in applications}) == 1
            assert len({event.payload.metadata["messaging_v1"]["message_id"] for event in applications}) == 3
            assert [item.content for item in model.requests[-1] if isinstance(item, HumanMessage)] == [
                item.text for item in submissions
            ]
        else:
            assert len(model.requests) == 1
            assert session._messaging_paused
            assert [event.payload.content for event in applications] == [submissions[0].text]
            for submission in submissions[1:]:
                receipt: MessageReceiptDAO | MessageErrorDAO = await client.get_receipt(
                    message_id=submission.message_id
                )
                assert isinstance(receipt, MessageReceiptDAO) and receipt.state == "accepted"
            resumed: MessageSubmissionDAO = MessageSubmissionDAO(
                message_id=str(uuid4()),
                target=session.messaging_target,
                kind="agent_input",
                text="Explicit resume",
            )
            assert isinstance(await client.submit(submission=resumed), MessageReceiptDAO)
            async with asyncio.timeout(delay=5):
                while len(model.requests) < 2 or session.is_running:
                    await asyncio.sleep(delay=0)
            assert len(model.requests) >= 2
            resumed_receipt: MessageReceiptDAO | MessageErrorDAO = await client.get_receipt(
                message_id=submissions[1].message_id
            )
            assert isinstance(resumed_receipt, MessageReceiptDAO) and resumed_receipt.state == "applied"
    finally:
        model.release.set()
        await client.close()
        await session.close_messaging()


async def test_active_invoke_observes_real_shared_execution_without_closing_owner(tmp_path: Path) -> None:
    """Two compatibility publishers associate before a fast terminal and never contend for execution."""
    model: RecordingModel = RecordingModel(
        responses=[FauxChatModel.assistant_message(content="Shared answer.") for _ in range(2)]
    )
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id: str = str(uuid4())
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=FilesystemSessionHistoryStore(root=root),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    await session.start_messaging()

    async def publish(*, text: str) -> list[AgentStreamEventDAO]:
        """Consume a real compatibility observer without taking execution ownership."""
        return [event async for event in session.invoke(text=text)]

    first: asyncio.Task[list[AgentStreamEventDAO]] = asyncio.create_task(coro=publish(text="First publisher"))
    second: Optional[asyncio.Task[list[AgentStreamEventDAO]]] = None
    try:
        async with asyncio.timeout(delay=5):
            await model.entered.wait()
        second = asyncio.create_task(coro=publish(text="Second publisher"))
        async with asyncio.timeout(delay=5):
            while len(session._invocation_observers) != 2:
                await asyncio.sleep(delay=0)
        model.release.set()
        async with asyncio.timeout(delay=5):
            first_events: list[AgentStreamEventDAO] = await first
            second_events: list[AgentStreamEventDAO] = await second
        assert [event.kind for event in first_events].count("run_completed") == 1
        assert [event.kind for event in second_events].count("run_completed") == 1
        assert len(model.requests) == 2
        assert not session._messaging_closing and not session._invocation_observers
        assert session._message_store is not None
        identities: tuple[MessageIdentityDAO, ...] = await session._message_store.read_identities()
        assert len(identities) == 2
        assert all(identity.receipt.state == "applied" for identity in identities)
        assert len({identity.receipt.run_id for identity in identities}) == 1
    finally:
        model.release.set()
        await session.close_messaging()
        await asyncio.gather(first, *([second] if second is not None else []), return_exceptions=True)


@pytest.mark.parametrize(argnames="limit", argvalues=["events", "bytes", "cancel", "close"])
async def test_compatibility_observer_never_owns_or_blocks_execution(tmp_path: Path, limit: str) -> None:
    """Slow/closed observers detach while the real SQLite/agent owner settles normally."""
    chunks: list[AIMessageChunk] = (
        [AIMessageChunk(content="x") for _ in range(300)]
        if limit == "events"
        else (
            [AIMessageChunk(content="x" * (1024 * 1024 + 1))]
            if limit == "bytes"
            else [AIMessageChunk(content="Answer")]
        )
    )
    model: RecordingModel = RecordingModel(
        responses=[FauxChatModel.assistant_message(content="Answer")], chunk_scripts=[chunks]
    )
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id: str = str(uuid4())
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=FilesystemSessionHistoryStore(root=root),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    await session.start_messaging()
    stream: AsyncGenerator[AgentStreamEventDAO, None] = session.invoke(text="One publisher")
    first: asyncio.Task[AgentStreamEventDAO] = asyncio.create_task(coro=anext(stream))
    closer: Optional[asyncio.Task[None]] = None
    try:
        async with asyncio.timeout(delay=5):
            await model.entered.wait()
        if limit == "cancel":
            first.cancel()
            with pytest.raises(expected_exception=asyncio.CancelledError):
                await first
            await stream.aclose()
            assert not session._invocation_observers and session.is_running
        if limit == "close":
            closer = asyncio.create_task(coro=session.close_messaging())
            async with asyncio.timeout(delay=5):
                while not session._messaging_closing:
                    await asyncio.sleep(delay=0)
            assert not closer.done()
        model.release.set()
        async with asyncio.timeout(delay=10):
            while session.is_running:
                await asyncio.sleep(delay=0)
        if limit in ("events", "bytes"):
            with pytest.raises(expected_exception=MessageAdmissionError) as overflow:
                await first
                _remaining: list[AgentStreamEventDAO] = [event async for event in stream]
            assert overflow.value.error.code == "replay_gap"
        elif limit == "close":
            assert closer is not None
            await closer
            first_event: AgentStreamEventDAO = await first
            remaining: list[AgentStreamEventDAO] = [first_event, *[event async for event in stream]]
            assert any(event.kind == "run_aborted" for event in remaining)
        assert not session._invocation_observers
        assert session._messaging_failure is None
    finally:
        model.release.set()
        await stream.aclose()
        await session.close_messaging()
        await asyncio.gather(first, *([closer] if closer is not None else []), return_exceptions=True)


async def test_configured_start_uses_production_scheduler_and_agent_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production config, not a custom agent factory, owns delivery after explicit start."""
    from src.agents.base import LLMFactory
    from src.agents.base import LLMBuildResult

    model: RecordingModel = RecordingModel(responses=[FauxChatModel.assistant_message(content="Done")])
    model.release.set()

    def external_model(**kwargs: object) -> LLMBuildResult:
        """Replace only the third-party model construction boundary."""
        return LLMBuildResult(llm=model, supports_explicit_caching=False)

    monkeypatch.setattr(target=LLMFactory, name="create", value=external_model)
    from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
    from src.auth.credential_store import CredentialStore

    auth_path: Path = tmp_path / "authentication.json"
    assert auth_path.resolve().is_relative_to(tmp_path.resolve())
    monkeypatch.setenv(name="SLO_AUTH_FILE", value=str(auth_path))
    credentials: CredentialStore = CredentialStore()
    assert credentials.path.resolve().is_relative_to(tmp_path.resolve())
    credentials.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.API_KEY,
            access_token="synthetic-model-boundary-only",
        )
    )
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    config: SessionConfigDAO = SessionConfigDAO(
        workdir=tmp_path, history_root=root, session_id=str(uuid4()), model_name="gpt-5.4"
    )
    session: SloAgentSession = SloAgentSession.build(config=config)
    try:
        await session.start_messaging()
        try:
            async with asyncio.timeout(delay=5):
                events: list[AgentStreamEventDAO] = [
                    event async for event in session.invoke(text="Production input")
                ]
        except MessageAdmissionError:
            if session._messaging_failure is not None:
                raise session._messaging_failure
            raise
        assert [event.kind for event in events].count("run_completed") == 1
        assert [item.content for item in model.requests[0] if isinstance(item, HumanMessage)] == [
            "Production input"
        ]
        assert session._message_store is not None
        identities: tuple[MessageIdentityDAO, ...] = await session._message_store.read_identities()
        assert len(identities) == 1 and identities[0].receipt.state == "applied"
    finally:
        await session.close_messaging()


async def test_close_waits_for_active_provider_and_releases_lease_last(tmp_path: Path) -> None:
    """Repeated close cancellation cannot abandon the active graph or release ownership early."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    model: RecordingModel = RecordingModel(responses=[FauxChatModel.assistant_message(content="Done")])
    session_id: str = str(uuid4())
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    closing: Optional[asyncio.Task[None]] = None
    try:
        assert isinstance(
            await client.submit(
                submission=MessageSubmissionDAO(
                    message_id=str(uuid4()),
                    target=session.messaging_target,
                    kind="agent_input",
                    text="Hold provider",
                )
            ),
            MessageReceiptDAO,
        )
        async with asyncio.timeout(delay=5):
            await model.entered.wait()
        closing = asyncio.create_task(coro=session.close_messaging())
        async with asyncio.timeout(delay=5):
            while not session._messaging_closing:
                await asyncio.sleep(delay=0)
        closing.cancel()
        await asyncio.sleep(delay=0)
        closing.cancel()
        assert not closing.done()
        with pytest.raises(expected_exception=SessionAlreadyOwnedError):
            await SessionExecutionOwnership.acquire(root=root, session_id=session_id)
        model.release.set()
        with pytest.raises(expected_exception=asyncio.CancelledError):
            await closing
        await session.close_messaging()
        assert not session._messaging_calls and not session.is_running
        assert session._messaging_scheduler is not None and session._messaging_scheduler.done()
        assert session._messaging_note_task is not None and session._messaging_note_task.done()
        lease: SessionExecutionOwnership = await SessionExecutionOwnership.acquire(
            root=root, session_id=session_id
        )
        await lease.release()
    finally:
        model.release.set()
        await client.close()
        await session.close_messaging()
        if closing is not None:
            await asyncio.gather(closing, return_exceptions=True)


@pytest.mark.parametrize(argnames="persistent", argvalues=[False, True])
async def test_started_history_is_only_admitted_before_first_ephemeral_input(
    tmp_path: Path, persistent: bool
) -> None:
    """Legacy history seeds only the idle ephemeral session, never a later publication."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    model: RecordingModel = RecordingModel(responses=[FauxChatModel.assistant_message(content="Done")])
    model.release.set()
    session_id: str = str(uuid4())
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        enable_history=persistent,
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    await session.start_messaging()
    try:
        if persistent:
            with pytest.raises(expected_exception=MessageAdmissionError) as rejected:
                _events: list[AgentStreamEventDAO] = [
                    event async for event in session.invoke(text="First", history=[])
                ]
            assert rejected.value.error.code == "invalid_message"
        else:
            events: list[AgentStreamEventDAO] = [
                event
                async for event in session.invoke(
                    text="First", history=[{"role": "user", "content": "Prior context"}]
                )
            ]
            assert events[-1].kind == "run_completed"
            assert [item.content for item in model.requests[0] if isinstance(item, HumanMessage)] == [
                "Prior context",
                "First",
            ]
            with pytest.raises(expected_exception=MessageAdmissionError) as rejected:
                _events = [event async for event in session.invoke(text="Second", history=[])]
            assert rejected.value.error.code == "invalid_message"
        assert session._message_store is not None
        identities: tuple[MessageIdentityDAO, ...] = await session._message_store.read_identities()
        assert len(identities) == (0 if persistent else 1)
    finally:
        await session.close_messaging()


@pytest.mark.parametrize(argnames="failure", argvalues=["terminal", "reconnect", "reconnect_terminal"])
async def test_real_outer_retry_retains_boundary_and_final_observer_outcome(
    tmp_path: Path, failure: str
) -> None:
    """Actual transport planning keeps one application and exposes only the final logical terminal."""
    import httpx

    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    original: Exception = ValueError("synthetic credential configuration failure")
    errors: list[Exception] = (
        [original]
        if failure == "terminal"
        else [httpx.RemoteProtocolError("synthetic disconnected stream")]
        + ([original] if failure == "reconnect_terminal" else [])
    )
    model: FailingModel = FailingModel(errors=errors)
    model.release.set()
    history: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=root)
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    await session.start_messaging()
    observed: list[AgentStreamEventDAO] = []
    try:
        async with asyncio.timeout(delay=10):
            if failure.endswith("terminal"):
                with pytest.raises(expected_exception=ValueError) as failed:
                    async for event in session.invoke(text="Keep applied through failure"):
                        observed.append(event)
                assert failed.value is original
            else:
                observed = [event async for event in session.invoke(text="Keep applied through failure")]
        assert [event.kind for event in observed if event.kind in ("run_failed", "run_completed")] == [
            "run_completed" if failure == "reconnect" else "run_failed"
        ]
        assert len(model.requests) == (1 if failure == "terminal" else 2)
        for request in model.requests:
            assert [item.content for item in request if isinstance(item, HumanMessage)] == [
                "Keep applied through failure"
            ]
        assert session._message_store is not None
        identities: tuple[MessageIdentityDAO, ...] = await session._message_store.read_identities()
        assert len(identities) == 1 and identities[0].receipt.state == "applied"
        events: list[SessionHistoryEventDAO] = await history.load_events(session_id=session.session_id)
        applications: list[SessionHistoryEventDAO] = [
            event for event in events if "messaging_v1" in event.payload.metadata
        ]
        assert len(applications) == 1 and not any(event.kind == "user_message" for event in events)
        attempts: set[str | None] = {event.turn_id for event in events if event.kind == "run_started"}
        assert len(attempts) == len(model.requests)
        assert applications[0].turn_id not in attempts
        assert not session._invocation_observers
    finally:
        await session.close_messaging()


async def test_observer_limit_refuses_before_the_257th_admission(
    tmp_path: Path,
) -> None:
    """The real public generator caps observers without allocating another durable identity."""
    from src.agents.model_catalog.service import ModelCatalogService
    from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO, ModelCatalogEntryDAO

    snapshot: ModelCatalogSnapshotDAO = ModelCatalogService.load()
    entry: ModelCatalogEntryDAO = snapshot.entries["gpt-5.4"]
    snapshot = snapshot.model_copy(
        update={
            "entries": {
                **snapshot.entries,
                "gpt-5.4": entry.model_copy(
                    update={
                        "runtime_profile": entry.runtime_profile.model_copy(
                            update={"requests_per_minute": 100000, "tokens_per_minute": 100000000}
                        )
                    }
                ),
            }
        }
    )
    model: RecordingModel = RecordingModel(
        responses=[FauxChatModel.assistant_message(content="x") for _ in range(256)]
    )
    model.release.set()
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        enable_history=False,
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
        catalog_snapshot=snapshot,
    )
    await session.start_messaging()
    streams: list[AsyncGenerator[AgentStreamEventDAO, None]] = [
        session.invoke(text=f"Publisher {index}") for index in range(256)
    ]
    waits: list[asyncio.Task[AgentStreamEventDAO]] = []
    try:
        for stream in streams:
            wait: asyncio.Task[AgentStreamEventDAO] = asyncio.create_task(coro=anext(stream))
            waits.append(wait)
            async with asyncio.timeout(delay=10):
                await asyncio.shield(arg=wait)
                while session.is_running:
                    await asyncio.sleep(delay=0)
        assert len(session._invocation_observers) == 256
        with pytest.raises(expected_exception=MessageAdmissionError) as excess:
            _events: list[AgentStreamEventDAO] = [event async for event in session.invoke(text="Excess")]
        assert excess.value.error.code == "queue_full"
        assert session._message_store is not None
        assert len(await session._message_store.read_identities()) == 256
    finally:
        for wait in waits:
            wait.cancel()
        await asyncio.gather(*waits, return_exceptions=True)
        for stream in streams:
            await stream.aclose()
        await session.close_messaging()


@pytest.mark.parametrize(argnames="preclaim", argvalues=[False, True])
async def test_observer_rejection_and_preclaim_failure_never_wait_forever(
    tmp_path: Path, preclaim: bool
) -> None:
    """Rejection removes registration; failed raw preparation retains accepted input and wakes it."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    model: RecordingModel = RecordingModel(responses=[])
    history: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=root)
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    await session.start_messaging()
    try:
        if preclaim:
            await history.ensure_session(
                session_id=session.session_id, workdir=tmp_path, model_name="gpt-5.4"
            )
            path: Path = root / session.session_id / "events.jsonl"
            assert path.resolve().is_relative_to(tmp_path.resolve())
            path.write_text(data="malformed terminated history\n", encoding="utf-8")
        async with asyncio.timeout(delay=5):
            with pytest.raises(expected_exception=MessageAdmissionError) as failed:
                _events: list[AgentStreamEventDAO] = [
                    event async for event in session.invoke(text="Accepted" if preclaim else "")
                ]
        assert failed.value.error.code == ("recovery_required" if preclaim else "invalid_message")
        assert not session._invocation_observers and not model.requests
        assert session._message_store is not None
        identities: tuple[MessageIdentityDAO, ...] = await session._message_store.read_identities()
        assert len(identities) == (1 if preclaim else 0)
        if preclaim:
            assert identities[0].receipt.state == "accepted"
            assert identities[0].receipt.retained_for_recovery
    finally:
        await session.close_messaging()


@pytest.mark.parametrize(argnames="hold_before", argvalues=[False, True])
async def test_unknown_observer_admission_settles_once_before_assignment(
    tmp_path: Path, hold_before: bool
) -> None:
    """A timed-out compatibility submit keeps its identity and observes the eventual real run."""
    from tests.agents.slo_agent.messaging.test_queue_closure import CompletionGate, wait_until

    gate: CompletionGate = CompletionGate(hold_before=hold_before)
    model: RecordingModel = RecordingModel(responses=[FauxChatModel.assistant_message(content="Done")])
    model.release.set()
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        enable_history=False,
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            messaging_limits=MessagingLimitsDAO(admission_seconds=0.02),
        ),
        messaging_executor_factory=lambda: gate,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    await session.start_messaging()
    await session._lock.acquire()
    from src.agents.slo_agent.messaging.queue import SessionMessageQueue

    queue: Optional[SessionMessageQueue] = session._message_queue
    assert queue is not None
    await wait_until(predicate=lambda: len(queue._changed._waiters) == 2)
    gate.armed = True
    stream: AsyncGenerator[AgentStreamEventDAO, None] = session.invoke(text="Unknown then applied")
    first: asyncio.Task[AgentStreamEventDAO] = asyncio.create_task(coro=anext(stream))
    try:
        await wait_until(predicate=gate.started.is_set if hold_before else gate.completed.is_set)
        await asyncio.sleep(delay=0.05)
        assert not first.done() and len(session._messaging_calls) == 1
        assert len(session._invocation_observers) == 1
        message_id: str = next(iter(session._invocation_observers))
        gate.release.set()
        session._lock.release()
        async with asyncio.timeout(delay=5):
            first_event: AgentStreamEventDAO = await first
            events: list[AgentStreamEventDAO] = [first_event, *[event async for event in stream]]
        assert events[-1].kind == "run_completed"
        assert session._message_store is not None
        identities: tuple[MessageIdentityDAO, ...] = await session._message_store.read_identities()
        assert len(identities) == 1 and identities[0].receipt.message_id == message_id
        assert identities[0].receipt.state == "applied" and len(model.requests) == 1
    finally:
        gate.release.set()
        if session._lock.locked() and not session.is_running:
            session._lock.release()
        await asyncio.gather(first, return_exceptions=True)
        await stream.aclose()
        await session.close_messaging()


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_multi_application_recovery_validates_all_before_applied_transition(
    tmp_path: Path, tree: bool
) -> None:
    """A bad later journal cannot certify an earlier reconstructed application as applied."""
    import sqlite3

    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id: str = str(uuid4())
    target: MessageAddressDAO = MessageAddressDAO(
        kind="agent_session", session_id=session_id, generation=str(uuid4())
    )
    history: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    await history.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    path: Path = root / session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store: MessageStore = await MessageStore.open(path=path, target=target, limits=MessagingLimitsDAO())
    await store.set_lifecycle(accepting=True)
    for index in range(2):
        submission: MessageSubmissionDAO = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text=f"Recovery {index}"
        )
        await store.admit(
            submission=submission, principal=MessagePrincipalDAO(principal_id="original", kind="human")
        )
        delivery: Optional[MessageDeliveryDAO] = await store.claim_one(
            boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0)
        )
        assert delivery is not None
        await store.prepare_application(
            delivery=delivery, event=application_event(delivery=delivery, generation=target.generation)
        )
    await store.close()
    connection: sqlite3.Connection = sqlite3.connect(database=str(path))
    try:
        connection.execute(
            "UPDATE applications SET event_json='{}' WHERE message_id=?", (submission.message_id,)
        )
        connection.commit()
    finally:
        connection.close()
    model: RecordingModel = RecordingModel(responses=[])
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        history_store=history,
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    try:
        with pytest.raises(expected_exception=MessageStoreError):
            await session.start_messaging()
        assert not model.requests and not session._messaging_accepting
    finally:
        await session.close_messaging()
    connection = sqlite3.connect(database=str(path))
    try:
        states: list[tuple[str]] = connection.execute(
            "SELECT state FROM messages ORDER BY sequence"
        ).fetchall()
        assert states == [("applying",), ("applying",)]
    finally:
        connection.close()


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
@pytest.mark.parametrize(argnames="applied", argvalues=[False, True])
@pytest.mark.parametrize(argnames="transcript_only", argvalues=[False, True])
async def test_recovery_requires_aggregate_projection_membership_before_any_applied(
    tmp_path: Path, tree: bool, applied: bool, transcript_only: bool
) -> None:
    """Two valid journals cannot be acknowledged when the real summary cut omits one input."""
    import sqlite3

    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id: str = str(uuid4())
    target: MessageAddressDAO = MessageAddressDAO(
        kind="agent_session", session_id=session_id, generation=str(uuid4())
    )
    history: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    await history.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    path: Path = root / session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store: MessageStore = await MessageStore.open(path=path, target=target, limits=MessagingLimitsDAO())
    await store.set_lifecycle(accepting=True)
    prepared: list[SessionHistoryEventDAO] = []
    message_ids: list[str] = []
    try:
        for index in range(2):
            submission: MessageSubmissionDAO = MessageSubmissionDAO(
                message_id=str(uuid4()),
                target=target,
                kind="transcript_note" if transcript_only else "agent_input",
                text=f"Prepared input {index}",
            )
            message_ids.append(submission.message_id)
            await store.admit(
                submission=submission, principal=MessagePrincipalDAO(principal_id="original", kind="human")
            )
            boundary: BoundaryDAO = BoundaryDAO(run_id=str(uuid4()), boundary_index=0)
            delivery: Optional[MessageDeliveryDAO] = (
                await store.claim_note(boundary=boundary)
                if transcript_only
                else await store.claim_one(boundary=boundary)
            )
            assert delivery is not None
            event: SessionHistoryEventDAO = application_event(delivery=delivery, generation=target.generation)
            await store.prepare_application(delivery=delivery, event=event)
            assert (
                SessionHistoryProjector.project_message_application(event=event) is None
            ) is transcript_only
            prepared.append(await history.append_message_application_once(event=event))
            if applied:
                await store.mark_history_committed(message_id=submission.message_id)
                await store.mark_applied(message_id=submission.message_id)
        await history.append_event(
            event=SessionHistoryEventDAO(
                session_id=session_id,
                kind="compaction_summary",
                payload=SessionHistoryEventPayloadDAO(
                    content="Unproven summary cut",
                    metadata={"first_kept_entry_id": prepared[1].event_id},
                ),
            )
        )
        raw: MessageHistoryEvidenceDAO = await history.application_evidence(session_id=session_id)
        projected: list[BaseMessage] = await SessionHistoryProjector.build_message_history(
            events=list(raw.events)
        )
        assert [item.id for item in projected if "messaging_v1" in item.additional_kwargs] == (
            [] if transcript_only else [prepared[1].event_id]
        )
        for message_id in message_ids:
            journal: SessionHistoryEventDAO = await store.load_application_event(message_id=message_id)
            assert (
                SessionHistoryProjector.project_message_application(event=journal) is None
            ) is transcript_only
    finally:
        await store.close()
    model: RecordingModel = RecordingModel(responses=[])
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        history_store=history,
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    try:
        if transcript_only:
            await session.start_messaging()
            assert session._messaging_accepting and session._agent is None
        else:
            with pytest.raises(expected_exception=MessageStoreError):
                await session.start_messaging()
            assert not session._messaging_accepting
        assert not model.requests
    finally:
        await session.close_messaging()
    connection: sqlite3.Connection = sqlite3.connect(database=str(path))
    try:
        states: list[tuple[str, int]] = connection.execute(
            "SELECT identity.state, applications.context_committed FROM identity "
            "JOIN applications USING(message_id) ORDER BY identity.sequence"
        ).fetchall()
        assert states == (
            [("applied", 1), ("applied", 1)]
            if applied or transcript_only
            else [("applying", 0), ("applying", 0)]
        )
    finally:
        connection.close()


async def test_pool_fallback_preserves_real_application_and_context(tmp_path: Path) -> None:
    """A real ModelPool switches before output without claiming a second instruction."""
    import httpx
    from openai import RateLimitError
    from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
    from src.auth.credential_dao import ProviderName

    first: FailingModel = FailingModel(
        errors=[
            RateLimitError(
                message="synthetic rate limit",
                response=httpx.Response(
                    status_code=429, request=httpx.Request(method="POST", url="https://example.invalid")
                ),
                body=None,
            )
        ]
    )
    second: RecordingModel = RecordingModel(responses=[FauxChatModel.assistant_message(content="Fallback")])
    second.release.set()
    pool: ModelPool = ModelPool(
        pool_dao=ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=0),
                ModelPoolEntryDAO(model_name="gpt-5.4-mini", provider=ProviderName.OPENAI, priority=1),
            ]
        ),
        models={"gpt-5.4": first, "gpt-5.4-mini": second},
    )
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        enable_history=False,
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    agent: SloAgent = SloAgent(llm=pool, tools=[], cwd=str(tmp_path), message_source=session)
    try:
        async with session._session_run_scope():
            submission: MessageSubmissionDAO = MessageSubmissionDAO(
                message_id=str(uuid4()),
                target=session.messaging_target,
                kind="agent_input",
                text="One fallback input",
            )
            await client.submit(submission=submission)
            run: MessageRunState = MessageRunState(run_id=str(uuid4()))
            session._message_run = run
            _events: list[AgentStreamEventDAO] = [
                event async for event in agent.invoke(query="", message_run=run)
            ]
            assert len(first.requests) == len(second.requests) == 1
            assert first.requests == second.requests
            assert run.boundary_index == 0 and run.applied_message_ids == {submission.message_id}
            session._message_run = None
    finally:
        await client.close()
        await session.close_messaging()


async def test_overflow_rebuild_keeps_applied_input_covered_without_second_pop(tmp_path: Path) -> None:
    """Actual overflow planning compacts real prior input and borrows the same boundary again."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    model: FailingModel = FailingModel(errors=[])
    model.release.set()
    history: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=root)
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    try:
        async with session._session_run_scope():
            await session._ensure_history_session()
            session._message_run = MessageRunState(run_id=str(uuid4()))
            for index in range(6):
                submission: MessageSubmissionDAO = MessageSubmissionDAO(
                    message_id=str(uuid4()),
                    target=session.messaging_target,
                    kind="agent_input",
                    text=f"Prior {index} " + "x" * 20000,
                )
                await client.submit(submission=submission)
                selected: BoundaryDeliveryDAO = await session.take_one(
                    boundary=BoundaryDAO(run_id=session._message_run.run_id, boundary_index=index)
                )
                assert selected.instruction is not None
                session._message_run.applied_message_ids |= {submission.message_id}
                await session.commit_applied(delivery=selected.instruction)
                session._message_run.boundary_index += 1
                session._message_run.delivery = None
            session._message_run = None
        model.errors = [RuntimeError("context_length_exceeded")]
        async with asyncio.timeout(delay=10):
            events: list[AgentStreamEventDAO] = [
                event async for event in session.invoke(text="Overflow input")
            ]
        assert events[-1].kind == "run_completed"
        assert any(event.kind == "compaction_retrying" for event in events)
        assert session._message_store is not None
        identities: tuple[MessageIdentityDAO, ...] = await session._message_store.read_identities()
        assert len(identities) == 7 and all(identity.receipt.state == "applied" for identity in identities)
        assert len(model.requests) == 2
        assert sum(item.content == "Overflow input" for item in model.requests[-1]) == 1
        ledgers: tuple[CompactionLedgerDAO, ...] = await session._message_store.read_compactions()
        assert len(ledgers) == 1 and ledgers[0].state == "committed"
    finally:
        await client.close()
        await session.close_messaging()


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_retry_after_empty_selection_keeps_late_urgent_input_for_next_boundary(
    tmp_path: Path, tree: bool
) -> None:
    """An outer rebuilt agent borrows a frozen empty boundary, never opportunistically repops it."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    history: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        history_store=history,
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    model: RecordingModel = RecordingModel(responses=[FauxChatModel.assistant_message(content="Done")])
    model.release.set()
    try:
        async with session._session_run_scope():
            await session._ensure_history_session()
            run: MessageRunState = MessageRunState(run_id=str(uuid4()))
            session._message_run = run
            boundary: BoundaryDAO = BoundaryDAO(run_id=run.run_id, boundary_index=0)
            empty: BoundaryDeliveryDAO = await session.take_one(boundary=boundary)
            assert empty.instruction is None and empty.note is None and empty.urgent_high_water == 0
            submission: MessageSubmissionDAO = MessageSubmissionDAO(
                message_id=str(uuid4()),
                target=session.messaging_target,
                kind="agent_input",
                priority="urgent",
                text="Late urgent",
            )
            await client.submit(submission=submission)
            assert session.urgent_high_water() > 0
            rebuilt: SloAgent = RealAgentFactory(model=model, workdir=tmp_path, stop_hook=stop_after_turn)(
                message_source=session
            )
            _events: list[AgentStreamEventDAO] = [
                event async for event in rebuilt.invoke(query="", message_run=run)
            ]
            assert run.delivery is empty and run.boundary_index == 0
            assert not any(isinstance(item, HumanMessage) for item in model.requests[0])
            receipt: MessageReceiptDAO | MessageErrorDAO = await client.get_receipt(
                message_id=submission.message_id
            )
            assert isinstance(receipt, MessageReceiptDAO) and receipt.state == "accepted"
            session._message_run = None
            session._messaging_paused = True
            session._messaging_resumed.clear()
    finally:
        await client.close()
        await session.close_messaging()


async def test_boundary_slot_priority_and_invalid_cursor_are_exact(tmp_path: Path) -> None:
    """One note precedes urgent FIFO input; wrong boundaries cannot claim another slot."""
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        enable_history=False,
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    try:
        async with session._session_run_scope():
            for kind, priority, text in (
                ("agent_input", "normal", "Normal"),
                ("context_note", "normal", "Note"),
                ("agent_input", "urgent", "Urgent first"),
                ("agent_input", "urgent", "Urgent second"),
            ):
                submission: MessageSubmissionDAO = MessageSubmissionDAO.model_validate(
                    {
                        "message_id": str(uuid4()),
                        "target": session.messaging_target,
                        "kind": kind,
                        "priority": priority,
                        "text": text,
                    }
                )
                await client.submit(submission=submission)
            run: MessageRunState = MessageRunState(run_id=str(uuid4()))
            session._message_run = run
            with pytest.raises(expected_exception=MessageStoreError):
                await session.take_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0))
            for index, expected in enumerate(["Urgent first", "Urgent second", "Normal"]):
                selected: BoundaryDeliveryDAO = await session.take_one(
                    boundary=BoundaryDAO(run_id=run.run_id, boundary_index=index)
                )
                assert (
                    selected.instruction is not None
                    and selected.instruction.envelope.submission.text == expected
                )
                assert (selected.note is not None) == (index == 0)
                assert selected.urgent_high_water == (4 if index < 2 else 0)
                for slot in (selected.note, selected.instruction):
                    if slot is not None:
                        run.applied_message_ids |= {slot.envelope.submission.message_id}
                        await session.commit_applied(delivery=slot)
                run.boundary_index += 1
                run.delivery = None
            session._message_run = None
    finally:
        await client.close()
        await session.close_messaging()


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_partial_boundary_claim_failure_never_runs_provider_or_pops_again(
    tmp_path: Path, tree: bool
) -> None:
    """A real second-claim SQLite failure leaves the first claim for startup, not live retry."""
    import sqlite3

    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id: str = str(uuid4())
    history: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    model: RecordingModel = RecordingModel(responses=[])
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        history_store=history,
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    path: Path = root / session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    try:
        async with session._session_run_scope():
            for kind in ("context_note", "agent_input"):
                await client.submit(
                    submission=MessageSubmissionDAO.model_validate(
                        {
                            "message_id": str(uuid4()),
                            "target": session.messaging_target,
                            "kind": kind,
                            "text": kind,
                        }
                    )
                )
            connection: sqlite3.Connection = sqlite3.connect(database=str(path))
            try:
                connection.execute(
                    "CREATE TRIGGER refuse_input_claim BEFORE UPDATE OF state ON messages "
                    "WHEN NEW.state='applying' AND NEW.kind='agent_input' "
                    "BEGIN SELECT RAISE(ABORT, 'synthetic second claim failure'); END"
                )
                connection.commit()
            finally:
                connection.close()
            run: MessageRunState = MessageRunState(run_id=str(uuid4()))
            session._message_run = run
            agent: SloAgent = RealAgentFactory(model=model, workdir=tmp_path)(message_source=session)
            with pytest.raises(expected_exception=MessageStoreError):
                _events: list[AgentStreamEventDAO] = [
                    event async for event in agent.invoke(query="", message_run=run)
                ]
            assert not model.requests and run.delivery is None
            assert session._message_store is not None
            identities: tuple[MessageIdentityDAO, ...] = await session._message_store.read_identities()
            assert [item.receipt.state for item in identities] == ["applying", "accepted"]
            session._message_run = None
    finally:
        await client.close()
        with pytest.raises(expected_exception=MessageStoreError):
            await session.close_messaging()
        assert session._messaging_scheduler is not None and session._messaging_scheduler.done()
        assert session._messaging_note_task is not None and session._messaging_note_task.done()
        lease: SessionExecutionOwnership = await SessionExecutionOwnership.acquire(
            root=root, session_id=session_id
        )
        await lease.release()


@pytest.mark.parametrize(argnames="cancelled", argvalues=[False, True])
async def test_restart_reconciliation_waiter_joins_before_readiness_and_release(
    tmp_path: Path, cancelled: bool
) -> None:
    """A held real history scan cannot publish readiness or lose ownership on cancellation."""
    from tests.agents.slo_agent.messaging.test_queue_closure import CompletionGate, wait_until

    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id: str = str(uuid4())
    history: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=root)
    await history.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    gate: CompletionGate = CompletionGate(hold_before=False)
    asyncio.get_running_loop().set_default_executor(executor=gate)
    gate.armed = True
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        history_store=history,
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
    )
    startup: asyncio.Task[None] = asyncio.create_task(coro=session.start_messaging())
    try:
        await wait_until(predicate=gate.completed.is_set)
        assert not session._messaging_accepting
        if cancelled:
            startup.cancel()
            await asyncio.sleep(delay=0)
            startup.cancel()
        assert not startup.done()
        with pytest.raises(expected_exception=SessionAlreadyOwnedError):
            await SessionExecutionOwnership.acquire(root=root, session_id=session_id)
        gate.release.set()
        if cancelled:
            with pytest.raises(expected_exception=asyncio.CancelledError):
                await startup
        else:
            await startup
        assert session._messaging_accepting
    finally:
        gate.release.set()
        await asyncio.gather(startup, return_exceptions=True)
        await session.close_messaging()
    lease: SessionExecutionOwnership = await SessionExecutionOwnership.acquire(
        root=root, session_id=session_id
    )
    await lease.release()


async def test_terminal_before_observer_resume_retains_one_final_outcome(tmp_path: Path) -> None:
    """A paused generator drains the final outcome even after its execution cursor is gone."""
    model: RecordingModel = RecordingModel(responses=[FauxChatModel.assistant_message(content="Done")])
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        enable_history=False,
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    await session.start_messaging()
    stream: AsyncGenerator[AgentStreamEventDAO, None] = session.invoke(text="Fast terminal")
    first: asyncio.Task[AgentStreamEventDAO] = asyncio.create_task(coro=anext(stream))
    try:
        async with asyncio.timeout(delay=5):
            await model.entered.wait()
        model.release.set()
        async with asyncio.timeout(delay=5):
            first_event: AgentStreamEventDAO = await first
            while session.is_running:
                await asyncio.sleep(delay=0)
        assert session._message_run is None and len(session._invocation_observers) == 1
        assert next(iter(session._invocation_observers.values())).terminal is not None
        events: list[AgentStreamEventDAO] = [first_event, *[event async for event in stream]]
        assert [event.kind for event in events].count("run_completed") == 1
        assert not session._invocation_observers
    finally:
        model.release.set()
        await asyncio.gather(first, return_exceptions=True)
        await stream.aclose()
        await session.close_messaging()


@pytest.mark.parametrize(argnames="stage", argvalues=["candidate", "metadata"])
async def test_real_compaction_filesystem_failure_rolls_back_prepared_membership(
    tmp_path: Path, stage: str
) -> None:
    """Real filesystem obstruction exercises tagged activation rollback, without durability mocks."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    history: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=root)
    session_id: str = str(uuid4())
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        history_store=history,
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    obstruction: Path = (
        root / session_id / ("events.jsonl.compaction-candidate" if stage == "candidate" else "session.json")
    )
    assert obstruction.resolve().is_relative_to(tmp_path.resolve())
    try:
        async with session._session_run_scope():
            await session._ensure_history_session()
            run: MessageRunState = MessageRunState(run_id=str(uuid4()))
            session._message_run = run
            submission: MessageSubmissionDAO = MessageSubmissionDAO(
                message_id=str(uuid4()),
                target=session.messaging_target,
                kind="agent_input",
                text="Preserve exact bytes",
            )
            await client.submit(submission=submission)
            selected: BoundaryDeliveryDAO = await session.take_one(
                boundary=BoundaryDAO(run_id=run.run_id, boundary_index=0)
            )
            assert selected.instruction is not None
            run.applied_message_ids |= {submission.message_id}
            await session.commit_applied(delivery=selected.instruction)
            kept: SessionHistoryEventDAO = await history.append_event(
                event=SessionHistoryEventDAO(session_id=session_id, kind="run_completed")
            )
            events: list[SessionHistoryEventDAO] = list(
                (await history.application_evidence(session_id=session_id)).events
            )
            active: Path = root / session_id / "events.jsonl"
            assert active.resolve().is_relative_to(tmp_path.resolve())
            before: bytes = active.read_bytes()
            if stage == "metadata":
                obstruction.unlink()
            obstruction.mkdir()
            with pytest.raises(expected_exception=(OSError, MessageStoreError)):
                async with session._history_barrier:
                    await session._activate_message_compaction(
                        events=events,
                        turn_id=str(uuid4()),
                        result=CompactionResult(
                            summary_text="Summary",
                            first_kept_entry_id=kept.event_id,
                            cut_point_entry_id=events[0].event_id,
                            tokens_before=20,
                            tokens_after=5,
                        ),
                    )
            assert active.read_bytes() == before
            assert session._message_store is not None
            ledgers: tuple[CompactionLedgerDAO, ...] = await session._message_store.read_compactions()
            assert len(ledgers) == 1 and ledgers[0].state == "rolled_back"
            obstruction.rmdir()
            await session._verify_borrowed_message_run()
            session._message_run = None
    finally:
        if obstruction.is_dir():
            obstruction.rmdir()
        await client.close()
        await session.close_messaging()


@pytest.mark.parametrize(argnames="outcome", argvalues=["failure", "cancel_before", "cancel_after"])
async def test_sqlite_compaction_finish_after_activation_settles_before_release(
    tmp_path: Path, outcome: str
) -> None:
    """Active tagged history plus failed/cancelled ledger finish reconciles once without reinsertion."""
    import sqlite3
    from tests.agents.slo_agent.messaging.test_queue_closure import CompletionGate, wait_until

    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id: str = str(uuid4())
    path: Path = root / session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    history: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=root)
    model: RecordingModel = RecordingModel(responses=[FauxChatModel.assistant_message(content="Done")])
    model.release.set()
    gate: CompletionGate = CompletionGate(hold_before=outcome == "cancel_before")
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        history_store=history,
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
        messaging_executor_factory=lambda: gate,
    )
    await session.start_messaging()
    _observed: list[AgentStreamEventDAO] = [
        event async for event in session.invoke(text="Compact this input")
    ]
    assert len(model.requests) == 1
    events: list[SessionHistoryEventDAO] = list(
        (await history.application_evidence(session_id=session_id)).events
    )
    application: SessionHistoryEventDAO = next(
        event for event in events if "messaging_v1" in event.payload.metadata
    )
    kept: SessionHistoryEventDAO = events[-1]
    assert kept.kind == "run_completed"
    assert session._message_store is not None
    identity: MessageIdentityDAO = (await session._message_store.read_identities())[0]
    if outcome == "failure":
        connection: sqlite3.Connection = sqlite3.connect(database=str(path))
        try:
            connection.execute(
                "CREATE TRIGGER refuse_finish BEFORE UPDATE OF state ON compactions "
                "WHEN NEW.state='committed' BEGIN SELECT RAISE(ABORT, 'synthetic ledger finish failure'); END"
            )
            connection.commit()
        finally:
            connection.close()

    async def arm_finish_after_prepare() -> None:
        """Observe real preparation before the history worker can finish its rewrite."""
        while True:
            connection: sqlite3.Connection = sqlite3.connect(database=str(path))
            try:
                prepared: bool = connection.execute("SELECT 1 FROM compactions").fetchone() is not None
            finally:
                connection.close()
            if prepared:
                gate.armed = True
                return
            await asyncio.sleep(delay=0)

    arming: Optional[asyncio.Task[None]] = (
        asyncio.create_task(coro=arm_finish_after_prepare()) if outcome != "failure" else None
    )

    async def compact() -> None:
        """Use the existing execution/history owners for this already-generated summary."""
        async with session._session_run_scope():
            async with session._history_barrier:
                await session._activate_message_compaction(
                    events=events,
                    result=CompactionResult(
                        summary_text="Input covered once",
                        first_kept_entry_id=kept.event_id,
                        cut_point_entry_id=application.event_id,
                        tokens_before=100,
                        tokens_after=10,
                    ),
                    turn_id=str(uuid4()),
                )

    rewriting: asyncio.Task[None] = asyncio.create_task(coro=compact())
    closing: Optional[asyncio.Task[None]] = None
    try:
        if outcome == "failure":
            with pytest.raises(expected_exception=MessageStoreError):
                await rewriting
            assert session._messaging_storage_failed and session._messaging_paused
            assert session._message_queue is not None and session._message_queue._sealed
        else:
            await wait_until(
                predicate=gate.started.is_set if outcome == "cancel_before" else gate.completed.is_set
            )
            rewriting.cancel()
            await asyncio.sleep(delay=0)
            rewriting.cancel()
            assert not rewriting.done() and session._history_barrier.locked()
            with pytest.raises(expected_exception=SessionAlreadyOwnedError):
                await SessionExecutionOwnership.acquire(root=root, session_id=session_id)
        active: MessageHistoryEvidenceDAO = await history.application_evidence(session_id=session_id)
        summaries: list[SessionHistoryEventDAO] = [
            event for event in active.events if event.kind == "compaction_summary"
        ]
        assert len(summaries) == 1
        summary: SessionHistoryEventDAO = summaries[0]
        compaction_id: object = summary.payload.metadata["messaging_compaction_id"]
        assert isinstance(compaction_id, str)
        assert not any(event.event_id == application.event_id for event in active.events)
        connection = sqlite3.connect(database=str(path))
        try:
            ledger_rows: list[tuple[str, Optional[str]]] = connection.execute(
                "SELECT state, summary_event_id FROM compactions"
            ).fetchall()
            expected_ledger_rows: list[tuple[str, Optional[str]]] = (
                [("committed", summary.event_id)] if outcome == "cancel_after" else [("prepared", None)]
            )
            assert ledger_rows == expected_ledger_rows
            members: list[tuple[str, str]] = connection.execute(
                "SELECT compaction_id, message_id FROM compacted_applications"
            ).fetchall()
            assert members == [(compaction_id, identity.receipt.message_id)]
        finally:
            connection.close()
        if outcome != "failure":
            closing = asyncio.create_task(coro=session.close_messaging())
            await asyncio.sleep(delay=0)
            closing.cancel()
            await asyncio.sleep(delay=0)
            closing.cancel()
            assert not closing.done()
            assert session._message_store is not None and not session._message_store._closed
            with pytest.raises(expected_exception=SessionAlreadyOwnedError):
                await SessionExecutionOwnership.acquire(root=root, session_id=session_id)
            gate.release.set()
            with pytest.raises(expected_exception=asyncio.CancelledError):
                await rewriting
            with pytest.raises(expected_exception=asyncio.CancelledError):
                await closing
        assert len(model.requests) == 1
    finally:
        gate.release.set()
        await asyncio.gather(rewriting, return_exceptions=True)
        if arming is not None:
            arming.cancel()
            await asyncio.gather(arming, return_exceptions=True)
        if closing is not None:
            await asyncio.gather(closing, return_exceptions=True)
        await session.close_messaging()
    lease: SessionExecutionOwnership = await SessionExecutionOwnership.acquire(
        root=root, session_id=session_id
    )
    await lease.release()
    if outcome == "failure":
        connection = sqlite3.connect(database=str(path))
        try:
            connection.execute("DROP TRIGGER refuse_finish")
            connection.commit()
        finally:
            connection.close()
    restarted: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        history_store=FilesystemSessionHistoryStore(root=root),
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    try:
        await restarted.start_messaging()
        assert restarted._message_store is not None
        ledgers: tuple[CompactionLedgerDAO, ...] = await restarted._message_store.read_compactions()
        assert len(ledgers) == 1 and ledgers[0].state == "committed"
        assert ledgers[0].summary_event_id == summary.event_id
        assert ledgers[0].message_ids == (identity.receipt.message_id,)
        assert (await restarted._message_store.read_identities())[0].receipt.state == "applied"
        await restarted._reconcile_message_applications(store=restarted._message_store)
        assert await restarted._message_store.read_compactions() == ledgers
        assert restarted._history_store is not None
        recovered: MessageHistoryEvidenceDAO = await restarted._history_store.application_evidence(
            session_id=session_id
        )
        assert sum(event.event_id == summary.event_id for event in recovered.events) == 1
        assert not any(event.event_id == application.event_id for event in recovered.events)
        assert len(model.requests) == 1
    finally:
        await restarted.close_messaging()


class CommittedDisconnectModel(RecordingModel):
    """Commit visible output once, then fail at the external stream boundary."""

    interrupted: bool = Field(
        default=False,
        description="Whether the one scripted committed-stream disconnect has already occurred.",
    )

    def __init__(self, *, responses: Sequence[AIMessage]) -> None:
        """Initialize the deterministic completion used after the committed disconnect."""
        super().__init__(responses=responses)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Hold the first disconnect until the test requests a real lazy rebuild."""
        import httpx

        if not self.interrupted:
            self.interrupted = True
            self.requests.append(list(messages))
            yield ChatGenerationChunk(message=AIMessageChunk(content="Committed partial answer"))
            self.entered.set()
            await self.release.wait()
            raise httpx.RemoteProtocolError("synthetic committed disconnect")
        async for chunk in super()._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


class RebuildRecordingFactory(RealAgentFactory):
    """Record actual agent constructions and the borrowed session cursor at each build."""

    def __init__(self, *, model: RecordingModel, workdir: Path) -> None:
        """Keep build observations without changing session or agent execution."""
        super().__init__(model=model, workdir=workdir)
        self.agents: list[SloAgent] = []
        self.runs: list[MessageRunState] = []
        self.deliveries: list[Optional[BoundaryDeliveryDAO]] = []

    def __call__(self, *, message_source: AgentMessageSource) -> SloAgent:
        """Construct through the original factory and inspect the real source's cursor."""
        assert isinstance(message_source, SloAgentSession)
        run: Optional[MessageRunState] = message_source._message_run
        assert run is not None
        self.runs.append(run)
        self.deliveries.append(run.delivery)
        agent: SloAgent = super().__call__(message_source=message_source)
        self.agents.append(agent)
        return agent


@pytest.mark.parametrize(argnames="persistence", argvalues=["flat", "tree", "ephemeral"])
async def test_committed_disconnect_continuation_rebuild_borrows_same_cursor(
    tmp_path: Path, persistence: str
) -> None:
    """A real outer continuation reloads a new agent without reclaiming or reinserting input."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    history: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if persistence == "tree"
        else FilesystemSessionHistoryStore(root=root)
    )
    model: CommittedDisconnectModel = CommittedDisconnectModel(
        responses=[FauxChatModel.assistant_message(content="Final answer")]
    )
    factory: RebuildRecordingFactory = RebuildRecordingFactory(model=model, workdir=tmp_path)
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        history_store=history,
        enable_history=persistence != "ephemeral",
        messaging_agent_factory=factory,
    )
    await session.start_messaging()
    stream: AsyncGenerator[AgentStreamEventDAO, None] = session.invoke(text="Original accepted input")
    observed: list[AgentStreamEventDAO] = []

    async def observe() -> None:
        """Drain only the real public compatibility observer to its final logical outcome."""
        async for event in stream:
            observed.append(event)

    observer: asyncio.Task[None] = asyncio.create_task(coro=observe())
    try:
        async with asyncio.timeout(delay=10):
            await model.entered.wait()
            while not any(event.kind == "text_delta" for event in observed):
                await asyncio.sleep(delay=0)
        run: Optional[MessageRunState] = session._message_run
        assert run is not None and run.delivery is not None
        selected: BoundaryDeliveryDAO = run.delivery
        assert selected.instruction is not None and run.boundary_index == 0
        message_id: str = selected.instruction.envelope.submission.message_id
        assert run.applied_message_ids == {message_id}
        assert session.switch_reasoning_level(reasoning_level="low") == "low"
        assert session._agent is None
        model.release.set()
        async with asyncio.timeout(delay=10):
            await observer
        assert len(factory.agents) == 2 and factory.agents[0] is not factory.agents[1]
        assert factory.runs == [run, run] and factory.runs[0] is factory.runs[1]
        assert factory.deliveries == [None, selected] and factory.deliveries[1] is selected
        assert run.delivery is selected and run.boundary_index == 0
        assert run.applied_message_ids == {message_id}
        assert len(model.requests) == 2
        for request in model.requests:
            assert [item.content for item in request if isinstance(item, HumanMessage)] == [
                "Original accepted input"
            ]
        assert [event.kind for event in observed if event.kind in ("run_failed", "run_completed")] == [
            "run_completed"
        ]
        assert session._message_store is not None
        identities: tuple[MessageIdentityDAO, ...] = await session._message_store.read_identities()
        assert len(identities) == 1 and identities[0].receipt.state == "applied"
        assert identities[0].receipt.run_id == run.run_id
        if persistence == "ephemeral":
            assert not root.exists()
            journal: SessionHistoryEventDAO = await session._message_store.load_application_event(
                message_id=message_id
            )
            assert journal.payload.content == "Original accepted input"
            assert not session._invocation_observers
            return
        events: list[SessionHistoryEventDAO] = await history.load_events(session_id=session.session_id)
        applications: list[SessionHistoryEventDAO] = [
            event for event in events if "messaging_v1" in event.payload.metadata
        ]
        assert len(applications) == 1 and applications[0].turn_id == run.run_id
        assert any(
            event.kind == "run_retrying"
            and event.payload.metadata.get("reason_code") == "provider_stream_interrupted"
            and event.payload.metadata.get("attempt") == 2
            for event in events
        )
        assert any(
            event.kind == "run_failed" and event.payload.metadata.get("partial_output_committed") is True
            for event in events
        )
        attempts: set[Optional[str]] = {event.turn_id for event in events if event.kind == "run_started"}
        assert len(attempts) == 2 and run.run_id not in attempts
        assert not any(event.kind == "user_message" for event in events)
        assert not session._invocation_observers
    finally:
        model.release.set()
        await asyncio.gather(observer, return_exceptions=True)
        await stream.aclose()
        await session.close_messaging()


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
@pytest.mark.parametrize(argnames="covered", argvalues=[False, True])
async def test_outer_rebuild_requires_applied_aggregate_membership_or_committed_coverage(
    tmp_path: Path, tree: bool, covered: bool
) -> None:
    """A real continuation must not borrow an applied ID omitted by an unproven summary cut."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    history: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    model: CommittedDisconnectModel = CommittedDisconnectModel(
        responses=[FauxChatModel.assistant_message(content="Covered continuation")]
    )
    factory: RebuildRecordingFactory = RebuildRecordingFactory(model=model, workdir=tmp_path)
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        history_store=history,
        messaging_agent_factory=factory,
    )
    await session.start_messaging()
    observed: list[AgentStreamEventDAO] = []

    async def observe() -> None:
        """Read the real compatibility stream, including the logical terminal failure."""
        async for event in session.invoke(text="Do not lose this applied instruction"):
            observed.append(event)

    observer: asyncio.Task[None] = asyncio.create_task(coro=observe())
    try:
        async with asyncio.timeout(delay=10):
            await model.entered.wait()
            while not any(event.kind == "text_delta" for event in observed):
                await asyncio.sleep(delay=0)
        run: Optional[MessageRunState] = session._message_run
        assert run is not None and run.delivery is not None
        selected: BoundaryDeliveryDAO = run.delivery
        assert selected.instruction is not None and selected.instruction.event is not None
        application: SessionHistoryEventDAO = selected.instruction.event
        message_id: str = selected.instruction.envelope.submission.message_id
        store: Optional[MessageStore] = session._message_store
        assert store is not None
        compaction_id: str = str(uuid4())
        async with session._history_barrier:
            if covered:
                await store.prepare_compaction(
                    compaction_id=compaction_id, message_ids=(message_id,), observation_ids=()
                )
            summary: SessionHistoryEventDAO = await history.append_event(
                event=SessionHistoryEventDAO(
                    session_id=session.session_id,
                    kind="compaction_summary",
                    payload=SessionHistoryEventPayloadDAO(
                        content="Committed coverage" if covered else "Unproven summary cut",
                        metadata={"messaging_compaction_id": compaction_id} if covered else {},
                    ),
                )
            )
            if covered:
                await store.finish_compaction(compaction_id=compaction_id, summary_event_id=summary.event_id)
        raw: MessageHistoryEvidenceDAO = await history.application_evidence(session_id=session.session_id)
        assert sum(event.event_id == application.event_id for event in raw.events) == 1
        assert (
            next(event for event in raw.events if event.event_id == application.event_id).application_sha256()
            == application.application_sha256()
        )
        projected: list[BaseMessage] = await SessionHistoryProjector.build_message_history(
            events=list(raw.events)
        )
        assert application.event_id not in {message.id for message in projected}
        assert SessionHistoryProjector.project_message_application(event=application) is not None
        assert session.switch_reasoning_level(reasoning_level="low") == "low"
        assert session._agent is None
        model.release.set()
        if covered:
            async with asyncio.timeout(delay=10):
                await observer
            assert len(factory.agents) == 2 and len(model.requests) == 2
            assert any("Committed coverage" in str(message.content) for message in model.requests[1])
            assert not any(message.content == application.payload.content for message in model.requests[1])
        else:
            with pytest.raises(expected_exception=MessageStoreError):
                async with asyncio.timeout(delay=10):
                    await observer
            assert len(factory.agents) == len(model.requests) == 1
            assert session._agent is None and session._messaging_storage_failed
            assert session._messaging_paused and not session._messaging_accepting
        assert run.delivery is selected and run.applied_message_ids == {message_id}
        identities: tuple[MessageIdentityDAO, ...] = await store.read_identities()
        assert len(identities) == 1 and identities[0].receipt.state == "applied"
        after: MessageHistoryEvidenceDAO = await history.application_evidence(session_id=session.session_id)
        assert sum(event.event_id == application.event_id for event in after.events) == 1
        assert not any(event.kind == "user_message" for event in after.events)
    finally:
        model.release.set()
        await asyncio.gather(observer, return_exceptions=True)
        await session.close_messaging()


@pytest.mark.parametrize(argnames="persistence", argvalues=["flat", "tree", "ephemeral"])
async def test_final_attempt_projection_rejects_excluded_applied_identity(
    tmp_path: Path, persistence: str
) -> None:
    """Final plan filtering cannot silently omit an otherwise valid applied journal."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    history: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if persistence == "tree"
        else FilesystemSessionHistoryStore(root=root)
    )
    model: RecordingModel = RecordingModel(responses=[])
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        history_store=history,
        enable_history=persistence != "ephemeral",
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    try:
        async with session._session_run_scope():
            await session._ensure_history_session()
            submission: MessageSubmissionDAO = MessageSubmissionDAO(
                message_id=str(uuid4()),
                target=session.messaging_target,
                kind="agent_input",
                text="Retain through final filtering",
            )
            accepted: MessageReceiptDAO | MessageErrorDAO = await client.submit(submission=submission)
            assert isinstance(accepted, MessageReceiptDAO)
            run: MessageRunState = MessageRunState(run_id=str(uuid4()))
            session._message_run = run
            selected: BoundaryDeliveryDAO = await session.take_one(
                boundary=BoundaryDAO(run_id=run.run_id, boundary_index=0)
            )
            assert selected.instruction is not None
            run.applied_message_ids |= {submission.message_id}
            await session.commit_applied(delivery=selected.instruction)
            plan: PromptAttemptPlanDAO = session._build_initial_attempt_plan(text="").model_copy(
                update={"excluded_turn_ids": frozenset({run.run_id})}
            )
            with pytest.raises(expected_exception=MessageStoreError):
                await session._prepare_attempt_context(plan=plan)
            assert not model.requests and session._messaging_storage_failed
            assert session._agent is None
            assert run.delivery is selected and run.applied_message_ids == {submission.message_id}
            session._message_run = None
    finally:
        await client.close()
        await session.close_messaging()


class FailingModel(RecordingModel):
    """Deterministic external failures exercise the real agent and session retry planners."""

    errors: list[Exception] = Field(
        default_factory=list,
        description="Ordered external failures consumed before a scripted successful response.",
    )

    def __init__(self, *, errors: list[Exception]) -> None:
        """Keep exact exception identity outside persistence and return one eventual answer."""
        super().__init__(responses=[FauxChatModel.assistant_message(content="Recovered") for _ in range(2)])
        self.errors = list(errors)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Raise before the first chunk without replacing any queue or persistence operation."""
        if self.errors:
            self.requests.append(list(messages))
            raise self.errors.pop(0)
        async for chunk in super()._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


class RetryOnceModel(RecordingModel):
    """Raise once before provider output, preserving the actual request recorder."""

    failures_left: int = Field(
        default=1,
        description="Remaining scripted preoutput failures before the external model succeeds.",
    )

    def __init__(self, *, responses: Sequence[AIMessage]) -> None:
        """Retain the explicit deterministic provider constructor contract."""
        super().__init__(responses=responses)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Fail at the external provider boundary before any chunk is committed."""
        if self.failures_left:
            self.failures_left -= 1
            self.requests.append(list(messages))
            raise ConnectionError("synthetic precommit failure")
        async for chunk in super()._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


def retry_first_failure(error: BaseException, visible: bool, attempt: int) -> RateLimitRetryPlanDAO:
    """External retry callback's Callable contract is positional and bounded."""
    return RateLimitRetryPlanDAO(retryable=not visible and attempt == 1, wait_seconds=0, message="Retry")


async def test_real_iteration_retry_reuses_application_boundary(tmp_path: Path) -> None:
    """A preoutput provider retry keeps one cached claim/insertion, not a second live pop."""
    session_id: str = str(uuid4())
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        enable_history=False,
        config=SessionConfigDAO(workdir=tmp_path, session_id=session_id, model_name="gpt-5.4"),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    model: RetryOnceModel = RetryOnceModel(responses=[FauxChatModel.assistant_message(content="Recovered")])
    model.release.set()
    agent: SloAgent = RealAgentFactory(model=model, workdir=tmp_path)(message_source=session)
    try:
        async with session._session_run_scope():
            submission: MessageSubmissionDAO = MessageSubmissionDAO(
                message_id=str(uuid4()),
                target=session.messaging_target,
                kind="agent_input",
                text="One exact input",
            )
            await client.submit(submission=submission)
            run: MessageRunState = MessageRunState(run_id=str(uuid4()))
            session._message_run = run
            events: list[AgentStreamEventDAO] = [
                event
                async for event in agent.invoke(
                    query="", message_run=run, iteration_retry_policy=retry_first_failure
                )
            ]
            assert any(event.kind == "run_retrying" for event in events)
            assert len(model.requests) == 2 and model.requests[0] == model.requests[1]
            assert run.boundary_index == 0 and run.applied_message_ids == {submission.message_id}
            assert session._message_store is not None
            identities: tuple[MessageIdentityDAO, ...] = await session._message_store.read_identities()
            assert len(identities) == 1 and identities[0].receipt.state == "applied"
            session._message_run = None
    finally:
        await client.close()
        await session.close_messaging()


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_client_delivery_reaches_real_agent_and_ack_before_provider(tmp_path: Path, tree: bool) -> None:
    """Actual graph input equals replay, one canonical application and applied receipt."""
    history_root: Path = tmp_path / "history"
    assert history_root.resolve().is_relative_to(tmp_path.resolve())
    store: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=history_root)
        if tree
        else FilesystemSessionHistoryStore(root=history_root)
    )
    model: RecordingModel = RecordingModel(responses=[FauxChatModel.assistant_message(content="Applied.")])
    session_id: str = str(uuid4())
    config: SessionConfigDAO = SessionConfigDAO(
        workdir=tmp_path, history_root=history_root, session_id=session_id, model_name="gpt-5.4"
    )
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=config,
        history_store=store,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    submission: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()),
        target=session.messaging_target,
        kind="agent_input",
        text="Use this exact canonical instruction.",
    )
    try:
        outcome: MessageReceiptDAO | MessageErrorDAO = await client.submit(submission=submission)
        assert isinstance(outcome, MessageReceiptDAO)
        try:
            async with asyncio.timeout(delay=5):
                await model.entered.wait()
        except TimeoutError:
            if session._messaging_failure is not None:
                raise session._messaging_failure
            raise
        applied: MessageReceiptDAO | MessageErrorDAO = await client.get_receipt(
            message_id=submission.message_id
        )
        assert isinstance(applied, MessageReceiptDAO)
        assert applied.state == "applied" and applied.applied_at is not None and applied.run_id is not None
        evidence: MessageHistoryEvidenceDAO = await store.application_evidence(session_id=session_id)
        applications: list[SessionHistoryEventDAO] = [
            event for event in evidence.events if "messaging_v1" in event.payload.metadata
        ]
        assert len(applications) == 1
        event: SessionHistoryEventDAO = applications[0]
        assert event.recorded_at == applied.admitted_at
        assert event.turn_id == applied.run_id
        assert event.payload.content == submission.text
        assert event.payload.metadata["messaging_v1"][
            "sender"
        ] == session.messaging_owner_principal.model_dump(mode="json")
        assert session._message_store is not None
        journal: SessionHistoryEventDAO = await session._message_store.load_application_event(
            message_id=submission.message_id
        )
        assert journal.application_sha256() == event.application_sha256()
        identities: tuple[MessageIdentityDAO, ...] = await session._message_store.read_identities()
        assert len(identities) == 1
        assert identities[0].history_event_id == event.event_id
        assert identities[0].event_sha256 == event.application_sha256()
        assert not any(item.kind == "user_message" for item in evidence.events)
        human: list[BaseMessage] = [
            message for message in model.requests[0] if isinstance(message, HumanMessage)
        ]
        assert len(human) == 1 and human[0].content == submission.text
        replay: list[BaseMessage] = await SessionHistoryProjector.build_message_history(
            events=list(evidence.events)
        )
        assert replay == human
        assert len(model.requests) == 1
    finally:
        model.release.set()
        async with asyncio.timeout(delay=5):
            while session.is_running:
                await asyncio.sleep(delay=0)
        await client.close()
        await session.close_messaging()


@pytest.mark.parametrize(argnames="note_kind", argvalues=["context_note", "transcript_note"])
async def test_note_and_instruction_share_next_real_boundary(tmp_path: Path, note_kind: str) -> None:
    """A held real graph admits both lanes; notes precede input and transcript never enters context."""
    history_root: Path = tmp_path / "history"
    assert history_root.resolve().is_relative_to(tmp_path.resolve())
    history: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=history_root)
    model: RecordingModel = RecordingModel(
        responses=[
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="echo", args={"text": "ok"})]
            ),
            FauxChatModel.assistant_message(content="Finished."),
        ]
    )
    session_id: str = str(uuid4())
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=history_root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path, tools=[echo_tool]),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    first: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="First input"
    )
    note: MessageSubmissionDAO = MessageSubmissionDAO.model_validate(
        {
            "message_id": str(uuid4()),
            "target": session.messaging_target,
            "kind": note_kind,
            "text": "Canonical note",
        }
    )
    second: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="Second input"
    )
    try:
        assert isinstance(await client.submit(submission=first), MessageReceiptDAO)
        async with asyncio.timeout(delay=5):
            await model.entered.wait()
        note_result: MessageReceiptDAO | MessageErrorDAO = await client.submit(submission=note)
        assert isinstance(note_result, MessageReceiptDAO)
        assert isinstance(await client.submit(submission=second), MessageReceiptDAO)
        model.release.set()
        async with asyncio.timeout(delay=5):
            while session.is_running:
                await asyncio.sleep(delay=0)
        assert session._messaging_failure is None
        assert len(model.requests) == 2
        human_messages: list[BaseMessage] = [
            item for item in model.requests[1] if isinstance(item, HumanMessage)
        ]
        assert [item.content for item in human_messages] == (
            [first.text, note.text, second.text] if note_kind == "context_note" else [first.text, second.text]
        )
        evidence: MessageHistoryEvidenceDAO = await history.application_evidence(session_id=session_id)
        applications: list[SessionHistoryEventDAO] = [
            item for item in evidence.events if "messaging_v1" in item.payload.metadata
        ]
        assert [item.payload.content for item in applications] == [first.text, note.text, second.text]
        for request in (first, note, second):
            receipt: MessageReceiptDAO | MessageErrorDAO = await client.get_receipt(
                message_id=request.message_id
            )
            assert isinstance(receipt, MessageReceiptDAO) and receipt.state == "applied"
    finally:
        model.release.set()
        await client.close()
        await session.close_messaging()


async def test_boundary_cache_freezes_empty_and_ack_retry_skips_context_insert(tmp_path: Path) -> None:
    """Real session source freezes even empty selection; repeat insertion only retries real ack."""
    session_id: str = str(uuid4())
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        enable_history=False,
        config=SessionConfigDAO(workdir=tmp_path, session_id=session_id, model_name="gpt-5.4"),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    model: RecordingModel = RecordingModel(responses=[])
    agent: SloAgent = RealAgentFactory(model=model, workdir=tmp_path)(message_source=session)
    messages: list[BaseMessage] = []
    try:
        async with session._session_run_scope():
            run: MessageRunState = MessageRunState(run_id=str(uuid4()))
            session._message_run = run
            boundary: BoundaryDAO = BoundaryDAO(run_id=run.run_id, boundary_index=0)
            empty: BoundaryDeliveryDAO = await session.take_one(boundary=boundary)
            assert empty.note is None and empty.instruction is None
            request: MessageSubmissionDAO = MessageSubmissionDAO(
                message_id=str(uuid4()),
                target=session.messaging_target,
                kind="agent_input",
                text="One insertion",
            )
            assert isinstance(await client.submit(submission=request), MessageReceiptDAO)
            assert await session.take_one(boundary=boundary) is empty
            run.boundary_index += 1
            run.delivery = None
            await agent._apply_message_boundary(accumulated_messages=messages, run=run)
            assert request.message_id in run.applied_message_ids
            await agent._apply_message_boundary(accumulated_messages=messages, run=run)
            assert len(messages) == 1 and messages[0].content == request.text
            receipt: MessageReceiptDAO | MessageErrorDAO = await client.get_receipt(
                message_id=request.message_id
            )
            assert isinstance(receipt, MessageReceiptDAO) and receipt.state == "applied"
            assert model.requests == []
    finally:
        session._message_run = None
        await client.close()
        await session.close_messaging()


@pytest.mark.parametrize(argnames="persistent", argvalues=[False, True])
async def test_idle_notes_are_journaled_without_provider_and_replayed_on_next_input(
    tmp_path: Path, persistent: bool
) -> None:
    """Idle local notes complete history acknowledgement without authorizing model work."""
    history_root: Path = tmp_path / "history"
    assert history_root.resolve().is_relative_to(tmp_path.resolve())
    session_id: str = str(uuid4())
    history: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=history_root)
    model: RecordingModel = RecordingModel(responses=[FauxChatModel.assistant_message(content="Done")])
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, session_id=session_id, history_root=history_root, model_name="gpt-5.4"
        ),
        history_store=history,
        enable_history=persistent,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session,
        target=session.messaging_target,
        principal=session.messaging_owner_principal,
    )
    note: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()),
        target=session.messaging_target,
        kind="context_note",
        text="Idle context",
    )
    transcript: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()),
        target=session.messaging_target,
        kind="transcript_note",
        text="Transcript only",
    )
    try:
        for submission in (note, transcript):
            assert isinstance(await client.submit(submission=submission), MessageReceiptDAO)
            async with asyncio.timeout(delay=5):
                while True:
                    receipt: MessageReceiptDAO | MessageErrorDAO = await client.get_receipt(
                        message_id=submission.message_id
                    )
                    if isinstance(receipt, MessageReceiptDAO) and receipt.state == "applied":
                        break
                    await asyncio.sleep(delay=0)
        assert model.requests == []
        request: MessageSubmissionDAO = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text="Now reason",
        )
        assert isinstance(await client.submit(submission=request), MessageReceiptDAO)
        async with asyncio.timeout(delay=5):
            await model.entered.wait()
        assert [item.content for item in model.requests[0] if isinstance(item, HumanMessage)] == [
            note.text,
            request.text,
        ]
    finally:
        model.release.set()
        await client.close()
        await session.close_messaging()


async def test_real_ack_failure_records_insertion_before_await_and_stops_provider(tmp_path: Path) -> None:
    """A real SQLite evidence failure seals delivery; repeated insertion skips text but retries acknowledgement."""
    import sqlite3

    from src.agents.slo_agent.messaging.dao import MessageStoreError

    history_root: Path = tmp_path / "history"
    session_id: str = str(uuid4())
    database_path: Path = history_root / session_id / "messaging.v1.sqlite3"
    assert database_path.resolve().is_relative_to(tmp_path.resolve())
    history: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=history_root)
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        history_store=history,
        config=SessionConfigDAO(
            workdir=tmp_path, session_id=session_id, history_root=history_root, model_name="gpt-5.4"
        ),
    )
    await session.start_messaging()
    await session._ensure_history_session()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session,
        target=session.messaging_target,
        principal=session.messaging_owner_principal,
    )
    model: RecordingModel = RecordingModel(
        responses=[FauxChatModel.assistant_message(content="Must not run")]
    )
    agent: SloAgent = RealAgentFactory(model=model, workdir=tmp_path)(message_source=session)
    request: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()),
        target=session.messaging_target,
        kind="agent_input",
        text="Only one insertion",
    )
    messages: list[BaseMessage] = []
    try:
        async with session._session_run_scope():
            run: MessageRunState = MessageRunState(run_id=str(uuid4()))
            session._message_run = run
            assert isinstance(await client.submit(submission=request), MessageReceiptDAO)
            delivery: BoundaryDeliveryDAO = await session.take_one(
                boundary=BoundaryDAO(run_id=run.run_id, boundary_index=0)
            )
            assert delivery.instruction is not None
            # Corrupt only disposable real SQLite proof, not a mocked mark_applied.
            connection: sqlite3.Connection
            with sqlite3.connect(database=database_path) as connection:
                connection.execute("UPDATE applications SET history_committed=0")
            with pytest.raises(expected_exception=MessageStoreError):
                await agent._apply_message_boundary(accumulated_messages=messages, run=run)
            assert request.message_id in run.applied_message_ids
            assert [item.content for item in messages] == [request.text]
            assert session._messaging_paused and model.requests == []
            with pytest.raises(expected_exception=MessageStoreError):
                await agent._apply_message_boundary(accumulated_messages=messages, run=run)
            assert len(messages) == 1
            # Public real-agent execution also fails before the external request.
            with pytest.raises(expected_exception=MessageStoreError):
                async for _event in agent.invoke(query="omitted", message_run=run):
                    pass
            assert model.requests == []
            with sqlite3.connect(database=database_path) as connection:
                row: Optional[tuple[int, int]] = connection.execute(
                    "SELECT history_committed, context_committed FROM applications",
                ).fetchone()
                assert row == (0, 0)
    finally:
        session._message_run = None
        await client.close()
        await session.close_messaging()


async def test_history_uncertainty_prevents_next_provider_step(tmp_path: Path) -> None:
    """Corrupt terminated history after one applied input stops the next boundary, not the first receipt."""
    history_root: Path = tmp_path / "history"
    session_id: str = str(uuid4())
    events_path: Path = history_root / session_id / "events.jsonl"
    assert events_path.resolve().is_relative_to(tmp_path.resolve())
    model: RecordingModel = RecordingModel(
        responses=[
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="echo", args={"text": "ok"})]
            ),
            FauxChatModel.assistant_message(content="Must not run"),
        ]
    )
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, session_id=session_id, history_root=history_root, model_name="gpt-5.4"
        ),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path, tools=[echo_tool]),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session,
        target=session.messaging_target,
        principal=session.messaging_owner_principal,
    )
    first: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="First"
    )
    second: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="Second"
    )
    try:
        assert isinstance(await client.submit(submission=first), MessageReceiptDAO)
        async with asyncio.timeout(delay=5):
            await model.entered.wait()
        assert isinstance(await client.submit(submission=second), MessageReceiptDAO)
        stream: BinaryIO
        with events_path.open(mode="ab") as stream:
            stream.write(b'{"corrupt":\n')
        model.release.set()
        async with asyncio.timeout(delay=5):
            while session._messaging_failure is None:
                await asyncio.sleep(delay=0)
        assert len(model.requests) == 1
        assert session._messaging_paused
        assert session._message_store is not None
        identities: tuple[MessageIdentityDAO, ...] = await session._message_store.read_identities()
        assert identities[0].receipt.state == "applied"
        # Marked opening persistence now detects the corrupt raw history before
        # the next boundary can claim input (rather than only at application).
        assert identities[1].receipt.state == "accepted"
    finally:
        model.release.set()
        await client.close()
        await session.close_messaging()
