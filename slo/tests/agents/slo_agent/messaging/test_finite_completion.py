"""Finite cutoff and settlement with real SQLite/history and controlled providers (DC07)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.messaging.dao import (
    BoundaryDAO,
    MessageAddressDAO,
    MessageAdmissionError,
    MessageErrorDAO,
    MessageReceiptDAO,
    MessagePrincipalDAO,
    MessageSubmissionDAO,
    MessagingLimitsDAO,
)
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.messaging.queue import SessionMessageQueue
from src.agents.slo_agent.messaging.store import MessageStore
from tests.agents.slo_agent.messaging.test_queue_closure import CompletionGate, wait_until, submission
from tests.agents.slo_agent.messaging.test_delivery import RecordingModel
from tests.tui.test_durable_composer import _build_factory_session


@pytest.mark.parametrize(argnames="lifecycle_accepting", argvalues=[False, True])
async def test_applying_count_prevents_cutoff(tmp_path: Path, lifecycle_accepting: bool) -> None:
    """Unowned applying input remains visible even when durable admission is closed."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(path=path, target=target, limits=MessagingLimitsDAO())
    queue = SessionMessageQueue(
        store=store, target=target, authorize=lambda request, sender: None, authorize_read=lambda reader: None
    )
    try:
        await queue.set_lifecycle(accepting=True)
        await queue.admit(submission=submission(target=target), principal=principal)
        await queue.take_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0))
        await queue.set_lifecycle(accepting=lifecycle_accepting)
        assert (await store.read_queue_state()).applying_records == 1
        assert (await queue.seal_if_quiescent(may_seal=lambda: True)).outcome == "applying"
    finally:
        await store.close()


async def test_admission_before_cutoff_is_pending(tmp_path: Path) -> None:
    """A real admission holding serialization commits before the quiescence check."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    gate = CompletionGate()
    store = await MessageStore.open(
        path=path, target=target, limits=MessagingLimitsDAO(), executor_factory=lambda: gate
    )
    queue = SessionMessageQueue(
        store=store, target=target, authorize=lambda request, sender: None, authorize_read=lambda reader: None
    )
    tasks: list[asyncio.Task] = []
    try:
        await queue.set_lifecycle(accepting=True)
        gate.armed = True
        admission = asyncio.create_task(
            queue.admit(submission=submission(target=target), principal=principal)
        )
        tasks.append(admission)
        await wait_until(predicate=gate.completed.is_set)
        cutoff = asyncio.create_task(queue.seal_if_quiescent(may_seal=lambda: True))
        tasks.append(cutoff)
        await wait_until(predicate=lambda: bool(queue._mutex._waiters))
        gate.release.set()
        await admission
        assert (await cutoff).outcome == "pending"
        assert len(await store.read_identities()) == 1
    finally:
        gate.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await store.close()


async def test_cutoff_refuses_unaccepted_admission(tmp_path: Path) -> None:
    """An admission queued behind the cutoff receives completing without a new row."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    gate = CompletionGate()
    store = await MessageStore.open(
        path=path, target=target, limits=MessagingLimitsDAO(), executor_factory=lambda: gate
    )
    queue = SessionMessageQueue(
        store=store, target=target, authorize=lambda request, sender: None, authorize_read=lambda reader: None
    )
    tasks: list[asyncio.Task] = []
    try:
        await queue.set_lifecycle(accepting=True)
        gate.armed = True
        cutoff = asyncio.create_task(queue.seal_if_quiescent(may_seal=lambda: True))
        tasks.append(cutoff)
        await wait_until(predicate=gate.completed.is_set)
        admission = asyncio.create_task(
            queue.admit(submission=submission(target=target), principal=principal)
        )
        tasks.append(admission)
        await wait_until(predicate=lambda: bool(queue._mutex._waiters))
        gate.release.set()
        assert (await cutoff).outcome == "sealed"
        with pytest.raises(MessageAdmissionError) as refused:
            await admission
        assert refused.value.error.code == "completing"
        assert await store.read_identities() == ()
        assert (await queue.seal_if_quiescent(may_seal=lambda: True)).outcome == "stopping"
    finally:
        gate.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await store.close()


async def test_finish_waits_for_actual_run_then_seals(tmp_path: Path) -> None:
    """Finite completion joins the sole real run, retains its terminal and exits consumers."""
    model = RecordingModel(responses=[AIMessage(content="settled answer")])
    session = _build_factory_session(tmp_path=tmp_path, model=model, stop_after_first=False)
    await session.start_messaging()
    owner = session.messaging_owner_principal
    target = session.messaging_target
    try:
        await session.admit_message(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=target, kind="agent_input", text="one"
            ),
            principal=owner,
        )
        await asyncio.wait_for(model.entered.wait(), timeout=3)
        finish = asyncio.create_task(session.finish_finite_messaging())
        await asyncio.sleep(0)
        assert not finish.done()
        model.release.set()
        terminal = await asyncio.wait_for(finish, timeout=3)
        assert (terminal.kind, terminal.content) == ("run_completed", "settled answer")
        assert session._messaging_scheduler is not None and session._messaging_note_task is not None
        assert session._messaging_scheduler.done() and session._messaging_note_task.done()
        assert len(model.requests) == 1
        assert (await session.finish_finite_messaging()) == terminal
        refused = await session.admit_message(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=target, kind="agent_input", text="late"
            ),
            principal=owner,
        )
        assert isinstance(refused, MessageErrorDAO)
        assert refused.code == "completing"
        assert session._history_store is not None
        events = await session._history_store.load_events(session_id=session.session_id)
        assert [event.payload.content for event in events if event.kind == "run_completed"] == [
            "settled answer"
        ]
    finally:
        model.release.set()
        await session.close_messaging()


@pytest.mark.parametrize(argnames="after_seal", argvalues=[False, True])
async def test_cancellation_joins_finite_task_without_reopening(tmp_path: Path, after_seal: bool) -> None:
    """Three cancellations of a finish waiter cannot cancel its owned settlement."""
    model = RecordingModel(responses=[AIMessage(content="done")])
    session = _build_factory_session(tmp_path=tmp_path, model=model, stop_after_first=False)
    await session.start_messaging()
    target = session.messaging_target
    owner = session.messaging_owner_principal
    gate = asyncio.Event()

    async def tracked_receipt() -> MessageReceiptDAO | MessageErrorDAO:
        """Hold a registered call outside locks until the test releases its callback."""
        await gate.wait()
        return await session.get_message_receipt(message_id=str(uuid4()), target=target, principal=owner)

    try:
        await session.admit_message(submission=submission(target=target), principal=owner)
        await asyncio.wait_for(model.entered.wait(), timeout=3)
        if after_seal:
            session.track_messaging_call(operation=tracked_receipt())
            model.release.set()
        waiter = asyncio.create_task(session.finish_finite_messaging())
        if after_seal:
            await wait_until(predicate=lambda: session._finite_stopping)
        else:
            await asyncio.sleep(0)
        for _ in range(3):
            waiter.cancel()
            await asyncio.sleep(0)
            assert not waiter.done()
        model.release.set()
        gate.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(waiter, timeout=3)
        assert (await session.finish_finite_messaging()).kind == "run_completed"
        refused = await session.admit_message(submission=submission(target=target), principal=owner)
        assert isinstance(refused, MessageErrorDAO)
        assert refused.code == "completing"
    finally:
        gate.set()
        model.release.set()
        await session.close_messaging()


async def test_concurrent_close_joins_finite_stop_path(tmp_path: Path) -> None:
    """Close and finish settle without circular joins and release the real store lease."""
    model = RecordingModel(responses=[AIMessage(content="done")])
    session = _build_factory_session(tmp_path=tmp_path, model=model, stop_after_first=False)
    await session.start_messaging()
    try:
        await session.admit_message(
            submission=submission(target=session.messaging_target),
            principal=session.messaging_owner_principal,
        )
        await asyncio.wait_for(model.entered.wait(), timeout=3)
        finish = asyncio.create_task(session.finish_finite_messaging())
        close = asyncio.create_task(session.close_messaging())
        await wait_until(predicate=lambda: session._messaging_closing)
        model.release.set()
        await asyncio.wait_for(asyncio.gather(finish, close), timeout=3)
        assert session._messaging_scheduler is not None and session._messaging_note_task is not None
        assert session._messaging_scheduler.done() and session._messaging_note_task.done()
        assert not session.is_messaging_ready
        from src.agents.slo_agent.messaging.ownership import SessionExecutionOwnership

        ownership = await SessionExecutionOwnership.acquire(
            root=tmp_path / "history", session_id=session.session_id
        )
        await ownership.release()
    finally:
        model.release.set()
        await session.close_messaging()


async def test_hard_stop_cancels_scheduler_and_settles_observer(tmp_path: Path) -> None:
    """A never-released provider is stopped by its real owner, not observer detachment."""
    model = RecordingModel(responses=[AIMessage(content="unreachable")])
    session = _build_factory_session(tmp_path=tmp_path, model=model, stop_after_first=False)
    await session.start_messaging()

    async def observe() -> list[AgentStreamEventDAO]:
        """Publish once and retain the assigned terminal for assertion."""
        return [event async for event in session.invoke(text="one")]

    observer = asyncio.create_task(observe())
    try:
        await asyncio.wait_for(model.entered.wait(), timeout=3)
        pending = await session.admit_message(
            submission=submission(target=session.messaging_target, text="pending"),
            principal=session.messaging_owner_principal,
        )
        await asyncio.wait_for(session.stop_messaging_execution(), timeout=3)
        events = await asyncio.wait_for(observer, timeout=3)
        assert events[-1].kind == "run_aborted"
        assert session._messaging_scheduler is not None and session._messaging_note_task is not None
        assert session._messaging_scheduler.done() and session._messaging_scheduler.cancelling() > 0
        assert session._messaging_note_task.done()
        assert not model.release.is_set()
        assert (await session.finish_finite_messaging()).kind == "run_aborted"
        assert session._message_store is not None
        identities = await session._message_store.read_identities()
        assert [identity.receipt.state for identity in identities] == ["applied", "accepted"]
        assert identities[-1].receipt.message_id == pending.message_id
        assert identities[-1].receipt.retained_for_recovery
    finally:
        await session.stop_messaging_execution()
        await asyncio.gather(observer, return_exceptions=True)
        await session.close_messaging()


async def test_terminal_between_check_and_wait_cannot_hang(tmp_path: Path) -> None:
    """Admission changes the captured revision before a pending cutoff releases execution."""
    model = RecordingModel(responses=[AIMessage(content="done")])
    model.release.set()
    session = _build_factory_session(tmp_path=tmp_path, model=model, stop_after_first=False)
    await session.start_messaging()
    try:
        async with session._lock:
            finish = asyncio.create_task(session.finish_finite_messaging())
            await wait_until(predicate=lambda: bool(session._lock._waiters))
            await session.admit_message(
                submission=submission(target=session.messaging_target),
                principal=session.messaging_owner_principal,
            )
        assert (await asyncio.wait_for(finish, timeout=3)).content == "done"
        assert len(model.requests) == 1
    finally:
        await session.close_messaging()


async def test_pending_notes_retain_and_consumers_exit(tmp_path: Path) -> None:
    """A note accepted before cutoff stays retained without invoking a provider."""
    model = RecordingModel(responses=[AIMessage(content="never called")])
    session = _build_factory_session(tmp_path=tmp_path, model=model, stop_after_first=False)
    await session.start_messaging()
    try:
        async with session._lock:
            finish = asyncio.create_task(session.finish_finite_messaging())
            await wait_until(predicate=lambda: bool(session._lock._waiters))
            note = MessageSubmissionDAO(
                message_id=str(uuid4()),
                target=session.messaging_target,
                kind="context_note",
                text="retained note",
            )
            await session.admit_message(submission=note, principal=session.messaging_owner_principal)
        assert (await asyncio.wait_for(finish, timeout=3)).kind == "run_failed"  # No run settled.
        assert model.requests == []
        assert session._message_store is not None
        identities = await session._message_store.read_identities()
        assert len(identities) == 1 and identities[0].receipt.retained_for_recovery
        consumers = (session._messaging_scheduler, session._messaging_note_task)
        assert all(task is not None and task.done() for task in consumers)
        await asyncio.sleep(0)
        assert consumers == (session._messaging_scheduler, session._messaging_note_task)
    finally:
        await session.close_messaging()
    import sqlite3

    path = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state, retained FROM messages").fetchall() == [("accepted", 1)]


async def test_orphan_applying_record_is_recovery_required(tmp_path: Path) -> None:
    """A claimed application with no execution owner cannot be reported as finite success."""
    model = RecordingModel(responses=[AIMessage(content="never called")])
    session = _build_factory_session(tmp_path=tmp_path, model=model, stop_after_first=False)
    await session.start_messaging()
    try:
        async with session._lock:
            await session.admit_message(
                submission=submission(target=session.messaging_target),
                principal=session.messaging_owner_principal,
            )
            # Existing queue's real claim seam simulates a crashed claimant without
            # fabricating model/session flags or replacing durable storage.
            assert session._message_queue is not None
            await session._message_queue.take_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0))
        terminal = await asyncio.wait_for(session.finish_finite_messaging(), timeout=3)
        assert terminal.kind == "run_failed" and "recovery" in (terminal.content or "").lower()
        assert isinstance(session._messaging_failure, MessageAdmissionError)
        assert session._messaging_failure.error.code == "recovery_required"
        assert model.requests == []
        assert session._message_store is not None
        assert (await session._message_store.read_queue_state()).applying_records == 1
    finally:
        await session.close_messaging()


async def test_hard_stop_reconciles_prepared_application(tmp_path: Path) -> None:
    """Host stop repairs a real prepared journal before acknowledgement and lease release."""
    from tests.agents.slo_agent.messaging.test_store_journey import application_event

    model = RecordingModel(responses=[AIMessage(content="never called")])
    session = _build_factory_session(tmp_path=tmp_path, model=model, stop_after_first=False)
    await session.start_messaging()
    try:
        assert session._history_store is not None
        await session._history_store.ensure_session(
            session_id=session.session_id, workdir=tmp_path, model_name="gpt-5.4"
        )
        async with session._lock:
            target = session.messaging_target
            await session.admit_message(
                submission=submission(target=target), principal=session.messaging_owner_principal
            )
            assert session._message_queue is not None and session._message_store is not None
            delivery = await session._message_queue.take_one(
                boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0)
            )
            assert delivery is not None
            event = application_event(delivery=delivery, generation=target.generation)
            await session._message_store.prepare_application(delivery=delivery, event=event)
            stop = asyncio.create_task(session.stop_messaging_execution())
            await wait_until(predicate=lambda: session._finite_stop_requested)
        await asyncio.wait_for(stop, timeout=3)
        assert model.requests == []
        identities = await session._message_store.read_identities()
        assert identities[0].receipt.state == "applied"
        assert session._history_store is not None
        events = await session._history_store.load_events(session_id=session.session_id)
        assert len([saved for saved in events if saved.event_id == event.event_id]) == 1
    finally:
        await session.close_messaging()


async def test_failed_run_retains_pending_and_finite_returns_failure(tmp_path: Path) -> None:
    """A settled model failure never permits the scheduler to start queued instructions."""
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    model = RecordingModel(responses=[])
    session = _build_factory_session(tmp_path=tmp_path, model=model, stop_after_first=False)
    await session.start_messaging()
    target = session.messaging_target
    principal = session.messaging_owner_principal

    async def queue_after_failure(event: AgentStreamEventDAO) -> None:
        """Commit the next input at the public terminal boundary before scheduler settlement."""
        if event.kind == "run_failed":
            await session.admit_message(
                submission=submission(target=target, text="must not run"), principal=principal
            )

    session.subscribe(handler=queue_after_failure)
    try:
        await session.admit_message(submission=submission(target=target), principal=principal)
        await asyncio.wait_for(model.entered.wait(), timeout=3)
        model.release.set()
        assert (await asyncio.wait_for(session.finish_finite_messaging(), timeout=3)).kind == "run_failed"
        from langchain_core.messages import HumanMessage

        assert all(
            message.content != "must not run"
            for messages in model.requests
            for message in messages
            if isinstance(message, HumanMessage)
        )  # Existing recovery attempts may retry the failed initial input, never the queued input.
        assert session._message_store is not None
        identities = await session._message_store.read_identities()
        assert [identity.receipt.state for identity in identities] == ["applied", "accepted"]
        assert identities[-1].receipt.retained_for_recovery
    finally:
        model.release.set()
        await session.close_messaging()


@pytest.mark.parametrize(argnames="admission_first", argvalues=[False, True])
async def test_registered_admission_at_session_cutoff(tmp_path: Path, admission_first: bool) -> None:
    """Tracked calls on either side of the real mutex drain or refuse without deadlock."""
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
    from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
    from src.agents.slo_agent.messaging.dao import MessageReceiptDAO
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from tests.agents.slo_agent.messaging.test_delivery import RealAgentFactory

    gate = CompletionGate()
    model = RecordingModel(responses=[AIMessage(content="drained")])
    model.release.set()
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id = str(uuid4())
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, session_id=session_id, history_root=root, model_name="gpt-5.4"
        ),
        history_store=FilesystemSessionHistoryStore(root=root),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
        messaging_executor_factory=lambda: gate,
    )
    await session.start_messaging()
    client = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    tasks: list[asyncio.Task] = []
    try:
        assert session._message_queue is not None
        queue = session._message_queue
        await wait_until(predicate=lambda: len(queue._changed._waiters) == 2)
        if admission_first:
            async with session._lock:
                gate.armed = True
                admission = asyncio.create_task(
                    client.submit(submission=submission(target=session.messaging_target))
                )
                tasks.append(admission)
                await wait_until(predicate=gate.completed.is_set)
                finish = asyncio.create_task(session.finish_finite_messaging())
                tasks.append(finish)
                await wait_until(predicate=lambda: bool(session._lock._waiters))
                gate.release.set()
                assert isinstance(await admission, MessageReceiptDAO)
        else:
            gate.armed = True
            finish = asyncio.create_task(session.finish_finite_messaging())
            tasks.append(finish)
            await wait_until(predicate=gate.completed.is_set)
            admission = asyncio.create_task(
                client.submit(submission=submission(target=session.messaging_target))
            )
            tasks.append(admission)
            await wait_until(predicate=lambda: bool(queue._mutex._waiters))
            assert session._messaging_calls
            gate.release.set()
            refused = await asyncio.wait_for(admission, timeout=3)
            assert isinstance(refused, MessageErrorDAO) and refused.code == "completing"
        terminal = await asyncio.wait_for(finish, timeout=3)
        assert terminal.kind == ("run_completed" if admission_first else "run_failed")
        assert len(model.requests) == int(admission_first)
        assert session._message_store is not None
        assert len(await session._message_store.read_identities()) == int(admission_first)
        assert not session._messaging_calls
    finally:
        gate.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client.close()
        await session.close_messaging()


async def test_stop_during_cutoff_read_wins_before_seal(tmp_path: Path) -> None:
    """Stop state changed during the real store read defeats the synchronous seal check."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    gate = CompletionGate()
    store = await MessageStore.open(
        path=path, target=target, limits=MessagingLimitsDAO(), executor_factory=lambda: gate
    )
    queue = SessionMessageQueue(
        store=store, target=target, authorize=lambda request, sender: None, authorize_read=lambda reader: None
    )
    may_seal = True
    task = None
    try:
        await queue.set_lifecycle(accepting=True)
        gate.armed = True
        task = asyncio.create_task(queue.seal_if_quiescent(may_seal=lambda: may_seal))
        await wait_until(predicate=gate.completed.is_set)
        may_seal = False
        gate.release.set()
        assert (await task).outcome == "stopping"
        assert not queue._sealed
        assert await store.read_identities() == ()
    finally:
        gate.release.set()
        if task is not None:
            await task
        await store.close()


async def test_repeated_cancelled_stop_joins_owned_persistence(tmp_path: Path) -> None:
    """Concurrent hard stops join one owned task through three waiter cancellations."""
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from tests.agents.slo_agent.messaging.test_delivery import RealAgentFactory

    gate = CompletionGate()
    model = RecordingModel(responses=[AIMessage(content="never")])
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id = str(uuid4())
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=FilesystemSessionHistoryStore(root=root),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
        messaging_executor_factory=lambda: gate,
    )
    await session.start_messaging()
    try:
        assert session._message_queue is not None
        queue = session._message_queue
        await wait_until(predicate=lambda: len(queue._changed._waiters) == 2)
        gate.armed = True
        first = asyncio.create_task(session.stop_messaging_execution())
        await wait_until(predicate=gate.completed.is_set)
        second = asyncio.create_task(session.stop_messaging_execution())
        owned = session._messaging_stop_task
        for _ in range(3):
            first.cancel()
            await asyncio.sleep(0)
            assert not first.done() and not second.done()
        gate.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(first, timeout=3)
        await asyncio.wait_for(second, timeout=3)
        assert session._messaging_stop_task is owned
        assert owned is not None and owned.done()
        assert model.requests == []
    finally:
        gate.release.set()
        await session.close_messaging()
