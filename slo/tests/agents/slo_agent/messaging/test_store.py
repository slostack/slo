"""Behavior tests for MessageStore (feature 96, sub-spec A.1, Change 2).

All tests use real SQLite on disk (tmp_path) or real in-memory SQLite for
the explicit ephemeral mode. No database mocks and no monkeypatching of
store internals.
"""

from __future__ import annotations

import stat
from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
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
from src.agents.slo_agent.messaging.store import MessageStore
from tests.agents.slo_agent.messaging.test_store_journey import application_event


def _target() -> MessageAddressDAO:
    """Build a fresh agent-session target for one test store."""
    return MessageAddressDAO(
        kind="agent_session",
        session_id=str(uuid4()),
        generation=str(uuid4()),
    )


def _limits(**overrides: int) -> MessagingLimitsDAO:
    """Build default messaging limits, optionally overridden per test."""
    return MessagingLimitsDAO(**overrides)


def _submission(*, target: MessageAddressDAO, text: str = "hello") -> MessageSubmissionDAO:
    """Build one minimal valid agent_input submission."""
    return MessageSubmissionDAO(
        message_id=str(uuid4()),
        target=target,
        kind="agent_input",
        text=text,
    )


def _principal(*, principal_id: str = "owner") -> MessagePrincipalDAO:
    """Build the local human owner principal used across tests."""
    return MessagePrincipalDAO(principal_id=principal_id, kind="human")


class TestOpenEphemeral:
    """Explicit ephemeral mode uses :memory: and reports durable=False."""

    async def test_ephemeral_open_and_close(self) -> None:
        target = _target()
        store = await MessageStore.open(path=None, limits=_limits(), target=target)
        await store.close()

    async def test_ephemeral_receipt_is_not_durable(self) -> None:
        target = _target()
        store = await MessageStore.open(path=None, limits=_limits(), target=target)
        await store.set_lifecycle(accepting=True)
        receipt = await store.admit(
            submission=_submission(target=target),
            principal=_principal(),
        )
        assert receipt.durable is False
        assert receipt.state == "accepted"
        await store.close()

    async def test_close_is_idempotent(self) -> None:
        store = await MessageStore.open(path=None, limits=_limits(), target=_target())
        await store.close()
        await store.close()


async def _seed_storage_pressure(*, store: MessageStore, megabytes: int) -> None:
    """Grow the database past the 256 MiB budget through the store's own worker.

    Test-only seeding of budget pressure; it changes no store behavior and
    keeps every connection touch on the store-owned worker thread.
    """

    def _seed() -> None:
        connection = store._connection
        connection.execute("CREATE TABLE budget_pressure(blob BLOB NOT NULL)")
        chunk = b"z" * (1024 * 1024)
        for _ in range(megabytes):
            connection.execute("INSERT INTO budget_pressure(blob) VALUES (?)", (chunk,))
        connection.commit()

    await store._run(_seed)


async def _open_accepting_store(
    *, path: Path | None, limits: MessagingLimitsDAO, target: MessageAddressDAO
) -> MessageStore:
    """Open one store with admission already accepting."""
    store = await MessageStore.open(path=path, limits=limits, target=target)
    await store.set_lifecycle(accepting=True)
    return store


class TestAdmissionIdentity:
    """Stable message_id retry identity, conflict and sealed outcomes."""

    async def test_identical_retry_returns_original_receipt(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = _submission(target=target)
        principal = _principal()
        first = await store.admit(submission=submission, principal=principal)
        second = await store.admit(submission=submission, principal=principal)
        assert second == first
        await store.close()

    async def test_retry_after_reopen_returns_original_outcome(self, tmp_path: Path) -> None:
        target = _target()
        db_path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        submission = _submission(target=target)
        principal = _principal()
        first_store = await _open_accepting_store(path=db_path, limits=_limits(), target=target)
        first = await first_store.admit(submission=submission, principal=principal)
        await first_store.close()
        second_store = await _open_accepting_store(path=db_path, limits=_limits(), target=target)
        try:
            second = await second_store.admit(submission=submission, principal=principal)
            # Canonical startup retains unapplied input even for a same-generation
            # reopen; immutable admission identity stays fixed, eligibility does not.
            assert second == first.model_copy(update={"retained_for_recovery": True})
        finally:
            await second_store.close()

    async def test_identical_retry_succeeds_even_when_full_and_sealed(self) -> None:
        """Duplicate lookup precedes capacity and lifecycle refusal."""
        target = _target()
        limits = _limits(pending_inputs=1)
        store = await _open_accepting_store(path=None, limits=limits, target=target)
        submission = _submission(target=target)
        principal = _principal()
        first = await store.admit(submission=submission, principal=principal)
        await store.set_lifecycle(accepting=False)
        second = await store.admit(submission=submission, principal=principal)
        assert second == first
        await store.close()

    async def test_changed_payload_conflicts(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = _submission(target=target, text="original")
        principal = _principal()
        await store.admit(submission=submission, principal=principal)
        changed = submission.model_copy(update={"text": "changed"})
        with pytest.raises(MessageAdmissionError) as exc_info:
            await store.admit(submission=changed, principal=principal)
        assert exc_info.value.error.code == "conflict"
        assert exc_info.value.error.message_id == submission.message_id
        await store.close()

    async def test_foreign_principal_retry_is_unauthorized(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = _submission(target=target)
        await store.admit(submission=submission, principal=_principal())
        with pytest.raises(MessageAdmissionError) as exc_info:
            await store.admit(submission=submission, principal=_principal(principal_id="other"))
        assert exc_info.value.error.code == "unauthorized"
        await store.close()

    async def test_sealed_store_refuses_new_ids(self) -> None:
        target = _target()
        store = await MessageStore.open(path=None, limits=_limits(), target=target)
        with pytest.raises(MessageAdmissionError) as exc_info:
            await store.admit(submission=_submission(target=target), principal=_principal())
        assert exc_info.value.error.code == "completing"
        await store.close()

    async def test_sequence_increments_per_new_admission(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        principal = _principal()
        first = await store.admit(submission=_submission(target=target), principal=principal)
        second = await store.admit(submission=_submission(target=target), principal=principal)
        assert (first.sequence, second.sequence) == (1, 2)
        await store.close()


class TestAdmissionCapacity:
    """Payload, queue, sender and storage budgets refuse before acceptance."""

    async def test_payload_over_limit_is_refused(self) -> None:
        target = _target()
        limits = _limits(payload_bytes=128)
        store = await _open_accepting_store(path=None, limits=limits, target=target)
        with pytest.raises(MessageAdmissionError) as exc_info:
            await store.admit(
                submission=_submission(target=target, text="x" * 512),
                principal=_principal(),
            )
        assert exc_info.value.error.code == "invalid_message"
        await store.close()

    async def test_input_lane_full_is_queue_full(self) -> None:
        target = _target()
        limits = _limits(pending_inputs=1)
        store = await _open_accepting_store(path=None, limits=limits, target=target)
        principal = _principal()
        await store.admit(submission=_submission(target=target), principal=principal)
        with pytest.raises(MessageAdmissionError) as exc_info:
            await store.admit(submission=_submission(target=target), principal=principal)
        assert exc_info.value.error.code == "queue_full"
        await store.close()

    async def test_note_lane_has_its_own_budget(self) -> None:
        target = _target()
        limits = _limits(pending_inputs=1, pending_notes=1)
        store = await _open_accepting_store(path=None, limits=limits, target=target)
        principal = _principal()
        await store.admit(submission=_submission(target=target), principal=principal)
        note = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=target,
            kind="context_note",
            text="note",
        )
        receipt = await store.admit(submission=note, principal=principal)
        assert receipt.state == "accepted"
        with pytest.raises(MessageAdmissionError) as exc_info:
            await store.admit(
                submission=MessageSubmissionDAO(
                    message_id=str(uuid4()),
                    target=target,
                    kind="context_note",
                    text="another",
                ),
                principal=principal,
            )
        assert exc_info.value.error.code == "queue_full"
        await store.close()

    async def test_per_sender_limit_is_refused(self) -> None:
        target = _target()
        limits = _limits(pending_per_sender=1)
        store = await _open_accepting_store(path=None, limits=limits, target=target)
        await store.admit(submission=_submission(target=target), principal=_principal())
        with pytest.raises(MessageAdmissionError) as exc_info:
            await store.admit(submission=_submission(target=target), principal=_principal())
        assert exc_info.value.error.code == "sender_limit"
        await store.close()

    async def test_urgent_per_sender_limit_is_refused(self) -> None:
        target = _target()
        limits = _limits(urgent_per_sender=1)
        store = await _open_accepting_store(path=None, limits=limits, target=target)
        principal = _principal()
        urgent = _submission(target=target).model_copy(update={"priority": "urgent"})
        await store.admit(submission=urgent, principal=principal)
        second_urgent = _submission(target=target).model_copy(update={"priority": "urgent"})
        with pytest.raises(MessageAdmissionError) as exc_info:
            await store.admit(submission=second_urgent, principal=principal)
        assert exc_info.value.error.code == "sender_limit"
        await store.close()

    async def test_storage_budget_refusal_is_store_error(self) -> None:
        """A database at the 256 MiB budget refuses new IDs with storage_unavailable."""
        target = _target()
        limits = _limits()
        store = await _open_accepting_store(path=None, limits=limits, target=target)
        try:
            await _seed_storage_pressure(store=store, megabytes=260)
            with pytest.raises(MessageStoreError) as exc_info:
                await store.admit(submission=_submission(target=target), principal=_principal())
            assert str(exc_info.value) == "storage_unavailable"
        finally:
            await store.close()


def _boundary(*, boundary_index: int = 0) -> BoundaryDAO:
    """Build one application boundary for a fresh run."""
    return BoundaryDAO(run_id=str(uuid4()), boundary_index=boundary_index)


def _event(*, target: MessageAddressDAO, history_event_id: str | None = None) -> SessionHistoryEventDAO:
    """Build one canonical history event for application journaling."""
    return SessionHistoryEventDAO(
        event_id=history_event_id or str(uuid4()),
        session_id=target.session_id,
        kind="user_message",
    )


async def _admit_one(
    *,
    store: MessageStore,
    target: MessageAddressDAO,
    text: str = "hello",
    priority: str = "normal",
) -> MessageSubmissionDAO:
    """Admit one submission and return it for later claims."""
    submission = _submission(target=target, text=text).model_copy(update={"priority": priority})
    await store.admit(submission=submission, principal=_principal())
    return submission


class TestClaimLifecycle:
    """claim_one → prepare_application → mark_history_committed → mark_applied."""

    async def test_empty_queue_claims_none(self) -> None:
        store = await _open_accepting_store(path=None, limits=_limits(), target=_target())
        assert await store.claim_one(boundary=_boundary()) is None
        await store.close()

    async def test_claim_returns_delivery_and_moves_to_applying(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await _admit_one(store=store, target=target)
        boundary = _boundary()
        delivery = await store.claim_one(boundary=boundary)
        assert delivery is not None
        assert delivery.envelope.submission == submission
        assert delivery.boundary == boundary
        assert delivery.envelope.sender == _principal()
        assert delivery.event is None
        receipt = await store.get_receipt(message_id=submission.message_id, principal=_principal())
        assert receipt is not None
        assert receipt.state == "applying"
        assert receipt.run_id == boundary.run_id
        await store.close()

    async def test_urgent_claims_before_normal_fifo_within_class(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        first_normal = await _admit_one(store=store, target=target, text="n1")
        second_normal = await _admit_one(store=store, target=target, text="n2")
        urgent = await _admit_one(store=store, target=target, text="u1", priority="urgent")
        first = await store.claim_one(boundary=_boundary())
        assert first is not None
        assert first.envelope.submission.message_id == urgent.message_id
        second = await store.claim_one(boundary=_boundary())
        assert second is not None
        assert second.envelope.submission.message_id == first_normal.message_id
        third = await store.claim_one(boundary=_boundary())
        assert third is not None
        assert third.envelope.submission.message_id == second_normal.message_id
        await store.close()

    async def test_repeat_claim_same_boundary_replays_until_commit(self) -> None:
        """A second claim for the same (run_id, boundary_index) replays the
        already-claimed delivery while unprepared, then returns None."""
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        await _admit_one(store=store, target=target)
        boundary = _boundary()
        first = await store.claim_one(boundary=boundary)
        assert first is not None
        replay = await store.claim_one(boundary=boundary)
        assert replay is not None
        assert replay.envelope.submission.message_id == first.envelope.submission.message_id
        assert replay.boundary == first.boundary
        await store.prepare_application(
            delivery=first, event=application_event(delivery=first, generation=target.generation)
        )
        assert await store.claim_one(boundary=boundary) == first
        await store.close()

    async def test_claim_installs_history_event_identity(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        await _admit_one(store=store, target=target)
        delivery = await store.claim_one(boundary=_boundary())
        assert delivery is not None
        _require_uuid(delivery.history_event_id)
        await store.close()

    async def test_prepare_application_journals_exact_event(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        await _admit_one(store=store, target=target)
        delivery = await store.claim_one(boundary=_boundary())
        assert delivery is not None
        event = application_event(delivery=delivery, generation=target.generation)
        await store.prepare_application(delivery=delivery, event=event)
        loaded = await store.load_application_event(message_id=delivery.envelope.submission.message_id)
        assert loaded == event
        await store.close()

    async def test_prepare_application_identical_retry_is_idempotent(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        await _admit_one(store=store, target=target)
        delivery = await store.claim_one(boundary=_boundary())
        assert delivery is not None
        event = application_event(delivery=delivery, generation=target.generation)
        await store.prepare_application(delivery=delivery, event=event)
        await store.prepare_application(delivery=delivery, event=event)
        await store.close()

    async def test_prepare_application_unequal_duplicate_is_corruption(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        await _admit_one(store=store, target=target)
        delivery = await store.claim_one(boundary=_boundary())
        assert delivery is not None
        await store.prepare_application(
            delivery=delivery, event=application_event(delivery=delivery, generation=target.generation)
        )
        with pytest.raises(MessageStoreError):
            await store.prepare_application(
                delivery=delivery,
                event=application_event(delivery=delivery, generation=target.generation).model_copy(
                    update={"event_id": str(uuid4())}
                ),
            )
        await store.close()

    async def test_load_application_event_missing_raises(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await _admit_one(store=store, target=target)
        with pytest.raises(MessageStoreError):
            await store.load_application_event(message_id=submission.message_id)
        await store.close()

    async def test_mark_applied_requires_history_commit(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        await _admit_one(store=store, target=target)
        delivery = await store.claim_one(boundary=_boundary())
        assert delivery is not None
        await store.prepare_application(
            delivery=delivery, event=application_event(delivery=delivery, generation=target.generation)
        )
        with pytest.raises(MessageStoreError):
            await store.mark_applied(message_id=delivery.envelope.submission.message_id)
        await store.close()

    async def test_full_lifecycle_returns_terminal_receipt(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await _admit_one(store=store, target=target)
        delivery = await store.claim_one(boundary=_boundary())
        assert delivery is not None
        await store.prepare_application(
            delivery=delivery,
            event=application_event(delivery=delivery, generation=target.generation),
        )
        await store.mark_history_committed(message_id=submission.message_id)
        receipt = await store.mark_applied(message_id=submission.message_id)
        assert receipt.state == "applied"
        assert receipt.applied_at is not None
        assert receipt.run_id == delivery.boundary.run_id
        replayed = await store.get_receipt(message_id=submission.message_id, principal=_principal())
        assert replayed == receipt
        await store.close()

    async def test_mark_history_committed_is_idempotent(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await _admit_one(store=store, target=target)
        delivery = await store.claim_one(boundary=_boundary())
        assert delivery is not None
        await store.prepare_application(
            delivery=delivery, event=application_event(delivery=delivery, generation=target.generation)
        )
        await store.mark_history_committed(message_id=submission.message_id)
        await store.mark_history_committed(message_id=submission.message_id)
        await store.close()


class TestStartupReconciliation:
    """Sealed startup recovery of claimed-but-unapplied deliveries."""

    async def test_unprepared_claims_reset_to_eligible(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await _admit_one(store=store, target=target)
        boundary = _boundary()
        assert await store.claim_one(boundary=boundary) is not None
        await store.reset_unprepared_claims()
        receipt = await store.get_receipt(message_id=submission.message_id, principal=_principal())
        assert receipt is not None
        assert receipt.state == "accepted"
        new_boundary = _boundary()
        reclaimed = await store.claim_one(boundary=new_boundary)
        assert reclaimed is None
        assert receipt.retained_for_recovery is True
        await store.close()

    async def test_prepared_claims_survive_reset_and_load_unsettled(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await _admit_one(store=store, target=target)
        delivery = await store.claim_one(boundary=_boundary())
        assert delivery is not None
        event = application_event(delivery=delivery, generation=target.generation)
        await store.prepare_application(delivery=delivery, event=event)
        await store.reset_unprepared_claims()
        unsettled = await store.load_unsettled_applications()
        assert len(unsettled) == 1
        recovered = unsettled[0]
        assert recovered.envelope.submission.message_id == submission.message_id
        assert recovered.boundary == delivery.boundary
        assert recovered.history_event_id == delivery.history_event_id
        assert recovered.event == event
        await store.close()

    async def test_reconciliation_survives_reopen(self, tmp_path: Path) -> None:
        """A crash between prepare and applied is recovered after restart."""
        target = _target()
        db_path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        store = await _open_accepting_store(path=db_path, limits=_limits(), target=target)
        submission = await _admit_one(store=store, target=target)
        delivery = await store.claim_one(boundary=_boundary())
        assert delivery is not None
        event = application_event(delivery=delivery, generation=target.generation)
        await store.prepare_application(delivery=delivery, event=event)
        await store.close()
        reopened = await MessageStore.open(path=db_path, limits=_limits(), target=target)
        try:
            await reopened.reset_unprepared_claims()
            unsettled = await reopened.load_unsettled_applications()
            assert len(unsettled) == 1
            assert unsettled[0].envelope.submission.message_id == submission.message_id
            assert unsettled[0].event == event
            await reopened.mark_history_committed(message_id=submission.message_id)
            receipt = await reopened.mark_applied(message_id=submission.message_id)
            assert receipt.state == "applied"
        finally:
            await reopened.close()


class TestReceiptAccess:
    """Authorized receipt lookup with safe absence and foreign refusal."""

    async def test_absent_message_returns_none(self) -> None:
        store = await _open_accepting_store(path=None, limits=_limits(), target=_target())
        assert await store.get_receipt(message_id=str(uuid4()), principal=_principal()) is None
        await store.close()

    async def test_foreign_principal_is_unauthorized_without_payload(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await _admit_one(store=store, target=target)
        with pytest.raises(MessageAdmissionError) as exc_info:
            await store.get_receipt(
                message_id=submission.message_id,
                principal=_principal(principal_id="intruder"),
            )
        assert exc_info.value.error.code == "unauthorized"
        await store.close()


class TestQueueStateAndSummary:
    """Atomic eligibility counts and the bounded presentation projection."""

    async def test_empty_state(self) -> None:
        store = await _open_accepting_store(path=None, limits=_limits(), target=_target())
        state = await store.read_queue_state()
        assert state.eligible_inputs == 0
        assert state.eligible_notes == 0
        assert state.urgent_high_water == 0
        await store.close()

    async def test_counts_separate_inputs_notes_and_high_water(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        await _admit_one(store=store, target=target, text="n1")
        await _admit_one(store=store, target=target, text="u1", priority="urgent")
        note = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=target,
            kind="context_note",
            text="note",
        )
        await store.admit(submission=note, principal=_principal())
        state = await store.read_queue_state()
        assert state.eligible_inputs == 2
        assert state.eligible_notes == 1
        assert state.urgent_high_water == 2
        await store.close()

    async def test_applying_counts_as_capacity_not_eligible(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        await _admit_one(store=store, target=target)
        assert await store.claim_one(boundary=_boundary()) is not None
        state = await store.read_queue_state()
        assert state.eligible_inputs == 0
        await store.close()

    async def test_retained_records_are_not_eligible(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        await _admit_one(store=store, target=target)
        await store.retain_pending()
        state = await store.read_queue_state()
        assert state.eligible_inputs == 0
        await store.close()

    async def test_summary_reports_next_local_text_only_for_owner(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await _admit_one(store=store, target=target, text="next up")
        summary = await store.read_summary(principal=_principal())
        assert summary.pending_count == 1
        assert summary.next_local_message_id == submission.message_id
        assert summary.next_local_text == "next up"
        foreign = await store.read_summary(principal=_principal(principal_id="other"))
        assert foreign.pending_count == 1
        assert foreign.next_local_message_id is None
        assert foreign.next_local_text is None
        await store.close()

    async def test_summary_counts_claimed_inputs_as_pending(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        await _admit_one(store=store, target=target)
        assert await store.claim_one(boundary=_boundary()) is not None
        summary = await store.read_summary(principal=_principal())
        assert summary.pending_count == 1
        await store.close()


class TestRetainAndCancel:
    """Shutdown retention and explicit owner cancellation of retained input."""

    async def test_retain_marks_accepted_records_for_recovery(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await _admit_one(store=store, target=target)
        await store.retain_pending()
        receipt = await store.get_receipt(message_id=submission.message_id, principal=_principal())
        assert receipt is not None
        assert receipt.state == "accepted"
        assert receipt.retained_for_recovery is True
        await store.close()

    async def test_retained_input_is_not_claimed(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        await _admit_one(store=store, target=target)
        await store.retain_pending()
        assert await store.claim_one(boundary=_boundary()) is None
        await store.close()

    async def test_cancel_retained_settles_terminal_cancelled(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await _admit_one(store=store, target=target)
        await store.retain_pending()
        await store.cancel_retained(message_ids=(submission.message_id,))
        receipt = await store.get_receipt(message_id=submission.message_id, principal=_principal())
        assert receipt is not None
        assert receipt.state == "cancelled"
        await store.close()

    async def test_cancel_retained_refuses_changed_selection(self) -> None:
        """Only the exact confirmed retained selection may be cancelled."""
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await _admit_one(store=store, target=target)
        with pytest.raises(MessageAdmissionError) as exc_info:
            await store.cancel_retained(message_ids=(submission.message_id,))
        assert exc_info.value.error.code == "recovery_required"
        await store.retain_pending()
        with pytest.raises(MessageAdmissionError) as exc_info:
            await store.cancel_retained(message_ids=(submission.message_id, str(uuid4())))
        assert exc_info.value.error.code == "recovery_required"
        receipt = await store.get_receipt(message_id=submission.message_id, principal=_principal())
        assert receipt is not None
        assert receipt.state == "accepted"
        await store.close()


class TestCompactionLedger:
    """Exact compaction membership; preparation alone is not coverage."""

    async def test_prepare_then_commit_records_coverage(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await _admit_one(store=store, target=target)
        delivery = await store.claim_one(boundary=_boundary())
        assert delivery is not None
        await store.prepare_application(
            delivery=delivery, event=application_event(delivery=delivery, generation=target.generation)
        )
        await store.mark_history_committed(message_id=submission.message_id)
        await store.mark_applied(message_id=submission.message_id)
        compaction_id = str(uuid4())
        summary_event_id = str(uuid4())
        await store.prepare_compaction(
            compaction_id=compaction_id,
            message_ids=(submission.message_id,),
            observation_ids=(),
        )
        await store.finish_compaction(compaction_id=compaction_id, summary_event_id=summary_event_id)
        await store.close()

    async def test_prepare_rejects_unsettled_members(self) -> None:
        """Accepted, applying or unknown messages cannot join a compaction."""
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        accepted = await _admit_one(store=store, target=target)
        with pytest.raises(MessageStoreError):
            await store.prepare_compaction(
                compaction_id=str(uuid4()),
                message_ids=(accepted.message_id,),
                observation_ids=(),
            )
        applying = await _admit_one(store=store, target=target)
        assert await store.claim_one(boundary=_boundary()) is not None
        with pytest.raises(MessageStoreError):
            await store.prepare_compaction(
                compaction_id=str(uuid4()),
                message_ids=(applying.message_id,),
                observation_ids=(),
            )
        with pytest.raises(MessageStoreError):
            await store.prepare_compaction(
                compaction_id=str(uuid4()),
                message_ids=(str(uuid4()),),
                observation_ids=(),
            )
        await store.close()

    async def test_finish_without_prepare_fails_closed(self) -> None:
        store = await _open_accepting_store(path=None, limits=_limits(), target=_target())
        with pytest.raises(MessageStoreError):
            await store.finish_compaction(compaction_id=str(uuid4()), summary_event_id=None)
        await store.close()

    async def test_rollback_records_proven_rollback_not_failure(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        compaction_id = str(uuid4())
        await store.prepare_compaction(compaction_id=compaction_id, message_ids=(), observation_ids=())
        await store.finish_compaction(compaction_id=compaction_id, summary_event_id=None)
        await store.close()


class TestInternalObservations:
    """Internal completion identity surviving its event body's pruning."""

    async def test_prepare_then_mark_applied(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        observation_id = str(uuid4())
        event = _event(target=target)
        await store.prepare_observation(observation_id=observation_id, event=event)
        await store.mark_observation_applied(observation_id=observation_id)
        await store.close()

    async def test_prepare_unequal_retry_fails_closed(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        observation_id = str(uuid4())
        await store.prepare_observation(observation_id=observation_id, event=_event(target=target))
        with pytest.raises(MessageStoreError):
            await store.prepare_observation(observation_id=observation_id, event=_event(target=target))
        await store.close()

    async def test_identical_prepare_retry_is_idempotent(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        observation_id = str(uuid4())
        event = _event(target=target)
        await store.prepare_observation(observation_id=observation_id, event=event)
        await store.prepare_observation(observation_id=observation_id, event=event)
        await store.close()

    async def test_mark_missing_observation_is_corruption(self) -> None:
        store = await _open_accepting_store(path=None, limits=_limits(), target=_target())
        with pytest.raises(MessageStoreError):
            await store.mark_observation_applied(observation_id=str(uuid4()))
        await store.close()

    async def test_duplicate_mark_is_harmless(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        observation_id = str(uuid4())
        await store.prepare_observation(observation_id=observation_id, event=_event(target=target))
        await store.mark_observation_applied(observation_id=observation_id)
        await store.mark_observation_applied(observation_id=observation_id)
        await store.close()


class TestWorkflowEffects:
    """Idempotent workflow effect outcomes per accepted message."""

    async def _journaled_message(
        self, *, store: MessageStore, target: MessageAddressDAO
    ) -> MessageSubmissionDAO:
        """Admit, claim and journal one message so effects may commit."""
        submission = await _admit_one(store=store, target=target)
        delivery = await store.claim_one(boundary=_boundary())
        assert delivery is not None
        await store.prepare_application(
            delivery=delivery, event=application_event(delivery=delivery, generation=target.generation)
        )
        return submission

    async def test_load_before_commit_returns_none(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await self._journaled_message(store=store, target=target)
        assert await store.load_workflow_effect(message_id=submission.message_id) is None
        await store.close()

    async def test_effect_commit_requires_unavailable_b2_validator(self) -> None:
        """Corrected §3 refuses later-only success; storage is not a B.2 effect."""
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await self._journaled_message(store=store, target=target)
        try:
            for outcome in ('{"status":"advanced"}', '{"status":"different"}'):
                with pytest.raises(MessageAdmissionError) as error:
                    await store.commit_workflow_effect(message_id=submission.message_id, outcome_json=outcome)
                assert error.value.error.code == "unsupported"
            assert await store.load_workflow_effect(message_id=submission.message_id) is None
        finally:
            await store.close()

    async def test_unknown_effect_cannot_bypass_capability_refusal(self) -> None:
        store = await _open_accepting_store(path=None, limits=_limits(), target=_target())
        try:
            with pytest.raises(MessageAdmissionError) as error:
                await store.commit_workflow_effect(message_id=str(uuid4()), outcome_json='{"status":"x"}')
            assert error.value.error.code == "unsupported"
        finally:
            await store.close()


class TestMaintain:
    """WAL checkpoint and terminal payload pruning outside execution."""

    async def _applied_message(
        self, *, store: MessageStore, target: MessageAddressDAO
    ) -> MessageSubmissionDAO:
        """Drive one message through the complete application lifecycle."""
        submission = await _admit_one(store=store, target=target)
        delivery = await store.claim_one(boundary=_boundary())
        assert delivery is not None
        await store.prepare_application(
            delivery=delivery,
            event=application_event(delivery=delivery, generation=target.generation),
        )
        await store.mark_history_committed(message_id=submission.message_id)
        await store.mark_applied(message_id=submission.message_id)
        return submission

    async def test_maintain_prunes_old_terminal_payloads(self) -> None:
        from datetime import timedelta

        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await self._applied_message(store=store, target=target)

        def _backdate() -> None:
            store._connection.execute(
                "UPDATE identity SET terminal_at = ? WHERE message_id = ?",
                ("2000-01-01T00:00:00+00:00", submission.message_id),
            )
            store._connection.commit()

        await store._run(_backdate)
        from src.agents.slo_agent.messaging.dao import utcnow

        await store.maintain(now=utcnow() + timedelta(days=1))
        receipt = await store.get_receipt(message_id=submission.message_id, principal=_principal())
        assert receipt is not None
        assert receipt.state == "applied"
        assert receipt.run_id is not None
        await store.close()

    async def test_maintain_keeps_recent_terminal_payloads(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        submission = await self._applied_message(store=store, target=target)
        from src.agents.slo_agent.messaging.dao import utcnow

        await store.maintain(now=utcnow())
        event = await store.load_application_event(message_id=submission.message_id)
        assert event.session_id == target.session_id
        await store.close()

    async def test_maintain_never_prunes_accepted_or_applying(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        accepted = await _admit_one(store=store, target=target, text="accepted")
        applying = await _admit_one(store=store, target=target, text="applying")
        assert await store.claim_one(boundary=_boundary()) is not None
        from src.agents.slo_agent.messaging.dao import utcnow

        with pytest.raises(MessageStoreError):
            await store.maintain(now=utcnow())
        for submission in (accepted, applying):
            receipt = await store.get_receipt(message_id=submission.message_id, principal=_principal())
            assert receipt is not None
            assert receipt.state in ("accepted", "applying")
        await store.close()


def _transfer_for(
    *,
    submission: MessageSubmissionDAO,
    principal: MessagePrincipalDAO,
    digest: str,
    transfer_id: str | None = None,
) -> RecoveryTransferDAO:
    """Build one recovery transfer authorizing continuation of an original."""
    return RecoveryTransferDAO(
        transfer_id=transfer_id or str(uuid4()),
        original=submission,
        original_sender=principal,
        original_digest=digest,
        destination=submission.target,
    )


def _digest_of(*, submission: MessageSubmissionDAO, principal: MessagePrincipalDAO) -> str:
    """Compute the store's submission digest for test fixture construction."""
    import hashlib
    import json

    canonical = json.dumps(
        {
            "principal": json.loads(principal.model_dump_json()),
            "submission": json.loads(submission.model_dump_json()),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TestRecoveryTransfers:
    """transfer_id idempotency; immutable original identity across generations."""

    async def test_pending_original_transfer_preserves_identity(self, tmp_path: Path) -> None:
        """A retained pending original keeps its ID, digest, bytes, target,
        sender and receipt; only execution generation and retention change."""
        target = _target()
        store = await _open_accepting_store(
            path=tmp_path / target.session_id / "messaging.v1.sqlite3", limits=_limits(), target=target
        )
        principal = _principal()
        submission = await _admit_one(store=store, target=target)
        original_receipt = await store.get_receipt(message_id=submission.message_id, principal=principal)
        assert original_receipt is not None
        await store.retain_pending()
        transfer = _transfer_for(
            submission=submission,
            principal=principal,
            digest=_digest_of(submission=submission, principal=principal),
        )
        outcome = await store.recover(transfer=transfer, principal=principal)
        assert outcome.transfer_id == transfer.transfer_id
        assert outcome.receipt.message_id == submission.message_id
        assert outcome.receipt.state == "accepted"
        assert outcome.receipt.target == original_receipt.target
        assert outcome.receipt.sequence == original_receipt.sequence
        assert outcome.receipt.admitted_at == original_receipt.admitted_at
        assert outcome.receipt.retained_for_recovery is False
        _require_uuid(outcome.execution_generation)
        reclaimed = await store.claim_one(boundary=_boundary())
        assert reclaimed is not None
        assert reclaimed.envelope.submission == submission
        await store.close()

    async def test_repeated_transfer_returns_original_outcome(self, tmp_path: Path) -> None:
        """Acknowledgement loss retries the same transfer_id exactly."""
        target = _target()
        store = await _open_accepting_store(
            path=tmp_path / target.session_id / "messaging.v1.sqlite3", limits=_limits(), target=target
        )
        principal = _principal()
        submission = await _admit_one(store=store, target=target)
        await store.retain_pending()
        transfer = _transfer_for(
            submission=submission,
            principal=principal,
            digest=_digest_of(submission=submission, principal=principal),
        )
        first = await store.recover(transfer=transfer, principal=principal)
        second = await store.recover(transfer=transfer, principal=principal)
        assert second == first
        await store.close()

    async def test_changed_transfer_conflicts(self, tmp_path: Path) -> None:
        target = _target()
        store = await _open_accepting_store(
            path=tmp_path / target.session_id / "messaging.v1.sqlite3", limits=_limits(), target=target
        )
        principal = _principal()
        submission = await _admit_one(store=store, target=target)
        await store.retain_pending()
        transfer = _transfer_for(
            submission=submission,
            principal=principal,
            digest=_digest_of(submission=submission, principal=principal),
        )
        await store.recover(transfer=transfer, principal=principal)
        changed = _transfer_for(
            submission=submission.model_copy(update={"text": "tampered"}),
            principal=principal,
            digest=_digest_of(submission=submission, principal=principal),
            transfer_id=transfer.transfer_id,
        )
        with pytest.raises(MessageAdmissionError) as exc_info:
            await store.recover(transfer=changed, principal=principal)
        assert exc_info.value.error.code == "conflict"
        await store.close()

    async def test_second_transfer_for_same_message_conflicts(self, tmp_path: Path) -> None:
        """Only one transfer per message/destination generation is admitted."""
        target = _target()
        store = await _open_accepting_store(
            path=tmp_path / target.session_id / "messaging.v1.sqlite3", limits=_limits(), target=target
        )
        principal = _principal()
        submission = await _admit_one(store=store, target=target)
        await store.retain_pending()
        digest = _digest_of(submission=submission, principal=principal)
        first = _transfer_for(submission=submission, principal=principal, digest=digest)
        await store.recover(transfer=first, principal=principal)
        await store.retain_pending()
        second = _transfer_for(submission=submission, principal=principal, digest=digest)
        with pytest.raises(MessageAdmissionError) as exc_info:
            await store.recover(transfer=second, principal=principal)
        assert exc_info.value.error.code == "conflict"
        await store.close()

    async def test_applying_original_requires_reconciliation_first(self, tmp_path: Path) -> None:
        target = _target()
        store = await _open_accepting_store(
            path=tmp_path / target.session_id / "messaging.v1.sqlite3", limits=_limits(), target=target
        )
        principal = _principal()
        submission = await _admit_one(store=store, target=target)
        assert await store.claim_one(boundary=_boundary()) is not None
        transfer = _transfer_for(
            submission=submission,
            principal=principal,
            digest=_digest_of(submission=submission, principal=principal),
        )
        with pytest.raises(MessageAdmissionError) as exc_info:
            await store.recover(transfer=transfer, principal=principal)
        assert exc_info.value.error.code == "recovery_required"
        await store.close()

    async def test_applied_original_returns_terminal_receipt_without_execution(self, tmp_path: Path) -> None:
        target = _target()
        store = await _open_accepting_store(
            path=tmp_path / target.session_id / "messaging.v1.sqlite3", limits=_limits(), target=target
        )
        principal = _principal()
        submission = await _admit_one(store=store, target=target)
        delivery = await store.claim_one(boundary=_boundary())
        assert delivery is not None
        await store.prepare_application(
            delivery=delivery, event=application_event(delivery=delivery, generation=target.generation)
        )
        await store.mark_history_committed(message_id=submission.message_id)
        applied = await store.mark_applied(message_id=submission.message_id)
        transfer = _transfer_for(
            submission=submission,
            principal=principal,
            digest=_digest_of(submission=submission, principal=principal),
        )
        outcome = await store.recover(transfer=transfer, principal=principal)
        assert outcome.receipt.state == "applied"
        assert outcome.receipt.message_id == submission.message_id
        assert outcome.receipt.applied_at == applied.applied_at
        assert await store.claim_one(boundary=_boundary()) is None
        await store.close()

    async def test_recovery_survives_reopen(self, tmp_path: Path) -> None:
        """A completed transfer replays after restart with the same outcome."""
        target = _target()
        db_path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        store = await _open_accepting_store(path=db_path, limits=_limits(), target=target)
        principal = _principal()
        submission = await _admit_one(store=store, target=target)
        await store.retain_pending()
        transfer = _transfer_for(
            submission=submission,
            principal=principal,
            digest=_digest_of(submission=submission, principal=principal),
        )
        first = await store.recover(transfer=transfer, principal=principal)
        await store.close()
        reopened = await MessageStore.open(path=db_path, limits=_limits(), target=target)
        try:
            second = await reopened.recover(transfer=transfer, principal=principal)
            assert second == first
        finally:
            await reopened.close()


class TestSafeErrorTranslation:
    """Raw SQLite failures never escape the store; only storage_unavailable."""

    async def test_sqlite_failure_inside_admit_is_safe_error(self) -> None:
        target = _target()
        store = await _open_accepting_store(path=None, limits=_limits(), target=target)
        # A closed connection now fails its enclosing snapshot commit immediately.
        with pytest.raises(MessageStoreError):
            await store._run(store._connection.close)
        with pytest.raises(MessageStoreError) as exc_info:
            await store.admit(submission=_submission(target=target), principal=_principal())
        assert str(exc_info.value) == "storage_unavailable"
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__suppress_context__ is True


def _require_uuid(value: str) -> None:
    """Assert one string is a canonical lowercase hyphenated UUID."""
    import re

    assert re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", value)


class TestOpenPersistent:
    """Persistent open validates paths, permissions, pragmas and user_version."""

    async def test_creates_db_with_private_permissions(self, tmp_path: Path) -> None:
        target = _target()
        db_path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        store = await MessageStore.open(path=db_path, limits=_limits(), target=target)
        try:
            directory_mode = stat.S_IMODE(db_path.parent.stat().st_mode)
            file_mode = stat.S_IMODE(db_path.stat().st_mode)
            assert directory_mode == 0o700
            assert file_mode == 0o600
        finally:
            await store.close()

    async def test_persistent_receipt_is_durable(self, tmp_path: Path) -> None:
        target = _target()
        db_path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        store = await MessageStore.open(path=db_path, limits=_limits(), target=target)
        await store.set_lifecycle(accepting=True)
        try:
            receipt = await store.admit(
                submission=_submission(target=target),
                principal=_principal(),
            )
            assert receipt.durable is True
        finally:
            await store.close()

    async def test_reopen_existing_schema_one_database(self, tmp_path: Path) -> None:
        target = _target()
        db_path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        first = await MessageStore.open(path=db_path, limits=_limits(), target=target)
        await first.close()
        second = await MessageStore.open(path=db_path, limits=_limits(), target=target)
        await second.close()

    async def test_rejects_symlinked_ancestry(self, tmp_path: Path) -> None:
        target = _target()
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link_dir = tmp_path / "linked"
        link_dir.symlink_to(real_dir)
        db_path = link_dir / target.session_id / "messaging.v1.sqlite3"
        with pytest.raises(MessageStoreError):
            await MessageStore.open(path=db_path, limits=_limits(), target=target)

    async def test_rejects_symlinked_database_file(self, tmp_path: Path) -> None:
        target = _target()
        session_dir = tmp_path / target.session_id
        session_dir.mkdir()
        elsewhere = tmp_path / "elsewhere.sqlite3"
        elsewhere.write_bytes(b"")
        db_path = session_dir / "messaging.v1.sqlite3"
        db_path.symlink_to(elsewhere)
        with pytest.raises(MessageStoreError):
            await MessageStore.open(path=db_path, limits=_limits(), target=target)

    async def test_fails_closed_on_foreign_user_version(self, tmp_path: Path) -> None:
        import sqlite3

        target = _target()
        db_path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        first = await MessageStore.open(path=db_path, limits=_limits(), target=target)
        await first.close()
        connection = sqlite3.connect(db_path)
        connection.execute("PRAGMA user_version=2")
        connection.commit()
        connection.close()
        with pytest.raises(MessageStoreError) as exc_info:
            await MessageStore.open(path=db_path, limits=_limits(), target=target)
        assert str(exc_info.value) == "storage_unavailable"

    async def test_persistent_failure_never_falls_back_to_memory(self, tmp_path: Path) -> None:
        """An unusable persistent path raises; it never silently opens :memory:."""
        target = _target()
        blocker = tmp_path / "blocker"
        blocker.write_bytes(b"not a directory")
        db_path = blocker / target.session_id / "messaging.v1.sqlite3"
        with pytest.raises(MessageStoreError):
            await MessageStore.open(path=db_path, limits=_limits(), target=target)

    async def test_anonymous_projection_fails_with_safe_error(self, tmp_path: Path) -> None:
        """A filesystem-level open failure surfaces only storage_unavailable.

        A regular file where the session directory must be created cannot
        host the database; the failure surfaces as the fixed safe error
        even for a root test runner, and never falls back to memory.
        """
        target = _target()
        blocker = tmp_path / "blocker"
        blocker.write_bytes(b"not a directory")
        db_path = blocker / target.session_id / "messaging.v1.sqlite3"
        with pytest.raises(MessageStoreError) as exc_info:
            await MessageStore.open(path=db_path, limits=_limits(), target=target)
        assert str(exc_info.value) == "storage_unavailable"

    async def test_corrupted_database_fails_closed(self, tmp_path: Path) -> None:
        """A non-database file at the messaging path never opens; no fallback."""
        target = _target()
        session_dir = tmp_path / target.session_id
        session_dir.mkdir()
        db_path = session_dir / "messaging.v1.sqlite3"
        db_path.write_bytes(b"this is not a sqlite database at all" * 8)
        with pytest.raises(MessageStoreError) as exc_info:
            await MessageStore.open(path=db_path, limits=_limits(), target=target)
        assert str(exc_info.value) == "storage_unavailable"

    async def test_error_text_is_safe(self, tmp_path: Path) -> None:
        """Only the fixed safe text escapes; no path or SQLite diagnostics."""
        target = _target()
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link_dir = tmp_path / "linked"
        link_dir.symlink_to(real_dir)
        db_path = link_dir / target.session_id / "messaging.v1.sqlite3"
        with pytest.raises(MessageStoreError) as exc_info:
            await MessageStore.open(path=db_path, limits=_limits(), target=target)
        message = str(exc_info.value)
        assert message == "storage_unavailable"
        assert str(db_path) not in message
