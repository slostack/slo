"""Mounted durable-composer journeys (96 revised 01.1/01.2 acceptance rows)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Generator
from typing import TypeVar

_TaskResult = TypeVar("_TaskResult")
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import BaseMessage, HumanMessage

import pytest

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
from src.agents.slo_agent.messaging.dao import (
    MessageAddressDAO,
    MessageErrorDAO,
    MessageReceiptDAO,
    MessageSubmissionDAO,
    utcnow,
)
from src.agents.slo_agent.messaging.ownership import SessionExecutionOwnership
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.hooks import Hook
from tests.agents.slo_agent.messaging.test_delivery import stop_after_turn
from src.tui.app import SloTUI
from tests.tui.recording_prompt import RecordingPromptInput
from src.tui.components.chat_transcript.component import ChatTranscriptComponent
from src.tui.components.prompt_input.adapters.message_submission import MessageSubmissionAdapter
from src.tui.components.prompt_input.commands import DiscardDraftDAO, ReplacePromptDAO, SubmitDraftDAO
from src.tui.components.prompt_input.component import PromptInputComponent
from src.tui.components.prompt_input.submission import (
    DraftSubmissionDAO,
    RecoverableDraftDAO,
    SubmissionOutcomeDAO,
)
from tests.agents.slo_agent.messaging.test_delivery import RealAgentFactory, RecordingModel
from tests.integration.test_session_messaging import read_closed_message_rows
from tests.tui.test_prompt_component_protocol import build_session


class SettableEvent:
    """Test gate whose ``wait`` never parks a task, so ``set`` releases it immediately."""

    def __init__(self) -> None:
        """Start unset, like ``asyncio.Event``."""
        self._is_set: bool = False
        self._waiters: list[asyncio.Future[None]] = []

    def clear(self) -> None:
        """Re-arm the gate."""
        self._is_set = False

    def is_set(self) -> bool:
        """Report the gate state."""
        return self._is_set

    async def wait(self) -> None:
        """Return once set; the parked future resolves on ``set`` without sleeping."""
        while not self._is_set:
            waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._waiters.append(waiter)
            await waiter

    def set(self) -> None:
        """Release every waiter."""
        self._is_set = True
        for waiter in self._waiters:
            if not waiter.done():
                waiter.set_result(None)
        self._waiters.clear()


class ScriptedMessagingClient:
    """Deterministic substitute for the bound session route; never a real session collaborator.

    Implements ``SessionMessagingClient`` with scripted per-ID outcomes, optional
    deterministic holds, and a full call record. Injection goes through
    ``PromptInputComponent.replace_submission_binding``; nothing is patched.
    """

    def __init__(
        self,
        *,
        outcomes: dict[str, MessageReceiptDAO | MessageErrorDAO] | None = None,
        held: SettableEvent | None = None,
        always: Callable[[MessageSubmissionDAO], MessageReceiptDAO | MessageErrorDAO] | None = None,
        hold: bool = False,
    ) -> None:
        """Script outcomes keyed by message ID.

        Args:
            outcomes: Per-message fixed answers.
            held: Optional global gate every operation waits on before answering.
            always: Optional factory answering every submit eagerly (A7 ordering).
            hold: When True, an unscripted submit holds until ``release`` with an
                outcome set; when False, it raises ``AssertionError`` so a missing
                script surfaces immediately instead of hanging the suite.
        """
        self._outcomes: dict[str, MessageReceiptDAO | MessageErrorDAO] = outcomes or {}
        self._held: SettableEvent | None = held
        self._always: Callable[[MessageSubmissionDAO], MessageReceiptDAO | MessageErrorDAO] | None = always
        self._hold: bool = hold
        self._release_events: dict[str, SettableEvent] = {}
        self.submit_calls: list[MessageSubmissionDAO] = []
        self.submission_tasks: dict[asyncio.Task[object], str] = {}
        self.receipt_calls: list[str] = []
        self.close_calls: int = 0

    def release(self, *, message_id: str) -> None:
        """Release one held message so its scripted outcome is delivered.

        Args:
            message_id: The canonical ID whose held call should now resolve.
        """
        self._release_events.setdefault(message_id, SettableEvent()).set()

    async def _answer(
        self, *, message_id: str, submission: MessageSubmissionDAO | None
    ) -> MessageReceiptDAO | MessageErrorDAO:
        """Resolve one scripted answer, holding deterministically when scripted to."""
        if self._held is not None:
            await self._held.wait()
        outcome: MessageReceiptDAO | MessageErrorDAO | None = self._outcomes.get(message_id)
        if outcome is None and submission is not None and self._always is not None:
            outcome = self._always(submission)
        if outcome is not None:
            return outcome
        if not self._hold:
            raise AssertionError(f"unscripted scripted-client answer for {message_id}")
        gate: SettableEvent = self._release_events.setdefault(message_id, SettableEvent())
        await gate.wait()
        outcome = self._outcomes.get(message_id)
        if outcome is None:
            raise AssertionError(f"released scripted hold without an outcome for {message_id}")
        return outcome

    async def submit(self, *, submission: MessageSubmissionDAO) -> MessageReceiptDAO | MessageErrorDAO:
        """Record the call and answer from the script."""
        self.submit_calls.append(submission)
        task: asyncio.Task[object] | None = asyncio.current_task()
        assert task is not None
        self.submission_tasks[task] = submission.message_id
        return await self._answer(message_id=submission.message_id, submission=submission)

    async def get_receipt(self, *, message_id: str) -> MessageReceiptDAO | MessageErrorDAO:
        """Record the call and answer from the script."""
        self.receipt_calls.append(message_id)
        return await self._answer(message_id=message_id, submission=None)

    async def close(self) -> None:
        """Record close; this substitute owns nothing else."""
        self.close_calls += 1


async def _wait_until(*, predicate: Callable[[], bool], timeout_seconds: float = 5.0) -> None:
    """Bounded asynchronous coordination; never a condition on a real deadline.

    Always yields at least one real sleep slice so already-true predicates and
    tight polls cannot starve the app's 0.5 s UI worker timers (Textual's
    ``run_test`` pilot does not add wall-clock delays between key presses).
    """
    async with asyncio.timeout(delay=timeout_seconds):
        while not predicate():
            await asyncio.sleep(delay=0.01)
        await asyncio.sleep(delay=0.01)


async def _wait_until_async(
    *, predicate: Callable[[], Coroutine[None, None, bool]], timeout_seconds: float = 5.0
) -> None:
    """Bounded coordination whose predicate performs asynchronous durable reads."""
    async with asyncio.timeout(delay=timeout_seconds):
        while not await predicate():
            await asyncio.sleep(delay=0.01)
        await asyncio.sleep(delay=0.01)


def _transcript_notices(app: SloTUI) -> list[str]:
    """Collect rendered transcript line text through the mounted component."""
    transcript: ChatTranscriptComponent = app.query_one(ChatTranscriptComponent)
    return [str(child.render()) for child in transcript.query_one("#transcript-content").children]


def _build_factory_session(
    *, tmp_path: Path, model: RecordingModel, stop_after_first: bool = True
) -> SloAgentSession:
    """Build a real session whose agent construction injects the scripted model.

    Args:
        tmp_path: Test-owned filesystem root.
        model: Recording substitute at the third-party model boundary.

    Returns:
        SloAgentSession: Config session using the trusted factory seam.
    """
    history_root: Path = tmp_path / "history"
    assert history_root.resolve().is_relative_to(tmp_path.resolve())
    session_id: str = str(uuid4())
    return SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=history_root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=FilesystemSessionHistoryStore(root=history_root),
        messaging_agent_factory=RealAgentFactory(
            model=model, workdir=tmp_path, stop_hook=stop_after_turn if stop_after_first else None
        ),
    )


async def _release_provider_once(*, model: RecordingModel, session: SloAgentSession) -> None:
    """Release the held provider, wait for one settled run, then re-arm the gate.

    Args:
        model: Recording substitute whose ``release`` gate holds each request.
        session: Owning session whose ``is_running`` bounds the wait.
    """
    model.release.set()
    await _wait_until(predicate=lambda: not session.is_running)
    model.release.clear()


class RecordingMessagingSession(SloAgentSession):
    """Real session recording public lifecycle calls and optionally holding startup return."""

    def __init__(
        self,
        *,
        tmp_path: Path,
        model: RecordingModel,
        pending_preparation: bool = False,
        hold_start: bool = False,
        executor_factory: Callable[[], ThreadPoolExecutor] | None = None,
    ) -> None:
        """Inject the model and real SQLite worker through existing construction seams."""
        history_root: Path = tmp_path / "history"
        assert history_root.resolve().is_relative_to(tmp_path.resolve())
        session_id: str = str(uuid4())
        super().__init__(
            workdir=tmp_path,
            session_id=session_id,
            config=SessionConfigDAO(
                workdir=tmp_path, history_root=history_root, session_id=session_id, model_name="gpt-5.4"
            ),
            history_store=FilesystemSessionHistoryStore(root=history_root),
            messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
            messaging_executor_factory=executor_factory,
            pending_preparation=pending_preparation,
        )
        self.lifecycle_calls: list[str] = []
        self.start_return: asyncio.Event = asyncio.Event()
        if not hold_start:
            self.start_return.set()
        self.start_entered: asyncio.Event = asyncio.Event()
        self.client_before_close: LocalSessionMessagingClient | None = None
        self.client_was_closed: bool = False

    async def start_external_reporting(self, *, interactive: bool = False) -> None:
        """Record completion of real reporting setup before messaging can start."""
        await super().start_external_reporting(interactive=interactive)
        self.lifecycle_calls.append("reporting_ready")

    async def prepare_startup(self) -> None:
        """Record real model preparation without replacing its policy or catalog."""
        await super().prepare_startup()
        self.lifecycle_calls.append("preparation_ready")

    async def start_messaging(self) -> None:
        """Start real resources, then optionally hold the host's post-await continuation."""
        assert self.preparation_status == "ready"
        assert "reporting_ready" in self.lifecycle_calls
        self.lifecycle_calls.append("messaging_start")
        await super().start_messaging()
        self.start_entered.set()
        await self.start_return.wait()
        self.lifecycle_calls.append("messaging_ready")

    async def close_messaging(self) -> None:
        """Observe client detachment before joining real resource shutdown."""
        if self.client_before_close is not None:
            probe_id: str = str(uuid4())
            receipt = await self.client_before_close.get_receipt(message_id=probe_id)
            self.client_was_closed = receipt == MessageErrorDAO(code="completing", message_id=probe_id)
        self.lifecycle_calls.append("messaging_close")
        await super().close_messaging()
        self.lifecycle_calls.append("messaging_closed")


@pytest.mark.parametrize(argnames="pending_preparation", argvalues=[False, True])
async def test_mount_starts_messaging_after_reporting_setup(
    tmp_path: Path, pending_preparation: bool
) -> None:
    """A4 (01.1): a mounted enabled host owns one started route and its client."""
    model: RecordingModel = RecordingModel(responses=[])
    session = RecordingMessagingSession(
        tmp_path=tmp_path, model=model, pending_preparation=pending_preparation
    )
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: app._messaging_session is session)
        expected = ["reporting_ready", "preparation_ready", "messaging_start", "messaging_ready"]
        assert session.lifecycle_calls == (
            expected if pending_preparation else [step for step in expected if step != "preparation_ready"]
        )
        assert model.requests == []
        database_path: Path = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
        assert database_path.resolve().is_relative_to(tmp_path.resolve())
        assert database_path.is_file()
        assert isinstance(app._messaging_client, LocalSessionMessagingClient)
        assert app._messaging_client._target == session.messaging_target
        assert app._messaging_session is session


async def test_startup_failure_refuses_prompts_without_memory_fallback(tmp_path: Path) -> None:
    """A5 (01.1): a held ownership lease disables prompts with the fixed notice."""
    model: RecordingModel = RecordingModel(responses=[])
    session: SloAgentSession = _build_factory_session(tmp_path=tmp_path, model=model)
    history_root: Path = tmp_path / "history"
    holder: SessionExecutionOwnership = await SessionExecutionOwnership.acquire(
        root=history_root, session_id=session.session_id
    )
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _wait_until(
                predicate=lambda: any(
                    "Durable messaging unavailable" in line for line in _transcript_notices(app)
                )
            )
            prompt: RecordingPromptInput = app.query_one(RecordingPromptInput)
            prompt.load_text("kept text")
            await pilot.press("enter")
            await pilot.pause()
            assert prompt.text == "kept text"
            assert app._in_flight_task is None
            # No legacy run means the persisted turn store stays empty.
            assert session.history_store is not None
            assert await session.history_store.load_events(session_id=session.session_id) == []
            assert app._messaging_client is None
            assert model.requests == []
            assert app._queued_prompt_text is None
    finally:
        await holder.release()


async def test_ephemeral_session_announces_non_durable_messaging(tmp_path: Path) -> None:
    """A6 (01.1): an in-memory store mounts with the fixed non-durable notice once."""
    agent: SloAgent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="ephemeral answer")]),
        cwd=str(tmp_path),
        tools=[],
    )
    session: SloAgentSession = SloAgentSession(
        agent=agent, workdir=tmp_path, session_id=str(uuid4()), enable_history=False
    )
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: session.is_messaging_ready)
        prompt: RecordingPromptInput = app.query_one(RecordingPromptInput)
        prompt.load_text("ephemeral instruction")
        await pilot.press("enter")
        await _wait_until(predicate=lambda: len(prompt.outcomes) == 1)
        admission = prompt.outcomes[0].outcome
        assert isinstance(admission, MessageReceiptDAO)
        assert admission.durable is False
        assert app._messaging_client is not None
        async with asyncio.timeout(delay=5):
            while True:
                receipt = await app._messaging_client.get_receipt(message_id=admission.message_id)
                if isinstance(receipt, MessageReceiptDAO) and receipt.state == "applied":
                    break
                await asyncio.sleep(delay=0.01)
        assert receipt.durable is False
        notices: list[str] = [line for line in _transcript_notices(app) if "not durable" in line]
        assert notices == ["Messages in this session are not durable."]
        assert not (tmp_path / "history" / session.session_id / "messaging.v1.sqlite3").exists()


async def test_exit_closes_client_then_session_and_retains_pending(tmp_path: Path) -> None:
    """A7 (01.1): exit joins client then session close, retaining unapplied input."""
    model: RecordingModel = RecordingModel(responses=[])
    session = RecordingMessagingSession(tmp_path=tmp_path, model=model)
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    submission: MessageSubmissionDAO | None = None

    async def release_execution_after_close_begins() -> None:
        """Hold the execution gate until real app shutdown has sealed the session."""
        await _wait_until(predicate=lambda: session._messaging_closing)
        session._lock.release()

    release_task: asyncio.Task[None] | None = None
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: session.is_messaging_ready)
        client: LocalSessionMessagingClient = app._messaging_client  # type: ignore[assignment]
        assert isinstance(client, LocalSessionMessagingClient)
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text="held pending input",
        )
        session.client_before_close = client
        # Freeze execution, not admission, until app shutdown has sealed the queue.
        await session._lock.acquire()
        try:
            admission: MessageReceiptDAO | MessageErrorDAO = await client.submit(submission=submission)
            assert isinstance(admission, MessageReceiptDAO)
            assert admission.state == "accepted"
            release_task = asyncio.create_task(coro=release_execution_after_close_begins())
            app.exit()
        except BaseException:
            session._lock.release()
            raise
    assert release_task is not None
    await release_task
    assert session.client_was_closed
    assert session.lifecycle_calls[-2:] == ["messaging_close", "messaging_closed"]
    assert model.requests == []
    lease = await SessionExecutionOwnership.acquire(root=tmp_path / "history", session_id=session.session_id)
    await lease.release()
    assert submission is not None
    assert session.is_messaging_ready is False
    database_path: Path = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
    assert database_path.resolve().is_relative_to(tmp_path.resolve())
    rows: tuple[tuple[str, int, str], ...] = await asyncio.to_thread(
        read_closed_message_rows, database_path=database_path, temporary_root=tmp_path
    )
    assert rows == ((submission.message_id, 1, "accepted"),)


@pytest.mark.parametrize(argnames="cutoff", argvalues=["cancelled", "displaced"])
async def test_activation_joins_cleanup_when_startup_is_cancelled_or_displaced(
    tmp_path: Path, cutoff: str
) -> None:
    """DC01: late startup never publishes a client and releases its real store and lease."""
    model: RecordingModel = RecordingModel(responses=[])
    session = RecordingMessagingSession(tmp_path=tmp_path, model=model, hold_start=True)
    # The existing host gateway is exercised directly to isolate its await cutoff;
    # mounted readiness/publication is covered above. No provider or owner is patched.
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    await session.start_external_reporting(interactive=True)
    activation: asyncio.Task[bool] = asyncio.create_task(
        coro=app._activate_session_messaging(session=session)
    )
    try:
        async with asyncio.timeout(delay=5):
            await session.start_entered.wait()
        assert session.is_messaging_ready
        if cutoff == "cancelled":
            activation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await activation
        else:
            # A genuinely different selected session triggers the identity guard;
            # replacement orchestration and draft retirement remain DC04/DC06.
            successor = build_session(tmp_path=tmp_path / "successor")
            assert app._adopt_replacement_session(
                old_session=session,
                candidate=successor,
                outcome=HerdrReporterCloseOutcomeDAO(replacement="safe"),
            )
            session.start_return.set()
            assert await activation is False
        assert app._messaging_client is None
        assert app._messaging_session is None
        assert not session.is_messaging_ready
        assert session.lifecycle_calls[-1] == "messaging_closed"
        assert model.requests == []
        lease = await SessionExecutionOwnership.acquire(
            root=tmp_path / "history", session_id=session.session_id
        )
        await lease.release()
        database_path = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
        assert (
            await asyncio.to_thread(
                read_closed_message_rows, database_path=database_path, temporary_root=tmp_path
            )
            == ()
        )
    finally:
        session.start_return.set()
        if not activation.done():
            activation.cancel()
        await asyncio.gather(activation, return_exceptions=True)
        await session.close_messaging()
        await session.close_external_reporting()


async def test_busy_enters_admit_three_distinct_durable_messages(tmp_path: Path) -> None:
    """DC02.A1: three captured Enter drafts apply once in order across real boundaries."""
    model: RecordingModel = RecordingModel(
        responses=[FauxChatModel.assistant_message(content=f"answer {index}") for index in range(3)]
    )
    session: SloAgentSession = _build_factory_session(tmp_path=tmp_path, model=model, stop_after_first=False)
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    captured_texts: list[str] = ["one", "two", "three"]
    message_ids: list[str] = []
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await _wait_until(predicate=lambda: app._messaging_session is session)
            prompt: RecordingPromptInput = app.query_one(RecordingPromptInput)
            for index, text in enumerate(captured_texts):
                prompt.load_text(text)
                await pilot.press("enter")
                await _wait_until(predicate=lambda: len(prompt.outcomes) == index + 1)
                outcome = prompt.outcomes[index]
                assert outcome.draft_submission.message_submission.text == text
                assert isinstance(outcome.outcome, MessageReceiptDAO)
                assert outcome.outcome.durable
                message_ids.append(outcome.outcome.message_id)
                assert prompt.text == ""
                assert app.focused is prompt
                assert app._in_flight_task is None
                assert app._queued_prompt_text is None
                if index == 0:
                    await _wait_until(predicate=model.entered.is_set)
                assert len(model.requests) == 1
                assert not model.release.is_set()
            assert len(set(message_ids)) == 3
            assert session._message_store is not None
            identities = await session._message_store.read_identities()
            assert [identity.receipt.message_id for identity in identities] == message_ids
            assert [identity.receipt.sequence for identity in identities] == [1, 2, 3]
            # New typing, including the reserved newline shortcut, survives delivery.
            await pilot.press("x", "ctrl+enter", "y")
            assert prompt.text == "x\ny"
            model.release.set()
            await _wait_until(predicate=lambda: len(model.requests) == 3 and not session.is_running)
            assert prompt.text == "x\ny"
            assert app._in_flight_task is None and app._queued_prompt_text is None
            # Prior input legitimately remains in context; each boundary adds exactly
            # one new instruction, not one occurrence across all cumulative requests.
            assert [
                [str(message.content) for message in request if isinstance(message, HumanMessage)]
                for request in model.requests
            ] == [captured_texts[:boundary] for boundary in (1, 2, 3)]
    finally:
        model.release.set()
        await session.close_messaging()
    assert session.history_store is not None
    events = await session.history_store.load_events(session_id=session.session_id)
    applications = [event for event in events if "messaging_v1" in event.payload.metadata]
    assert [event.payload.content for event in applications] == captured_texts
    assert [event.payload.metadata["messaging_v1"]["message_id"] for event in applications] == message_ids
    assert [event.payload.metadata["messaging_v1"]["sequence"] for event in applications] == [1, 2, 3]
    assert len({event.event_id for event in applications}) == 3
    assert len({event.turn_id for event in applications}) == 1
    assert [event.payload.content for event in events if event.kind == "assistant_message"] == [
        "answer 0",
        "answer 1",
        "answer 2",
    ]
    assert not any(event.kind in ("run_failed", "run_aborted") for event in events)
    database_path = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
    assert await asyncio.to_thread(
        read_closed_message_rows, database_path=database_path, temporary_root=tmp_path
    ) == tuple((message_id, 0, "applied") for message_id in message_ids)


class FailingCloseMessagingClient(LocalSessionMessagingClient):
    """Real owner client that reports failure only after its calls have joined."""

    async def close(self) -> None:
        """Detach the real client, then expose a deterministic cleanup failure."""
        await super().close()
        raise ValueError("scripted client close failure")


async def test_client_close_failure_still_joins_session_cleanup(tmp_path: Path) -> None:
    """EF-04: failing client cleanup cannot skip real session close or lease release."""
    model = RecordingModel(responses=[])
    session = RecordingMessagingSession(tmp_path=tmp_path, model=model)

    def client_factory(owner: SloAgentSession) -> LocalSessionMessagingClient:
        """Construct the real bound client through the host's ownership seam."""
        client = FailingCloseMessagingClient(
            session=owner, target=owner.messaging_target, principal=owner.messaging_owner_principal
        )
        session.client_before_close = client
        return client

    app = SloTUI(
        prompt_factory=RecordingPromptInput,
        session=session,
        messaging_enabled=True,
        messaging_client_factory=client_factory,
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await _wait_until(predicate=lambda: app._messaging_session is session)
        # The host lifecycle gateway must propagate this exact client failure,
        # but only after its real session cleanup finishes.
        with pytest.raises(ValueError, match="scripted client close failure"):
            await app._close_session_messaging(session=session)
        assert session.client_was_closed
        assert session.lifecycle_calls[-1] == "messaging_closed"
        assert not session.is_messaging_ready
        assert app._messaging_client is None and app._messaging_session is None
        lease = await SessionExecutionOwnership.acquire(
            root=tmp_path / "history", session_id=session.session_id
        )
        await lease.release()
        assert model.requests == []
        # A repeated call uses only the public idempotent session close.
        await app._close_session_messaging(session=session)


class _TrackedDraftView:
    """Test-only read model of the component's tracked drafts, including settling waits."""

    @staticmethod
    def pending_ids(*, prompt: RecordingPromptInput) -> tuple[str, ...]:
        """Return tracked draft IDs plus any uncommitted in-flight capture.

        A receipt outcome can settle its entry before the UI loop observes it, so
        "still pending" means "tracked or captured but not yet settled".
        """
        ids: list[str] = [message_id for message_id in prompt._tracked_drafts]
        capture = prompt._pending_capture
        if capture is not None and capture.message_id not in ids:
            ids.append(capture.message_id)
        settled: set[str] = {
            outcome.draft_submission.message_submission.message_id
            for outcome in prompt.outcomes
            if isinstance(outcome.outcome, MessageReceiptDAO)
        }
        return tuple(message_id for message_id in ids if message_id not in settled)


async def test_enter_admits_exact_draft_once_and_editor_stays_responsive(tmp_path: Path) -> None:
    """A1 (01.2) minimal exact-once journey plus one explicitly retained busy Enter.

    The held provider proves the exact normalized draft reaches the real model
    boundary once, as one application, with the scripted successful terminal
    outcome. The busy second Enter is admitted while that provider request is
    verifiably held; the intentional stop hook leaves it retained (accepted and
    durable), never applied and never dropped. The separate three-input journey
    above proves DC02.A1 without this intentional stop policy.
    """
    model: RecordingModel = RecordingModel(
        responses=[FauxChatModel.assistant_message(content="adapter answer")]
    )
    session: SloAgentSession = _build_factory_session(tmp_path=tmp_path, model=model)
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: session.is_messaging_ready, timeout_seconds=15.0)
        prompt: RecordingPromptInput = app.query_one(RecordingPromptInput)
        prompt.load_text("one")
        await pilot.press("enter")
        await _wait_until(predicate=lambda: prompt.text == "", timeout_seconds=15.0)
        assert app.focused is prompt
        # The provider request must be verifiably held before any busy Enter.
        await _wait_until(predicate=lambda: model.entered.is_set(), timeout_seconds=15.0)
        assert not model.release.is_set()
        await _wait_until(predicate=lambda: len(model.requests) == 1, timeout_seconds=15.0)
        # The provider request is verifiably held. The first draft's identity
        # is read from its delivered outcome, recorded synchronously at the
        # adapter boundary; tracked entries settle silently, so they are never
        # the identity source.
        await _wait_until(predicate=lambda: len(prompt.outcomes) >= 1, timeout_seconds=15.0)
        first_message_id: str = prompt.outcomes[0].draft_submission.message_submission.message_id
        prompt.load_text("two")
        await pilot.press("enter")
        assert session._message_store is not None

        async def _second_identity_row() -> bool:
            """Poll the durable store until the busy Enter commits its identity row."""
            identities = await session._message_store.read_identities()  # type: ignore[union-attr]
            return any(identity.receipt.message_id != first_message_id for identity in identities)

        await _wait_until_async(predicate=_second_identity_row, timeout_seconds=15.0)
        identities = await session._message_store.read_identities()
        assert len(identities) == 2
        second_message_id: str = next(
            identity.receipt.message_id
            for identity in identities
            if identity.receipt.message_id != first_message_id
        )
        # The editor still edits normally while messaging owns the submission path.
        await pilot.press("x", "shift+enter", "y")
        assert prompt.text == "x\ny"
        assert app._in_flight_task is None
        assert app._queued_prompt_text is None
        await _release_provider_once(model=model, session=session)
        assert app.focused is prompt
        # The exact normalized text occurs once in the recorded provider input.
        assert len(model.requests) == 1
        human_texts: list[str] = [
            str(message.content) for message in model.requests[0] if isinstance(message, HumanMessage)
        ]
        assert human_texts == ["one"]
    # Exactly one application history event carries the exact captured text/ID.
    assert session.history_store is not None
    events: list[SessionHistoryEventDAO] = await session.history_store.load_events(
        session_id=session.session_id
    )
    messaging_updates: list[SessionHistoryEventDAO] = [
        event for event in events if "messaging_v1" in event.payload.metadata
    ]
    assert [event.payload.content for event in messaging_updates] == ["one"]
    assert [event.payload.metadata["messaging_v1"]["message_id"] for event in messaging_updates] == [
        first_message_id
    ]
    # The scripted response is the one successful terminal model outcome.
    terminal_updates: list[SessionHistoryEventDAO] = [
        event
        for event in events
        if event.kind == "assistant_message" and event.payload.content == "adapter answer"
    ]
    assert len(terminal_updates) == 1
    # First input applied once; the busy second input is retained, not applied.
    database_path: Path = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
    assert database_path.resolve().is_relative_to(tmp_path.resolve())
    rows: tuple[tuple[str, int, str], ...] = await asyncio.to_thread(
        read_closed_message_rows, database_path=database_path, temporary_root=tmp_path
    )
    assert rows == ((first_message_id, 0, "applied"), (second_message_id, 1, "accepted"))


def _draft_for_test(*, text: str) -> DraftSubmissionDAO:
    """Build one direct binding-shaped snapshot for adapter-level lifecycle tests."""
    return DraftSubmissionDAO(
        message_submission=MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4())),
            kind="agent_input",
            text=text,
        ),
        draft_revision=0,
        binding_version=1,
    )


async def _rebind_scripted_client(
    *, prompt: PromptInputComponent, client: "ScriptedMessagingClient"
) -> MessageSubmissionAdapter:
    """Retire the mounted binding publicly before borrowing the scripted route.

    Args:
        prompt (PromptInputComponent): Mounted editor owning the binding lifetime.
        client (ScriptedMessagingClient): Injected replacement route.

    Returns:
        MessageSubmissionAdapter: Fresh component-owned adapter.
    """
    address: MessageAddressDAO | None = prompt._submission_address
    assert address is not None
    predecessor: MessageSubmissionAdapter | None = prompt._submission_adapter
    assert predecessor is not None
    await prompt.replace_submission_binding(client=client, address=address)
    adapter: MessageSubmissionAdapter | None = prompt._submission_adapter
    assert adapter is not None and adapter is not predecessor
    assert predecessor._client is None and predecessor._receiver is None
    return adapter


class RecordingOutcomeReceiver:
    """Injected adapter receiver with deterministic first-delivery failure and call order."""

    def __init__(self, *, fail_message_id: str) -> None:
        """Keep the one failing ID; all other outcomes succeed."""
        self.fail_message_id: str = fail_message_id
        self.message_ids: list[str] = []

    async def handle(self, *, command: SubmissionOutcomeDAO) -> None:
        """Record delivery before raising for the explicitly scripted failed receiver."""
        message_id: str = command.draft_submission.message_submission.message_id
        self.message_ids.append(message_id)
        if message_id == self.fail_message_id:
            raise ValueError("held receiver failure")


async def test_submission_adapter_joins_held_sibling_after_in_progress_receiver_fails() -> None:
    """EF-02: failure DURING shielded join cannot escape before a held sibling settles."""
    failing = _draft_for_test(text="receiver failure")
    sibling = _draft_for_test(text="held sibling")
    client = ScriptedMessagingClient(hold=True)
    receiver = RecordingOutcomeReceiver(fail_message_id=failing.message_submission.message_id)
    adapter = MessageSubmissionAdapter.register(client=client, receiver=receiver)
    await adapter.handle(event=failing)
    await adapter.handle(event=sibling)
    await _wait_until(predicate=lambda: len(client.submit_calls) == 2)
    # The adapter intentionally owns an unordered task set. Read (never mutate)
    # its first join candidate so this regression exercises failure inside shield,
    # rather than accidentally joining the held sibling before observing failure.
    first_wait = next(iter(adapter._tasks))
    failing_id: str = client.submission_tasks[first_wait]
    sibling_id: str = next(call.message_id for call in client.submit_calls if call.message_id != failing_id)
    receiver.fail_message_id = failing_id
    closing: asyncio.Task[None] = asyncio.create_task(coro=adapter.close())
    concurrent: asyncio.Task[None] = asyncio.create_task(coro=adapter.close())
    await asyncio.sleep(delay=0)
    await asyncio.sleep(delay=0)
    try:
        client._outcomes[failing_id] = MessageErrorDAO(code="queue_full", message_id=failing_id)
        client.release(message_id=failing_id)
        await _wait_until(predicate=lambda: receiver.message_ids == [failing_id])
        assert not closing.done() and not concurrent.done()
        assert adapter._client is client and adapter._receiver is receiver
    finally:
        client._outcomes[sibling_id] = MessageErrorDAO(code="queue_full", message_id=sibling_id)
        client.release(message_id=sibling_id)
        results = await asyncio.gather(closing, concurrent, return_exceptions=True)
    assert all(isinstance(failure, ValueError) for failure in results)
    assert set(receiver.message_ids) == {failing_id, sibling_id}
    assert adapter._client is None and adapter._receiver is None
    assert client.close_calls == 0


def _offline_outcome(submission: MessageSubmissionDAO) -> MessageErrorDAO:
    """Answer a completed admission without allocating a durable session."""
    return MessageErrorDAO(code="offline", message_id=submission.message_id)


@pytest.mark.parametrize(argnames="fail", argvalues=[False, True])
async def test_submission_adapter_repeated_completions_release_tasks_and_bound_failures(fail: bool) -> None:
    """FR-02: completion/reset history stays bounded without losing sticky failures."""
    receiver: RecordingOutcomeReceiver = RecordingOutcomeReceiver(fail_message_id="")
    client: ScriptedMessagingClient = ScriptedMessagingClient(always=_offline_outcome)
    adapter: MessageSubmissionAdapter = MessageSubmissionAdapter.register(client=client, receiver=receiver)
    first_failure: BaseException | None = None
    for index in range(100):
        draft: DraftSubmissionDAO = _draft_for_test(text=f"completion {index}")
        if fail:
            receiver.fail_message_id = draft.message_submission.message_id
        await adapter.handle(event=draft)
        await _wait_until(predicate=lambda: len(receiver.message_ids) == index + 1)
        # Resource assertion only: inputs and lifetimes use the public interface.
        assert adapter._tasks == set()
        if fail:
            with pytest.raises(ValueError, match="held receiver failure") as raised:
                await adapter.reset()
            if first_failure is None:
                first_failure = raised.value
            assert raised.value is first_failure
            assert adapter._first_wait_failure is first_failure
            traceback_depth: int = 0
            traceback = raised.value.__traceback__
            while traceback is not None:
                traceback_depth += 1
                traceback = traceback.tb_next
            assert traceback_depth <= 5
        else:
            await adapter.reset()
            assert adapter._first_wait_failure is None
        assert adapter._tasks == set()
    # Also complete a long burst without lifecycle calls: reset cannot be the
    # only cleanup mechanism for a long-lived mounted binding.
    for index in range(100, 200):
        draft = _draft_for_test(text=f"unjoined completion {index}")
        if fail:
            receiver.fail_message_id = draft.message_submission.message_id
        await adapter.handle(event=draft)
        await _wait_until(predicate=lambda: len(receiver.message_ids) == index + 1)
        assert adapter._tasks == set()
    if fail:
        assert adapter._first_wait_failure is first_failure
        with pytest.raises(ValueError, match="held receiver failure"):
            await adapter.close()
        with pytest.raises(ValueError, match="held receiver failure"):
            await adapter.close()
    else:
        await adapter.close()
        await adapter.close()
    assert adapter._tasks == set()
    assert adapter._client is None and adapter._receiver is None
    assert client.close_calls == 0
    assert len(receiver.message_ids) == 200


@pytest.mark.parametrize(argnames="closing", argvalues=[False, True])
async def test_submission_adapter_retired_failure_still_joins_held_sibling(closing: bool) -> None:
    """FR-02/EF-02: released failed Tasks cannot let reset or close skip a sibling."""
    failed: DraftSubmissionDAO = _draft_for_test(text="failed before barrier")
    sibling: DraftSubmissionDAO = _draft_for_test(text="still held")
    receiver: RecordingOutcomeReceiver = RecordingOutcomeReceiver(
        fail_message_id=failed.message_submission.message_id
    )
    client: ScriptedMessagingClient = ScriptedMessagingClient(hold=True)
    adapter: MessageSubmissionAdapter = MessageSubmissionAdapter.register(client=client, receiver=receiver)
    await adapter.handle(event=failed)
    failed_id: str = failed.message_submission.message_id
    client._outcomes[failed_id] = MessageErrorDAO(code="offline", message_id=failed_id)
    client.release(message_id=failed_id)
    await _wait_until(predicate=lambda: receiver.message_ids == [failed_id])
    assert adapter._tasks == set()
    await adapter.handle(event=sibling)
    await _wait_until(predicate=lambda: len(client.submit_calls) == 2)
    barrier: asyncio.Task[None] = asyncio.create_task(coro=adapter.close() if closing else adapter.reset())
    for _ in range(3):
        await asyncio.sleep(delay=0)
        barrier.cancel()
        await asyncio.sleep(delay=0)
        assert not barrier.done()
        assert adapter._client is client and adapter._receiver is receiver
    sibling_id: str = sibling.message_submission.message_id
    client._outcomes[sibling_id] = MessageErrorDAO(code="offline", message_id=sibling_id)
    client.release(message_id=sibling_id)
    with pytest.raises(ValueError, match="held receiver failure"):
        await barrier
    assert receiver.message_ids == [failed_id, sibling_id]
    assert adapter._tasks == set()
    with pytest.raises(ValueError, match="held receiver failure"):
        await adapter.close()
    assert adapter._client is None and adapter._receiver is None
    assert client.close_calls == 0


class _RaisingClient(ScriptedMessagingClient):
    """A broken borrowed route; adapter code never raises it directly."""

    async def submit(self, *, submission: MessageSubmissionDAO) -> MessageReceiptDAO | MessageErrorDAO:
        """Fail immediately with an unexpected exception, not a scripted outcome."""
        raise ValueError("broken borrowed client")


async def test_submission_adapter_rejects_bad_input_loop_and_closed() -> None:
    """A9/FR-01: real lifetimes preserve closed-wins and foreign-loop refusal."""
    client: ScriptedMessagingClient = ScriptedMessagingClient(always=_offline_outcome)
    receiver: RecordingOutcomeReceiver = RecordingOutcomeReceiver(fail_message_id="")
    adapter: MessageSubmissionAdapter = MessageSubmissionAdapter.register(client=client, receiver=receiver)
    with pytest.raises(TypeError):
        await adapter.handle(event=object())  # type: ignore[arg-type]
    await adapter.close()
    await adapter.close()
    with pytest.raises(RuntimeError, match="closed"):
        await adapter.handle(event=_draft_for_test(text="after close"))
    with pytest.raises(RuntimeError, match="closed"):
        await adapter.handle(event=object())  # type: ignore[arg-type]

    foreign_adapter: MessageSubmissionAdapter = MessageSubmissionAdapter.register(
        client=client, receiver=receiver
    )
    await foreign_adapter.handle(event=_draft_for_test(text="pin home loop"))
    await foreign_adapter.reset()

    async def foreign_loop_call() -> None:
        """Refuse supported and unsupported delivery on a foreign loop, open or closed."""
        with pytest.raises(RuntimeError, match="first delivery loop"):
            await foreign_adapter.handle(event=_draft_for_test(text="foreign loop"))
        with pytest.raises(RuntimeError, match="first delivery loop"):
            await foreign_adapter.handle(event=object())  # type: ignore[arg-type]

    def run_on_foreign_loop() -> None:
        """Drive the registered adapter from a thread with its own loop."""
        foreign_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(foreign_loop)
            foreign_loop.run_until_complete(foreign_loop_call())
        finally:
            foreign_loop.close()
            asyncio.set_event_loop(None)

    try:
        await asyncio.to_thread(run_on_foreign_loop)
        await foreign_adapter.close()
        await asyncio.to_thread(run_on_foreign_loop)
    finally:
        await foreign_adapter.close()
    assert client.close_calls == 0


async def test_submission_adapter_reset_joins_through_repeated_cancellation(tmp_path: Path) -> None:
    """A9 (01.2): reset joins an outstanding held wait through repeated cancellation."""
    session: SloAgentSession = build_session(tmp_path=tmp_path)
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: session.is_messaging_ready)
        prompt: RecordingPromptInput = app.query_one(RecordingPromptInput)
        reset_client: ScriptedMessagingClient = ScriptedMessagingClient(held=SettableEvent(), hold=True)
        reset_adapter: MessageSubmissionAdapter = await _rebind_scripted_client(
            prompt=prompt, client=reset_client
        )
        prompt.load_text("resettable")
        await pilot.press("enter")
        await _wait_until(predicate=lambda: reset_client.submit_calls != [])
        await _wait_until(predicate=lambda: prompt.text == "")
        reset_task: asyncio.Task[None] = asyncio.create_task(coro=reset_adapter.reset())
        await asyncio.sleep(delay=0)
        assert not reset_task.done()
        reset_task.cancel()
        await asyncio.sleep(delay=0)
        reset_task.cancel()
        await asyncio.sleep(delay=0)
        assert not reset_task.done()
        assert reset_client._held is not None
        reset_client._outcomes[reset_client.submit_calls[0].message_id] = MessageReceiptDAO(
            message_id=reset_client.submit_calls[0].message_id,
            target=reset_client.submit_calls[0].target,
            state="accepted",
            sequence=1,
            durable=True,
            admitted_at=utcnow(),
        )
        reset_client._held.set()
        with pytest.raises(asyncio.CancelledError):
            await reset_task
        receipt_id: str = reset_client.submit_calls[0].message_id
        await _wait_until(
            predicate=lambda: any(
                outcome.draft_submission.message_submission.message_id == receipt_id
                for outcome in prompt.outcomes
            )
        )
        # reset keeps the binding usable; close joins once and never closes the client.
        prompt.load_text("still usable")
        await pilot.press("enter")
        await _wait_until(predicate=lambda: len(reset_client.submit_calls) == 2)
        # Keep the second wait held so the close barrier provably blocks on it.
        closing: asyncio.Task[None] = asyncio.create_task(coro=reset_adapter.close())
        concurrent: asyncio.Task[None] = asyncio.create_task(coro=reset_adapter.close())
        await asyncio.sleep(delay=0)
        assert not closing.done()
        closing.cancel()
        await asyncio.sleep(delay=0)
        closing.cancel()
        await asyncio.sleep(delay=0)
        assert not closing.done() and not concurrent.done()
        second_id: str = reset_client.submit_calls[1].message_id
        reset_client._outcomes[second_id] = MessageReceiptDAO(
            message_id=second_id,
            target=reset_client.submit_calls[1].target,
            state="accepted",
            sequence=2,
            durable=True,
            admitted_at=utcnow(),
        )
        reset_client.release(message_id=second_id)
        with pytest.raises(asyncio.CancelledError):
            await closing
        await concurrent
        await reset_adapter.close()
        assert reset_client.close_calls == 0
        assert len(reset_client.submit_calls) == 2


async def test_submission_adapter_receiver_failure_joins_all_siblings(tmp_path: Path) -> None:
    """EF-02: a failing receiver joins every held sibling before close re-raises."""
    sibling_gate: SettableEvent = SettableEvent()
    failing_client: ScriptedMessagingClient = ScriptedMessagingClient(held=sibling_gate, hold=True)
    session: SloAgentSession = build_session(tmp_path=tmp_path)
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: session.is_messaging_ready)
        prompt: RecordingPromptInput = app.query_one(RecordingPromptInput)
        failing_adapter: MessageSubmissionAdapter = await _rebind_scripted_client(
            prompt=prompt, client=failing_client
        )
        prompt.failures_remaining = 1
        prompt.load_text("failing outcome")
        await pilot.press("enter")
        await _wait_until(predicate=lambda: failing_client.submit_calls != [])
        first_id: str = failing_client.submit_calls[0].message_id
        failing_client._outcomes[first_id] = MessageErrorDAO(code="queue_full", message_id=first_id)
        failing_client.release(message_id=first_id)
        await _wait_until(predicate=lambda: prompt.text == "")
        prompt.load_text("held sibling")
        await pilot.press("enter")
        await _wait_until(predicate=lambda: len(failing_client.submit_calls) == 2)
        sibling_id: str = failing_client.submit_calls[1].message_id
        failing_client._outcomes[sibling_id] = MessageErrorDAO(code="queue_full", message_id=sibling_id)
        failing_client.release(message_id=sibling_id)
        sibling_gate.set()
        with pytest.raises(RuntimeError, match="injected outcome failure"):
            await failing_adapter.close()
        # Every owned wait was joined and observed: no task exception is dropped.
        assert all(task.done() for task in failing_adapter._tasks)
        assert failing_client.close_calls == 0


async def test_submission_adapter_client_failure_propagates_after_all_joins(tmp_path: Path) -> None:
    """EF-02: an unexpected client failure re-raises from reset and close after joins."""
    session: SloAgentSession = build_session(tmp_path=tmp_path)
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: session.is_messaging_ready)
        prompt: RecordingPromptInput = app.query_one(RecordingPromptInput)
        broken_adapter: MessageSubmissionAdapter = await _rebind_scripted_client(
            prompt=prompt, client=_RaisingClient()
        )
        prompt.load_text("broken client")
        await pilot.press("enter")
        await _wait_until(predicate=lambda: broken_adapter._first_wait_failure is not None)
        with pytest.raises(ValueError, match="broken borrowed client"):
            await broken_adapter.reset()
        with pytest.raises(ValueError, match="broken borrowed client"):
            await broken_adapter.close()


@pytest.mark.parametrize(argnames="edit_back_empty", argvalues=[False, True])
async def test_rejection_never_overwrites_newer_typing(tmp_path: Path, edit_back_empty: bool) -> None:
    """A2/A8: late rejection cannot overwrite typing, even after editing back to empty."""
    gate: SettableEvent = SettableEvent()
    client: ScriptedMessagingClient = ScriptedMessagingClient(held=gate, hold=True)
    session: SloAgentSession = build_session(tmp_path=tmp_path)
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    message_id: str = ""
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: session.is_messaging_ready)
        prompt: RecordingPromptInput = app.query_one(RecordingPromptInput)
        await _rebind_scripted_client(prompt=prompt, client=client)
        prompt.load_text("B")
        await pilot.press("enter")
        await _wait_until(predicate=lambda: prompt.text == "")
        await _wait_until(predicate=lambda: client.submit_calls != [])
        message_id = client.submit_calls[0].message_id
        await pilot.press("C")
        assert prompt.text == "C"
        if edit_back_empty:
            await pilot.press("backspace")
            assert prompt.text == ""
        client._outcomes[message_id] = MessageErrorDAO(code="sender_limit", message_id=message_id)
        gate.set()
        await _wait_until(
            predicate=lambda: any(
                "too many of your messages are waiting" in line for line in _transcript_notices(app)
            )
        )
        assert prompt.text == ("" if edit_back_empty else "C")
        assert len(client.submit_calls) == 1 and not client.receipt_calls
        drafts: tuple[RecoverableDraftDAO, ...] = prompt.list_recoverable_drafts()
        assert [draft.draft_submission.message_submission.message_id for draft in drafts] == [message_id]
        assert drafts[0].state == "recoverable"
        assert drafts[0].draft_submission.message_submission.text == "B"
    # Scripted refusal leaves no durable row: nothing was ever admitted.
    database_path: Path = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
    assert database_path.resolve().is_relative_to(tmp_path.resolve())
    rows: tuple[tuple[str, int, str], ...] = await asyncio.to_thread(
        read_closed_message_rows, database_path=database_path, temporary_root=tmp_path
    )
    assert rows == ()


async def test_rejection_restores_unchanged_cleared_draft(tmp_path: Path) -> None:
    """A3 (01.2): a rejected untouched cleared draft is restored with cursor at end."""
    gate: SettableEvent = SettableEvent()
    client: ScriptedMessagingClient = ScriptedMessagingClient(held=gate, hold=True)
    session: SloAgentSession = build_session(tmp_path=tmp_path)
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    message_id: str = ""
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: session.is_messaging_ready)
        prompt: RecordingPromptInput = app.query_one(RecordingPromptInput)
        await _rebind_scripted_client(prompt=prompt, client=client)
        prompt.load_text("B")
        await pilot.press("enter")
        await _wait_until(predicate=lambda: prompt.text == "")
        await _wait_until(predicate=lambda: client.submit_calls != [])
        message_id = client.submit_calls[0].message_id
        client._outcomes[message_id] = MessageErrorDAO(code="queue_full", message_id=message_id)
        gate.set()
        await _wait_until(predicate=lambda: any("text restored" in line for line in _transcript_notices(app)))
        assert prompt.text == "B"
        assert prompt.cursor_location == (0, 1)
        assert prompt.list_recoverable_drafts() == ()
    database_path: Path = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
    rows: tuple[tuple[str, int, str], ...] = await asyncio.to_thread(
        read_closed_message_rows, database_path=database_path, temporary_root=tmp_path
    )
    assert rows == ()


async def test_unknown_outcome_retries_same_id_without_duplicate(tmp_path: Path) -> None:
    """A4 (01.2): an uncertain admission retries the identical ID exactly once."""
    gate: SettableEvent = SettableEvent()
    client: ScriptedMessagingClient = ScriptedMessagingClient(held=gate, hold=True)
    session: SloAgentSession = build_session(tmp_path=tmp_path)
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    message_id: str = ""
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: session.is_messaging_ready)
        prompt: RecordingPromptInput = app.query_one(RecordingPromptInput)
        await _rebind_scripted_client(prompt=prompt, client=client)
        prompt.load_text("U")
        await pilot.press("enter")
        await _wait_until(predicate=lambda: prompt.text == "")
        await _wait_until(predicate=lambda: client.submit_calls != [])
        message_id = client.submit_calls[0].message_id
        # Submit and its single lookup both time out before the store commits.
        client._outcomes[message_id] = MessageErrorDAO(code="unknown_outcome", message_id=message_id)
        gate.set()
        await _wait_until(
            predicate=lambda: any("delivery uncertain" in line for line in _transcript_notices(app))
        )
        assert client.receipt_calls == [message_id]
        drafts: tuple[RecoverableDraftDAO, ...] = prompt.list_recoverable_drafts()
        assert [draft.draft_submission.message_submission.message_id for draft in drafts] == [message_id]
        assert drafts[0].state == "recoverable"
        assert drafts[0].last_error_code == "unknown_outcome"
        # The store committed meanwhile: same-ID retry observes it, never resubmits.
        client._outcomes[message_id] = MessageReceiptDAO(
            message_id=message_id,
            target=session.messaging_target,
            state="applied",
            sequence=1,
            durable=True,
            admitted_at=utcnow(),
            applied_at=utcnow(),
            run_id=str(uuid4()),
        )
        prompt.load_text(f"/messages retry {message_id[:8]}")
        await pilot.press("enter")
        await _wait_until(predicate=lambda: prompt.list_recoverable_drafts() == ())
        assert [submission.message_id for submission in client.submit_calls] == [message_id]
        assert client.receipt_calls == [message_id, message_id]


async def test_fifth_waiting_draft_is_refused_before_clear(tmp_path: Path) -> None:
    """A5 (01.2): four held waits bound admission; the fifth Enter keeps its text."""
    client: ScriptedMessagingClient = ScriptedMessagingClient(hold=True)
    session: SloAgentSession = build_session(tmp_path=tmp_path)
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    adapter: MessageSubmissionAdapter | None = None
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: session.is_messaging_ready)
        prompt: RecordingPromptInput = app.query_one(RecordingPromptInput)
        adapter = await _rebind_scripted_client(prompt=prompt, client=client)
        for index in range(4):
            prompt.load_text(f"draft {index}")
            await pilot.press("enter")
            await _wait_until(predicate=lambda: prompt.text == "")
        await _wait_until(predicate=lambda: len(client.submit_calls) == 4)
        prompt.load_text("fifth")
        await pilot.press("enter")
        await _wait_until(
            predicate=lambda: any("Too many prompts are waiting" in line for line in _transcript_notices(app))
        )
        assert prompt.text == "fifth"
        assert len(client.submit_calls) == 4
        assert len(prompt.list_recoverable_drafts()) == 4
        # DC04 now joins the binding before pruning; release test-owned holds
        # while still mounted rather than relying on leaked admission waits.
        for submission in list(client.submit_calls):
            client._outcomes[submission.message_id] = MessageReceiptDAO(
                message_id=submission.message_id,
                target=submission.target,
                state="accepted",
                sequence=1,
                durable=True,
                admitted_at=utcnow(),
            )
            client.release(message_id=submission.message_id)
    assert client.close_calls == 0


async def test_recoverable_budget_counts_waiting_and_retained_bytes(tmp_path: Path) -> None:
    """A6 (01.2): sixteen tracked snapshots bound admission; discard frees one slot."""
    client: ScriptedMessagingClient = ScriptedMessagingClient(hold=True)
    session: SloAgentSession = build_session(tmp_path=tmp_path)
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: session.is_messaging_ready)
        prompt: RecordingPromptInput = app.query_one(RecordingPromptInput)
        await _rebind_scripted_client(prompt=prompt, client=client)
        # One forever-held wait occupies the in-flight slot; it never resolves.
        prompt.load_text("held")
        await pilot.press("enter")
        await _wait_until(predicate=lambda: prompt.text == "")
        await _wait_until(predicate=lambda: client.submit_calls != [])
        held_id: str = client.submit_calls[0].message_id
        recoverable_ids: list[str] = []
        for index in range(15):
            # A distinct trailing space per draft survives the Enter-time strip,
            # so the editor is never the cleared revision when the refusal lands.
            prompt.load_text(f"recoverable {index}")
            await pilot.press("enter")
            await _wait_until(predicate=lambda: len(client.submit_calls) == index + 2)
            # Type one kept character after the admission clears the draft.
            prompt.insert(" ")
            failed_id: str = client.submit_calls[-1].message_id
            client._outcomes[failed_id] = MessageErrorDAO(code="queue_full", message_id=failed_id)
            client.release(message_id=failed_id)

            def _recoverable(fid: str = failed_id) -> bool:
                """Predicate closure over the failed ID without lambda inference."""
                return any(
                    draft.draft_submission.message_submission.message_id == fid
                    and draft.state == "recoverable"
                    for draft in prompt.list_recoverable_drafts()
                )

            await _wait_until(predicate=_recoverable)
            recoverable_ids.append(failed_id)
        prompt.load_text("seventeenth")
        await pilot.press("enter")
        await _wait_until(
            predicate=lambda: any("Too many prompts are waiting" in line for line in _transcript_notices(app))
        )
        assert prompt.text == "seventeenth"
        assert len(client.submit_calls) == 16
        drafts: tuple[RecoverableDraftDAO, ...] = prompt.list_recoverable_drafts()
        assert len(drafts) == 16
        assert [draft.state for draft in drafts].count("waiting") == 1
        # Discard frees exactly one snapshot slot; the held wait still counts in-flight.
        prompt.load_text(f"/messages discard {recoverable_ids[0][:8]}")
        await pilot.press("enter")
        await _wait_until(predicate=lambda: len(prompt.list_recoverable_drafts()) == 15)
        prompt.load_text("after discard")
        await pilot.press("enter")
        await _wait_until(predicate=lambda: len(client.submit_calls) == 17)
        prompt.insert(" ")  # keep the replacement's rejection, as above
        # The freed slot's replacement is kept once its scripted refusal lands.
        seventeenth_id: str = client.submit_calls[-1].message_id
        client._outcomes[seventeenth_id] = MessageErrorDAO(code="queue_full", message_id=seventeenth_id)
        client.release(message_id=seventeenth_id)
        await _wait_until(
            predicate=lambda: any(
                draft.draft_submission.message_submission.message_id == seventeenth_id
                and draft.state == "recoverable"
                for draft in prompt.list_recoverable_drafts()
            )
        )
        client._outcomes[held_id] = MessageErrorDAO(code="storage_unavailable", message_id=held_id)
        client.release(message_id=held_id)
    assert client.close_calls == 0


async def test_eager_outcome_waits_for_registration_and_clear(tmp_path: Path) -> None:
    """A7: genuinely inline task execution delivers before the editor's clear commit."""
    from contextvars import Context
    from typing import Any
    from src.tui.components.prompt_input.commands import PromptCommand

    class PrecommitProbe(RecordingPromptInput):
        """Observe delivery before/after the real receiver without assigning its state."""

        def __init__(self) -> None:
            """Keep precommit delivery identities for this test's mounted lifetime."""
            super().__init__()
            self.precommit_deliveries: list[str] = []

        async def handle(self, *, command: PromptCommand) -> None:
            """Prove real receiver delivery precedes clear, without mutating tracked state."""
            if isinstance(command, SubmissionOutcomeDAO):
                entry = self._tracked_drafts[command.draft_submission.message_submission.message_id]
                assert not entry.committed
                assert self.text == "eager"
                await super().handle(command=command)
                assert self.text == "eager"
                assert entry.early_outcome == command.outcome
                assert self._prompt_history._entries == []
                self.precommit_deliveries.append(command.draft_submission.message_submission.message_id)
                return
            await super().handle(command=command)

    session = build_session(tmp_path=tmp_path)
    app = SloTUI(prompt_factory=PrecommitProbe, session=session, messaging_enabled=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: session.is_messaging_ready)
        prompt = app.query_one(PrecommitProbe)

        def eager_receipt(submission: MessageSubmissionDAO) -> MessageReceiptDAO:
            """Answer without suspension so a single inline step completes delivery."""
            return MessageReceiptDAO(
                message_id=submission.message_id,
                target=submission.target,
                state="accepted",
                sequence=1,
                durable=True,
                admitted_at=utcnow(),
            )

        client = ScriptedMessagingClient(always=eager_receipt)
        await _rebind_scripted_client(prompt=prompt, client=client)
        prompt.load_text("eager")
        draft = prompt.build_draft_submission(text="eager", intent_revision=prompt._draft_revision)
        assert draft is not None
        loop = asyncio.get_running_loop()
        previous = loop.get_task_factory()

        # Any here matches asyncio's heterogeneous task-factory contract, not a domain boundary.
        def inline_submission_factory(
            loop: asyncio.AbstractEventLoop,
            coro: Coroutine[Any, Any, _TaskResult] | Generator[Any, None, _TaskResult],
            *,
            context: Context | None = None,
        ) -> asyncio.Future[_TaskResult]:
            """Eagerly complete only this admission flow; leave all framework tasks native."""
            if getattr(getattr(coro, "cr_code", None), "co_name", None) != "_submit_flow":
                return asyncio.Task(coro=coro, loop=loop, context=context)
            completed: asyncio.Future[_TaskResult] = loop.create_future()
            try:
                coro.send(None)
            except StopIteration as result:
                completed.set_result(result.value)
            except BaseException as error:
                completed.set_exception(error)
            else:
                coro.close()
                raise AssertionError("The scripted eager admission unexpectedly suspended")
            return completed

        loop.set_task_factory(factory=inline_submission_factory)
        try:
            await prompt.handle(command=SubmitDraftDAO(draft_submission=draft))
        finally:
            loop.set_task_factory(factory=previous)
        receipt_id = draft.message_submission.message_id
        assert prompt.precommit_deliveries == [receipt_id]
        assert len(prompt.outcomes) == 1
        assert prompt.text == "" and prompt.list_recoverable_drafts() == ()
        assert prompt._tracked_drafts == {}
        assert prompt._prompt_history._entries == ["eager"]
        assert len(client.submit_calls) == 1
        await pilot.press("up")
        assert prompt.text == "eager"
    assert client.close_calls == 0


async def test_empty_and_literal_drafts_follow_existing_rules(tmp_path: Path) -> None:
    """A11 (01.2): whitespace Enter and multi-line literals never reach admission."""
    model: RecordingModel = RecordingModel(
        responses=[FauxChatModel.assistant_message(content="literal outcome")]
    )
    session: SloAgentSession = _build_factory_session(tmp_path=tmp_path, model=model)
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: session.is_messaging_ready)
        prompt: RecordingPromptInput = app.query_one(RecordingPromptInput)
        prompt.load_text("   ")
        await pilot.press("enter")
        await pilot.pause()
        assert prompt.text == ""
        assert prompt.list_recoverable_drafts() == ()
        literal: str = "line one [brackets]\nline two {braces}"
        prompt.load_text(literal)
        await pilot.press("enter")
        await _wait_until(predicate=lambda: prompt.text == "")
        await _wait_until(predicate=lambda: model.entered.is_set())
        await _release_provider_once(model=model, session=session)
        assert len(model.requests) == 1
        human_texts: list[str] = [
            str(message.content) for message in model.requests[0] if isinstance(message, HumanMessage)
        ]
        assert human_texts == [literal]
        assert app._in_flight_task is None
        assert app._queued_prompt_text is None
    events: list[SessionHistoryEventDAO] = await session.history_store.load_events(  # type: ignore[union-attr]
        session_id=session.session_id
    )
    messaging_updates: list[SessionHistoryEventDAO] = [
        event for event in events if "messaging_v1" in event.payload.metadata
    ]
    assert [event.payload.content for event in messaging_updates] == [literal]


async def test_enter_during_session_change_keeps_text_with_notice(tmp_path: Path) -> None:
    """A12 (01.2): a sealed binding refuses capture and keeps the draft text."""
    client: ScriptedMessagingClient = ScriptedMessagingClient()
    session: SloAgentSession = build_session(tmp_path=tmp_path)
    app: SloTUI = SloTUI(prompt_factory=RecordingPromptInput, session=session, messaging_enabled=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _wait_until(predicate=lambda: session.is_messaging_ready)
        prompt: RecordingPromptInput = app.query_one(RecordingPromptInput)
        prompt._submission_sealed = True  # 01.4 retirement seal; driven directly here.
        prompt.load_text("kept during change")
        await pilot.press("enter")
        await _wait_until(
            predicate=lambda: any(
                "Session is changing; your text was kept." in line for line in _transcript_notices(app)
            )
        )
        assert prompt.text == "kept during change"
        assert client.submit_calls == []
        assert prompt.list_recoverable_drafts() == ()
        prompt._submission_sealed = False
        await _rebind_scripted_client(prompt=prompt, client=client)
    assert client.close_calls == 0


async def test_successful_draft_snapshots_are_released_across_reset_and_rebind(tmp_path: Path) -> None:
    """Settled snapshots do not survive in the real production editor or adapter."""
    import gc
    import weakref

    session = build_session(tmp_path=tmp_path)
    app = SloTUI(session=session, messaging_enabled=True)
    snapshots: list[weakref.ReferenceType[DraftSubmissionDAO]] = []

    def receipt(submission: MessageSubmissionDAO) -> MessageReceiptDAO:
        """Accept each original identity without keeping its enclosing draft snapshot."""
        return MessageReceiptDAO(
            message_id=submission.message_id,
            target=submission.target,
            state="accepted",
            sequence=1,
            durable=True,
            admitted_at=utcnow(),
        )

    async with app.run_test() as pilot:
        await _wait_until(predicate=lambda: session.is_messaging_ready)
        prompt = app.query_one(PromptInputComponent)
        client = ScriptedMessagingClient(always=receipt)
        adapter = await _rebind_scripted_client(prompt=prompt, client=client)
        for index in range(24):
            prompt.load_text(text=f"settled {index}")
            draft = prompt.build_draft_submission(text=prompt.text, intent_revision=prompt._draft_revision)
            assert draft is not None
            snapshots.append(weakref.ref(draft))
            await prompt.handle(command=SubmitDraftDAO(draft_submission=draft))
            del draft
            await adapter.reset()
            assert prompt._tracked_drafts == {} and prompt.list_recoverable_drafts() == ()
            assert not adapter._tasks and not adapter._drafts_by_id
            gc.collect()
            assert all(snapshot() is None for snapshot in snapshots)
        await prompt.reset()
        await _rebind_scripted_client(prompt=prompt, client=ScriptedMessagingClient(always=receipt))
        gc.collect()
        assert all(snapshot() is None for snapshot in snapshots)
        assert len(client.submit_calls) == 24
