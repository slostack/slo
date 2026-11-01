"""Finite queue selection and eligibility journeys over real SQLite."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.dao import (
    BoundaryDAO,
    MessageAddressDAO,
    MessageAdmissionError,
    MessagePrincipalDAO,
    MessageSubmissionDAO,
    MessagingLimitsDAO,
    RecoveryTransferDAO,
    MessageStoreError,
)
from src.agents.slo_agent.messaging.queue import SessionMessageQueue
from src.agents.slo_agent.messaging.store import MessageStore


async def test_combined_selection_bounds_notes_and_preserves_urgency(tmp_path: Path) -> None:
    """A full note lane cannot consume the independent instruction slot."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(
        path=path, limits=MessagingLimitsDAO(pending_notes=2, pending_inputs=1), target=target
    )
    queue = SessionMessageQueue(
        store=store,
        target=target,
        authorize=lambda submission, sender: None,
        authorize_read=lambda reader: None,
    )
    try:
        await store.set_lifecycle(accepting=True)
        notes = [
            MessageSubmissionDAO(message_id=str(uuid4()), target=target, kind="context_note", text="note")
            for _ in range(3)
        ]
        for note in notes[:2]:
            await queue.admit(submission=note, principal=principal)
        with pytest.raises(MessageAdmissionError, match="queue_full"):
            await queue.admit(submission=notes[2], principal=principal)
        instruction = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="urgent", priority="urgent"
        )
        receipt = await queue.admit(submission=instruction, principal=principal)
        boundary = BoundaryDAO(run_id=str(uuid4()), boundary_index=0)
        claims = await queue.select_boundary(boundary=boundary)
        assert claims.boundary == boundary
        assert claims.urgent_high_water == receipt.sequence
        assert claims.note is not None and claims.note.envelope.submission == notes[0]
        assert claims.instruction is not None and claims.instruction.envelope.submission == instruction
        state = await store.read_queue_state()
        assert state.eligible_inputs == 0 and state.eligible_notes == 1
        repeated = await queue.select_boundary(boundary=boundary)
        assert repeated.note == claims.note and repeated.instruction == claims.instruction
        assert (await store.read_queue_state()).eligible_notes == 1
    finally:
        await store.close()


async def test_live_retention_recovery_and_lifecycle_publish_eligibility(tmp_path: Path) -> None:
    """Recovery wakes an existing waiter; durable seal removes claim eligibility."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
    queue = SessionMessageQueue(
        store=store,
        target=target,
        authorize=lambda submission, sender: None,
        authorize_read=lambda reader: None,
    )
    waiter = None
    try:
        await queue.set_lifecycle(accepting=True)
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="retained"
        )
        await queue.admit(submission=submission, principal=principal)
        await queue.retain_pending()
        summary = await queue.summary(principal=principal)
        assert summary.pending_count == 1 and summary.next_local_text is None
        waiter = asyncio.create_task(queue.wait_for_work())
        async with asyncio.timeout(2):
            while not queue._changed._waiters:
                await asyncio.sleep(0)
        identity = (await store.read_identities())[0]
        transfer = RecoveryTransferDAO(
            transfer_id=str(uuid4()),
            original=submission,
            original_sender=principal,
            original_digest=identity.digest,
            destination=target,
        )
        outcome = await queue.recover(transfer=transfer, principal=principal)
        assert outcome.receipt.message_id == submission.message_id
        await asyncio.wait_for(waiter, timeout=2)
        await queue.set_lifecycle(accepting=False)
        assert (await store.read_queue_state()).eligible_inputs == 0
        await queue.set_lifecycle(accepting=True)
        assert (await store.read_queue_state()).eligible_inputs == 1
        await queue.retain_pending()
        await queue.cancel_retained(message_ids=(submission.message_id,))
        assert (await queue.summary(principal=principal)).pending_count == 0
    finally:
        if waiter is not None:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        await store.close()


async def test_mismatched_stored_note_kind_fails_integrity(tmp_path: Path) -> None:
    """A corrupted kind mirror fails closed before eligibility is queried."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
    try:
        await store.set_lifecycle(accepting=True)
        await store.admit(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=target, kind="context_note", text="future lane"
            ),
            principal=principal,
        )
        # Corrupt only the kind mirror in disposable storage; this is not a valid notice.
        import sqlite3

        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE messages SET kind = 'ui_notice'")
        with pytest.raises(MessageStoreError):
            await store.read_queue_state()
    finally:
        await store.close()
