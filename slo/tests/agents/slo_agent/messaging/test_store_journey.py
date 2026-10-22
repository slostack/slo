"""Recipient-store journeys using real SQLite and canonical application evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import pytest

from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.messaging.dao import (
    BoundaryDAO,
    MessageAddressDAO,
    MessageApplicationMetadataDAO,
    MessageDeliveryDAO,
    MessagePrincipalDAO,
    MessageStoreError,
    MessageSubmissionDAO,
    MessagingLimitsDAO,
)
from src.agents.slo_agent.messaging.store import MessageStore


def application_event(*, delivery: MessageDeliveryDAO, generation: str) -> SessionHistoryEventDAO:
    """Build the exact event prescribed by A.1 §8 delivery, not a user_message."""
    envelope = delivery.envelope
    submission = envelope.submission
    metadata = MessageApplicationMetadataDAO(
        message_id=submission.message_id,
        kind=submission.kind,
        sender=envelope.sender,
        sequence=envelope.sequence,
        run_id=delivery.boundary.run_id,
        execution_generation=generation,
    )
    return SessionHistoryEventDAO(
        event_id=str(
            uuid5(namespace=UUID(submission.target.session_id), name="message:" + submission.message_id)
        ),
        session_id=submission.target.session_id,
        kind="workflow_update",
        turn_id=delivery.boundary.run_id,
        recorded_at=envelope.admitted_at,
        payload=SessionHistoryEventPayloadDAO(
            content=submission.text, metadata={"messaging_v1": metadata.model_dump(mode="json")}
        ),
    )


def event_hash(*, event: SessionHistoryEventDAO) -> str:
    """Normalize only the two history-assigned fields, per the history contract."""
    data = event.model_dump(mode="json")
    data.pop("sequence")
    data["payload"].pop("token_usage")
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


async def claimed_store(*, path: Path | None = None) -> tuple[MessageStore, MessageDeliveryDAO]:
    """Admit and claim one real message through public store ports."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
    await store.set_lifecycle(accepting=True)
    await store.admit(
        submission=MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="exact é"
        ),
        principal=MessagePrincipalDAO(principal_id="owner", kind="human"),
    )
    delivery = await store.claim_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0))
    assert delivery is not None
    return store, delivery


class TestExactApplication:
    @pytest.mark.parametrize(
        "field",
        ["event_id", "session_id", "kind", "recorded_at", "turn_id", "content", "metadata", "iteration"],
    )
    async def test_unrelated_event_cannot_certify_claim(self, field: str) -> None:
        """Every supplied event component except assigned history fields is authoritative."""
        from datetime import timedelta

        store, delivery = await claimed_store()
        event = application_event(
            delivery=delivery, generation=delivery.envelope.submission.target.generation
        )
        values = {
            "event_id": str(uuid4()),
            "session_id": str(uuid4()),
            "kind": "user_message",
            "recorded_at": event.recorded_at + timedelta(seconds=1),
            "turn_id": str(uuid4()),
            "iteration": 1,
        }
        if field in ("content", "metadata"):
            event.payload = event.payload.model_copy(update={field: "wrong" if field == "content" else {}})
        else:
            event = event.model_copy(update={field: values[field]})
        try:
            with pytest.raises(MessageStoreError, match="^storage_unavailable$"):
                await store.prepare_application(delivery=delivery, event=event)
            with pytest.raises(MessageStoreError):
                await store.mark_history_committed(message_id=delivery.envelope.submission.message_id)
        finally:
            await store.close()

    async def test_supplied_delivery_must_equal_stored_claim(self) -> None:
        """A real message ID does not authorize a different boundary or envelope."""
        store, delivery = await claimed_store()
        forged = delivery.model_copy(update={"boundary": BoundaryDAO(run_id=str(uuid4()), boundary_index=0)})
        try:
            with pytest.raises(MessageStoreError):
                await store.prepare_application(
                    delivery=forged,
                    event=application_event(
                        delivery=forged, generation=delivery.envelope.submission.target.generation
                    ),
                )
        finally:
            await store.close()

    async def test_prepare_retains_normalized_proof_before_acknowledgement(self) -> None:
        """Prepared identity survives history-assigned fields without premature application."""
        store, delivery = await claimed_store()
        message_id = delivery.envelope.submission.message_id
        event = application_event(
            delivery=delivery, generation=delivery.envelope.submission.target.generation
        )
        assigned = event.model_copy(
            update={"sequence": 42, "payload": event.payload.model_copy(update={"token_usage": 123})}
        )
        try:
            await store.prepare_application(delivery=delivery, event=event)
            await store.prepare_application(delivery=delivery, event=assigned)
            assert await store.load_application_event(message_id=message_id) == event
            with pytest.raises(MessageStoreError):
                await store.mark_applied(message_id=message_id)
            identities = await store.read_identities(limit=1)
            assert identities[0].receipt.state == "applying"
            assert identities[0].history_event_id == event.event_id
            assert identities[0].event_sha256 == event_hash(event=event)
            await store.mark_history_committed(message_id=message_id)
            first = await store.mark_applied(message_id=message_id)
            assert await store.mark_applied(message_id=message_id) == first
        finally:
            await store.close()
