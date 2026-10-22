"""Public store cancellation regressions using real SQLite and dedicated workers."""

from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.dao import (
    MessageAddressDAO,
    MessagePrincipalDAO,
    MessageSubmissionDAO,
    MessagingLimitsDAO,
)
from src.agents.slo_agent.messaging.store import MessageStore


def _target() -> MessageAddressDAO:
    """Build the exact session incarnation for a disposable database."""
    return MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))


async def _turns() -> None:
    """Advance bounded event-loop turns without waiting for the worker gate."""
    for _ in range(10):
        await asyncio.sleep(0)


class TestStoreEvidenceRepairs:
    async def test_claim_identity_is_deterministic_for_original_message(self) -> None:
        """Claim/event identity is replayable across restart, not a random pop token."""
        from uuid import UUID, uuid5

        target = _target()
        store = await MessageStore.open(path=None, limits=MessagingLimitsDAO(), target=target)
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="stable event"
        )
        from src.agents.slo_agent.messaging.dao import BoundaryDAO

        try:
            await store.set_lifecycle(accepting=True)
            await store.admit(
                submission=submission, principal=MessagePrincipalDAO(principal_id="owner", kind="human")
            )
            delivery = await store.claim_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0))
            assert delivery is not None
            assert delivery.history_event_id == str(
                uuid5(namespace=UUID(target.session_id), name="message:" + submission.message_id)
            )
        finally:
            await store.close()

    async def test_repeated_applied_acknowledgement_preserves_original_receipt_after_pruning(self) -> None:
        """Repeated acknowledgement cannot rewrite application time or require a pruned body."""
        from datetime import timedelta
        from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
        from src.agents.slo_agent.messaging.dao import BoundaryDAO, utcnow

        target = _target()
        store = await MessageStore.open(path=None, limits=MessagingLimitsDAO(), target=target)
        principal = MessagePrincipalDAO(principal_id="owner", kind="human")
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="once"
        )
        try:
            await store.set_lifecycle(accepting=True)
            await store.admit(submission=submission, principal=principal)
            delivery = await store.claim_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0))
            assert delivery is not None
            from tests.agents.slo_agent.messaging.test_store_journey import application_event

            event = application_event(delivery=delivery, generation=target.generation)
            await store.prepare_application(delivery=delivery, event=event)
            await store.mark_history_committed(message_id=submission.message_id)
            first = await store.mark_applied(message_id=submission.message_id)
            assert await store.mark_applied(message_id=submission.message_id) == first
            await store.maintain(now=utcnow() + timedelta(days=8))
            assert await store.mark_applied(message_id=submission.message_id) == first
            assert await store.admit(submission=submission, principal=principal) == first
        finally:
            await store.close()

    async def test_schema_creation_rolls_back_all_new_tables_on_collision(self, tmp_path: Path) -> None:
        """DDL and version are one atomic transaction even on a mid-script failure."""
        from src.agents.slo_agent.messaging.dao import MessageStoreError

        target = _target()
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        path.parent.mkdir()
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE messages(sentinel TEXT)")
        connection.commit()
        connection.close()
        with pytest.raises(MessageStoreError):
            await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        connection = sqlite3.connect(path)
        try:
            assert connection.execute("PRAGMA user_version").fetchone() == (0,)
            assert connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall() == [("messages",)]
        finally:
            connection.close()


class TestStoreWorkerJoins:
    async def test_cancelled_admission_joins_real_locked_transaction_before_return(
        self, tmp_path: Path
    ) -> None:
        """An uncertain caller cannot release its outer barrier before its writer settles."""
        target = _target()
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        await store.set_lifecycle(accepting=True)
        blocker = sqlite3.connect(path)
        blocker.execute("BEGIN IMMEDIATE")
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="joined"
        )
        principal = MessagePrincipalDAO(principal_id="owner", kind="human")
        task = asyncio.create_task(store.admit(submission=submission, principal=principal))
        try:
            await _turns()
            task.cancel()
            await _turns()
            task.cancel()
            await _turns()
            assert not task.done()
            blocker.rollback()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
            receipt = await store.get_receipt(message_id=submission.message_id, principal=principal)
            assert receipt is not None and receipt.state == "accepted"
        finally:
            blocker.rollback()
            blocker.close()
            await asyncio.gather(task, return_exceptions=True)
            await store.close()

    async def test_cancelled_startup_joins_then_closes_connection_and_worker(self, tmp_path: Path) -> None:
        """The open waiter owns any connection created after its cancellation."""
        target = _target()
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        worker = ThreadPoolExecutor(max_workers=1)
        gate = Event()
        blocker = worker.submit(gate.wait, timeout=10)
        task = asyncio.create_task(
            MessageStore.open(
                path=path, limits=MessagingLimitsDAO(), target=target, executor_factory=lambda: worker
            )
        )
        try:
            await _turns()
            task.cancel()
            await _turns()
            task.cancel()
            await _turns()
            assert not task.done()
            gate.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
            with pytest.raises(RuntimeError):
                worker.submit(lambda: None)
            reopened = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
            await reopened.close()
        finally:
            gate.set()
            blocker.result(timeout=5)
            results = await asyncio.gather(task, return_exceptions=True)
            for result in results:
                if isinstance(result, MessageStore):
                    await result.close()
            worker.shutdown(wait=True)

    async def test_concurrent_close_waiters_join_even_when_first_is_cancelled_twice(self) -> None:
        """Closed means joined, not merely that the first closer set a boolean."""
        worker = ThreadPoolExecutor(max_workers=1)
        store = await MessageStore.open(
            path=None, limits=MessagingLimitsDAO(), target=_target(), executor_factory=lambda: worker
        )
        gate = Event()
        blocker = worker.submit(gate.wait, timeout=10)
        first = asyncio.create_task(store.close())
        second = asyncio.create_task(store.close())
        try:
            await _turns()
            first.cancel()
            await _turns()
            first.cancel()
            await _turns()
            assert not first.done() and not second.done()
            gate.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(first), timeout=5)
            await asyncio.wait_for(second, timeout=5)
            await store.close()
            with pytest.raises(RuntimeError):
                worker.submit(lambda: None)
        finally:
            gate.set()
            blocker.result(timeout=5)
            await asyncio.gather(first, second, return_exceptions=True)
            worker.shutdown(wait=True)
