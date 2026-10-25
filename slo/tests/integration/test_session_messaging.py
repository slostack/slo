"""Admission-only CD02 journeys through a real session and disposable SQLite."""

import asyncio
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
from src.agents.slo_agent.messaging.dao import (
    MessageAddressDAO,
    MessageAdmissionError,
    MessageErrorDAO,
    MessageEnvelopeDAO,
    MessageIdentityDAO,
    MessagePrincipalDAO,
    MessageReceiptDAO,
    MessageSubmissionDAO,
    MessagingLimitsDAO,
)
from src.agents.slo_agent.messaging.store import MessageStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession


def read_closed_message_rows(
    *, database_path: Path, temporary_root: Path
) -> tuple[tuple[str, int, str], ...]:
    """Read close-time retention without invoking a mutating adapter startup.

    The journey calls this on a worker only after session shutdown has joined.
    SQLite is opened read-only inside the test's resolved temporary root.
    """
    assert database_path.resolve().is_relative_to(temporary_root.resolve())
    connection: sqlite3.Connection = sqlite3.connect(database=f"{database_path.as_uri()}?mode=ro", uri=True)
    try:
        cursor: sqlite3.Cursor = connection.execute(
            "SELECT message_id, retained, state FROM messages ORDER BY sequence"
        )
        rows: tuple[tuple[str, int, str], ...] = tuple(cursor.fetchall())
        return rows
    finally:
        connection.close()


async def test_local_client_submit_receipt_milestone(tmp_path: Path) -> None:
    """Explicit start admits once, reads durably, and retains rather than delivers on close."""
    history_root: Path = tmp_path / "history"
    session_id: str = str(uuid4())
    database_path: Path = history_root / session_id / "messaging.v1.sqlite3"
    assert database_path.resolve().is_relative_to(tmp_path.resolve())
    config: SessionConfigDAO = SessionConfigDAO(
        workdir=tmp_path, session_id=session_id, history_root=history_root, model_name="gpt-5.4"
    )
    session: SloAgentSession = SloAgentSession.build(config=config)
    assert not database_path.exists()
    await session.start_messaging()
    await session._lock.acquire()  # Freeze execution, not admission, for this receipt/retention journey.
    target: MessageAddressDAO = session.messaging_target
    principal: MessagePrincipalDAO = session.messaging_owner_principal
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=target, principal=principal
    )
    submission: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()), target=target, kind="agent_input", text="Retain this exact input."
    )
    try:
        admission: MessageReceiptDAO | MessageErrorDAO = await client.submit(submission=submission)
        assert isinstance(admission, MessageReceiptDAO)
        assert admission.message_id == submission.message_id
        assert admission.target == target
        assert admission.sequence == 1
        assert admission.durable is True
        assert admission.state == "accepted"
        assert admission.run_id is None and admission.applied_at is None
        # Started compatibility invocation is now covered by the real delivery journeys.
        # This milestone verifies the original admission receipt without racing consumption.
        assert await client.get_receipt(message_id=submission.message_id) == admission
        assert await client.submit(submission=submission) == admission
        await client.close()
        assert await client.get_receipt(message_id=submission.message_id) == MessageErrorDAO(
            code="completing", message_id=submission.message_id
        )
        # Detachment does not close the borrowed session.
        second_client: LocalSessionMessagingClient = LocalSessionMessagingClient(
            session=session, target=target, principal=principal
        )
        try:
            assert await second_client.get_receipt(message_id=submission.message_id) == admission
        finally:
            await second_client.close()
    finally:
        await client.close()
        session._lock.release()
        await session.close_messaging()

    # Observe close's commit before MessageStore.open can reseal retained rows.
    # asyncio.to_thread's callable operand is positional-only.
    retained_before_reopen: tuple[tuple[str, int, str], ...] = await asyncio.to_thread(
        read_closed_message_rows, database_path=database_path, temporary_root=tmp_path
    )
    assert retained_before_reopen == ((submission.message_id, 1, "accepted"),)

    # A fresh real adapter verifies the actual database after session writers/lease joined.
    store: MessageStore = await MessageStore.open(
        path=database_path, target=target, limits=MessagingLimitsDAO()
    )
    try:
        receipt: MessageReceiptDAO | None = await store.get_receipt(
            message_id=submission.message_id, principal=principal
        )
        assert receipt is not None and receipt.state == "accepted"
        assert receipt.retained_for_recovery is True
        assert receipt.sequence == 1 and receipt.run_id is None and receipt.applied_at is None
        identities: tuple[MessageIdentityDAO, ...] = await store.read_identities()
        assert len(identities) == 1
        retained: tuple[MessageEnvelopeDAO, ...] = await store.read_retained()
        assert len(retained) == 1
        assert retained[0].submission == submission
        assert retained[0].sender == principal
        assert retained[0].sequence == receipt.sequence
    finally:
        await store.close()
