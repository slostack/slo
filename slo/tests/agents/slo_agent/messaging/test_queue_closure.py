"""Finite queue closure using real SQLite and an injected worker completion gate."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
import sqlite3
from threading import Event
from typing import Callable, Coroutine, Literal, ParamSpec, TypeVar
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.dao import (
    BoundaryDAO,
    MessageAddressDAO,
    MessageAdmissionError,
    MessagePrincipalDAO,
    MessageStoreError,
    MessageSubmissionDAO,
    MessagingLimitsDAO,
    RecoveryTransferDAO,
)
from src.agents.slo_agent.messaging.queue import SessionMessageQueue
from src.agents.slo_agent.messaging.store import MessageStore

P = ParamSpec("P")
T = TypeVar("T")


class CompletionGate(ThreadPoolExecutor):
    """Hold one completed real worker operation before returning its result."""

    def __init__(self, *, hold_before: bool = False) -> None:
        """Gate before execution or after success; cleanup always releases the worker."""
        super().__init__(max_workers=1)
        self.armed = False
        self.hold_before = hold_before
        self.started = Event()
        self.failed = Event()
        self.completed = Event()
        self.release = Event()

    def submit(self, fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> Future[T]:
        """Execute unchanged persistence then gate only delivery of its result."""
        hold = self.armed
        self.armed = False

        def execute() -> T:
            """Gate scheduling without replacing the real operation or its failure."""
            if hold and self.hold_before:
                self.started.set()
                self.release.wait()
            try:
                result = fn(*args, **kwargs)
            except MessageStoreError:
                self.failed.set()
                raise
            if hold:
                self.completed.set()
                self.release.wait()
            return result

        return super().submit(execute)


async def wait_until(*, predicate: Callable[[], bool]) -> None:
    """Bound test coordination without imposing a writer lifetime deadline."""
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0)


def submission(*, target: MessageAddressDAO, text: str = "input") -> MessageSubmissionDAO:
    """Build a distinct ordinary input for the real admission boundary."""
    return MessageSubmissionDAO(message_id=str(uuid4()), target=target, kind="agent_input", text=text)


@pytest.mark.parametrize("fail_refresh", [False, True])
async def test_postcommit_cancel_settles_publication(tmp_path: Path, fail_refresh: bool) -> None:
    """Committed cancellation publishes eligibility or sticky failure before seal."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    gate = CompletionGate()
    store = await MessageStore.open(
        path=path, limits=MessagingLimitsDAO(), target=target, executor_factory=lambda: gate
    )
    queue = SessionMessageQueue(
        store=store, target=target, authorize=lambda request, sender: None, authorize_read=lambda reader: None
    )
    tasks: list[asyncio.Task] = []
    try:
        await queue.set_lifecycle(accepting=True)
        work = asyncio.create_task(queue.wait_for_work())
        tasks.append(work)
        await wait_until(predicate=lambda: len(queue._changed._waiters) == 1)
        request = submission(target=target)
        gate.armed = True
        admission = asyncio.create_task(queue.admit(submission=request, principal=principal))
        tasks.append(admission)
        await wait_until(predicate=gate.completed.is_set)
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT message_id FROM identity").fetchall() == [(request.message_id,)]
            if fail_refresh:
                connection.execute("UPDATE meta SET value='invalid' WHERE key='lifecycle'")
        admission.cancel()
        await asyncio.sleep(0)
        admission.cancel()
        seal = asyncio.create_task(queue.seal())
        tasks.append(seal)
        await wait_until(predicate=lambda: bool(queue._mutex._waiters))
        assert not admission.done() and not work.done() and not seal.done()
        gate.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(admission, timeout=3)
        await asyncio.wait_for(seal, timeout=3)
        if fail_refresh:
            with pytest.raises(MessageStoreError):
                await asyncio.wait_for(work, timeout=3)
            # Repair disposable bytes only to prove the queue latch, not persistent damage, refuses reuse.
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE meta SET value='accepting' WHERE key='lifecycle'")
            identity = (await store.read_identities())[0]
            transfer = RecoveryTransferDAO(
                transfer_id=str(uuid4()),
                original=request,
                original_sender=principal,
                original_digest=identity.digest,
                destination=target,
            )
            boundary = BoundaryDAO(run_id=str(uuid4()), boundary_index=0)
            operations = [
                lambda: queue.admit(submission=request, principal=principal),
                lambda: queue.take_one(boundary=boundary),
                lambda: queue.take_note(boundary=boundary),
                lambda: queue.select_boundary(boundary=boundary),
                queue.retain_pending,
                lambda: queue.cancel_retained(message_ids=(request.message_id,)),
                lambda: queue.recover(transfer=transfer, principal=principal),
                lambda: queue.set_lifecycle(accepting=True),
                lambda: queue.summary(principal=principal),
                queue.wait_for_work,
                queue.wait_for_notes,
                lambda: queue.wait_for_yield(after_sequence=0),
            ]
            for operation in operations:
                with pytest.raises(MessageStoreError):
                    await operation()
            assert await store.read_identities() == (identity,)
        else:
            await asyncio.wait_for(work, timeout=3)
            assert queue._work.is_set()
        receipt = await store.get_receipt(message_id=request.message_id, principal=principal)
        assert receipt is not None and receipt.state == "accepted"
    finally:
        gate.release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await store.close()


async def test_canceled_waiter_and_newer_urgency(tmp_path: Path) -> None:
    """Canceling one sleeping consumer leaves its sibling waiting for newer urgency."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
    queue = SessionMessageQueue(
        store=store, target=target, authorize=lambda request, sender: None, authorize_read=lambda reader: None
    )
    tasks: list[asyncio.Task] = []
    try:
        await queue.set_lifecycle(accepting=True)
        first = submission(target=target).model_copy(update={"priority": "urgent"})
        receipt = await queue.admit(submission=first, principal=principal)
        for _ in range(2):
            tasks.append(asyncio.create_task(queue.wait_for_yield(after_sequence=receipt.sequence)))
        await wait_until(predicate=lambda: len(queue._changed._waiters) == 2)
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        assert len(queue._changed._waiters) == 1 and not tasks[1].done()
        await queue.admit(submission=submission(target=target), principal=principal)
        await wait_until(predicate=lambda: len(queue._changed._waiters) == 1)
        assert not tasks[1].done()
        newer = submission(target=target).model_copy(update={"priority": "urgent"})
        await queue.admit(submission=newer, principal=principal)
        await asyncio.wait_for(tasks[1], timeout=3)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await store.close()


@pytest.mark.parametrize("read_path", ["summary", "work", "notes", "yield"])
@pytest.mark.parametrize("fail_read", [False, True])
async def test_cancelled_read_settles_before_publishing_outcome(
    tmp_path: Path, read_path: Literal["summary", "work", "notes", "yield"], fail_read: bool
) -> None:
    """Read cancellation preserves failure wakeups without poisoning healthy storage."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    gate = CompletionGate(hold_before=True)
    store = await MessageStore.open(
        path=path, limits=MessagingLimitsDAO(), target=target, executor_factory=lambda: gate
    )
    queue = SessionMessageQueue(
        store=store, target=target, authorize=lambda request, sender: None, authorize_read=lambda reader: None
    )
    tasks: list[asyncio.Task[object]] = []
    try:
        await queue.set_lifecycle(accepting=True)
        sibling = asyncio.create_task(queue.wait_for_work())
        tasks.append(sibling)
        await wait_until(predicate=lambda: len(queue._changed._waiters) == 1)
        operations: dict[str, Callable[[], Coroutine[object, object, object]]] = {
            "summary": lambda: queue.summary(principal=principal),
            "work": queue.wait_for_work,
            "notes": queue.wait_for_notes,
            "yield": lambda: queue.wait_for_yield(after_sequence=0),
        }
        gate.armed = True
        reader = asyncio.create_task(operations[read_path]())
        tasks.append(reader)
        await wait_until(predicate=gate.started.is_set)
        reader.cancel()
        await asyncio.sleep(0)
        reader.cancel()
        await asyncio.sleep(0)
        assert queue._mutex.locked()
        assert not reader.done() and not sibling.done()
        if fail_read:
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE meta SET value='invalid' WHERE key='lifecycle'")
        gate.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(reader, timeout=3)
        assert gate.failed.is_set() == fail_read
        assert gate.completed.is_set() != fail_read
        if fail_read:
            # Repair before any further queue read can rediscover the failure and
            # accidentally rescue the sleeping sibling.
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE meta SET value='accepting' WHERE key='lifecycle'")
            with pytest.raises(MessageStoreError):
                await asyncio.wait_for(sibling, timeout=3)
            assert (await store.read_queue_state()).eligible_inputs == 0
            with pytest.raises(MessageStoreError):
                await queue.summary(principal=principal)
            with pytest.raises(MessageStoreError):
                await queue.admit(submission=submission(target=target), principal=principal)
            assert await store.read_identities() == ()
        else:
            assert (await queue.summary(principal=principal)).pending_count == 0
            assert not sibling.done()
            request = submission(target=target)
            await queue.admit(submission=request, principal=principal)
            await asyncio.wait_for(sibling, timeout=3)
            receipt = await store.get_receipt(message_id=request.message_id, principal=principal)
            assert receipt is not None and receipt.state == "accepted"
    finally:
        gate.release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await store.close()
