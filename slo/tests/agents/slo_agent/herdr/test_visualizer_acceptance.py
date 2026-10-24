"""Operational T4 acceptance through the registered executable capability."""

import asyncio
import json
import threading
from typing import Literal
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.dao import (
    HerdrCliCommandDAO,
    HerdrCommandAdmission,
    HerdrCommandResultDAO,
    HerdrVisualizerRequestDAO,
    VisualizerLaunchOutcomeDAO,
)
from tests.agents.slo_agent.herdr.test_viewer_authority_closure import active_reporter
from tests.agents.slo_agent.herdr.test_visualizer_lifecycle import PARENT
from tests.agents.slo_agent.herdr.test_reporter import publication
from tests.state_isolation import FakeHerdrFixture


@pytest.mark.parametrize(argnames="ending", argvalues=["release", "close", "cancel", "timeout"])
@pytest.mark.parametrize(argnames="changed_generation", argvalues=[False, True])
async def test_operational_viewer_supersedes_queued_report(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    changed_generation: bool,
    ending: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove viewer entry → durable A → queued A → B → viewer release.

    The lease is setup, but A is reserved only after the real viewer enters.
    Reservation completion and transport entry have distinct barriers: never
    poll for a waiter while the filesystem worker is still reserving A.
    The real one-second deadline remains active throughout viewer contention.
    """
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as stream:
        stream.write(
            f"if sys.argv[2] == 'split':\n import select\n barrier = Path({str(fake_herdr.barrier)!r})\n"
            " while not barrier.read_text(): select.select([], [], [], 0.001)\n"
            ' print(\'{"result":{"pane":{"pane_id":"pane-2"}}}\')\n'
        )
    owner = active_reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    owner._sequence_store.acquire()
    viewer = owner.build_visualizer()
    reserve_release = threading.Event()
    reserve_entered = asyncio.Event()
    prepared = asyncio.Event()
    enter_transport = asyncio.Event()
    queued = asyncio.Event()
    loop = asyncio.get_running_loop()
    reserve = owner._sequence_store.reserve
    invoke = owner._transport.invoke
    invoke_locked = owner._transport._invoke_locked

    def blocked_reserve(*, source: Literal["custom:slo", "custom:slo-display"]) -> int:
        """Gate only A's disk reservation while the viewer deadline remains real."""
        if not reserve_release.is_set():
            loop.call_soon_threadsafe(reserve_entered.set)
            reserve_release.wait()
            assert owner._transport._command_lock.locked(), "G2 requires viewer before A reservation"
            assert fake_herdr.capture.read_text(), "G2 requires actual viewer executable entry"
        return reserve(source=source)

    async def prepared_report(
        *, command: HerdrCliCommandDAO, admission: HerdrCommandAdmission
    ) -> HerdrCommandResultDAO:
        """Hold the first durable report outside the real transport timeout scope."""
        if command.argv[1] == "report-agent" and not prepared.is_set():
            prepared.set()
            await enter_transport.wait()
        return await invoke(command=command, admission=admission)

    async def observe_queue(
        *, command: HerdrCliCommandDAO, admission: HerdrCommandAdmission
    ) -> HerdrCommandResultDAO:
        """Signal before delegating directly into the real held-lock acquisition."""
        if command.argv[1] == "report-agent" and not queued.is_set():
            assert owner._transport._command_lock.locked()
            queued.set()
        return await invoke_locked(command=command, admission=admission)

    monkeypatch.setattr(target=owner._sequence_store, name="reserve", value=blocked_reserve)
    monkeypatch.setattr(target=owner._transport, name="invoke", value=prepared_report)
    monkeypatch.setattr(target=owner._transport, name="_invoke_locked", value=observe_queue)
    first = publication()
    old = None
    launch = asyncio.create_task(
        coro=viewer.invoke(request=HerdrVisualizerRequestDAO(parent_session_id=PARENT, history_root=tmp_path))
    )
    try:
        async with asyncio.timeout(delay=2):
            while not fake_herdr.capture.read_text():
                assert not launch.done(), "Viewer ended before executable entry"
                await asyncio.sleep(delay=0)
            assert owner._transport._command_lock.locked()
            assert owner._reserved_ticket is None
            owner.publish(publication=first)
            old = asyncio.create_task(
                coro=owner._send_report_operation(operation="claim", publication=first, revision=1)
            )
            await reserve_entered.wait()
            assert owner._reservation_task is not None and not old.done()
            assert not prepared.is_set() and not queued.is_set()
            reserve_release.set()
            await prepared.wait()
            assert owner._reservation_task is None
            assert owner._reserved_ticket is not None
            assert not launch.done(), "Viewer deadline crossed during reservation; not canonical G2"
            enter_transport.set()
            await queued.wait()
        assert not old.done() and not launch.done()
        assert owner._transport._command_lock._waiters
        assert owner._admitted_ticket is None
        assert owner._transport._config.command_timeout_seconds == 1.0
        ticket = owner._reserved_ticket
        assert ticket is not None
        assert owner._sequence_store._load().lifecycle_sequence == ticket.sequence
        newer = first.model_copy(
            update={
                "configuration_generation": int(changed_generation),
                "snapshot": first.snapshot.model_copy(update={"state": "working"}),
            }
        )
        owner.publish(publication=newer)
        if ending == "close":
            await viewer.close()
        elif ending == "cancel":
            viewer._pending_by_parent[PARENT].cancel()
        elif ending == "release":
            fake_herdr.guard.require_registered(path=fake_herdr.executable)
            fake_herdr.barrier.write_text("release")
        assert not await old
        if ending in ("close", "cancel"):
            with pytest.raises(asyncio.CancelledError):
                await launch
        else:
            assert (await launch).status == ("submitted" if ending == "release" else "failed")
        assert not owner._transport.closed
        assert not viewer._pending_by_parent
        assert await owner._send_report_operation(operation="claim", publication=newer, revision=2)
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        reports = [command for command in commands if command[1] == "report-agent"]
        assert len(reports) == 1
        assert int(reports[0][reports[0].index("--seq") + 1]) > ticket.sequence
        expected = (
            ["split", "rename", "run", "report-agent"] if ending == "release" else ["split", "report-agent"]
        )
        assert [command[1] for command in commands] == expected
        retained = viewer._attempt_by_parent[PARENT]
        assert retained.state == ("pane_known" if ending == "release" else "uncertain")
        before = fake_herdr.capture.read_text()
        repeated = await viewer.invoke(
            request=HerdrVisualizerRequestDAO(parent_session_id=PARENT, history_root=tmp_path)
        )
        assert (
            repeated.status
            == {"release": "reused", "close": "skipped", "cancel": "failed", "timeout": "failed"}[ending]
        )
        assert fake_herdr.capture.read_text() == before
    finally:
        reserve_release.set()
        enter_transport.set()
        await viewer.close()
        if old is not None:
            old.cancel()
            await asyncio.gather(old, return_exceptions=True)
        await asyncio.gather(launch, return_exceptions=True)
        await owner.close()
        await owner.close_transport()


async def test_reservation_outlives_viewer_deadline(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An expired viewer is not queued-A evidence; superseded late A still cannot spawn."""
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as stream:
        stream.write("if sys.argv[2] == 'split':\n import select\n select.select([], [], [], 10)\n")
    owner = active_reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    owner._sequence_store.acquire()
    viewer = owner.build_visualizer()
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    reserve = owner._sequence_store.reserve

    def delayed_reserve(*, source: Literal["custom:slo", "custom:slo-display"]) -> int:
        """Hold the real disk write until the real viewer timeout has completed."""
        loop.call_soon_threadsafe(entered.set)
        release.wait()
        return reserve(source=source)

    monkeypatch.setattr(target=owner._sequence_store, name="reserve", value=delayed_reserve)
    launch = asyncio.create_task(
        coro=viewer.invoke(request=HerdrVisualizerRequestDAO(parent_session_id=PARENT, history_root=tmp_path))
    )
    old = None
    try:
        async with asyncio.timeout(delay=3):
            while not fake_herdr.capture.read_text():
                assert not launch.done()
                await asyncio.sleep(delay=0)
            first = publication()
            owner.publish(publication=first)
            old = asyncio.create_task(
                coro=owner._send_report_operation(operation="claim", publication=first, revision=1)
            )
            await entered.wait()
            assert owner._reserved_ticket is None
            assert not owner._transport._command_lock._waiters
            assert (await launch).status == "failed"
            assert owner._reservation_task is not None and not old.done()
            owner.publish(publication=first.model_copy(update={"configuration_generation": 1}))
            release.set()
            assert not await old
        assert [json.loads(line)[1] for line in fake_herdr.capture.read_text().splitlines()] == ["split"]
        assert owner._reserved_ticket is not None
        assert owner._sequence_store._load().lifecycle_sequence == owner._reserved_ticket.sequence
        assert owner._admitted_ticket is None
    finally:
        release.set()
        await viewer.close()
        if old is not None:
            await asyncio.gather(old, return_exceptions=True)
        await asyncio.gather(launch, return_exceptions=True)
        await owner.close()
        await owner.close_transport()


@pytest.mark.parametrize(argnames="changed_generation", argvalues=[False, True])
async def test_public_viewer_joins_already_admitted_report(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, changed_generation: bool
) -> None:
    """Admitted A completes before the queued public viewer, without acknowledging B."""
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as stream:
        stream.write(
            f"if sys.argv[2] == 'report-agent':\n import select\n barrier = Path({str(fake_herdr.barrier)!r})\n"
            " while not barrier.read_text(): select.select([], [], [], 0.001)\n"
            'if sys.argv[2] == \'split\': print(\'{"result":{"pane":{"pane_id":"pane-2"}}}\')\n'
        )
    owner = active_reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    owner._sequence_store.acquire()
    viewer = owner.build_visualizer()
    first = publication()
    owner.publish(publication=first)
    old = asyncio.create_task(coro=owner._publish_batch(publication=first, revision=1))
    launch = None
    try:
        async with asyncio.timeout(delay=0.5):
            while not fake_herdr.capture.read_text():
                await asyncio.sleep(delay=0)
            ticket = owner._admitted_ticket
            assert ticket is not None and owner._binding is not None
            assert owner._sequence_store._load().lifecycle_sequence == ticket.sequence
            launch = asyncio.create_task(
                coro=viewer.invoke(
                    request=HerdrVisualizerRequestDAO(parent_session_id=PARENT, history_root=tmp_path)
                )
            )
            while not owner._transport._command_lock._waiters:
                await asyncio.sleep(delay=0)
        newer = first.model_copy(
            update={
                "configuration_generation": int(changed_generation),
                "snapshot": first.snapshot.model_copy(update={"state": "working"}),
            }
        )
        owner.publish(publication=newer)
        fake_herdr.guard.require_registered(path=fake_herdr.executable)
        fake_herdr.barrier.write_text("release")
        await old
        assert (await launch).status == "submitted"
        assert owner._binding is not None and owner._binding.certainty == "confirmed"
        assert owner._binding.configuration_generation == first.configuration_generation
        assert owner._binding.session_id == first.snapshot.session_id
        assert owner._admitted_ticket is None and owner._pending is newer
        assert owner._lifecycle_ack is None and owner._restore_ack is None
        assert owner._display_ack_revision is None
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        assert [command[1] for command in commands] == ["report-agent", "split", "rename", "run"]
        assert int(commands[0][commands[0].index("--seq") + 1]) == ticket.sequence
        assert owner._transport.resources_drained and not viewer._pending_by_parent
    finally:
        await viewer.close()
        old.cancel()
        await asyncio.gather(*(task for task in (old, launch) if task is not None), return_exceptions=True)
        await owner.close()
        await owner.close_transport()


@pytest.mark.parametrize(argnames="terminal", argvalues=["ok", "error", "cancelled"])
async def test_done_callback_identity_and_retrieval(tmp_path: Path, terminal: str) -> None:
    """An old completion retrieves errors without deleting a replacement task."""
    viewer = active_reporter(root=tmp_path).build_visualizer()
    release = asyncio.Event()

    async def finish() -> VisualizerLaunchOutcomeDAO:
        """Produce each terminal state without I/O."""
        if terminal == "error":
            raise RuntimeError("private-callback-sentinel")
        if terminal == "cancelled":
            raise asyncio.CancelledError
        return VisualizerLaunchOutcomeDAO(status="failed")

    async def replacement() -> VisualizerLaunchOutcomeDAO:
        """Retain a distinct pending owner until explicitly released."""
        await release.wait()
        return VisualizerLaunchOutcomeDAO(status="failed")

    old = asyncio.create_task(coro=finish())
    current = asyncio.create_task(coro=replacement())
    viewer._pending_by_parent[PARENT] = current
    await asyncio.sleep(delay=0)
    viewer._on_launch_done(old, parent_session_id=PARENT)
    assert viewer._pending_by_parent[PARENT] is current
    assert not old._log_traceback
    release.set()
    await current
    viewer._on_launch_done(current, parent_session_id=PARENT)
    assert not viewer._pending_by_parent
    await viewer.close()


@pytest.mark.parametrize(argnames="failure", argvalues=["none", "rename", "run", "split", "oversize"])
async def test_public_retained_outcome(tmp_path: Path, fake_herdr: FakeHerdrFixture, failure: str) -> None:
    """Public invoke retains successful and failed effects without any resend.

    Args:
        tmp_path: Isolated state root.
        fake_herdr: Registered regular executable and capture files.
        failure: CLI response boundary to reject.
    """
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as stream:
        stream.write(
            f"failure = {failure!r}\n"
            "if sys.argv[2] == failure: sys.exit(7)\n"
            "if sys.argv[2] == 'split':\n"
            " print('x' * 16385 if failure == 'oversize' else "
            '\'{"result":{"pane":{"pane_id":"pane-2"}}}\')\n'
        )
    owner = active_reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    viewer = owner.build_visualizer()
    request = HerdrVisualizerRequestDAO(parent_session_id=PARENT, history_root=tmp_path)
    try:
        outcome = await viewer.invoke(request=request)
        assert outcome.status == ("submitted" if failure in ("none", "rename") else "failed")
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        known = failure not in ("split", "oversize")
        assert [command[1] for command in commands] == (["split", "rename", "run"] if known else ["split"])
        retained = await viewer.invoke(request=request)
        assert retained.status == ("reused" if known else "failed")
        assert retained.pane_id == ("pane-2" if known else None)
        assert len(fake_herdr.capture.read_text().splitlines()) == len(commands)
        assert not viewer._pending_by_parent
    finally:
        await viewer.close()
        assert not owner._transport.closed
        await owner._transport.close()


async def test_cancelled_waiter_does_not_cancel_shared_launch(
    tmp_path: Path, fake_herdr: FakeHerdrFixture
) -> None:
    """Cancel one public waiter twice while another receives the same owned result."""
    owner = active_reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    viewer = owner.build_visualizer()
    request = HerdrVisualizerRequestDAO(parent_session_id=PARENT, history_root=tmp_path)
    lock = owner._transport._command_lock
    await lock.acquire()
    first = asyncio.create_task(coro=viewer.invoke(request=request))
    second = asyncio.create_task(coro=viewer.invoke(request=request))
    try:
        async with asyncio.timeout(delay=0.5):
            while not lock._waiters:
                await asyncio.sleep(delay=0)
        owned = viewer._pending_by_parent[PARENT]
        first.cancel()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not owned.done() and not second.done()
        assert viewer._pending_by_parent[PARENT] is owned
        lock.release()
        assert (await second).status == "failed"
        assert owned.done() and not owned.cancelled()
        assert not viewer._pending_by_parent
        assert len(fake_herdr.capture.read_text().splitlines()) == 1
    finally:
        if lock.locked():
            lock.release()
        await viewer.close()
        await asyncio.gather(first, second, return_exceptions=True)
        await owner._transport.close()
