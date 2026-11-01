"""Persistent recipient-local recovery, distinct from ordinary live retry."""

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
    RecoveryTransferDAO,
)
from src.agents.slo_agent.messaging.store import MessageStore
from tests.agents.slo_agent.messaging.test_store import _digest_of


async def retained_original(
    *, root: Path
) -> tuple[MessageStore, MessageSubmissionDAO, MessagePrincipalDAO, MessageAddressDAO]:
    """Reopen a real recipient database under its second owner generation."""
    old = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    path = root / old.session_id / "messaging.v1.sqlite3"
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    submission = MessageSubmissionDAO(
        message_id=str(uuid4()), target=old, kind="agent_input", text="retained original"
    )
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=old)
    await store.set_lifecycle(accepting=True)
    await store.admit(submission=submission, principal=principal)
    await store.close()
    current = old.model_copy(update={"generation": str(uuid4())})
    reopened = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=current)
    return reopened, submission, principal, current


def transfer_for(
    *, original: MessageSubmissionDAO, sender: MessagePrincipalDAO, destination: MessageAddressDAO
) -> RecoveryTransferDAO:
    """Bind consent evidence to immutable original bytes, author and current destination."""
    return RecoveryTransferDAO(
        transfer_id=str(uuid4()),
        original=original,
        original_sender=sender,
        original_digest=_digest_of(submission=original, principal=sender),
        destination=destination,
    )


class TestLocalRecovery:
    @pytest.mark.parametrize("alteration", ["bytes", "sender", "destination", "confirmer"])
    async def test_confirmed_record_must_match_recipient_identity(
        self, tmp_path: Path, alteration: str
    ) -> None:
        """Self-consistent caller hashes cannot replace the stored original proof."""
        store, original, sender, current = await retained_original(root=tmp_path)
        selected = original.model_copy(update={"text": "forged"}) if alteration == "bytes" else original
        author = sender.model_copy(update={"session_id": str(uuid4())}) if alteration == "sender" else sender
        destination = (
            current.model_copy(update={"session_id": str(uuid4())})
            if alteration == "destination"
            else current
        )
        confirmer = (
            MessagePrincipalDAO(principal_id="agent", kind="agent") if alteration == "confirmer" else sender
        )
        try:
            before = await store.get_receipt(message_id=original.message_id, principal=sender)
            with pytest.raises(MessageAdmissionError):
                await store.recover(
                    transfer=transfer_for(original=selected, sender=author, destination=destination),
                    principal=confirmer,
                )
            assert await store.get_receipt(message_id=original.message_id, principal=sender) == before
        finally:
            await store.close()

    async def test_two_generations_replay_original_outcome_and_confirmer(self, tmp_path: Path) -> None:
        """A lost response reuses immutable transfer outcome, not a fresh acceptance."""
        store, original, sender, current = await retained_original(root=tmp_path)
        transfer = transfer_for(original=original, sender=sender, destination=current)
        path = tmp_path / current.session_id / "messaging.v1.sqlite3"
        try:
            outcome = await store.recover(transfer=transfer, principal=sender)
            assert outcome.receipt.target == original.target
            assert outcome.execution_generation == current.generation
            assert outcome.receipt.sequence == 1
            await store.set_lifecycle(accepting=True)
            delivery = await store.claim_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0))
            assert delivery is not None and delivery.envelope.submission == original
        finally:
            await store.close()
        third = current.model_copy(update={"generation": str(uuid4())})
        store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=third)
        try:
            assert await store.recover(transfer=transfer, principal=sender) == outcome
            with pytest.raises(MessageAdmissionError) as error:
                await store.recover(
                    transfer=transfer, principal=sender.model_copy(update={"session_id": str(uuid4())})
                )
            assert error.value.error.code == "unauthorized"
        finally:
            await store.close()

    async def test_reset_claim_is_retained_not_automatically_reexecuted(self, tmp_path: Path) -> None:
        """Reset removes claim identity without granting execution permission."""
        store, original, sender, current = await retained_original(root=tmp_path)
        try:
            await store.recover(
                transfer=transfer_for(original=original, sender=sender, destination=current), principal=sender
            )
            await store.set_lifecycle(accepting=True)
            boundary = BoundaryDAO(run_id=str(uuid4()), boundary_index=0)
            assert await store.claim_one(boundary=boundary) is not None
            await store.reset_unprepared_claims()
            receipt = await store.get_receipt(message_id=original.message_id, principal=sender)
            assert receipt is not None and receipt.retained_for_recovery and receipt.state == "accepted"
            assert await store.claim_one(boundary=boundary) is None
        finally:
            await store.close()

    async def test_ephemeral_recovery_is_unsupported(self) -> None:
        """No durable recipient evidence means no persistent recovery capability."""
        target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
        store = await MessageStore.open(path=None, limits=MessagingLimitsDAO(), target=target)
        sender = MessagePrincipalDAO(principal_id="owner", kind="human")
        original = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="local"
        )
        try:
            await store.set_lifecycle(accepting=True)
            await store.admit(submission=original, principal=sender)
            await store.retain_pending()
            with pytest.raises(MessageAdmissionError) as error:
                await store.recover(
                    transfer=transfer_for(original=original, sender=sender, destination=target),
                    principal=sender,
                )
            assert error.value.error.code == "unsupported"
        finally:
            await store.close()
