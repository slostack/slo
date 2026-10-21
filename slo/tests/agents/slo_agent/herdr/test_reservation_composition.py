"""Reservation ownership across publication replacement and repeated cancellation."""

import asyncio
import threading
from pathlib import Path
from typing import Literal

import pytest

from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceUnavailableError
from tests.agents.slo_agent.herdr.test_reporter import publication, reporter


@pytest.mark.parametrize("case", ["current", "stale", "close", "cancel", "error_cancel"])
async def test_reservation_thread_is_drained_before_cutoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """A durable thread completes before cancellation; obsolete tickets cannot admit."""
    owner = reporter(root=tmp_path)
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    facts = publication()
    owner.publish(publication=facts)
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = owner._sequence_store.reserve

    def reserve(*, source: Literal["custom:slo", "custom:slo-display"]) -> int:
        """Pause the real durable reservation without blocking the event loop."""
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=5)
        if case == "error_cancel":
            raise HerdrSequenceUnavailableError()
        return original(source=source)

    monkeypatch.setattr(owner._sequence_store, "reserve", reserve)
    task = asyncio.create_task(
        coro=owner._reserve_ticket(operation="claim", publication=facts, revision=owner._revision)
    )
    closer = None
    try:
        await asyncio.wait_for(fut=entered.wait(), timeout=2)
        owned = owner._reservation_task
        assert owned is not None and not owned.done()
        if case == "stale":
            owner.publish(publication=publication(generation=1))
        if case == "close":
            closer = asyncio.create_task(coro=owner.close())
            await asyncio.sleep(delay=0)
            closer.cancel()
            await asyncio.sleep(delay=0)
            closer.cancel()
        if case in ("cancel", "error_cancel"):
            task.cancel()
            await asyncio.sleep(delay=0)
            task.cancel()
        await asyncio.sleep(delay=0)
        assert not task.done() and not owned.done()
        assert closer is None or not closer.done()
        release.set()
        if case in ("cancel", "error_cancel"):
            with pytest.raises(asyncio.CancelledError):
                await task
            assert owner._reserved_ticket is None
        else:
            ticket = await task
            assert ticket is not None
            assert owner._admit_command(ticket=ticket) == (case == "current")
        if closer is not None:
            with pytest.raises(asyncio.CancelledError):
                await closer
        assert owned.done() and not owned._log_traceback
        assert owner._reservation_task is None
        assert owner._disabled == (case == "error_cancel")
        assert owner._sequence_safe == (case != "error_cancel")
        assert owner._transport._active is None
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        if closer is not None:
            await asyncio.gather(closer, return_exceptions=True)
        await owner.close_transport()
    assert not owner._lease_held
