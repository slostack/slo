"""Module-entry journeys through the real queue and disposable SQLite store."""

import asyncio
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.dao import (
    BoundaryDAO,
    MessageAddressDAO,
    MessageAdmissionError,
    MessageErrorDAO,
    MessagePrincipalDAO,
    MessageSubmissionDAO,
    MessagingLimitsDAO,
)
from src.agents.slo_agent.messaging.queue import SessionMessageQueue
from src.agents.slo_agent.messaging.store import MessageStore
from tests.agents.slo_agent.messaging.test_store_journey import application_event


class RegisteredAuthority:
    """Injected synchronous authority stub; not actual session registration."""

    def __init__(self, *, principal: MessagePrincipalDAO) -> None:
        """Bind one identity whose authority can later be revoked."""
        self.principal = principal
        self.allowed = True
        self.calls = 0

    def authorize(self, submission: MessageSubmissionDAO, principal: MessagePrincipalDAO) -> None:
        """Reject revoked identity or unavailable capabilities without I/O."""
        self.calls += 1
        if not self.allowed or principal != self.principal:
            raise MessageAdmissionError(error=MessageErrorDAO(code="unauthorized"))
        if submission.kind != "agent_input" or submission.payload.type != "text":
            raise MessageAdmissionError(error=MessageErrorDAO(code="unsupported"))


async def test_durable_priority_fifo_and_stable_boundary(tmp_path: Path) -> None:
    """Admitted inputs read back durably and claim once in priority/FIFO order."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    authority = RegisteredAuthority(principal=principal)
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
    try:
        await store.set_lifecycle(accepting=True)
        queue = SessionMessageQueue(
            store=store, target=target, authorize=authority.authorize, authorize_read=lambda reader: None
        )
        assert authority.calls == 0
        ordered_inputs: list[tuple[str, Literal["normal", "urgent"]]] = [
            ("normal1", "normal"),
            ("urgent1", "urgent"),
            ("urgent2", "urgent"),
            ("normal2", "normal"),
        ]
        submissions = [
            MessageSubmissionDAO(
                message_id=str(uuid4()), target=target, kind="agent_input", text=text, priority=priority
            )
            for text, priority in ordered_inputs
        ]
        for submission in submissions:
            receipt = await queue.admit(submission=submission, principal=principal)
            assert receipt is not None and receipt.durable and receipt.state == "accepted"
            assert await store.get_receipt(message_id=submission.message_id, principal=principal) == receipt
            assert await queue.admit(submission=submission, principal=principal) == receipt
        assert (await store.read_queue_state()).eligible_inputs == 4
        run_id = str(uuid4())
        for index, expected in enumerate([submissions[1], submissions[2], submissions[0], submissions[3]]):
            boundary = BoundaryDAO(run_id=run_id, boundary_index=index)
            delivery = await queue.take_one(boundary=boundary)
            assert delivery is not None and delivery.envelope.submission == expected
            assert await queue.take_one(boundary=boundary) == delivery
            event = application_event(delivery=delivery, generation=target.generation)
            await store.prepare_application(delivery=delivery, event=event)
            await store.mark_history_committed(message_id=expected.message_id)
            await store.mark_applied(message_id=expected.message_id)
            assert await queue.take_one(boundary=boundary) is None
        assert (await store.read_queue_state()).eligible_inputs == 0
    finally:
        await store.close()


async def test_work_and_yield_wait_on_eligibility_and_seal(tmp_path: Path) -> None:
    """Waiters wake after durable admission, not for old urgency; seal releases them."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    authority = RegisteredAuthority(principal=principal)
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
    waiters: list[asyncio.Task[None]] = []
    try:
        await store.set_lifecycle(accepting=True)
        queue = SessionMessageQueue(
            store=store, target=target, authorize=authority.authorize, authorize_read=lambda reader: None
        )
        work = asyncio.create_task(queue.wait_for_work())
        urgency = asyncio.create_task(queue.wait_for_yield(after_sequence=0))
        waiters.extend([work, urgency])
        await asyncio.sleep(0)
        assert not work.done() and not urgency.done()
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="urgent", priority="urgent"
        )
        receipt = await queue.admit(submission=submission, principal=principal)
        await asyncio.wait_for(asyncio.gather(work, urgency), timeout=2)
        assert await store.get_receipt(message_id=submission.message_id, principal=principal) == receipt
        old_urgency = asyncio.create_task(queue.wait_for_yield(after_sequence=receipt.sequence))
        waiters.append(old_urgency)
        await asyncio.sleep(0)
        assert not old_urgency.done()
        await queue.take_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0))
        no_work = asyncio.create_task(queue.wait_for_work())
        waiters.append(no_work)
        await asyncio.sleep(0)
        assert not no_work.done()
        await asyncio.wait_for(queue.seal(), timeout=2)
        await asyncio.wait_for(asyncio.gather(old_urgency, no_work), timeout=2)
    finally:
        for waiter in waiters:
            waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)
        await store.close()


async def test_bound_authority_and_seal_refuse_without_admission(tmp_path: Path) -> None:
    """Revocation and queue seal are rechecked on every new admission."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    principal = MessagePrincipalDAO(principal_id="owner", kind="human")
    authority = RegisteredAuthority(principal=principal)
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
    submission = MessageSubmissionDAO(message_id=str(uuid4()), target=target, kind="agent_input", text="held")
    try:
        await store.set_lifecycle(accepting=True)
        queue = SessionMessageQueue(
            store=store, target=target, authorize=authority.authorize, authorize_read=lambda reader: None
        )
        authority.allowed = False
        with pytest.raises(MessageAdmissionError, match="unauthorized"):
            await queue.admit(submission=submission, principal=principal)
        assert await store.get_receipt(message_id=submission.message_id, principal=principal) is None
        authority.allowed = True
        await queue.seal()
        with pytest.raises(MessageAdmissionError, match="completing"):
            await queue.admit(submission=submission, principal=principal)
        assert await store.get_receipt(message_id=submission.message_id, principal=principal) is None
    finally:
        await store.close()
