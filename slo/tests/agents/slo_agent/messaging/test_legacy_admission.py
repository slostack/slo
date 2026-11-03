"""Trusted legacy capabilities and original admission proof over real SQLite."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest
from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient

from src.agents.slo_agent.messaging.dao import (
    LegacyInboxAdmissionDAO,
    MessageAdmissionError,
    MessageErrorDAO,
    MessageIdentityDAO,
    MessagePrincipalDAO,
    MessageReceiptDAO,
    MessageSubmissionDAO,
)
from tests.agents.slo_agent.messaging.test_delivery import RecordingModel
from tests.tui.test_durable_composer import _build_factory_session


@pytest.mark.parametrize(
    argnames="changes",
    argvalues=[
        {"message_id": "not-canonical"},
        {"text": " "},
        {"text": "x" * 65536},
        {"text": "\ud800"},
        {"target": {}},
        {"principal": {}},
    ],
)
def test_legacy_admission_rejects_invalid_or_authority_fields(changes: dict[str, object]) -> None:
    """Boundary validation rejects authority-bearing data and unrepresentable content."""
    values: dict[str, object] = {"message_id": str(uuid4()), "kind": "context_note", "text": "exact"}
    values.update(changes)
    with pytest.raises(ValueError):
        LegacyInboxAdmissionDAO.model_validate(values)


def test_legacy_admission_schema_describes_required_frozen_content() -> None:
    """Schema documents exact Inbox content without relaxing requiredness or validation."""
    schema = LegacyInboxAdmissionDAO.model_json_schema()
    assert set(schema["required"]) == {"message_id", "kind", "text"}
    assert schema["additionalProperties"] is False
    for name in ("message_id", "kind", "text"):
        assert schema["properties"][name]["description"].strip()
        assert "default" not in schema["properties"][name]
    assert schema["properties"]["kind"]["enum"] == ["agent_input", "context_note", "transcript_note"]
    admission = LegacyInboxAdmissionDAO(message_id=str(uuid4()), kind="context_note", text="exact")
    with pytest.raises(ValueError, match="frozen"):
        admission.text = "changed"
    with pytest.raises(ValueError):
        LegacyInboxAdmissionDAO.model_validate(
            {"message_id": admission.message_id, "kind": "ui_notice", "text": "exact"}
        )
    for name in ("message_id", "kind", "text"):
        values = admission.model_dump()
        del values[name]
        with pytest.raises(ValueError):
            LegacyInboxAdmissionDAO.model_validate(values)


async def test_forged_capabilities_are_unauthorized(tmp_path: Path) -> None:
    """Equal owner values and copied clients cannot register or discover identities."""
    model = RecordingModel(responses=[])
    session = _build_factory_session(tmp_path=tmp_path, model=model)
    await session.start_messaging()
    owner = session.messaging_owner_principal
    admission = LegacyInboxAdmissionDAO(message_id=str(uuid4()), kind="context_note", text="exact note")
    try:
        with pytest.raises(MessageAdmissionError) as refused:
            session.register_legacy_inbox_client(owner=owner.model_copy(), source="scheduler")
        assert refused.value.error.code == "unauthorized"
        client = session.register_legacy_inbox_client(owner=owner, source="scheduler")
        assert session.register_legacy_inbox_client(owner=owner, source="scheduler") is client
        for candidate_owner, candidate_client in [(owner.model_copy(), client), (owner, copy.copy(client))]:
            outcome = await session.get_legacy_inbox_admission(
                owner=candidate_owner, client=candidate_client, admission=admission
            )
            assert isinstance(outcome, MessageErrorDAO) and outcome.code == "unauthorized"
        outcome = await session.get_legacy_inbox_admission(owner=owner, client=client, admission=admission)
        assert isinstance(outcome, MessageErrorDAO) and outcome.code == "not_found"
        submission = MessageSubmissionDAO(
            message_id=admission.message_id,
            target=session.messaging_target,
            kind=admission.kind,
            text=admission.text,
            source_event_id="legacy-inbox:" + admission.message_id,
        )
        receipt = await client.submit(submission=submission)
        assert isinstance(receipt, MessageReceiptDAO)
        identity = await session.get_legacy_inbox_admission(owner=owner, client=client, admission=admission)
        assert isinstance(identity, MessageIdentityDAO)
        assert identity.sender == MessagePrincipalDAO(
            principal_id=f"legacy:scheduler:{session.session_id}", kind="scheduler"
        )
        assert identity.receipt.message_id == admission.message_id
        for changed in [
            admission.model_copy(update={"text": "changed"}),
            admission.model_copy(update={"kind": "transcript_note"}),
        ]:
            outcome = await session.get_legacy_inbox_admission(owner=owner, client=client, admission=changed)
            assert isinstance(outcome, MessageErrorDAO) and outcome.code == "conflict"
        foreign = session.register_legacy_inbox_client(owner=owner, source="workflow")
        outcome = await session.get_legacy_inbox_admission(owner=owner, client=foreign, admission=admission)
        assert isinstance(outcome, MessageErrorDAO) and outcome.code == "unauthorized"
        # Receipt-read authority must not leak into owner-only recovery or observation.
        principal = identity.sender
        # The equal decoded sender is deliberately not the registered capability.
        copied = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=principal
        )
        result = await copied.get_receipt(message_id=admission.message_id)
        assert isinstance(result, MessageErrorDAO) and result.code == "unauthorized"
        registered_principal = session._legacy_inbox_principals["scheduler"]
        retained = await session.list_retained_messages(principal=registered_principal)
        assert isinstance(retained, MessageErrorDAO) and retained.code == "unauthorized"
        stream = session.observe_messaging(principal=registered_principal)
        with pytest.raises(MessageAdmissionError) as observer_refused:
            await anext(stream)
        assert observer_refused.value.error.code == "unauthorized"
        invalid_submissions: list[tuple[dict[str, object], str]] = [
            ({"source_event_id": None}, "unauthorized"),
            ({"priority": "urgent", "kind": "agent_input"}, "unsupported"),
            ({"reply_to": str(uuid4())}, "unauthorized"),
            ({"workflow_id": "injected"}, "unauthorized"),
            ({"dispatch_id": str(uuid4())}, "unauthorized"),
        ]
        for update, code in invalid_submissions:
            result = await client.submit(submission=submission.model_copy(update=update))
            assert isinstance(result, MessageErrorDAO) and result.code == code
        assert not model.requests
    finally:
        await session.close_messaging()
    outcome = await session.get_legacy_inbox_admission(owner=owner, client=client, admission=admission)
    assert isinstance(outcome, MessageErrorDAO) and outcome.code == "unauthorized"


async def test_store_verify_admission_precedence(tmp_path: Path) -> None:
    """Foreign sender wins over changed digest; exact identity survives retained restart."""
    from src.agents.slo_agent.messaging.dao import MessageAddressDAO, MessagingLimitsDAO
    from src.agents.slo_agent.messaging.store import MessageStore

    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="legacy:workflow:test", kind="workflow")
    message_id = str(uuid4())
    submission = MessageSubmissionDAO(
        message_id=message_id,
        target=target,
        kind="context_note",
        text="exact",
        source_event_id="legacy-inbox:" + message_id,
    )
    path = tmp_path / "history" / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(path=path, target=target, limits=MessagingLimitsDAO())
    try:
        await store.set_lifecycle(accepting=True)
        receipt = await store.admit(submission=submission, principal=principal)
        identity = await store.verify_admission(submission=submission, principal=principal)
        assert identity.receipt == receipt
        changed = submission.model_copy(update={"text": "changed"})
        for sender, expected in [
            (MessagePrincipalDAO(principal_id="foreign", kind="workflow"), "unauthorized"),
            (principal, "conflict"),
        ]:
            with pytest.raises(MessageAdmissionError) as refused:
                await store.verify_admission(submission=changed, principal=sender)
            assert refused.value.error.code == expected
        with pytest.raises(MessageAdmissionError) as missing:
            await store.verify_admission(
                submission=submission.model_copy(update={"message_id": str(uuid4())}), principal=principal
            )
        assert missing.value.error.code == "not_found"
        invalid_senders: tuple[Literal["human", "scheduler"], ...] = ("human", "scheduler")
        for kind in invalid_senders:
            source = "legacy-inbox:" + str(uuid4())
            with pytest.raises(MessageAdmissionError) as invalid:
                await store.admit(
                    submission=submission.model_copy(
                        update={"message_id": str(uuid4()), "source_event_id": source}
                    ),
                    principal=MessagePrincipalDAO(principal_id="invalid", kind=kind),
                )
            assert invalid.value.error.code == "invalid_message"
    finally:
        await store.close()
