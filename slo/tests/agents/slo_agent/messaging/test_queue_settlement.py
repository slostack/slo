"""Cancellation journeys retain the queue barrier across real SQLite contention."""

import asyncio
import sqlite3
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
)
from src.agents.slo_agent.messaging.queue import SessionMessageQueue
from src.agents.slo_agent.messaging.store import MessageStore


@pytest.mark.parametrize(
    "mismatch,expected", [("session_id", "invalid_message"), ("generation", "stale_generation")]
)
async def test_target_refusal_has_correct_code(tmp_path: Path, mismatch: str, expected: str) -> None:
    """Logical route and incarnation mismatches do not allocate an identity."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
    try:
        await store.set_lifecycle(accepting=True)
        queue = SessionMessageQueue(
            store=store,
            target=target,
            authorize=lambda submission, sender: None,
            authorize_read=lambda reader: None,
        )
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=target.model_copy(update={mismatch: str(uuid4())}),
            kind="agent_input",
            text="wrong route",
        )
        with pytest.raises(MessageAdmissionError, match=expected):
            await queue.admit(submission=submission, principal=principal)
        assert await store.read_identities() == ()
    finally:
        await store.close()


async def test_note_lane_claims_without_executable_work(tmp_path: Path) -> None:
    """One note is claimable without creating input or urgency eligibility."""
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
    try:
        await store.set_lifecycle(accepting=True)
        note = MessageSubmissionDAO(message_id=str(uuid4()), target=target, kind="context_note", text="note")
        await queue.admit(submission=note, principal=principal)
        await asyncio.wait_for(queue.wait_for_notes(), timeout=2)
        boundary = BoundaryDAO(run_id=str(uuid4()), boundary_index=0)
        delivery = await queue.take_note(boundary=boundary)
        assert delivery is not None and delivery.envelope.submission == note
        assert await queue.take_note(boundary=boundary) == delivery
        state = await store.read_queue_state()
        assert state.eligible_inputs == state.urgent_high_water == state.eligible_notes == 0
    finally:
        await store.close()


async def test_late_waits_after_seal_do_not_read_closed_store(tmp_path: Path) -> None:
    """Admission seal is sufficient to release new waits after storage teardown."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
    queue = SessionMessageQueue(
        store=store,
        target=target,
        authorize=lambda submission, sender: None,
        authorize_read=lambda reader: None,
    )
    try:
        await queue.seal()
        await queue.seal()
        await store.close()
        await asyncio.wait_for(queue.wait_for_work(), timeout=2)
        await asyncio.wait_for(queue.wait_for_yield(after_sequence=0), timeout=2)
    finally:
        await store.close()


async def test_summary_requires_bound_read_authority(tmp_path: Path) -> None:
    """A registered reader sees its text after seal, never another principal's text."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    other = MessagePrincipalDAO(principal_id="other", kind="human")
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
    allowed = True

    def authorize_read(reader: MessagePrincipalDAO) -> None:
        """Enforce injected registration independently from admission permission."""
        if not allowed or reader != principal:
            from src.agents.slo_agent.messaging.dao import MessageErrorDAO

            raise MessageAdmissionError(error=MessageErrorDAO(code="unauthorized"))

    try:
        await store.set_lifecycle(accepting=True)
        queue = SessionMessageQueue(
            store=store,
            target=target,
            authorize=lambda submission, sender: None,
            authorize_read=authorize_read,
        )
        foreign = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="foreign secret"
        )
        await queue.admit(submission=foreign, principal=other)
        summary = await queue.summary(principal=principal)
        assert summary.pending_count == 1 and summary.next_local_text is None
        own = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="own text"
        )
        await queue.admit(submission=own, principal=principal)
        await queue.seal()
        summary = await queue.summary(principal=principal)
        assert summary.pending_count == 2 and summary.next_local_text == "own text"
        allowed = False
        with pytest.raises(MessageAdmissionError, match="unauthorized"):
            await queue.summary(principal=principal)
    finally:
        await store.close()


async def test_cancelled_admission_publishes_before_seal(tmp_path: Path) -> None:
    """Repeated caller cancellation cannot release serialization before publication."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
    authorized = asyncio.Event()

    def authorize(submission: MessageSubmissionDAO, sender: MessagePrincipalDAO) -> None:
        """Record the serialized authority boundary without replacing storage."""
        assert sender == principal
        authorized.set()

    queue = SessionMessageQueue(
        store=store, target=target, authorize=authorize, authorize_read=lambda reader: None
    )
    tasks: list[asyncio.Task] = []
    blocker = sqlite3.connect(path)
    try:
        await store.set_lifecycle(accepting=True)
        work = asyncio.create_task(queue.wait_for_work())
        tasks.append(work)
        # Observation only: prove Condition.wait was entered, not merely task scheduling.
        async with asyncio.timeout(2):
            while not queue._changed._waiters:
                await asyncio.sleep(0)
        blocker.execute("BEGIN IMMEDIATE")
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="held"
        )
        admission = asyncio.create_task(queue.admit(submission=submission, principal=principal))
        tasks.append(admission)
        await asyncio.wait_for(authorized.wait(), timeout=2)
        admission.cancel()
        await asyncio.sleep(0)
        admission.cancel()
        await asyncio.sleep(0)
        assert not admission.done()
        assert not work.done()
        blocker.rollback()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(admission, timeout=2)
        receipt = await store.get_receipt(message_id=submission.message_id, principal=principal)
        assert receipt is not None and receipt.state == "accepted"
        await asyncio.wait_for(work, timeout=2)
    finally:
        blocker.rollback()
        blocker.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await store.close()


async def test_cancelled_claim_joins_publication_and_preserves_boundary(tmp_path: Path) -> None:
    """Repeated cancellation cannot leave a committed claim outside serialization."""
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
    tasks: list[asyncio.Task] = []
    blocker = sqlite3.connect(path)
    try:
        await store.set_lifecycle(accepting=True)
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="claim"
        )
        await queue.admit(submission=submission, principal=principal)
        blocker.execute("BEGIN IMMEDIATE")
        boundary = BoundaryDAO(run_id=str(uuid4()), boundary_index=0)
        claim = asyncio.create_task(queue.take_one(boundary=boundary))
        tasks.append(claim)
        async with asyncio.timeout(2):
            while not queue._mutex.locked():
                await asyncio.sleep(0)
        claim.cancel()
        await asyncio.sleep(0)
        claim.cancel()
        await asyncio.sleep(0)
        assert not claim.done()
        seal = asyncio.create_task(queue.seal())
        tasks.append(seal)
        blocker.rollback()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(claim, timeout=2)
        await asyncio.wait_for(seal, timeout=2)
        receipt = await store.get_receipt(message_id=submission.message_id, principal=principal)
        assert receipt is not None and receipt.state == "applying"
        delivery = await queue.take_one(boundary=boundary)
        assert delivery is not None and delivery.envelope.submission == submission
        assert (await store.read_queue_state()).eligible_inputs == 0
    finally:
        blocker.rollback()
        blocker.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await store.close()
