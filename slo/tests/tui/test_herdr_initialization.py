"""Owned mount initialization barriers with real temporary delivery stores."""

import asyncio
from pathlib import Path
from unittest.mock import patch

from src.agents.slo_agent.history.inbox.dao import SessionOwnershipLeaseDAO
from src.agents.slo_agent.history.inbox.lease import SessionOwnershipLeaseStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI


async def test_mount_initialization_is_joined_before_shutdown(tmp_path: Path) -> None:
    """Unmount cannot finish while an acquired mount lease is still being returned."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    entered = asyncio.Event()
    release = asyncio.Event()
    original = SessionOwnershipLeaseStore.acquire

    async def acquire(
        self: SessionOwnershipLeaseStore, *, session_id: str, owner_id: str, ttl_seconds: float
    ) -> SessionOwnershipLeaseDAO:
        """Hold the real persisted acquisition before returning to its caller."""
        lease = await original(self, session_id=session_id, owner_id=owner_id, ttl_seconds=ttl_seconds)
        entered.set()
        await release.wait()
        return lease

    async def cutoff() -> None:
        """Drive shutdown independently while Textual is still inside mount."""
        await asyncio.wait_for(entered.wait(), timeout=5)
        shutdown = asyncio.create_task(coro=app.on_unmount())
        try:
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert app._app_closing
            retained = getattr(app, "_mount_runtime_task", None)
            assert retained is not None and not retained.done()
            assert not shutdown.done()
        finally:
            release.set()
            await asyncio.wait_for(shutdown, timeout=5)

    with patch.object(SessionOwnershipLeaseStore, "acquire", new=acquire):
        observer = asyncio.create_task(coro=cutoff())
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                await observer
                assert app._lease_timer is None and app._inbox_timer is None
                assert app._delivery_quiescing
                assert app._lease_store is not None
                assert await app._lease_store.read(session_id=session.session_id) is None
        finally:
            release.set()
            await asyncio.gather(observer, return_exceptions=True)
