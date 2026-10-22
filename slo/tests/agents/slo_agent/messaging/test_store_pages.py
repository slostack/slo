"""Bounded store recovery reads, independent note slots and compaction proof."""

from datetime import timedelta
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.dao import (
    BoundaryDAO,
    MessageAdmissionError,
    MessageStoreError,
    MessageSubmissionDAO,
    MessageKind,
    utcnow,
)
from tests.agents.slo_agent.messaging.test_store_journey import application_event, claimed_store, event_hash


class TestRecoveryPages:
    @pytest.mark.parametrize(
        "method,kwargs",
        [
            ("read_identities", {"after_sequence": -1}),
            ("read_identities", {"limit": True}),
            ("read_compactions", {"after_id": "invalid"}),
            ("read_observations", {"limit": 257}),
        ],
    )
    async def test_invalid_pagination_is_fixed_admission_error(self, method: str, kwargs: dict) -> None:
        """Invalid cursors never become arbitrary SQL reads or storage corruption."""
        store, _ = await claimed_store()
        try:
            with pytest.raises(MessageAdmissionError) as error:
                await getattr(store, method)(**kwargs)
            assert error.value.error.code == "invalid_message"
        finally:
            await store.close()

    async def test_note_fifo_uses_independent_boundary_slot(self) -> None:
        """A note and instruction coexist; retries cannot drain the next note."""
        store, instruction = await claimed_store()
        target = instruction.envelope.submission.target
        kinds: tuple[MessageKind, ...] = ("transcript_note", "context_note")
        notes = [
            MessageSubmissionDAO(message_id=str(uuid4()), target=target, kind=kind, text=kind)
            for kind in kinds
        ]
        try:
            for note in notes:
                await store.admit(submission=note, principal=instruction.envelope.sender)
            first = await store.claim_note(boundary=instruction.boundary)
            assert first is not None and first.envelope.submission == notes[0]
            event = application_event(delivery=first, generation=target.generation)
            await store.prepare_application(delivery=first, event=event)
            replay = await store.claim_note(boundary=instruction.boundary)
            assert replay == first
            assert await store.claim_one(boundary=instruction.boundary) == instruction
            second = await store.claim_note(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0))
            assert second is not None and second.envelope.submission == notes[1]
        finally:
            await store.close()

    async def test_compaction_readback_is_exact_and_final_outcome_immutable(self) -> None:
        """Prepared membership is not coverage; committed proof survives pruning."""
        store, delivery = await claimed_store()
        target = delivery.envelope.submission.target
        message_id = delivery.envelope.submission.message_id
        event = application_event(delivery=delivery, generation=target.generation)
        observation_id = str(uuid4())
        compaction_id = str(uuid4())
        summary_id = str(uuid4())
        try:
            await store.prepare_application(delivery=delivery, event=event)
            await store.mark_history_committed(message_id=message_id)
            applied = await store.mark_applied(message_id=message_id)
            await store.prepare_observation(observation_id=observation_id, event=event)
            with pytest.raises(MessageStoreError):
                await store.prepare_compaction(
                    compaction_id=compaction_id, message_ids=(message_id,), observation_ids=(observation_id,)
                )
            await store.mark_observation_applied(observation_id=observation_id)
            await store.prepare_compaction(
                compaction_id=compaction_id, message_ids=(message_id,), observation_ids=(observation_id,)
            )
            await store.prepare_compaction(
                compaction_id=compaction_id, message_ids=(message_id,), observation_ids=(observation_id,)
            )
            with pytest.raises(MessageStoreError):
                await store.prepare_compaction(compaction_id=str(uuid4()), message_ids=(), observation_ids=())
            prepared = await store.read_compactions(limit=1)
            assert prepared[0].state == "prepared" and prepared[0].summary_event_id is None
            assert prepared[0].message_ids == (message_id,)
            assert prepared[0].observation_ids == (observation_id,)
            await store.finish_compaction(compaction_id=compaction_id, summary_event_id=summary_id)
            await store.finish_compaction(compaction_id=compaction_id, summary_event_id=summary_id)
            with pytest.raises(MessageStoreError):
                await store.finish_compaction(compaction_id=compaction_id, summary_event_id=None)
            await store.maintain(now=utcnow() + timedelta(days=8))
            assert (
                await store.get_receipt(message_id=message_id, principal=delivery.envelope.sender) == applied
            )
            identity = (await store.read_identities())[0]
            assert identity.event_sha256 == event_hash(event=event)
            ledger = (await store.read_compactions())[0]
            assert ledger.state == "committed" and ledger.summary_event_id == summary_id
            observation = (await store.read_observations())[0]
            assert observation.state == "applied" and observation.event_sha256 == event_hash(event=event)
            assert observation.event is None
            assert await store.read_compactions(after_id=ledger.compaction_id) == ()
            assert await store.read_observations(after_id=observation_id) == ()
        finally:
            await store.close()

    async def test_compaction_refuses_any_unsettled_application_not_just_members(self) -> None:
        """Even an empty proposed cut cannot cross an unsettled journal barrier."""
        store, _ = await claimed_store()
        try:
            with pytest.raises(MessageStoreError):
                await store.prepare_compaction(compaction_id=str(uuid4()), message_ids=(), observation_ids=())
        finally:
            await store.close()
