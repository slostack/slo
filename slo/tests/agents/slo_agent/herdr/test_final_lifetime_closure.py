"""Finite real-adapter lifetime compositions; OS faults are injected, not certified."""

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Literal

import pytest

from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO
from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceStore, HerdrSequenceUnavailableError
from tests.agents.slo_agent.herdr.test_cli_transport import RecordingAdmission
from tests.agents.slo_agent.herdr.test_reporter import publication, reporter
from tests.state_isolation import FakeHerdrFixture


@pytest.mark.parametrize(argnames="cancel", argvalues=[False, True])
async def test_shutdown_deadline_joins_durable_reservation(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    """Expiry seals release admission but cannot abandon the real reservation thread."""
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    assert tmp_path.resolve() == tmp_path and not tmp_path.is_symlink()
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    facts = publication()
    owner.publish(publication=facts)
    entered, expired = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = owner._sequence_store.reserve

    def reserve(*, source: Literal["custom:slo", "custom:slo-display"]) -> int:
        """Hold only this test's off-loop reservation, then persist through the real store."""
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=6)
        return original(source=source)

    task = None
    timer = None
    try:
        assert await owner._send_report_operation(operation="claim", publication=facts, revision=1)
        before = fake_herdr.capture.read_text()
        monkeypatch.setattr(target=owner._sequence_store, name="reserve", value=reserve)
        task = asyncio.create_task(coro=owner.close())
        await asyncio.wait_for(fut=entered.wait(), timeout=2)
        owned = owner._reservation_task
        assert owned is not None and owner._close_deadline is not None
        timer = loop.call_at(owner._close_deadline + 0.02, expired.set)
        await asyncio.wait_for(fut=expired.wait(), timeout=3)
        assert not task.done() and not owned.done() and owner._lease_held
        assert not owner._shutdown_admitted and fake_herdr.capture.read_text() == before
        if cancel:
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(delay=0)
                assert not task.done()
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(fut=task, timeout=2)
        else:
            assert (await asyncio.wait_for(fut=task, timeout=2)).replacement == "uncertain"
        assert owned.done() and not owned._log_traceback
        assert owner._reservation_task is None and owner._reserved_ticket is None
        assert owner._sequence_store._load().lifecycle_sequence == 2
        assert not owner._shutdown_admitted and not owner._shutdown_released
        assert (await owner.close()).replacement == "uncertain"
        assert fake_herdr.capture.read_text() == before
    finally:
        release.set()
        if timer is not None:
            timer.cancel()
        if task is not None:
            await asyncio.wait_for(fut=asyncio.gather(task, return_exceptions=True), timeout=7)
        await asyncio.wait_for(fut=owner.close_transport(), timeout=2)
    assert not owner.retains_external_resources


@pytest.mark.parametrize(argnames="cancel", argvalues=[False, True])
async def test_persistent_transport_failure_retains_real_lease(
    fake_herdr: FakeHerdrFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    cancel: bool,
) -> None:
    """The final failed local attempt is cached with its actual child and pane lease."""
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    assert tmp_path.resolve() == tmp_path and not tmp_path.is_symlink()
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    contender = HerdrSequenceStore(state_root=tmp_path, socket_namespace="default", pane_id="p")
    original = owner._transport._terminate_and_reap
    entered, release = asyncio.Event(), asyncio.Event()
    attempts = 0

    async def fail_reap(*, process: asyncio.subprocess.Process) -> None:
        """Inject a finite reap refusal around an actual fixture child, never a host PID."""
        nonlocal attempts
        attempts += 1
        if attempts == 3:
            entered.set()
            await asyncio.wait_for(fut=release.wait(), timeout=3)
        raise OSError("private-final-reap")

    monkeypatch.setattr(target=owner._transport, name="_terminate_and_reap", value=fail_reap)
    admission = RecordingAdmission()
    task = None
    try:
        await asyncio.wait_for(
            fut=owner._transport.invoke(
                command=HerdrCliCommandDAO(argv=("pane", "split")), admission=admission
            ),
            timeout=2,
        )
        process, spawn = owner._transport._active, owner._transport._spawn_task
        assert process is not None and spawn is not None
        assert (await owner.close_transport()).resources == "retained"
        task = asyncio.create_task(coro=owner.drain_retained_external_resources())
        await asyncio.wait_for(fut=entered.wait(), timeout=2)
        retained = owner._retired_reporter_drain_task
        if cancel:
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(delay=0)
                assert not task.done()
        with pytest.raises(HerdrSequenceUnavailableError):
            contender.acquire()
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(fut=task, timeout=2)
        else:
            await asyncio.wait_for(fut=task, timeout=2)
        result = await owner.drain_retained_external_resources()
        assert result.resources == "retained" and result.replacement == "uncertain"
        assert owner._retired_reporter_drain_task is retained
        assert retained is not None and retained.done() and not retained._log_traceback
        assert owner._transport._active is process and owner._transport._spawn_task is spawn
        assert owner._lease_held and owner.retains_external_resources
        with pytest.raises(HerdrSequenceUnavailableError):
            contender.acquire()
        assert attempts == 3 and len(admission.results) == 1
        assert len(fake_herdr.capture.read_text().splitlines()) == 1
        assert not owner._shutdown_admitted
        assert owner._transport._cleanup_failure_active
        assert "herdr_cleanup_unavailable_recovered" not in caplog.messages
    finally:
        release.set()
        if task is not None:
            await asyncio.wait_for(fut=asyncio.gather(task, return_exceptions=True), timeout=4)
        monkeypatch.setattr(target=owner._transport, name="_terminate_and_reap", value=original)
        await asyncio.wait_for(fut=owner._transport._drain_quarantined_resources(), timeout=2)
        await asyncio.wait_for(fut=owner._release_lease(), timeout=2)
        contender.close()


@pytest.mark.parametrize(argnames="persistent", argvalues=[False, True])
async def test_real_lease_close_fault_retains_owner(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, persistent: bool
) -> None:
    """Ambiguous close is inspection-only even when a second syscall would succeed."""
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    assert tmp_path.resolve() == tmp_path and not tmp_path.is_symlink()
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    lease = owner._sequence_store._lease
    fd = lease._fd
    assert fd is not None
    contender = HerdrSequenceStore(state_root=tmp_path, socket_namespace="default", pane_id="p")
    original = os.close
    attempts = 0

    def close_fd(target: int) -> None:
        """Refuse only this test-owned descriptor; every unrelated close delegates."""
        nonlocal attempts
        if target == fd:
            attempts += 1
            if persistent or attempts == 1:
                raise OSError("private-lease-close")
        original(target)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(target=os, name="close", value=close_fd)
            result = await asyncio.wait_for(fut=owner.close_transport(), timeout=2)
            assert result.resources == "retained" and owner._lease_held
            assert owner._transport.closed and owner._transport.resources_drained
            assert owner._sequence_store._lease is lease and lease._fd == fd
            with pytest.raises(HerdrSequenceUnavailableError):
                contender.acquire()
            result = await asyncio.wait_for(fut=owner.drain_retained_external_resources(), timeout=2)
            assert result.replacement == "uncertain"
            assert result.resources == "retained"
            assert owner._lease_held
            assert await owner.drain_retained_external_resources() is result
            assert attempts == 1 and fake_herdr.capture.read_text() == ""
            assert lease._fd == fd
            with pytest.raises(HerdrSequenceUnavailableError):
                contender.acquire()
    finally:
        # The fixture knows no close occurred; production has no such evidence.
        original(fd)
        await asyncio.wait_for(fut=owner._release_lease(), timeout=2)
        contender.close()


@pytest.mark.parametrize(argnames="prior_failure", argvalues=[False, True])
async def test_admitted_cancellation_preserves_diagnostic_episode(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, caplog: pytest.LogCaptureFixture, prior_failure: bool
) -> None:
    """Real admitted cancellation drains the child without failure or recovery diagnostics."""
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    assert tmp_path.resolve() == tmp_path and not tmp_path.is_symlink()
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    facts = publication()
    owner.publish(publication=facts)
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    script = fake_herdr.executable.read_text()
    fake_herdr.executable.write_text(script + "\nimport time\ntime.sleep(5)\n")
    if prior_failure:
        owner.record_publication_failure()
        owner._transport._command_failure_active = True
    episodes = owner._diagnostic_failures.copy()
    caplog.clear()
    task = asyncio.create_task(
        coro=owner._send_report_operation(operation="claim", publication=facts, revision=1)
    )
    try:
        async with asyncio.timeout(delay=0.8):
            while not fake_herdr.capture.read_text():
                await asyncio.sleep(delay=0)
        assert owner._admitted_ticket is not None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(fut=task, timeout=2)
        assert owner._admitted_ticket is None and owner._transport.resources_drained
        assert owner._binding is not None and owner._binding.certainty == "possible"
        assert owner._lifecycle_ack is None
        assert owner._diagnostic_failures == episodes
        assert owner._transport._command_failure_active is prior_failure
        assert not caplog.records
        fake_herdr.guard.require_registered(path=fake_herdr.executable)
        fake_herdr.executable.write_text(script)
        assert await owner._send_report_operation(operation="claim", publication=facts, revision=1)
        expected = ["herdr_publication_failed_recovered", "herdr_command_unavailable_recovered"]
        assert [record.message for record in caplog.records] == (expected if prior_failure else [])
        assert await owner._send_report_operation(operation="claim", publication=facts, revision=1)
        assert [record.message for record in caplog.records] == (expected if prior_failure else [])
    finally:
        if not task.done():
            task.cancel()
        await asyncio.wait_for(fut=asyncio.gather(task, return_exceptions=True), timeout=3)
        await asyncio.wait_for(fut=owner.close_transport(), timeout=2)


@pytest.mark.parametrize(argnames="sink_throws", argvalues=[False, True])
async def test_retained_cleanup_emits_one_recovery_after_actual_drain(
    fake_herdr: FakeHerdrFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    sink_throws: bool,
) -> None:
    """A successful final local reap ends its diagnostic episode, not remote uncertainty."""
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    assert tmp_path.resolve() == tmp_path and not tmp_path.is_symlink()
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    original = owner._transport._terminate_and_reap
    attempts = 0

    async def fail_twice(*, process: asyncio.subprocess.Process) -> None:
        """Fail bounded OS cleanup attempts before delegating the final actual reap."""
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise OSError("private-cleanup-episode")
        await original(process=process)

    monkeypatch.setattr(target=owner._transport, name="_terminate_and_reap", value=fail_twice)
    admission = RecordingAdmission()
    try:
        await asyncio.wait_for(
            fut=owner._transport.invoke(
                command=HerdrCliCommandDAO(argv=("pane", "split")), admission=admission
            ),
            timeout=2,
        )
        assert (await owner.close_transport()).resources == "retained"
        assert [record.message for record in caplog.records] == ["herdr_cleanup_unavailable"]
        recovery_calls: list[str] = []
        original_warning = logging.Logger.warning

        def warning(logger: logging.Logger, message: str) -> None:
            """Observe the fixed recovery before optionally refusing its sink."""
            recovery_calls.append(message)
            if sink_throws:
                raise OSError("private-sink-error")
            original_warning(logger, message)

        monkeypatch.setattr(target=logging.Logger, name="warning", value=warning)
        outcome = await asyncio.wait_for(fut=owner.drain_retained_external_resources(), timeout=2)
        assert outcome.resources == "drained" and outcome.replacement == "uncertain"
        assert not owner._lease_held and owner._transport.resources_drained
        assert await owner.drain_retained_external_resources() is outcome
        assert attempts == 3 and len(admission.results) == 1
        assert len(fake_herdr.capture.read_text().splitlines()) == 1
        assert recovery_calls == ["herdr_cleanup_unavailable_recovered"]
        assert owner._transport.closed and owner._transport._cleanup_failed
        assert not owner._transport._cleanup_failure_active
        expected = ["herdr_cleanup_unavailable"]
        if not sink_throws:
            expected.append("herdr_cleanup_unavailable_recovered")
        assert [record.message for record in caplog.records] == expected
    finally:
        monkeypatch.setattr(target=owner._transport, name="_terminate_and_reap", value=original)
        if not owner._transport.resources_drained:
            await asyncio.wait_for(fut=owner._transport._drain_quarantined_resources(), timeout=2)
        await asyncio.wait_for(fut=owner._release_lease(), timeout=2)
