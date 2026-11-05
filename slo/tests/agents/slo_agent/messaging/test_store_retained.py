"""Retained source reads and idle-only pruning barriers."""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.dao import (
    BoundaryDAO,
    MessageStoreError,
    MessageSubmissionDAO,
    utcnow,
)
from tests.agents.slo_agent.messaging.test_store_journey import application_event, claimed_store
from tests.agents.slo_agent.messaging.test_store_recovery_journey import retained_original


class TestRetainedEvidence:
    async def test_retained_pages_supply_original_bytes_and_author(self, tmp_path: Path) -> None:
        """Local source selection needs original envelopes, not just receipt tombstones."""
        store, original, sender, _ = await retained_original(root=tmp_path)
        try:
            retained = await store.read_retained(limit=1)
            assert len(retained) == 1
            assert retained[0].submission == original and retained[0].sender == sender
            assert retained[0].sequence == 1
            assert await store.read_retained(after_sequence=1) == ()
            await store.cancel_retained(message_ids=(original.message_id,))
            assert await store.read_retained() == ()
        finally:
            await store.close()

    async def test_prune_refuses_unsettled_application_and_prepared_compaction(self) -> None:
        """Worker serialization is not proof that execution/history activation is idle."""
        store, delivery = await claimed_store()
        message_id = delivery.envelope.submission.message_id
        try:
            with pytest.raises(MessageStoreError):
                await store.maintain(now=utcnow() + timedelta(days=8))
            await store.prepare_application(
                delivery=delivery,
                event=application_event(
                    delivery=delivery, generation=delivery.envelope.submission.target.generation
                ),
            )
            await store.mark_history_committed(message_id=message_id)
            await store.mark_applied(message_id=message_id)
            compaction_id = str(uuid4())
            await store.prepare_compaction(
                compaction_id=compaction_id, message_ids=(message_id,), observation_ids=()
            )
            with pytest.raises(MessageStoreError):
                await store.maintain(now=utcnow() + timedelta(days=8))
            await store.finish_compaction(compaction_id=compaction_id, summary_event_id=None)
            await store.maintain(now=utcnow() + timedelta(days=8))
        finally:
            await store.close()
