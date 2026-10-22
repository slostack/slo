"""Real closed-store failures notify already sleeping queue consumers."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.dao import MessageAddressDAO, MessageStoreError, MessagingLimitsDAO
from src.agents.slo_agent.messaging.queue import SessionMessageQueue
from src.agents.slo_agent.messaging.store import MessageStore


async def test_initial_refresh_failure_wakes_existing_waiter(tmp_path: Path) -> None:
    """A second wait's failed initial read must terminate the first wait too."""
    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
    queue = SessionMessageQueue(
        store=store,
        target=target,
        authorize=lambda submission, sender: None,
        authorize_read=lambda reader: None,
    )
    waiter = asyncio.create_task(queue.wait_for_work())
    try:
        async with asyncio.timeout(2):
            while not queue._changed._waiters:
                await asyncio.sleep(0)
        await store.close()
        with pytest.raises(MessageStoreError):
            await queue.wait_for_notes()
        with pytest.raises(MessageStoreError):
            await asyncio.wait_for(waiter, timeout=2)
        await queue.seal()
        with pytest.raises(MessageStoreError):
            await queue.wait_for_yield(after_sequence=0)
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        await store.close()


async def test_summary_failure_wakes_existing_waiter(tmp_path: Path) -> None:
    """Diagnostic read failures terminate consumers rather than stranding them."""
    from src.agents.slo_agent.messaging.dao import MessagePrincipalDAO

    target = MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))
    path = tmp_path / target.session_id / "messaging.v1.sqlite3"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
    queue = SessionMessageQueue(
        store=store,
        target=target,
        authorize=lambda submission, sender: None,
        authorize_read=lambda reader: None,
    )
    waiter = asyncio.create_task(queue.wait_for_notes())
    try:
        async with asyncio.timeout(2):
            while not queue._changed._waiters:
                await asyncio.sleep(0)
        await store.close()
        with pytest.raises(MessageStoreError):
            await queue.summary(principal=MessagePrincipalDAO(principal_id="owner", kind="human"))
        with pytest.raises(MessageStoreError):
            await asyncio.wait_for(waiter, timeout=2)
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        await store.close()
