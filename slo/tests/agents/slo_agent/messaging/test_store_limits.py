"""Canonical byte admission boundaries and validated observation acknowledgement."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.agents.slo_agent.messaging.dao import (
    MessageAddressDAO,
    MessageAdmissionError,
    MessagePrincipalDAO,
    MessageStoreError,
    MessageSubmissionDAO,
    MessagingLimitsDAO,
    canonical_submission_bytes,
)
from src.agents.slo_agent.messaging.store import MessageStore
from tests.agents.slo_agent.messaging.test_store_journey import application_event
from tests.agents.slo_agent.messaging.test_store_recovery_journey import retained_original, transfer_for


class TestStoreLimits:
    @pytest.mark.parametrize("text", ["x" * 65536, "\ud800"])
    async def test_invalid_complete_utf8_submission_rejected_at_construction(self, text: str) -> None:
        """64 KiB includes the entire canonical JSON, not merely its text field."""
        target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
        with pytest.raises(ValidationError):
            MessageSubmissionDAO(message_id=str(uuid4()), target=target, kind="agent_input", text=text)

    async def test_exact_configured_byte_budget_is_inclusive(self) -> None:
        """Sorted UTF-8 JSON at limit succeeds; one byte over refuses without sequence allocation."""
        target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
        principal = MessagePrincipalDAO(principal_id="owner", kind="human")
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="é"
        )
        budget = len(canonical_submission_bytes(submission=submission))
        store = await MessageStore.open(
            path=None, limits=MessagingLimitsDAO(payload_bytes=budget), target=target
        )
        try:
            await store.set_lifecycle(accepting=True)
            receipt = await store.admit(submission=submission, principal=principal)
            assert receipt.sequence == 1
            with pytest.raises(MessageAdmissionError) as error:
                await store.admit(
                    submission=submission.model_copy(update={"message_id": str(uuid4()), "text": "éx"}),
                    principal=principal,
                )
            assert error.value.error.code == "invalid_message"
            assert len(await store.read_identities()) == 1
        finally:
            await store.close()

    async def test_observation_ack_cannot_certify_corrupt_event(self, tmp_path: Path) -> None:
        """An applied flag requires a decodable matching observation body in the same transaction."""
        from src.agents.slo_agent.messaging.dao import BoundaryDAO

        store, original, sender, target = await retained_original(root=tmp_path)
        await store.recover(
            transfer=transfer_for(original=original, sender=sender, destination=target), principal=sender
        )
        await store.set_lifecycle(accepting=True)
        delivery = await store.claim_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0))
        assert delivery is not None
        event = application_event(delivery=delivery, generation=target.generation)
        observation_id = str(uuid4())
        await store.prepare_observation(observation_id=observation_id, event=event)
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        connection = sqlite3.connect(path)
        try:
            connection.execute("UPDATE internal_observations SET event_sha256=?", ("0" * 64,))
            connection.commit()
            before = tuple(connection.iterdump())
            with pytest.raises(MessageStoreError):
                await store.mark_observation_applied(observation_id=observation_id)
            assert tuple(connection.iterdump()) == before
        finally:
            connection.close()
            await store.close()
