"""Queue capacity, diagnostic projection and serialized refusal closure."""

import asyncio
from pathlib import Path
import sqlite3
from typing import Literal
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
    canonical_submission_bytes,
)
from src.agents.slo_agent.messaging.queue import SessionMessageQueue
from src.agents.slo_agent.messaging.store import MessageStore
from tests.agents.slo_agent.messaging.test_queue import RegisteredAuthority
from tests.agents.slo_agent.messaging.test_queue_closure import CompletionGate, submission, wait_until
from tests.agents.slo_agent.messaging.test_store_journey import application_event


@pytest.mark.parametrize("ordering", ["revoke", "seal_first", "admit_first"])
async def test_contended_authority_and_seal(tmp_path: Path, ordering: str) -> None:
    """Admissions waiting behind an owned operation recheck authority and seal."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    authority = RegisteredAuthority(principal=principal)
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    gate = CompletionGate()
    store = await MessageStore.open(
        path=path, limits=MessagingLimitsDAO(), target=target, executor_factory=lambda: gate
    )
    queue = SessionMessageQueue(
        store=store, target=target, authorize=authority.authorize, authorize_read=lambda reader: None
    )
    tasks: list[asyncio.Task] = []
    try:
        await queue.set_lifecycle(accepting=True)
        gate.armed = True
        holder = asyncio.create_task(queue.retain_pending())
        tasks.append(holder)
        await wait_until(predicate=gate.completed.is_set)
        if ordering == "seal_first":
            tasks.append(asyncio.create_task(queue.seal()))
            await wait_until(predicate=lambda: len(queue._mutex._waiters or ()) == 1)
        request = submission(target=target)
        admission = asyncio.create_task(queue.admit(submission=request, principal=principal))
        tasks.append(admission)
        await wait_until(
            predicate=lambda: len(queue._mutex._waiters or ()) == (2 if ordering == "seal_first" else 1)
        )
        assert authority.calls == 0
        if ordering == "revoke":
            authority.allowed = False
        if ordering == "admit_first":
            tasks.append(asyncio.create_task(queue.seal()))
            await wait_until(predicate=lambda: len(queue._mutex._waiters or ()) == 2)
        gate.release.set()
        await holder
        if ordering == "admit_first":
            receipt = await admission
            assert await store.get_receipt(message_id=request.message_id, principal=principal) == receipt
        else:
            with pytest.raises(
                MessageAdmissionError, match="unauthorized" if ordering == "revoke" else "completing"
            ):
                await admission
            assert await store.read_identities() == ()
        await asyncio.gather(*[task for task in tasks if task is not admission])
        await queue.seal()
        await queue.seal()
    finally:
        gate.release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await store.close()


async def test_refusal_full_conflict_and_failed_write(tmp_path: Path) -> None:
    """Refusals do not allocate or wake; real SQLite write failure wakes with error."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(pending_inputs=1), target=target)
    authority = RegisteredAuthority(principal=principal)
    queue = SessionMessageQueue(
        store=store, target=target, authorize=authority.authorize, authorize_read=lambda reader: None
    )
    waiter = None
    try:
        await queue.set_lifecycle(accepting=True)
        waiter = asyncio.create_task(queue.wait_for_yield(after_sequence=0))
        await wait_until(predicate=lambda: bool(queue._changed._waiters))
        unsupported = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="context_note", text="note"
        )
        with pytest.raises(MessageAdmissionError, match="unsupported"):
            await queue.admit(submission=unsupported, principal=principal)
        assert await store.read_identities() == ()
        request = submission(target=target)
        receipt = await queue.admit(submission=request, principal=principal)
        assert await queue.admit(submission=request, principal=principal) == receipt
        with pytest.raises(MessageAdmissionError, match="conflict"):
            await queue.admit(submission=request.model_copy(update={"text": "changed"}), principal=principal)
        with pytest.raises(MessageAdmissionError, match="queue_full"):
            await queue.admit(submission=submission(target=target), principal=principal)
        assert len(await store.read_identities()) == 1 and not waiter.done()
        await queue.retain_pending()
        await queue.cancel_retained(message_ids=(request.message_id,))
        # SQLite trigger aborts the real insert inside its real transaction.
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TRIGGER fail_insert BEFORE INSERT ON messages BEGIN SELECT RAISE(ABORT, 'test write failure'); END"
            )
        failed = submission(target=target)
        with pytest.raises(MessageStoreError):
            await queue.admit(submission=failed, principal=principal)
        with pytest.raises(MessageStoreError):
            await asyncio.wait_for(waiter, timeout=3)
        assert await store.get_receipt(message_id=failed.message_id, principal=principal) is None
        assert len(await store.read_identities()) == 1
    finally:
        if waiter is not None:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        await store.close()


async def test_summary_states_payload_limit_and_foreign_privacy(tmp_path: Path) -> None:
    """Summary counts applying/retained input but previews one eligible owned text."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    other = MessagePrincipalDAO(principal_id="other", kind="human")
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    request = submission(target=target, text="é" * 20000)
    limit = len(canonical_submission_bytes(submission=request))
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(payload_bytes=limit), target=target)
    queue = SessionMessageQueue(
        store=store, target=target, authorize=lambda request, sender: None, authorize_read=lambda reader: None
    )
    try:
        await queue.set_lifecycle(accepting=True)
        assert (await queue.summary(principal=principal)).pending_count == 0
        await queue.admit(submission=request, principal=principal)
        oversized = submission(target=target, text=request.text + "é")
        with pytest.raises(MessageAdmissionError, match="invalid_message"):
            await queue.admit(submission=oversized, principal=principal)
        foreign = submission(target=target, text="foreign secret")
        await queue.admit(submission=foreign, principal=other)
        preview = await queue.summary(principal=principal)
        assert preview.pending_count == 2 and preview.next_local_text == request.text
        assert preview.next_local_message_id == request.message_id
        boundary = BoundaryDAO(run_id=str(uuid4()), boundary_index=0)
        claimed = await queue.take_one(boundary=boundary)
        assert claimed is not None
        summary = await queue.summary(principal=principal)
        assert summary.pending_count == 2 and summary.next_local_text is None
        await queue.retain_pending()
        summary = await queue.summary(principal=other)
        assert summary.pending_count == 2 and summary.next_local_text is None
        await store.prepare_application(
            delivery=claimed, event=application_event(delivery=claimed, generation=target.generation)
        )
        await store.mark_history_committed(message_id=request.message_id)
        await store.mark_applied(message_id=request.message_id)
        assert (await queue.summary(principal=principal)).pending_count == 1
        await queue.cancel_retained(message_ids=(foreign.message_id,))
        assert (await queue.summary(principal=principal)).pending_count == 0
    finally:
        await store.close()


@pytest.mark.parametrize("kind", ["context_note", "transcript_note"])
async def test_legitimate_notes_terminal_boundary_and_independent_capacity(
    tmp_path: Path, kind: Literal["context_note", "transcript_note"]
) -> None:
    """Both note kinds remain claimable with a full input lane and occupy applied boundaries."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(
        path=path, limits=MessagingLimitsDAO(pending_inputs=1, pending_notes=2), target=target
    )
    queue = SessionMessageQueue(
        store=store, target=target, authorize=lambda request, sender: None, authorize_read=lambda reader: None
    )
    try:
        await queue.set_lifecycle(accepting=True)
        await queue.admit(submission=submission(target=target), principal=principal)
        with pytest.raises(MessageAdmissionError, match="queue_full"):
            await queue.admit(submission=submission(target=target), principal=principal)
        for _ in range(2):
            note = MessageSubmissionDAO(message_id=str(uuid4()), target=target, kind=kind, text="note")
            await queue.admit(submission=note, principal=principal)
        assert (await store.read_queue_state()).eligible_notes == 2
        boundary = BoundaryDAO(run_id=str(uuid4()), boundary_index=0)
        claimed = await queue.take_note(boundary=boundary)
        assert claimed is not None and claimed.envelope.submission.kind == kind
        assert await queue.take_note(boundary=boundary) == claimed
        await store.prepare_application(
            delivery=claimed, event=application_event(delivery=claimed, generation=target.generation)
        )
        await store.mark_history_committed(message_id=claimed.envelope.submission.message_id)
        await store.mark_applied(message_id=claimed.envelope.submission.message_id)
        assert await queue.take_note(boundary=boundary) is None
        state = await store.read_queue_state()
        assert state.eligible_notes == state.eligible_inputs == 1
    finally:
        await store.close()
