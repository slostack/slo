"""Real restart and explicit owner-consent recovery journeys (DC05)."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.messaging.dao import (
    MessageAddressDAO,
    MessageErrorDAO,
    MessagePrincipalDAO,
    MessageSubmissionDAO,
    MessagingLimitsDAO,
    RecoveryConfirmationDAO,
    VerifiedRecoverySourceDAO,
    utcnow,
)
from src.agents.slo_agent.messaging.store import MessageStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.agents.slo_agent.messaging.test_delivery import RecordingModel, RealAgentFactory
from tests.integration.test_session_messaging import read_closed_message_rows


class RecoveryClock:
    """Advance consent time without sleeping or replacing runtime internals."""

    def __init__(self) -> None:
        """Start at current aware UTC."""
        self.now: datetime = utcnow()

    def __call__(self) -> datetime:
        """Return the test-owned consent time."""
        return self.now


async def restart_retained(
    *,
    root: Path,
    tree: bool = False,
    count: int = 2,
    session_type: type[SloAgentSession] = SloAgentSession,
) -> tuple[
    SloAgentSession,
    RecordingModel,
    tuple[MessageSubmissionDAO, ...],
    MessagePrincipalDAO,
    RecoveryClock,
    FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore,
]:
    """Close an old real session's store, then start a new owner on its history."""
    history_root = root / "history"
    assert history_root.resolve().is_relative_to(root.resolve())
    session_id = str(uuid4())
    history = (
        TreeBasedFilesystemSessionHistoryStore(root=history_root)
        if tree
        else FilesystemSessionHistoryStore(root=history_root)
    )
    await history.ensure_session(session_id=session_id, workdir=root, model_name="gpt-5.4")
    target = MessageAddressDAO(kind="agent_session", session_id=session_id, generation=str(uuid4()))
    sender = MessagePrincipalDAO(principal_id="old-owner", kind="human")
    originals = tuple(
        MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=target,
            kind="agent_input",
            text=f"Original {index} — exact\nbytes",
        )
        for index in range(count)
    )
    store = await MessageStore.open(
        path=history_root / session_id / "messaging.v1.sqlite3", limits=MessagingLimitsDAO(), target=target
    )
    try:
        await store.set_lifecycle(accepting=True)
        for submission in originals:
            await store.admit(submission=submission, principal=sender)
    finally:
        await store.close()
    model = RecordingModel(responses=[FauxChatModel.assistant_message(content="continued")])
    model.release.set()
    clock = RecoveryClock()
    session = session_type(
        workdir=root,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=root, history_root=history_root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=root),
        messaging_clock=clock,
    )
    await session.start_messaging()
    return session, model, originals, sender, clock, history


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True], ids=["flat", "tree"])
async def test_confirmed_continue_executes_original_once(tmp_path: Path, tree: bool) -> None:
    """Restart is inert; consent changes generation, never original identity or bytes."""
    session, model, originals, sender, _, history = await restart_retained(root=tmp_path, tree=tree)
    try:
        principal = session.messaging_owner_principal
        page = await session.list_retained_messages(principal=principal, limit=1)
        assert not isinstance(page, MessageErrorDAO)
        assert [item.submission for item in page.items] == [originals[0]]
        assert page.next_after_sequence == 1 and not model.requests
        preview = await session.preview_retained_message(
            message_id=originals[0].message_id, principal=principal
        )
        assert isinstance(preview, RecoveryConfirmationDAO)
        assert preview.transfer.original == originals[0] and preview.transfer.original_sender == sender
        outcome = await session.recover_message(confirmation=preview, principal=principal)
        assert not isinstance(outcome, MessageErrorDAO)
        assert outcome.receipt.target == originals[0].target
        assert outcome.execution_generation == session.messaging_target.generation
        assert await session.recover_message(confirmation=preview, principal=principal) == outcome
        async with asyncio.timeout(5):
            while (
                not (await history.application_evidence(session_id=session.session_id)).events
                or session.is_running
            ):
                await asyncio.sleep(0.01)
        assert len(model.requests) == 1
        assert [m.content for m in model.requests[0] if isinstance(m, HumanMessage)] == [originals[0].text]
        page = await session.list_retained_messages(principal=principal)
        assert not isinstance(page, MessageErrorDAO)
        assert [item.submission for item in page.items] == [originals[1]]
    finally:
        await session.close_messaging()
    path = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    with sqlite3.connect(database=path) as connection:
        assert connection.execute("SELECT count(*) FROM recovery_transfers").fetchone() == (1,)
        stored = connection.execute(
            "SELECT submission_json FROM messages WHERE message_id=?", (originals[0].message_id,)
        ).fetchone()
        assert MessageSubmissionDAO.model_validate_json(stored[0]) == originals[0]
    assert read_closed_message_rows(database_path=path, temporary_root=tmp_path) == (
        (originals[0].message_id, 0, "applied"),
        (originals[1].message_id, 1, "accepted"),
    )


async def test_expired_preview_requires_new_consent(tmp_path: Path) -> None:
    """Expiry forbids an uncommitted transfer and preserves retained bytes."""
    session, model, originals, _, clock, _ = await restart_retained(root=tmp_path)
    try:
        principal = session.messaging_owner_principal
        preview = await session.preview_retained_message(
            message_id=originals[0].message_id, principal=principal
        )
        assert isinstance(preview, RecoveryConfirmationDAO)
        clock.now += timedelta(minutes=6)
        outcome = await session.recover_message(confirmation=preview, principal=principal)
        assert isinstance(outcome, MessageErrorDAO) and outcome.code == "conflict"
        page = await session.list_retained_messages(principal=principal)
        assert not isinstance(page, MessageErrorDAO) and len(page.items) == 2
        assert not model.requests
    finally:
        await session.close_messaging()


async def test_changed_selection_refuses_stale_consent(tmp_path: Path) -> None:
    """Cancelling another consent's selected input invalidates stale continuation."""
    from src.agents.slo_agent.messaging.dao import CancelRecoveryConfirmationDAO

    session, model, originals, _, _, _ = await restart_retained(root=tmp_path)
    try:
        principal = session.messaging_owner_principal
        preview = await session.preview_retained_message(
            message_id=originals[0].message_id, principal=principal
        )
        assert isinstance(preview, RecoveryConfirmationDAO)
        cancel = await session.preview_cancel_retained(
            message_ids=(originals[0].message_id,), principal=principal
        )
        assert isinstance(cancel, CancelRecoveryConfirmationDAO)
        cancelled = await session.cancel_retained_messages(confirmation=cancel, principal=principal)
        assert not isinstance(cancelled, MessageErrorDAO)
        outcome = await session.recover_message(confirmation=preview, principal=principal)
        assert isinstance(outcome, MessageErrorDAO) and outcome.code == "conflict"
        assert not model.requests
    finally:
        await session.close_messaging()


async def test_cancel_is_all_or_none_and_replay_safe(tmp_path: Path) -> None:
    """Concurrent confirmations commit one exact ordered selection without provider work."""
    from src.agents.slo_agent.messaging.dao import CancelRecoveryConfirmationDAO, CancelRecoveryOutcomeDAO

    session, model, originals, _, clock, _ = await restart_retained(root=tmp_path)
    try:
        principal = session.messaging_owner_principal
        message_ids = tuple(submission.message_id for submission in reversed(originals))
        preview = await session.preview_cancel_retained(message_ids=message_ids, principal=principal)
        assert isinstance(preview, CancelRecoveryConfirmationDAO)
        outcomes = await asyncio.gather(
            session.cancel_retained_messages(confirmation=preview, principal=principal),
            session.cancel_retained_messages(confirmation=preview, principal=principal),
        )
        assert isinstance(outcomes[0], CancelRecoveryOutcomeDAO) and outcomes[0] == outcomes[1]
        assert tuple(receipt.message_id for receipt in outcomes[0].receipts) == message_ids
        assert session._message_queue is not None
        session.abort()
        await session._message_queue.seal()
        clock.now += timedelta(minutes=6)
        assert (
            await session.cancel_retained_messages(confirmation=preview, principal=principal) == outcomes[0]
        )
        page = await session.list_retained_messages(principal=principal)
        assert not isinstance(page, MessageErrorDAO) and not page.items
        assert not model.requests
    finally:
        await session.close_messaging()
    assert read_closed_message_rows(
        database_path=tmp_path / "history" / session.session_id / "messaging.v1.sqlite3",
        temporary_root=tmp_path,
    ) == tuple((s.message_id, 0, "cancelled") for s in originals)


async def test_consent_requires_session_registered_sources_and_capacity(tmp_path: Path) -> None:
    """Equal caller-created sources, modified consent and seventeenth previews never authorize."""
    session, model, originals, _, clock, history = await restart_retained(root=tmp_path)
    principal = session.messaging_owner_principal
    try:
        preview = await session.preview_retained_message(
            message_id=originals[0].message_id, principal=principal
        )
        assert isinstance(preview, RecoveryConfirmationDAO)
        source = VerifiedRecoverySourceDAO(
            transfer=preview.transfer,
            source_kind="recipient",
            source_key="recipient:" + originals[0].message_id,
            evidence_sha256=preview.evidence_sha256,
        )
        forged = await session.preview_recovery(source=source, principal=principal)
        assert isinstance(forged, MessageErrorDAO) and forged.code == "unauthorized"
        changed = await session.recover_message(
            confirmation=preview.model_copy(update={"evidence_sha256": "0" * 64}), principal=principal
        )
        assert isinstance(changed, MessageErrorDAO) and changed.code == "unauthorized"
        for _ in range(15):
            assert isinstance(
                await session.preview_retained_message(
                    message_id=originals[0].message_id, principal=principal
                ),
                RecoveryConfirmationDAO,
            )
        full = await session.preview_retained_message(message_id=originals[1].message_id, principal=principal)
        assert isinstance(full, MessageErrorDAO) and full.code == "queue_full"
        clock.now += timedelta(minutes=5)
        assert isinstance(
            await session.preview_retained_message(message_id=originals[1].message_id, principal=principal),
            RecoveryConfirmationDAO,
        )
        assert not model.requests
    finally:
        await session.close_messaging()
    successor = SloAgentSession(
        workdir=tmp_path,
        session_id=session.session_id,
        config=SessionConfigDAO(
            workdir=tmp_path,
            history_root=tmp_path / "history",
            session_id=session.session_id,
            model_name="gpt-5.4",
        ),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    try:
        await successor.start_messaging()
        refused = await successor.recover_message(
            confirmation=preview, principal=successor.messaging_owner_principal
        )
        assert isinstance(refused, MessageErrorDAO) and refused.code == "unauthorized"
        assert not model.requests
    finally:
        await successor.close_messaging()


async def test_lost_reply_retry_returns_saved_outcome(tmp_path: Path) -> None:
    """Store commit without a session-cache reply is replayed before expiry/state checks."""
    session, model, originals, _, clock, _ = await restart_retained(root=tmp_path)
    try:
        principal = session.messaging_owner_principal
        confirmation = await session.preview_retained_message(
            message_id=originals[0].message_id, principal=principal
        )
        assert isinstance(confirmation, RecoveryConfirmationDAO)
        # Exercise the existing queue commit seam to simulate a lost result before cache publication.
        assert session._message_queue is not None
        committed = await session._message_queue.recover(transfer=confirmation.transfer, principal=principal)
        clock.now += timedelta(minutes=6)
        assert await session.recover_message(confirmation=confirmation, principal=principal) == committed
        assert await session.recover_message(confirmation=confirmation, principal=principal) == committed
    finally:
        model.release.set()
        await session.close_messaging()
    path = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    with sqlite3.connect(database=f"{path.as_uri()}?mode=ro", uri=True) as connection:
        assert connection.execute("SELECT count(*) FROM recovery_transfers").fetchone() == (1,)


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True], ids=["flat", "tree"])
async def test_restart_reconciles_without_provider_and_lists_retained(tmp_path: Path, tree: bool) -> None:
    """One startup reconciles applying/applied/compacted records and retains only pending input."""
    from src.agents.slo_agent.compaction.compacter import CompactionResult
    from src.agents.slo_agent.messaging.dao import BoundaryDAO
    from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
    from tests.agents.slo_agent.messaging.test_store_journey import application_event

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id = str(uuid4())
    history = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    await history.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    target = MessageAddressDAO(kind="agent_session", session_id=session_id, generation=str(uuid4()))
    sender = MessagePrincipalDAO(principal_id="previous-owner", kind="human")
    store = await MessageStore.open(
        path=root / session_id / "messaging.v1.sqlite3", limits=MessagingLimitsDAO(), target=target
    )
    submissions = tuple(
        MessageSubmissionDAO(message_id=str(uuid4()), target=target, kind="agent_input", text=stage)
        for stage in ("compacted", "applied", "applying", "pending")
    )
    try:
        await store.set_lifecycle(accepting=True)
        compacted_event = None
        for index, submission in enumerate(submissions):
            await store.admit(submission=submission, principal=sender)
            if index == 3:
                continue
            delivery = await store.claim_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0))
            assert delivery is not None
            event = application_event(delivery=delivery, generation=target.generation)
            await store.prepare_application(delivery=delivery, event=event)
            if index == 2:
                continue
            await history.append_message_application_once(event=event)
            await store.mark_history_committed(message_id=submission.message_id)
            await store.mark_applied(message_id=submission.message_id)
            if index == 0:
                compacted_event = event
                retained = await history.append_event(
                    event=SessionHistoryEventDAO(session_id=session_id, kind="run_completed")
                )
                compaction_id = str(uuid4())
                await store.prepare_compaction(
                    compaction_id=compaction_id, message_ids=(submission.message_id,), observation_ids=()
                )
                summary = await history.compact_to_boundary(
                    session_id=session_id,
                    events=list((await history.application_evidence(session_id=session_id)).events),
                    result=CompactionResult(
                        summary_text="Earlier compacted input",
                        first_kept_entry_id=retained.event_id,
                        cut_point_entry_id=event.event_id,
                        tokens_before=100,
                        tokens_after=10,
                    ),
                    turn_id=str(uuid4()),
                    messaging_compaction_id=compaction_id,
                )
                await store.finish_compaction(compaction_id=compaction_id, summary_event_id=summary.event_id)
    finally:
        await store.close()
    model = RecordingModel(responses=[])
    config = SessionConfigDAO(
        workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
    )
    for _ in range(2):
        session = SloAgentSession(
            workdir=tmp_path,
            session_id=session_id,
            config=config,
            history_store=history,
            messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
        )
        try:
            await session.start_messaging()
            page = await session.list_retained_messages(principal=session.messaging_owner_principal)
            assert not isinstance(page, MessageErrorDAO)
            assert tuple(item.submission for item in page.items) == (submissions[3],)
            evidence = await history.application_evidence(session_id=session_id)
            assert sum(event.payload.content == "applying" for event in evidence.events) == 1
            assert sum(event.payload.content == "applied" for event in evidence.events) == 1
            assert compacted_event is not None
            assert all(event.event_id != compacted_event.event_id for event in evidence.events)
            assert not model.requests and not session.is_running
        finally:
            await session.close_messaging()
    assert read_closed_message_rows(
        database_path=root / session_id / "messaging.v1.sqlite3", temporary_root=tmp_path
    ) == (
        (submissions[0].message_id, 0, "applied"),
        (submissions[1].message_id, 0, "applied"),
        (submissions[2].message_id, 0, "applied"),
        (submissions[3].message_id, 1, "accepted"),
    )


async def test_retained_paging_validation_and_owner_authority(tmp_path: Path) -> None:
    """Strict page limits, exclusive cursors and owner authorization never mutate retained work."""
    session, model, originals, _, _, _ = await restart_retained(root=tmp_path, count=17)
    try:
        principal = session.messaging_owner_principal
        page = await session.list_retained_messages(principal=principal)
        assert not isinstance(page, MessageErrorDAO) and len(page.items) == 16
        assert page.next_after_sequence == 16
        tail = await session.list_retained_messages(principal=principal, after_sequence=16)
        assert not isinstance(tail, MessageErrorDAO)
        assert tuple(item.submission for item in tail.items) == (originals[-1],)
        assert tail.next_after_sequence is None
        for cursor, limit in ((-1, 16), (True, 16), (0, True), (0, 0), (0, 17)):
            error = await session.list_retained_messages(
                principal=principal, after_sequence=cursor, limit=limit
            )
            assert isinstance(error, MessageErrorDAO) and error.code == "invalid_message"
        foreign = principal.model_copy(update={"principal_id": "foreign"})
        error = await session.list_retained_messages(principal=foreign)
        assert isinstance(error, MessageErrorDAO) and error.code == "unauthorized"
        for message_id in ("bad", str(uuid4())):
            preview_error = await session.preview_retained_message(message_id=message_id, principal=principal)
            assert isinstance(preview_error, MessageErrorDAO) and preview_error.code == "invalid_message"
        for selected in (
            (),
            ("bad",),
            (originals[0].message_id,) * 2,
            tuple(s.message_id for s in originals),
        ):
            cancel_error = await session.preview_cancel_retained(message_ids=selected, principal=principal)
            assert isinstance(cancel_error, MessageErrorDAO) and cancel_error.code == "invalid_message"
        assert not model.requests
    finally:
        await session.close_messaging()


async def test_cancel_expiry_mixed_selection_and_committed_replay(tmp_path: Path) -> None:
    """Expired and mixed selections refuse atomically; committed cancellation bypasses expiry."""
    from src.agents.slo_agent.messaging.dao import CancelRecoveryConfirmationDAO

    session, model, originals, _, clock, _ = await restart_retained(root=tmp_path)
    try:
        principal = session.messaging_owner_principal
        ids = tuple(s.message_id for s in originals)
        preview = await session.preview_cancel_retained(message_ids=ids, principal=principal)
        assert isinstance(preview, CancelRecoveryConfirmationDAO)
        # An action-specific token cannot authorize continuation, even with an existing UUID.
        wrong = await session.recover_message(confirmation=preview, principal=principal)  # type: ignore[arg-type]
        assert isinstance(wrong, MessageErrorDAO) and wrong.code == "unauthorized"
        clock.now += timedelta(minutes=5)
        expired = await session.cancel_retained_messages(confirmation=preview, principal=principal)
        assert isinstance(expired, MessageErrorDAO) and expired.code == "conflict"
        fresh = await session.preview_cancel_retained(message_ids=ids, principal=principal)
        assert isinstance(fresh, CancelRecoveryConfirmationDAO)
        single = await session.preview_cancel_retained(message_ids=ids[:1], principal=principal)
        assert isinstance(single, CancelRecoveryConfirmationDAO)
        assert not isinstance(
            await session.cancel_retained_messages(confirmation=single, principal=principal), MessageErrorDAO
        )
        mixed = await session.cancel_retained_messages(confirmation=fresh, principal=principal)
        assert isinstance(mixed, MessageErrorDAO) and mixed.code == "conflict"
        page = await session.list_retained_messages(principal=principal)
        assert (
            not isinstance(page, MessageErrorDAO) and tuple(e.submission for e in page.items) == originals[1:]
        )
        last = await session.preview_cancel_retained(message_ids=ids[1:], principal=principal)
        assert isinstance(last, CancelRecoveryConfirmationDAO)
        # Simulate committed cancellation whose response was lost before preview cache publication.
        assert session._message_queue is not None
        await session._message_queue.cancel_retained(message_ids=ids[1:])
        session.abort()
        await session._message_queue.seal()
        # Durable replay, like cached replay, remains valid after the cutoff.
        clock.now += timedelta(minutes=6)
        outcome = await session.cancel_retained_messages(confirmation=last, principal=principal)
        assert not isinstance(outcome, MessageErrorDAO)
        assert outcome.receipts[0].state == "cancelled" and not model.requests
    finally:
        await session.close_messaging()


async def test_sealed_recovery_refuses_without_mutation(tmp_path: Path) -> None:
    """Seal refuses new continuation/cancellation while the session stays open, without mutation."""
    from src.agents.slo_agent.messaging.dao import CancelRecoveryConfirmationDAO

    session, model, originals, _, _, _ = await restart_retained(root=tmp_path)
    principal = session.messaging_owner_principal
    preview = await session.preview_retained_message(message_id=originals[0].message_id, principal=principal)
    cancel = await session.preview_cancel_retained(
        message_ids=(originals[1].message_id,), principal=principal
    )
    assert isinstance(preview, RecoveryConfirmationDAO) and isinstance(cancel, CancelRecoveryConfirmationDAO)
    try:
        assert session._message_queue is not None
        # Pause consumers before a standalone queue seal: finite/stop normally owns
        # their exit. Keep the session open and owner-authorized for this cutoff.
        session.abort()
        await session._message_queue.seal()
        outcome = await session.recover_message(confirmation=preview, principal=principal)
        assert isinstance(outcome, MessageErrorDAO) and outcome.code == "completing"
        cancelled = await session.cancel_retained_messages(confirmation=cancel, principal=principal)
        assert isinstance(cancelled, MessageErrorDAO) and cancelled.code == "completing"
        page = await session.list_retained_messages(principal=principal)
        assert not isinstance(page, MessageErrorDAO)
        assert tuple(item.submission for item in page.items) == originals
        assert not model.requests
    finally:
        await session.close_messaging()
    cancelled = await session.cancel_retained_messages(confirmation=cancel, principal=principal)
    assert isinstance(cancelled, MessageErrorDAO) and cancelled.code == "completing"
    assert read_closed_message_rows(
        database_path=tmp_path / "history" / session.session_id / "messaging.v1.sqlite3",
        temporary_root=tmp_path,
    ) == tuple((s.message_id, 1, "accepted") for s in originals)


def test_recovery_boundary_schema_describes_fields_without_relaxing_validation() -> None:
    """The ten recovery fields document consent without changing constraints or requiredness."""
    from pydantic import ValidationError
    from src.agents.slo_agent.messaging.dao import (
        CancelRecoveryConfirmationDAO,
        CancelRecoveryOutcomeDAO,
        RetainedSelectionDAO,
    )

    for record in (RetainedSelectionDAO, CancelRecoveryConfirmationDAO, CancelRecoveryOutcomeDAO):
        schema = record.model_json_schema()
        assert all(field.get("description") for field in schema["properties"].values())
    selection = RetainedSelectionDAO.model_json_schema()
    assert set(selection["required"]) == {"target", "items"}
    assert selection["properties"]["items"]["maxItems"] == 16
    assert RetainedSelectionDAO.model_fields["next_after_sequence"].default is None
    confirmation = CancelRecoveryConfirmationDAO.model_json_schema()
    assert set(confirmation["required"]) == {
        "confirmation_id",
        "target",
        "message_ids",
        "evidence_sha256",
        "expires_at",
    }
    assert confirmation["properties"]["message_ids"]["minItems"] == 1
    assert confirmation["properties"]["message_ids"]["maxItems"] == 16
    with pytest.raises(ValidationError):
        CancelRecoveryConfirmationDAO(
            confirmation_id="invalid",
            target=MessageAddressDAO(
                kind="agent_session",
                session_id=str(uuid4()),
                generation=str(uuid4()),
            ),
            message_ids=(),
            evidence_sha256="bad",
            expires_at=datetime.now(),
        )
