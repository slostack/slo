"""Worker snapshots validate only addressed/lane records, never full lifetime prechecks."""

import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.dao import (
    MessageAddressDAO,
    MessageAdmissionError,
    MessagePrincipalDAO,
    MessageStoreError,
    MessageSubmissionDAO,
    MessagingLimitsDAO,
    RecoveryTransferDAO,
    utcnow,
)
from src.agents.slo_agent.messaging.store import MessageStore
from tests.agents.slo_agent.messaging.test_store import _digest_of
from tests.agents.slo_agent.messaging.test_store_journey import application_event
from tests.agents.slo_agent.messaging.test_store_recovery_journey import retained_original, transfer_for


class TestAtomicReads:
    async def test_retained_journal_read_rejects_corruption_in_same_snapshot(self, tmp_path: Path) -> None:
        """Old prepared claims are excluded from live lanes but must still be validated on read."""
        from src.agents.slo_agent.messaging.dao import BoundaryDAO

        store, original, sender, current = await retained_original(root=tmp_path)
        await store.recover(
            transfer=transfer_for(original=original, sender=sender, destination=current), principal=sender
        )
        await store.set_lifecycle(accepting=True)
        delivery = await store.claim_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0))
        assert delivery is not None
        event = application_event(delivery=delivery, generation=current.generation)
        await store.prepare_application(delivery=delivery, event=event)
        await store.close()
        path = tmp_path / current.session_id / "messaging.v1.sqlite3"
        store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=current)
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "UPDATE applications SET event_json=?",
                (event.model_copy(update={"iteration": 1}).model_dump_json(),),
            )
            connection.commit()
            with pytest.raises(MessageStoreError):
                await store.load_application_event(message_id=original.message_id)
        finally:
            connection.close()
            await store.close()

    async def test_recovery_obeys_live_capacity_and_preserves_retained_record(self, tmp_path: Path) -> None:
        """Continuation is not permission to exceed configured execution capacity."""
        store, original, sender, current = await retained_original(root=tmp_path)
        await store.close()
        path = tmp_path / current.session_id / "messaging.v1.sqlite3"
        store = await MessageStore.open(
            path=path, limits=MessagingLimitsDAO(pending_inputs=1), target=current
        )
        try:
            await store.set_lifecycle(accepting=True)
            live = MessageSubmissionDAO(
                message_id=str(uuid4()), target=current, kind="agent_input", text="live"
            )
            await store.admit(submission=live, principal=sender)
            before = await store.get_receipt(message_id=original.message_id, principal=sender)
            with pytest.raises(MessageAdmissionError) as error:
                await store.recover(
                    transfer=transfer_for(original=original, sender=sender, destination=current),
                    principal=sender,
                )
            assert error.value.error.code == "queue_full"
            assert await store.get_receipt(message_id=original.message_id, principal=sender) == before
        finally:
            await store.close()

    async def test_operation_snapshot_does_not_scan_lifetime_ledger(self, tmp_path: Path) -> None:
        """A real native trace demonstrates bounded prechecks within one read transaction."""
        statements: list[str] = []

        def connect(*, database: str, uri: bool) -> sqlite3.Connection:
            """Observe real SQL without replacing engine behavior or storage."""
            connection = sqlite3.connect(database=database, uri=uri)
            connection.set_trace_callback(statements.append)
            return connection

        target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
        store = await MessageStore.open(
            path=tmp_path / target.session_id / "messaging.v1.sqlite3",
            limits=MessagingLimitsDAO(),
            target=target,
            connection_factory=connect,
        )
        try:
            statements.clear()
            assert await store.read_identities(limit=1) == ()
            assert statements[0] == "BEGIN IMMEDIATE"
            assert statements[-1] == "COMMIT"
            assert "SELECT * FROM identity" not in statements
            assert any("LIMIT 1" in statement for statement in statements)
        finally:
            await store.close()
