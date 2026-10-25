"""Real-session client authority, uncertainty and lifecycle journeys with real SQLite."""

import asyncio
import sqlite3
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
from src.agents.slo_agent.messaging.dao import (
    MessageAddressDAO,
    MessageAdmissionError,
    MessageErrorDAO,
    MessagePrincipalDAO,
    MessageReceiptDAO,
    MessageSubmissionDAO,
    MessageStoreError,
    SessionAlreadyOwnedError,
    MessagingLimitsDAO,
)
from src.agents.slo_agent.messaging.ownership import SessionExecutionOwnership
from src.agents.slo_agent.messaging.queue import SessionMessageQueue
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.agents.slo_agent.messaging.test_queue_closure import CompletionGate, wait_until
from tests.integration.test_session_messaging import read_closed_message_rows


@pytest.mark.parametrize(argnames="hold_before", argvalues=[True, False])
@pytest.mark.parametrize(argnames="wait_outcome", argvalues=["timeout", "cancel"])
async def test_client_admission_wait_never_abandons_real_commit(
    tmp_path: Path, hold_before: bool, wait_outcome: Literal["timeout", "cancel"]
) -> None:
    """Deadline/cancellation stop a caller, while client and owner close join the same writer."""
    session_id: str = str(uuid4())
    history_root: Path = tmp_path / "history"
    database_path: Path = history_root / session_id / "messaging.v1.sqlite3"
    assert database_path.resolve().is_relative_to(tmp_path.resolve())
    gate: CompletionGate = CompletionGate(hold_before=hold_before)
    config: SessionConfigDAO = SessionConfigDAO(
        workdir=tmp_path,
        session_id=session_id,
        history_root=history_root,
        model_name="gpt-5.4",
        messaging_limits=MessagingLimitsDAO(admission_seconds=0.05),
    )
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path, session_id=session_id, config=config, messaging_executor_factory=lambda: gate
    )
    await session.start_messaging()
    await session._lock.acquire()  # Keep the real scheduler behind execution while admission is gated.
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    request: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="Exactly once."
    )
    queue: Optional[SessionMessageQueue] = session._message_queue
    assert queue is not None
    await wait_until(predicate=lambda: len(queue._changed._waiters) == 2)
    gate.armed = True
    admission: asyncio.Task[MessageReceiptDAO | MessageErrorDAO] = asyncio.create_task(
        coro=client.submit(submission=request)
    )
    closes: list[asyncio.Task[None]] = []
    try:
        await wait_until(predicate=gate.started.is_set if hold_before else gate.completed.is_set)
        if wait_outcome == "cancel":
            admission.cancel()
            cancellation: pytest.ExceptionInfo[asyncio.CancelledError]
            with pytest.raises(expected_exception=asyncio.CancelledError) as cancellation:
                await admission
            assert cancellation.type is asyncio.CancelledError
        else:
            assert await admission == MessageErrorDAO(code="unknown_outcome", message_id=request.message_id)
        assert len(client._calls) == 1 and len(session._messaging_calls) == 1
        client_close: asyncio.Task[None] = asyncio.create_task(coro=client.close())
        closes.append(client_close)
        second_client_close: asyncio.Task[None] = asyncio.create_task(coro=client.close())
        closes.append(second_client_close)
        await wait_until(predicate=lambda: client._closing)
        client_close.cancel()
        await asyncio.sleep(delay=0)
        client_close.cancel()
        owner_close: asyncio.Task[None] = asyncio.create_task(coro=session.close_messaging())
        closes.append(owner_close)
        await wait_until(predicate=lambda: session._messaging_closing)
        assert not client_close.done() and not second_client_close.done() and not owner_close.done()
        with pytest.raises(expected_exception=SessionAlreadyOwnedError):
            await SessionExecutionOwnership.acquire(root=history_root, session_id=session_id)
        assert await client.submit(submission=request) == MessageErrorDAO(
            code="completing", message_id=request.message_id
        )
        session._lock.release()
        gate.release.set()
        with pytest.raises(expected_exception=asyncio.CancelledError):
            await asyncio.wait_for(fut=client_close, timeout=3)
        await asyncio.wait_for(fut=second_client_close, timeout=3)
        await asyncio.wait_for(fut=owner_close, timeout=3)
        rows: tuple[tuple[str, int, str], ...] = await asyncio.to_thread(
            read_closed_message_rows, database_path=database_path, temporary_root=tmp_path
        )
        assert rows == ((request.message_id, 1, "accepted"),)
        assert not client._calls and not session._messaging_calls
    finally:
        gate.release.set()
        await asyncio.gather(admission, *closes, return_exceptions=True)
        await client.close()
        await session.close_messaging()


async def test_cancelled_start_joins_real_failed_open_before_propagating_cancellation(tmp_path: Path) -> None:
    """A corrupt disposable database cannot replace caller cancellation or leak its lease/worker."""
    session_id: str = str(uuid4())
    history_root: Path = tmp_path / "history"
    database_path: Path = history_root / session_id / "messaging.v1.sqlite3"
    assert database_path.resolve().is_relative_to(tmp_path.resolve())
    gate: CompletionGate = CompletionGate(hold_before=True)
    gate.armed = True
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(workdir=tmp_path, history_root=history_root, model_name="gpt-5.4"),
        messaging_executor_factory=lambda: gate,
    )
    startup: asyncio.Task[None] = asyncio.create_task(coro=session.start_messaging())
    try:
        await wait_until(predicate=gate.started.is_set)
        # Ownership has created the private directory, but SQLite has not opened it.
        assert database_path.resolve().is_relative_to(tmp_path.resolve())
        database_path.write_bytes(b"deliberately corrupt test-owned SQLite")
        database_path.chmod(mode=0o600)
        startup.cancel()
        await asyncio.sleep(delay=0)
        startup.cancel()
        await asyncio.sleep(delay=0)
        assert not startup.done()
        gate.release.set()
        with pytest.raises(expected_exception=asyncio.CancelledError):
            await asyncio.wait_for(fut=startup, timeout=3)
        await session.close_messaging()
        lease: SessionExecutionOwnership = await SessionExecutionOwnership.acquire(
            root=history_root, session_id=session_id
        )
        await lease.release()
        assert not session._messaging_calls
    finally:
        gate.release.set()
        await asyncio.gather(startup, return_exceptions=True)
        await session.close_messaging()


@pytest.mark.parametrize(argnames="known", argvalues=[False, True])
async def test_receipt_deadline_is_not_absence_and_detach_leaves_session_usable(
    tmp_path: Path, known: bool
) -> None:
    """Blocked reads stay uncertain; detach preserves admission without starting provider execution."""
    session_id: str = str(uuid4())
    history_root: Path = tmp_path / "history"
    assert (history_root / session_id).resolve().is_relative_to(tmp_path.resolve())
    gate: CompletionGate = CompletionGate(hold_before=True)
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path,
            history_root=history_root,
            model_name="gpt-5.4",
            messaging_limits=MessagingLimitsDAO(admission_seconds=0.05),
        ),
        messaging_executor_factory=lambda: gate,
    )
    await session.start_messaging()
    # This admission/receipt journey must not race consumption or lazy provider startup.
    await session._lock.acquire()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    request: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="Same identity."
    )
    accepted: Optional[MessageReceiptDAO | MessageErrorDAO] = None
    if known:
        accepted = await client.submit(submission=request)
        assert isinstance(accepted, MessageReceiptDAO)
    gate.armed = True
    lookup: asyncio.Task[MessageReceiptDAO | MessageErrorDAO] = asyncio.create_task(
        coro=client.get_receipt(message_id=request.message_id)
    )
    detach: Optional[asyncio.Task[None]] = None
    try:
        await wait_until(predicate=gate.started.is_set)
        assert await lookup == MessageErrorDAO(code="unknown_outcome", message_id=request.message_id)
        detach = asyncio.create_task(coro=client.close())
        await wait_until(predicate=lambda: client._closing)
        assert not detach.done()
        gate.release.set()
        await asyncio.wait_for(fut=detach, timeout=3)
        second: LocalSessionMessagingClient = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        try:
            observed: MessageReceiptDAO | MessageErrorDAO = await second.get_receipt(
                message_id=request.message_id
            )
            assert observed == (
                accepted if known else MessageErrorDAO(code="not_found", message_id=request.message_id)
            )
            retried: MessageReceiptDAO | MessageErrorDAO = await second.submit(submission=request)
            assert isinstance(retried, MessageReceiptDAO) and retried.sequence == 1
            duplicate: MessageReceiptDAO | MessageErrorDAO = await second.submit(submission=request)
            assert duplicate == retried, repr(duplicate)
            assert session._agent is None and session._messaging_failure is None
        finally:
            await second.close()
    finally:
        gate.release.set()
        await asyncio.gather(lookup, return_exceptions=True)
        if detach is not None:
            await detach
        await client.close()
        session._lock.release()
        await session.close_messaging()

    rows: tuple[tuple[str, int, str], ...] = await asyncio.to_thread(
        read_closed_message_rows,
        database_path=history_root / session_id / "messaging.v1.sqlite3",
        temporary_root=tmp_path,
    )
    assert rows == ((request.message_id, 1, "accepted"),)


async def test_lifecycle_is_rechecked_after_waiting_for_admission_mutex(tmp_path: Path) -> None:
    """Closing during a prior real commit refuses a waiting publisher before it can allocate sequence two."""
    session_id: str = str(uuid4())
    history_root: Path = tmp_path / "history"
    database_path: Path = history_root / session_id / "messaging.v1.sqlite3"
    assert database_path.resolve().is_relative_to(tmp_path.resolve())
    gate: CompletionGate = CompletionGate(hold_before=True)
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(workdir=tmp_path, history_root=history_root, model_name="gpt-5.4"),
        messaging_executor_factory=lambda: gate,
    )
    await session.start_messaging()
    await session._lock.acquire()  # Admission and shutdown retain their real mutex/store paths.
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    first: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="First commit."
    )
    second: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="Must be refused."
    )
    queue: Optional[SessionMessageQueue] = session._message_queue
    assert queue is not None
    await wait_until(predicate=lambda: len(queue._changed._waiters) == 2)
    gate.armed = True
    admission: asyncio.Task[MessageReceiptDAO | MessageErrorDAO] = asyncio.create_task(
        coro=client.submit(submission=first)
    )
    waiting: Optional[asyncio.Task[MessageReceiptDAO | MessageErrorDAO]] = None
    closing: Optional[asyncio.Task[None]] = None
    try:
        await wait_until(predicate=gate.started.is_set)
        waiting = asyncio.create_task(coro=client.submit(submission=second))
        await wait_until(predicate=lambda: len(session._messaging_calls) == 2)
        closing = asyncio.create_task(coro=session.close_messaging())
        await wait_until(predicate=lambda: session._messaging_closing)
        session._lock.release()
        gate.release.set()
        committed: MessageReceiptDAO | MessageErrorDAO = await admission
        assert isinstance(committed, MessageReceiptDAO) and committed.sequence == 1
        assert await waiting == MessageErrorDAO(code="completing", message_id=second.message_id)
        await closing
        rows: tuple[tuple[str, int, str], ...] = await asyncio.to_thread(
            read_closed_message_rows, database_path=database_path, temporary_root=tmp_path
        )
        assert rows == ((first.message_id, 1, "accepted"),)
    finally:
        gate.release.set()
        await asyncio.gather(admission, return_exceptions=True)
        if waiting is not None:
            await waiting
        if closing is not None:
            await closing
        await client.close()
        await session.close_messaging()


async def test_bound_route_registration_capabilities_and_capacity_refuse_before_allocation(
    tmp_path: Path,
) -> None:
    """Exact current identity and destination precede capability checks; duplicate identity beats capacity."""
    session_id: str = str(uuid4())
    history_root: Path = tmp_path / "history"
    database_path: Path = history_root / session_id / "messaging.v1.sqlite3"
    assert database_path.resolve().is_relative_to(tmp_path.resolve())
    session: SloAgentSession = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            session_id=session_id,
            history_root=history_root,
            model_name="gpt-5.4",
            messaging_limits=MessagingLimitsDAO(pending_inputs=1),
        )
    )
    await session.start_messaging()
    await session._lock.acquire()  # Freeze consumption while asserting capacity and immutable identity.
    target: MessageAddressDAO = session.messaging_target
    owner: MessagePrincipalDAO = session.messaging_owner_principal
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=target, principal=owner
    )
    stale_target: MessageAddressDAO = target.model_copy(update={"generation": str(uuid4())})
    other_target: MessageAddressDAO = target.model_copy(update={"session_id": str(uuid4())})
    stale: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=stale_target, principal=owner
    )
    foreign: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=other_target, principal=owner
    )
    forged_owner: MessagePrincipalDAO = MessagePrincipalDAO(principal_id=owner.principal_id, kind="agent")
    forged: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=target, principal=forged_owner
    )
    request: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()), target=target, kind="agent_input", text="Only accepted body."
    )
    try:
        assert await client.submit(
            submission=request.model_copy(update={"target": stale_target})
        ) == MessageErrorDAO(code="invalid_message", message_id=request.message_id)
        assert await stale.submit(
            submission=request.model_copy(update={"target": stale_target})
        ) == MessageErrorDAO(code="stale_generation", message_id=request.message_id)
        assert await stale.get_receipt(message_id=request.message_id) == MessageErrorDAO(
            code="stale_generation", message_id=request.message_id
        )
        assert await foreign.submit(
            submission=request.model_copy(update={"target": other_target})
        ) == MessageErrorDAO(code="invalid_message", message_id=request.message_id)
        assert await foreign.get_receipt(message_id=request.message_id) == MessageErrorDAO(
            code="invalid_message", message_id=request.message_id
        )
        assert await forged.submit(submission=request) == MessageErrorDAO(
            code="unauthorized", message_id=request.message_id
        )
        assert await forged.get_receipt(message_id=request.message_id) == MessageErrorDAO(
            code="unauthorized", message_id=request.message_id
        )
        assert await client.get_receipt(message_id="not-a-uuid") == MessageErrorDAO(code="invalid_message")
        accepted: MessageReceiptDAO | MessageErrorDAO = await client.submit(submission=request)
        assert isinstance(accepted, MessageReceiptDAO) and accepted.sequence == 1
        assert await client.submit(submission=request) == accepted
        assert await client.submit(
            submission=request.model_copy(update={"text": "Conflicting intent."})
        ) == MessageErrorDAO(code="conflict", message_id=request.message_id)
        excess: MessageSubmissionDAO = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="Over capacity."
        )
        assert await client.submit(submission=excess) == MessageErrorDAO(
            code="queue_full", message_id=excess.message_id
        )
    finally:
        await client.close()
        await stale.close()
        await foreign.close()
        await forged.close()
        session._lock.release()
        await session.close_messaging()
    rows: tuple[tuple[str, int, str], ...] = await asyncio.to_thread(
        read_closed_message_rows, database_path=database_path, temporary_root=tmp_path
    )
    assert rows == ((request.message_id, 1, "accepted"),)


async def test_valid_future_capability_is_refused_without_accepted_row(tmp_path: Path) -> None:
    """A fully valid workflow payload is unsupported, not stranded awaiting B.2 effects."""
    from src.agents.slo_agent.messaging.dao import WorkflowPayloadDAO, WorkflowMessagePayloadDAO

    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        enable_history=False,
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"),
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session,
        target=session.messaging_target,
        principal=session.messaging_owner_principal,
    )
    workflow_id: str = "future-workflow"
    generation: str = str(uuid4())
    submission: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()),
        target=session.messaging_target,
        kind="context_note",
        text="Started",
        workflow_id=workflow_id,
        source_event_id=f"workflow:{workflow_id}:{generation}:1",
        payload=WorkflowMessagePayloadDAO(
            workflow=WorkflowPayloadDAO(
                event="started",
                owner_session_id=session.session_id,
                orchestrator_session_id=str(uuid4()),
                orchestrator_generation=generation,
                workflow_id=workflow_id,
                revision=1,
            )
        ),
    )
    try:
        assert await client.submit(submission=submission) == MessageErrorDAO(
            code="unsupported",
            message_id=submission.message_id,
        )
        assert session._message_store is not None
        assert not await session._message_store.read_identities()
        assert session._agent is None
        assert await client.get_receipt(message_id=submission.message_id) == MessageErrorDAO(
            code="not_found",
            message_id=submission.message_id,
        )
    finally:
        await client.close()
        await session.close_messaging()


def corrupt_test_lifecycle(*, database_path: Path, temporary_root: Path) -> None:
    """Corrupt only a resolved test-owned database using the real SQLite engine."""
    assert database_path.resolve().is_relative_to(temporary_root.resolve())
    connection: sqlite3.Connection = sqlite3.connect(database=str(database_path))
    try:
        connection.execute("UPDATE meta SET value='secret-native-error-sentinel' WHERE key='lifecycle'")
        connection.commit()
    finally:
        connection.close()


async def test_corrupt_receipt_is_safe_and_sticky_before_next_admission(tmp_path: Path) -> None:
    """Corruption never becomes absence or a native error; a later call cannot continue acceptance."""
    session_id: str = str(uuid4())
    history_root: Path = tmp_path / "history"
    database_path: Path = history_root / session_id / "messaging.v1.sqlite3"
    assert database_path.resolve().is_relative_to(tmp_path.resolve())
    session: SloAgentSession = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            session_id=session_id,
            history_root=history_root,
            model_name="gpt-5.4",
        )
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    request: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="No row."
    )
    try:
        await asyncio.to_thread(corrupt_test_lifecycle, database_path=database_path, temporary_root=tmp_path)
        refused: MessageReceiptDAO | MessageErrorDAO = await client.get_receipt(message_id=request.message_id)
        assert refused == MessageErrorDAO(code="storage_unavailable", message_id=request.message_id)
        assert "secret-native-error-sentinel" not in repr(refused)
        assert await client.submit(submission=request) == refused
        absent_id: str = str(uuid4())
        assert await client.get_receipt(message_id=absent_id) == MessageErrorDAO(
            code="storage_unavailable", message_id=absent_id
        )
    finally:
        await client.close()
        # A broken store must report unconfirmed retention, but still join and release ownership.
        with pytest.raises(expected_exception=MessageStoreError):
            await session.close_messaging()
    lease: SessionExecutionOwnership = await SessionExecutionOwnership.acquire(
        root=history_root, session_id=session_id
    )
    await lease.release()
    rows: tuple[tuple[str, int, str], ...] = await asyncio.to_thread(
        read_closed_message_rows, database_path=database_path, temporary_root=tmp_path
    )
    assert rows == ()


@pytest.mark.parametrize(argnames="persistent", argvalues=[False, True])
async def test_repeated_start_is_one_owner_and_closed_instances_never_restart(
    tmp_path: Path, persistent: bool
) -> None:
    """Concurrent starts share one binding; explicit ephemeral startup never creates persistent state."""
    session_id: str = str(uuid4())
    history_root: Path = tmp_path / "history"
    assert (history_root / session_id).resolve().is_relative_to(tmp_path.resolve())
    config: SessionConfigDAO = SessionConfigDAO(
        workdir=tmp_path, session_id=session_id, history_root=history_root, model_name="gpt-5.4"
    )
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path, session_id=session_id, config=config, enable_history=persistent
    )
    competitor: SloAgentSession = SloAgentSession(
        workdir=tmp_path, session_id=session_id, config=config, enable_history=persistent
    )
    await asyncio.gather(session.start_messaging(), session.start_messaging())
    await session._lock.acquire()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    target: MessageAddressDAO = session.messaging_target
    request: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()), target=target, kind="agent_input", text="Actual durability mode."
    )
    try:
        assert session.messaging_target == target
        with pytest.raises(expected_exception=SessionAlreadyOwnedError):
            await competitor.start_messaging()
        accepted: MessageReceiptDAO | MessageErrorDAO = await client.submit(submission=request)
        assert isinstance(accepted, MessageReceiptDAO) and accepted.durable is persistent
        if not persistent:
            assert not history_root.exists()
        assert session._agent is None and session._messaging_failure is None
        closing: asyncio.Task[None] = asyncio.create_task(coro=session.close_messaging())
        await wait_until(predicate=lambda: session._messaging_closing)
        session._lock.release()
        await asyncio.gather(closing, session.close_messaging())
        assert session._agent is None
        restart_error: pytest.ExceptionInfo[MessageAdmissionError]
        with pytest.raises(expected_exception=MessageAdmissionError) as restart_error:
            await session.start_messaging()
        assert restart_error.value.error.code == "completing"
        assert await client.submit(submission=request) == MessageErrorDAO(
            code="completing", message_id=request.message_id
        )
    finally:
        await client.close()
        if session._lock.locked():
            session._lock.release()
        await session.close_messaging()
        await competitor.close_messaging()


async def test_close_during_start_joins_worker_without_publishing_ready(tmp_path: Path) -> None:
    """Shutdown racing real SQLite startup owns cleanup and holds the execution lease until it joins."""
    session_id: str = str(uuid4())
    history_root: Path = tmp_path / "history"
    assert (history_root / session_id).resolve().is_relative_to(tmp_path.resolve())
    gate: CompletionGate = CompletionGate(hold_before=True)
    gate.armed = True
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(workdir=tmp_path, history_root=history_root, model_name="gpt-5.4"),
        messaging_executor_factory=lambda: gate,
    )
    starting: asyncio.Task[None] = asyncio.create_task(coro=session.start_messaging())
    closing: Optional[asyncio.Task[None]] = None
    try:
        await wait_until(predicate=gate.started.is_set)
        closing = asyncio.create_task(coro=session.close_messaging())
        await wait_until(predicate=lambda: session._messaging_closing)
        closing.cancel()
        await asyncio.sleep(delay=0)
        closing.cancel()
        await asyncio.sleep(delay=0)
        assert not starting.done() and not closing.done()
        with pytest.raises(expected_exception=SessionAlreadyOwnedError):
            await SessionExecutionOwnership.acquire(root=history_root, session_id=session_id)
        gate.release.set()
        await asyncio.wait_for(fut=starting, timeout=3)
        with pytest.raises(expected_exception=asyncio.CancelledError):
            await asyncio.wait_for(fut=closing, timeout=3)
        ready_error: pytest.ExceptionInfo[MessageAdmissionError]
        with pytest.raises(expected_exception=MessageAdmissionError) as ready_error:
            session.messaging_target
        assert ready_error.value.error.code == "completing"
        lease: SessionExecutionOwnership = await SessionExecutionOwnership.acquire(
            root=history_root, session_id=session_id
        )
        await lease.release()
    finally:
        gate.release.set()
        await asyncio.gather(starting, return_exceptions=True)
        if closing is not None:
            await asyncio.gather(closing, return_exceptions=True)
        await session.close_messaging()


@pytest.mark.parametrize(argnames="hold_before", argvalues=[False, True])
async def test_unknown_admission_reuses_original_identity_after_worker_settles(
    tmp_path: Path, hold_before: bool
) -> None:
    """Lost pre/post-commit replies converge on one receipt and never consume a second sequence."""
    session_id: str = str(uuid4())
    history_root: Path = tmp_path / "history"
    database_path: Path = history_root / session_id / "messaging.v1.sqlite3"
    assert database_path.resolve().is_relative_to(tmp_path.resolve())
    gate: CompletionGate = CompletionGate(hold_before=hold_before)
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path,
            history_root=history_root,
            model_name="gpt-5.4",
            messaging_limits=MessagingLimitsDAO(admission_seconds=0.05),
        ),
        messaging_executor_factory=lambda: gate,
    )
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    request: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()),
        target=session.messaging_target,
        kind="agent_input",
        text="Unchanged identity.",
    )
    await session._lock.acquire()
    queue: Optional[SessionMessageQueue] = session._message_queue
    assert queue is not None
    await wait_until(predicate=lambda: len(queue._changed._waiters) == 2)
    gate.armed = True
    admission: asyncio.Task[MessageReceiptDAO | MessageErrorDAO] = asyncio.create_task(
        coro=client.submit(submission=request)
    )
    try:
        await wait_until(predicate=gate.started.is_set if hold_before else gate.completed.is_set)
        assert await admission == MessageErrorDAO(code="unknown_outcome", message_id=request.message_id)
        assert len(client._calls) == 1 and len(session._messaging_calls) == 1
        gate.release.set()
        await wait_until(predicate=lambda: not client._calls and not session._messaging_calls)
        observed: MessageReceiptDAO | MessageErrorDAO = await client.get_receipt(
            message_id=request.message_id
        )
        assert isinstance(observed, MessageReceiptDAO) and observed.sequence == 1
        assert await client.submit(submission=request) == observed
        next_input: MessageSubmissionDAO = MessageSubmissionDAO(
            message_id=str(uuid4()), target=request.target, kind="agent_input", text="Next identity."
        )
        next_receipt: MessageReceiptDAO | MessageErrorDAO = await client.submit(submission=next_input)
        assert isinstance(next_receipt, MessageReceiptDAO) and next_receipt.sequence == 2
    finally:
        gate.release.set()
        await asyncio.gather(admission, return_exceptions=True)
        await client.close()
        session._lock.release()
        await session.close_messaging()
    rows: tuple[tuple[str, int, str], ...] = await asyncio.to_thread(
        read_closed_message_rows, database_path=database_path, temporary_root=tmp_path
    )
    assert rows == ((request.message_id, 1, "accepted"), (next_input.message_id, 1, "accepted"))


async def test_registered_new_owner_cannot_read_prior_authors_receipt(tmp_path: Path) -> None:
    """Registration permits a read transaction, not access to another author's retained input."""
    session_id: str = str(uuid4())
    history_root: Path = tmp_path / "history"
    assert (history_root / session_id).resolve().is_relative_to(tmp_path.resolve())
    config: SessionConfigDAO = SessionConfigDAO(
        workdir=tmp_path, session_id=session_id, history_root=history_root, model_name="gpt-5.4"
    )
    original: SloAgentSession = SloAgentSession.build(config=config)
    await original.start_messaging()
    await original._lock.acquire()
    old_target: MessageAddressDAO = original.messaging_target
    old_principal: MessagePrincipalDAO = original.messaging_owner_principal
    first: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=original, target=old_target, principal=old_principal
    )
    request: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()), target=old_target, kind="agent_input", text="Original authorship."
    )
    try:
        assert original._lock.locked()  # Admission-only journeys must exclude lazy provider construction.
        accepted: MessageReceiptDAO | MessageErrorDAO = await first.submit(submission=request)
        assert isinstance(accepted, MessageReceiptDAO)
        closing: asyncio.Task[None] = asyncio.create_task(coro=original.close_messaging())
        await wait_until(predicate=lambda: original._messaging_closing)
        assert original._agent is None and original._messaging_failure is None
    finally:
        await first.close()
        original._lock.release()
        await original.close_messaging()
        assert original._agent is None
    restarted: SloAgentSession = SloAgentSession.build(config=config)
    await restarted.start_messaging()
    current: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=restarted, target=restarted.messaging_target, principal=restarted.messaging_owner_principal
    )
    revoked: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=restarted, target=restarted.messaging_target, principal=old_principal
    )
    try:
        assert restarted.messaging_target.generation != old_target.generation
        assert restarted.messaging_owner_principal != old_principal
        assert restarted._agent is None
        assert await current.get_receipt(message_id=request.message_id) == MessageErrorDAO(
            code="unauthorized", message_id=request.message_id
        )
        absent_id: str = str(uuid4())
        assert await current.get_receipt(message_id=absent_id) == MessageErrorDAO(
            code="not_found", message_id=absent_id
        )
        assert await revoked.get_receipt(message_id=absent_id) == MessageErrorDAO(
            code="unauthorized", message_id=absent_id
        )
        assert await revoked.get_receipt(message_id=request.message_id) == MessageErrorDAO(
            code="unauthorized", message_id=request.message_id
        )
    finally:
        await current.close()
        await revoked.close()
        await restarted.close_messaging()


async def test_client_never_starts_or_grants_and_receipt_authority_precedes_absence(tmp_path: Path) -> None:
    """Real session registration, not a constructed principal, authorizes known and absent IDs."""
    session_id: str = str(uuid4())
    history_root: Path = tmp_path / "history"
    assert (history_root / session_id).resolve().is_relative_to(tmp_path.resolve())
    session: SloAgentSession = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path, session_id=session_id, history_root=history_root, model_name="gpt-5.4"
        )
    )
    invented_target: MessageAddressDAO = MessageAddressDAO(
        kind="agent_session", session_id=session_id, generation=str(uuid4())
    )
    invented_principal: MessagePrincipalDAO = MessagePrincipalDAO(principal_id="not-registered", kind="human")
    offline_client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=invented_target, principal=invented_principal
    )
    message_id: str = str(uuid4())
    try:
        assert await offline_client.get_receipt(message_id=message_id) == MessageErrorDAO(
            code="offline", message_id=message_id
        )
        assert not (history_root / session_id / "messaging.v1.sqlite3").exists()
        await session.start_messaging()
        await session._lock.acquire()
        target: MessageAddressDAO = session.messaging_target
        owner: MessagePrincipalDAO = session.messaging_owner_principal
        client: LocalSessionMessagingClient = LocalSessionMessagingClient(
            session=session, target=target, principal=owner
        )
        unauthorized_client: LocalSessionMessagingClient = LocalSessionMessagingClient(
            session=session, target=target, principal=invented_principal
        )
        try:
            assert await client.get_receipt(message_id=message_id) == MessageErrorDAO(
                code="not_found", message_id=message_id
            )
            assert await unauthorized_client.get_receipt(message_id=message_id) == MessageErrorDAO(
                code="unauthorized", message_id=message_id
            )
            submission: MessageSubmissionDAO = MessageSubmissionDAO(
                message_id=message_id, target=target, kind="agent_input", text="Only the real owner admits."
            )
            assert await unauthorized_client.submit(submission=submission) == MessageErrorDAO(
                code="unauthorized", message_id=message_id
            )
            assert session._lock.locked()  # Refuse an unsafe fixture before admitting executable input.
            accepted: MessageReceiptDAO | MessageErrorDAO = await client.submit(submission=submission)
            assert isinstance(accepted, MessageReceiptDAO) and accepted.sequence == 1
            assert await unauthorized_client.get_receipt(message_id=message_id) == MessageErrorDAO(
                code="unauthorized", message_id=message_id
            )
            assert session._agent is None and session._messaging_failure is None
            closing: asyncio.Task[None] = asyncio.create_task(coro=session.close_messaging())
            await wait_until(predicate=lambda: session._messaging_closing)
            session._lock.release()
            await closing
            assert session._agent is None
            assert await client.get_receipt(message_id=message_id) == MessageErrorDAO(
                code="completing", message_id=message_id
            )
        finally:
            await client.close()
            await unauthorized_client.close()
            if session._lock.locked():
                session._lock.release()
    finally:
        await offline_client.close()
        await session.close_messaging()
