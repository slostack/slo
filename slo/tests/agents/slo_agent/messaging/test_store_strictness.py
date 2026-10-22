"""Concrete store/DAO integrity corrections, not future capability activation."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.agents.slo_agent.messaging.dao import (
    CompactionLedgerDAO,
    MessageAdmissionError,
    MessagePrincipalDAO,
    MessageReceiptDAO,
    MessageSubmissionDAO,
)
from tests.agents.slo_agent.messaging.test_store_journey import application_event, claimed_store


class TestStoredStrictness:
    async def test_workflow_effect_is_not_placeholder_success(self) -> None:
        """A.1 cannot certify B.2 advancement by persisting arbitrary JSON."""
        store, delivery = await claimed_store()
        try:
            await store.prepare_application(
                delivery=delivery,
                event=application_event(
                    delivery=delivery, generation=delivery.envelope.submission.target.generation
                ),
            )
            with pytest.raises(MessageAdmissionError) as error:
                await store.commit_workflow_effect(
                    message_id=delivery.envelope.submission.message_id, outcome_json='{"status":"advanced"}'
                )
            assert error.value.error.code == "unsupported"
            assert (
                await store.load_workflow_effect(message_id=delivery.envelope.submission.message_id) is None
            )
        finally:
            await store.close()

    @pytest.mark.parametrize(
        "state,summary,ids",
        [
            ("committed", None, ()),
            ("prepared", str(uuid4()), ()),
            ("rolled_back", str(uuid4()), ()),
            ("prepared", None, ("duplicate",)),
        ],
    )
    async def test_invalid_compaction_dao_is_rejected(
        self, state: str, summary: str | None, ids: tuple[str, ...]
    ) -> None:
        """Membership is a unique set, and only committed coverage names a summary."""
        member = str(uuid4())
        with pytest.raises(ValidationError):
            CompactionLedgerDAO.model_validate(
                {
                    "compaction_id": str(uuid4()),
                    "state": state,
                    "message_ids": (member, member) if ids else (),
                    "observation_ids": (),
                    "summary_event_id": summary,
                }
            )

    async def test_receipt_state_cannot_claim_unproven_application(self) -> None:
        """Applied needs run/time; accepted cannot carry application or retained terminal data."""
        store, delivery = await claimed_store()
        try:
            base = dict(
                message_id=delivery.envelope.submission.message_id,
                target=delivery.envelope.submission.target,
                sequence=1,
                durable=False,
                admitted_at=delivery.envelope.admitted_at,
            )
            for fields in (
                {"state": "applied"},
                {"state": "accepted", "run_id": str(uuid4())},
                {"state": "cancelled", "retained_for_recovery": True},
            ):
                with pytest.raises(ValidationError):
                    MessageReceiptDAO.model_validate({**base, **fields})
        finally:
            await store.close()

    @pytest.mark.parametrize("principal_id", ["", "owner\n", "x" * 129])
    async def test_principal_identity_is_bounded(self, principal_id: str) -> None:
        """Lifetime identity rows cannot carry unbounded/control principal identifiers."""
        with pytest.raises(ValidationError):
            MessagePrincipalDAO(principal_id=principal_id, kind="human")

    async def test_source_identity_requires_matching_scheduler_author(self) -> None:
        """A text sender cannot reserve somebody else's source-event uniqueness key."""
        store, delivery = await claimed_store()
        source = f"schedule:{uuid4()}:{uuid4()}"
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=delivery.envelope.submission.target,
            kind="agent_input",
            text="forged source",
            source_event_id=source,
        )
        try:
            with pytest.raises(MessageAdmissionError) as error:
                await store.admit(submission=submission, principal=delivery.envelope.sender)
            assert error.value.error.code == "invalid_message"
            scheduler = MessagePrincipalDAO(principal_id="scheduler", kind="scheduler")
            first = await store.admit(submission=submission, principal=scheduler)
            with pytest.raises(MessageAdmissionError) as conflict:
                await store.admit(
                    submission=submission.model_copy(update={"message_id": str(uuid4())}), principal=scheduler
                )
            assert conflict.value.error.code == "conflict"
            assert await store.get_receipt(message_id=submission.message_id, principal=scheduler) == first
        finally:
            await store.close()
