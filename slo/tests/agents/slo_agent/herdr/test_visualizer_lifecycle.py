"""One-shot viewer admission and lifecycle evidence."""

from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.dao import HerdrVisualizerAttemptDAO
from src.agents.slo_agent.herdr.visualizer import HerdrViewerAdmission
from tests.agents.slo_agent.herdr.test_viewer_authority_closure import active_reporter, AUTHORITY_CHANGES
from tests.state_isolation import FakeHerdrFixture
from src.agents.slo_agent.herdr.dao import HerdrViewerOperation

PARENT = "a81d92fa-7a2e-4ccd-9975-445832a91d5e"


@pytest.mark.parametrize("operation", ["split", "rename", "run"])
def test_operation_is_consumed_once(tmp_path: Path, operation: HerdrViewerOperation) -> None:
    """Immutable replacement cannot grant a second admission of an operation."""
    viewer = active_reporter(root=tmp_path).build_visualizer()
    attempt = HerdrVisualizerAttemptDAO(state="pane_known", pane_id="pane-2")
    viewer._attempt_by_parent[PARENT] = attempt
    admission = HerdrViewerAdmission(
        launcher=viewer, parent_session_id=PARENT, attempt=attempt, operation=operation
    )
    assert admission.try_admit()
    assert not admission.try_admit()
    current = viewer._attempt_by_parent[PARENT]
    assert current is not attempt
    assert current.admitted_operations == frozenset([operation])
    assert not HerdrViewerAdmission(
        launcher=viewer, parent_session_id=PARENT, attempt=current, operation=operation
    ).try_admit()


@pytest.mark.parametrize("reason", ["stale", "closing", "revoked", "unknown"])
def test_operation_refused(tmp_path: Path, reason: str) -> None:
    """Current identity, lifetime and known target are mandatory before rename."""
    owner = active_reporter(root=tmp_path)
    viewer = owner.build_visualizer()
    attempt = HerdrVisualizerAttemptDAO(state="split_attempted")
    if reason != "unknown":
        attempt = HerdrVisualizerAttemptDAO(state="pane_known", pane_id="pane-2")
    viewer._attempt_by_parent[PARENT] = attempt.model_copy() if reason == "stale" else attempt
    viewer._closing = reason == "closing"
    if reason == "revoked":
        owner.revoke_viewer_admission()
    assert not HerdrViewerAdmission(
        launcher=viewer, parent_session_id=PARENT, attempt=attempt, operation="rename"
    ).try_admit()
    assert not viewer._attempt_by_parent[PARENT].admitted_operations


async def test_send_uses_real_transport(tmp_path: Path, fake_herdr: FakeHerdrFixture) -> None:
    """The real guarded executable receives only one admitted command."""
    owner = active_reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    viewer = owner.build_visualizer()
    viewer._attempt_by_parent[PARENT] = HerdrVisualizerAttemptDAO(state="split_attempted")
    try:
        result = await viewer._send_viewer_operation(parent_session_id=PARENT, operation="split")
        assert result.admitted and result.outcome.status == "ok"
        duplicate = await viewer._send_viewer_operation(parent_session_id=PARENT, operation="split")
        assert duplicate.outcome.status == "suppressed"
        assert len(fake_herdr.capture.read_text().splitlines()) == 1
    finally:
        await owner._transport.close()


@pytest.mark.parametrize("split_ok", [True, False])
async def test_split_retains_result(tmp_path: Path, fake_herdr: FakeHerdrFixture, split_ok: bool) -> None:
    """Real CLI split decoding retains either a known pane or uncertainty."""
    from src.agents.slo_agent.herdr.dao import HerdrVisualizerRequestDAO

    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open("a") as stream:
        stream.write('print(\'{"result":{"pane":{"pane_id":"pane-2"}}}\')\n' if split_ok else "print('{}')\n")
    owner = active_reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    viewer = owner.build_visualizer()
    viewer._attempt_by_parent[PARENT] = HerdrVisualizerAttemptDAO(state="split_attempted")
    try:
        outcome = await viewer._split_and_submit(
            request=HerdrVisualizerRequestDAO(parent_session_id=PARENT, history_root=tmp_path)
        )
        assert outcome.status == ("submitted" if split_ok else "failed")
        attempt = viewer._attempt_by_parent[PARENT]
        assert attempt.state == ("pane_known" if split_ok else "uncertain")
        assert attempt.admitted_operations == frozenset(["split", "rename", "run"] if split_ok else ["split"])
        assert len(fake_herdr.capture.read_text().splitlines()) == (3 if split_ok else 1)
    finally:
        await owner._transport.close()


async def test_simultaneous_then_retained(tmp_path: Path, fake_herdr: FakeHerdrFixture) -> None:
    """Concurrent requests share a task, while completed requests never resend."""
    import asyncio
    from src.agents.slo_agent.herdr.dao import HerdrVisualizerRequestDAO

    owner = active_reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    viewer = owner.build_visualizer()
    request = HerdrVisualizerRequestDAO(parent_session_id=PARENT, history_root=tmp_path)
    try:
        first, second = await asyncio.gather(viewer.invoke(request=request), viewer.invoke(request=request))
        assert first is second
        assert first.status == "failed"
        assert not viewer._pending_by_parent
        assert (await viewer.invoke(request=request)).status == "failed"
        assert len(fake_herdr.capture.read_text().splitlines()) == 1
    finally:
        await owner._transport.close()


async def test_close_joins_pending(tmp_path: Path, fake_herdr: FakeHerdrFixture) -> None:
    """Close revokes queued launches but does not close their shared transport."""
    import asyncio
    from src.agents.slo_agent.herdr.dao import HerdrVisualizerRequestDAO

    owner = active_reporter(root=tmp_path)
    viewer = owner.build_visualizer()
    request = HerdrVisualizerRequestDAO(parent_session_id=PARENT, history_root=tmp_path)
    await owner._transport._command_lock.acquire()
    waiter = asyncio.create_task(coro=viewer.invoke(request=request))
    try:
        async with asyncio.timeout(0.5):
            while not owner._transport._command_lock._waiters:
                await asyncio.sleep(0)
        await viewer.close()
        assert not viewer._pending_by_parent
        assert not owner._transport.closed
        assert viewer._attempt_by_parent[PARENT].state == "uncertain"
        assert (await viewer.invoke(request=request)).status == "skipped"
        assert fake_herdr.capture.read_text() == ""
    finally:
        owner._transport._command_lock.release()
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        await owner._transport.close()


@pytest.mark.parametrize("operation", ["split", "rename", "run"])
@pytest.mark.parametrize("field,value", AUTHORITY_CHANGES)
async def test_queued_operation_revocation(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, operation: HerdrViewerOperation, field: str, value: bool
) -> None:
    """Every queued operation observes live reporter authority under the real lock."""
    import asyncio
    from tests.agents.slo_agent.herdr.test_viewer_authority_closure import change_authority

    owner = active_reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    viewer = owner.build_visualizer()
    viewer._attempt_by_parent[PARENT] = HerdrVisualizerAttemptDAO(state="pane_known", pane_id="pane-2")
    lock = owner._transport._command_lock
    await lock.acquire()
    task = asyncio.create_task(
        coro=viewer._send_viewer_operation(parent_session_id=PARENT, operation=operation)
    )
    try:
        async with asyncio.timeout(0.5):
            while not lock._waiters:
                await asyncio.sleep(0)
        change_authority(owner=owner, field=field, value=value)
        lock.release()
        result = await task
        assert result.outcome.status == "suppressed" and not result.admitted
        assert not viewer._attempt_by_parent[PARENT].admitted_operations
        assert fake_herdr.capture.read_text() == ""
    finally:
        if lock.locked():
            lock.release()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await owner._transport.close()
