"""Startup recovery-ledger validation using real persisted corruption."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.dao import MessageStoreError, MessagingLimitsDAO
from src.agents.slo_agent.messaging.store import MessageStore
from tests.agents.slo_agent.messaging.test_store_journey import application_event
from tests.agents.slo_agent.messaging.test_store_recovery_journey import retained_original, transfer_for


class TestRecoveryLedgerValidation:
    @pytest.mark.parametrize(
        "change",
        [
            "UPDATE recovery_transfers SET original_digest='" + "0" * 64 + "'",
            "UPDATE recovery_transfers SET confirmed_by='not-json'",
            "UPDATE recovery_transfers SET outcome_json='{}'",
            "UPDATE recovery_transfers SET from_generation='invalid'",
            "UPDATE internal_observations SET event_sha256='" + "0" * 64 + "'",
            "UPDATE compactions SET state='committed'",
        ],
    )
    async def test_startup_rejects_corrupt_recovery_ledgers_before_reseal(
        self, tmp_path: Path, change: str
    ) -> None:
        """Startup cannot adopt a new generation over contradictory durable proof."""
        store, original, sender, target = await retained_original(root=tmp_path)
        transfer = transfer_for(original=original, sender=sender, destination=target)
        await store.recover(transfer=transfer, principal=sender)
        await store.set_lifecycle(accepting=True)
        from src.agents.slo_agent.messaging.dao import BoundaryDAO

        delivery = await store.claim_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0))
        assert delivery is not None
        event = application_event(delivery=delivery, generation=target.generation)
        await store.prepare_application(delivery=delivery, event=event)
        await store.mark_history_committed(message_id=original.message_id)
        await store.mark_applied(message_id=original.message_id)
        await store.prepare_observation(observation_id=str(uuid4()), event=event)
        # Finish the observation before an empty prepared compaction.
        observation = (await store.read_observations())[0]
        await store.mark_observation_applied(observation_id=observation.observation_id)
        await store.prepare_compaction(compaction_id=str(uuid4()), message_ids=(), observation_ids=())
        await store.close()
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        connection = sqlite3.connect(path)
        connection.execute(change)
        connection.commit()
        before = tuple(connection.iterdump())
        opened = None
        try:
            with pytest.raises(MessageStoreError, match="^storage_unavailable$"):
                opened = await MessageStore.open(
                    path=path,
                    limits=MessagingLimitsDAO(),
                    target=target.model_copy(update={"generation": str(uuid4())}),
                )
            assert tuple(connection.iterdump()) == before
        finally:
            if opened is not None:
                await opened.close()
            connection.close()
