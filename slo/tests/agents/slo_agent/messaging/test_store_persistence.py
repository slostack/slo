"""Lifetime paging and real externally corrupted journal refusal."""

import sqlite3
from datetime import timedelta
from pathlib import Path
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
    utcnow,
)
from src.agents.slo_agent.messaging.store import MessageStore
from tests.agents.slo_agent.messaging.test_store_journey import application_event


class TestLifetimeStore:
    async def test_513_terminal_identities_and_17_observations_page_after_prune(self, tmp_path: Path) -> None:
        """Lifetime pages terminate without omissions; proof survives body pruning/reopen."""
        target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        principal = MessagePrincipalDAO(principal_id="owner", kind="human")
        expected = []
        observations = []
        try:
            await store.set_lifecycle(accepting=True)
            for index in range(513):
                submission = MessageSubmissionDAO(
                    message_id=str(uuid4()), target=target, kind="agent_input", text=str(index)
                )
                expected.append(submission.message_id)
                await store.admit(submission=submission, principal=principal)
                delivery = await store.claim_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0))
                assert delivery is not None
                event = application_event(delivery=delivery, generation=target.generation)
                await store.prepare_application(delivery=delivery, event=event)
                await store.mark_history_committed(message_id=submission.message_id)
                await store.mark_applied(message_id=submission.message_id)
                if index < 17:
                    observation_id = str(uuid4())
                    observations.append(observation_id)
                    await store.prepare_observation(observation_id=observation_id, event=event)
                    await store.mark_observation_applied(observation_id=observation_id)
            await store.maintain(now=utcnow() + timedelta(days=8))
        finally:
            await store.close()
        store = await MessageStore.open(
            path=path,
            limits=MessagingLimitsDAO(),
            target=target.model_copy(update={"generation": str(uuid4())}),
        )
        try:
            for limit in (1, 256):
                cursor = 0
                found: list[str] = []
                while page := await store.read_identities(after_sequence=cursor, limit=limit):
                    found.extend(record.receipt.message_id for record in page)
                    assert all(record.event_sha256 and record.receipt.state == "applied" for record in page)
                    cursor = page[-1].receipt.sequence
                assert found == expected and cursor == 513
            found_observations: list[str] = []
            after_id = None
            while observation_page := await store.read_observations(after_id=after_id, limit=1):
                found_observations.extend(item.observation_id for item in observation_page)
                after_id = observation_page[-1].observation_id
            assert found_observations == sorted(observations)
        finally:
            await store.close()

    @pytest.mark.parametrize(
        "change",
        [
            "UPDATE applications SET event_json='{}'",
            "UPDATE identity SET event_sha256='" + "0" * 64 + "'",
            "UPDATE applications SET context_committed=1",
        ],
    )
    async def test_corrupt_prepared_evidence_refuses_without_partial_ack(
        self, tmp_path: Path, change: str
    ) -> None:
        """Read, ack and restart all reject contradictory prepared evidence."""
        target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        principal = MessagePrincipalDAO(principal_id="owner", kind="human")
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="journal"
        )
        await store.set_lifecycle(accepting=True)
        await store.admit(submission=submission, principal=principal)
        delivery = await store.claim_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0))
        assert delivery is not None
        await store.prepare_application(
            delivery=delivery, event=application_event(delivery=delivery, generation=target.generation)
        )
        connection = sqlite3.connect(path)
        try:
            connection.execute(change)
            connection.commit()
            before = tuple(connection.iterdump())
            for operation in (
                lambda: store.read_identities(),
                lambda: store.mark_history_committed(message_id=submission.message_id),
            ):
                with pytest.raises(MessageStoreError, match="^storage_unavailable$"):
                    await operation()
                assert tuple(connection.iterdump()) == before
        finally:
            connection.close()
            await store.close()
        with pytest.raises(MessageStoreError):
            await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)

    async def test_unsettled_prune_and_exact_cancel_are_atomic(self, tmp_path: Path) -> None:
        """An invalid mixed cancel cannot settle a prefix; pruning never loses pending bodies."""
        target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        principal = MessagePrincipalDAO(principal_id="owner", kind="human")
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="kept"
        )
        try:
            await store.set_lifecycle(accepting=True)
            await store.admit(submission=submission, principal=principal)
            await store.retain_pending()
            before = await store.get_receipt(message_id=submission.message_id, principal=principal)
            with pytest.raises(MessageAdmissionError):
                await store.cancel_retained(message_ids=(submission.message_id, str(uuid4())))
            await store.maintain(now=utcnow() + timedelta(days=8))
            assert await store.get_receipt(message_id=submission.message_id, principal=principal) == before
        finally:
            await store.close()
