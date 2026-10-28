"""Public coordinator barriers for visibility paint and shutdown ownership."""

import asyncio

import pytest

from src.tui.workflows.dao import WorkflowSessionSnapshotDAO
from src.tui.workflows.progress_coordinator import WorkflowProgressCoordinator
from tests.tui.workflows.test_progress_coordinator import (
    _FakeService,
    _RecordingSink,
    _Scheduler,
    _row,
    _sessions,
)


class GatedSink(_RecordingSink):
    """Hold the first paint; later paints record normally."""

    def __init__(self, *, fail: bool = False) -> None:
        """Create a one-shot barrier and optional presentation failure."""
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.settled = asyncio.Event()
        self.fail = fail

    async def apply_sessions(self, *, snapshot: WorkflowSessionSnapshotDAO) -> None:
        """Record only after the first paint is released."""
        if not self.entered.is_set():
            self.entered.set()
            await self.release.wait()
            self.settled.set()
            if self.fail:
                raise ValueError("presentation failed")
        await super().apply_sessions(snapshot=snapshot)


async def checkpoint() -> None:
    """Cross a scheduler barrier without a timed sleep."""
    reached = asyncio.Event()
    asyncio.get_running_loop().call_soon(reached.set)
    await asyncio.wait_for(reached.wait(), timeout=5)


@pytest.mark.parametrize("fail", [False, True])
async def test_repeated_close_cancellation_joins_one_paint(fail: bool) -> None:
    """All close callers wait for the same sink, including its retrieved error."""
    sink = GatedSink(fail=fail)
    coordinator = WorkflowProgressCoordinator(service=_FakeService(), sink=sink, schedule=_Scheduler())
    paint = asyncio.create_task(coordinator.apply_local_snapshot(snapshot=_sessions(_row())))
    await asyncio.wait_for(sink.entered.wait(), timeout=5)
    paint.cancel()
    first_close = asyncio.create_task(coordinator.close())
    await checkpoint()
    first_close.cancel()
    await checkpoint()
    first_close.cancel()
    second_close = asyncio.create_task(coordinator.close())
    await checkpoint()
    try:
        assert not paint.done()
        assert not first_close.done()
        assert not second_close.done()
        assert not sink.settled.is_set()
    finally:
        sink.release.set()
        results = await asyncio.wait_for(
            asyncio.gather(paint, first_close, second_close, return_exceptions=True), timeout=5
        )
    assert isinstance(results[0], asyncio.CancelledError)
    assert isinstance(results[1], asyncio.CancelledError)
    assert results[2] is None
    assert sink.settled.is_set()
    assert await coordinator.apply_local_snapshot(snapshot=_sessions()) is False
    before = list(sink.events)
    coordinator.minimize()
    assert sink.events == before


async def test_cancelled_paint_keeps_lock_until_next_local_paint() -> None:
    """Repeated cancellation cannot let a newer local paint finish first."""
    sink = GatedSink()
    coordinator = WorkflowProgressCoordinator(service=_FakeService(), sink=sink, schedule=_Scheduler())
    old = _sessions(_row())
    first = asyncio.create_task(coordinator.apply_local_snapshot(snapshot=old))
    await asyncio.wait_for(sink.entered.wait(), timeout=5)
    first.cancel()
    await checkpoint()
    first.cancel()
    local = asyncio.create_task(coordinator.apply_local_snapshot(snapshot=_sessions()))
    await checkpoint()
    try:
        assert not first.done() and not local.done()
        assert sink.applied_sessions == []
    finally:
        sink.release.set()
        results = await asyncio.wait_for(asyncio.gather(first, local, return_exceptions=True), timeout=5)
    assert isinstance(results[0], asyncio.CancelledError)
    assert results[1] is True
    assert sink.applied_sessions == [old, _sessions()]
    await coordinator.close()


async def test_close_twice_waits_for_accepted_submission() -> None:
    """Repeated service-close cancellation never releases accepted work ownership."""
    from tests.tui.workflows.test_child_abort_confirmation import _Attached

    world = _Attached()
    await world.service.load_session_snapshot()
    world.abort.gate.clear()
    world.service.begin_child_abort(target=world.target())
    await asyncio.wait_for(world.abort.entered.wait(), timeout=5)
    first = asyncio.create_task(world.service.close())
    await checkpoint()
    first.cancel()
    await checkpoint()
    first.cancel()
    second = asyncio.create_task(world.service.close())
    await checkpoint()
    try:
        assert not first.done()
        assert not second.done()
        assert len(world.abort.calls) == 1
    finally:
        world.abort.gate.set()
        results = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), timeout=5)
    assert isinstance(results[0], asyncio.CancelledError)
    assert results[1] is None
    assert (await world.service.load_session_snapshot()).rows == ()


async def test_blocked_old_paint_finishes_before_local_acknowledgement() -> None:
    """The local result is returned only after old paint then local paint settle."""
    sink = GatedSink()
    source = _FakeService()
    old = _sessions(_row())
    source.default_sessions = old
    coordinator = WorkflowProgressCoordinator(service=source, sink=sink, schedule=_Scheduler())
    coordinator.start()
    await asyncio.wait_for(sink.entered.wait(), timeout=5)
    local = asyncio.create_task(coordinator.apply_local_snapshot(snapshot=_sessions()))
    await checkpoint()
    try:
        assert not local.done()
    finally:
        sink.release.set()
    assert await asyncio.wait_for(local, timeout=5) is True
    assert sink.applied_sessions == [old, _sessions()]
    await coordinator.close()


async def test_local_hide_ack_survives_selection_retirement() -> None:
    """Selection invalidation caused by hide does not invalidate its list acknowledgement."""
    from tests.tui.workflows.test_progress_coordinator import _CHILD_KEY

    source = _FakeService()
    source.default_sessions = _sessions(_row())
    source.list_gate = asyncio.Event()
    sink = _RecordingSink()
    coordinator = WorkflowProgressCoordinator(service=source, sink=sink, schedule=_Scheduler())
    coordinator.select(key=_CHILD_KEY)
    await asyncio.wait_for(source.list_entered.wait(), timeout=5)
    assert await coordinator.apply_local_snapshot(snapshot=_sessions()) is True
    assert sink.events == ["open:child-a", "sessions", "minimize", "removed:child-a"]
    restored = _sessions(_row())
    assert await coordinator.apply_local_snapshot(snapshot=restored) is True
    await coordinator.close()
    assert sink.applied_sessions == [_sessions(), restored]


async def test_sink_error_is_retrieved_and_next_local_paint_succeeds() -> None:
    """A failed sink does not retain the lock or poison later refreshes."""
    sink = GatedSink(fail=True)
    coordinator = WorkflowProgressCoordinator(service=_FakeService(), sink=sink, schedule=_Scheduler())
    pending = asyncio.create_task(coordinator.apply_local_snapshot(snapshot=_sessions()))
    await asyncio.wait_for(sink.entered.wait(), timeout=5)
    sink.release.set()
    with pytest.raises(ValueError, match="presentation failed"):
        await asyncio.wait_for(pending, timeout=5)
    assert await coordinator.apply_local_snapshot(snapshot=_sessions(_row())) is True
    await coordinator.close()


async def test_captured_old_read_released_after_hide_show_never_paints() -> None:
    """A captured source result released normally cannot overwrite either local command."""

    class CapturedSource(_FakeService):
        """Capture before waiting, unlike a supplier sampled after its barrier."""

        async def load_session_snapshot(self) -> WorkflowSessionSnapshotDAO:
            """Return the old immutable value only after both local paints."""
            captured = self.default_sessions
            self.list_entered.set()
            assert self.list_gate is not None
            await self.list_gate.wait()
            return captured

    source = CapturedSource()
    source.default_sessions = _sessions(_row())
    source.list_gate = asyncio.Event()
    sink = _RecordingSink()
    coordinator = WorkflowProgressCoordinator(service=source, sink=sink, schedule=_Scheduler())
    coordinator.start()
    await asyncio.wait_for(source.list_entered.wait(), timeout=5)
    hidden = _sessions()
    restored = _sessions(_row(availability="stale"))
    assert await coordinator.apply_local_snapshot(snapshot=hidden)
    assert await coordinator.apply_local_snapshot(snapshot=restored)
    source.list_gate.set()
    await checkpoint()
    await checkpoint()
    assert sink.applied_sessions == [hidden, restored]
    await coordinator.close()
