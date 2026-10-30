"""Real-lock cancellation, late-spawn and bounded pipe integration evidence."""

import asyncio
from pathlib import Path
from typing import cast

import pytest

from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO, HerdrReporterConfigDAO
from src.agents.slo_agent.herdr.service import HerdrCliTransport
from tests.agents.slo_agent.herdr.test_cli_transport import RecordingAdmission
from tests.state_isolation import FakeHerdrFixture


def transport_for(*, fake: FakeHerdrFixture, root: Path) -> HerdrCliTransport:
    """Build an inert transport bound to this registered fixture only."""
    return HerdrCliTransport(
        config=HerdrReporterConfigDAO(
            pane_id="p", binary_path=fake.executable, state_root=root, metadata_profile="compact"
        ),
        environment={},
    )


@pytest.mark.parametrize(argnames="case", argvalues=["stale", "timeout", "cancel", "close"])
async def test_transport_waiter(fake_herdr: FakeHerdrFixture, tmp_path: Path, case: str) -> None:
    """Queued invocations cannot admit after revocation or touch the lock owner."""
    transport = transport_for(fake=fake_herdr, root=tmp_path)
    owner = RecordingAdmission()
    await transport._command_lock.acquire()
    task = asyncio.create_task(
        coro=transport.invoke(command=HerdrCliCommandDAO(argv=("pane", "split")), admission=owner)
    )
    await asyncio.sleep(delay=0)
    assert not task.done() and owner.attempts == 0
    if case == "timeout":
        result = await task
        assert result.outcome.status == "timeout" and not result.admitted
    elif case == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif case == "stale":
        owner.allowed = False
    else:
        closer = asyncio.create_task(coro=transport.close())
        await asyncio.sleep(delay=0)
        assert transport.closed
    assert transport._command_lock.locked()
    transport._command_lock.release()
    if case in ("stale", "close"):
        assert (await task).outcome.status == "suppressed"
    if case == "close":
        await closer
    assert not owner.results and not fake_herdr.capture.read_text()
    await transport.close()


async def test_cancel_during_late_spawn(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated cancellation cannot abandon a committed spawn before PID creation."""
    transport = transport_for(fake=fake_herdr, root=tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    original = transport._spawn
    processes: list[asyncio.subprocess.Process] = []

    async def delayed(*, command: HerdrCliCommandDAO) -> asyncio.subprocess.Process:
        """Hold creation but preserve the actual root guard on delegation."""
        entered.set()
        await release.wait()
        process = await original(command=command)
        processes.append(process)
        return process

    monkeypatch.setattr(target=transport, name="_spawn", value=delayed)
    owner = RecordingAdmission()
    task = asyncio.create_task(
        coro=transport.invoke(command=HerdrCliCommandDAO(argv=("pane", "split")), admission=owner)
    )
    await entered.wait()
    for _ in range(3):
        task.cancel()
        await asyncio.sleep(delay=0)
        assert transport._command_lock.locked() and not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(processes) == 1 and processes[0].returncode is not None
    assert len(owner.results) == 1 and owner.results[0].outcome.status == "cancelled"
    assert transport.resources_drained and not transport._command_lock.locked()


@pytest.mark.parametrize(argnames="mode", argvalues=["exact", "stdout_overflow", "stderr_overflow", "reject"])
async def test_concurrent_real_pipes(fake_herdr: FakeHerdrFixture, tmp_path: Path, mode: str) -> None:
    """Both actual pipe streams are bounded; rejected output is never retained."""
    # Change contents in place only after capability/containment verification.
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    assert fake_herdr.executable.resolve().is_relative_to(tmp_path.resolve())
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as script:
        script.write(
            "\nimport threading\n"
            f"mode = {mode!r}\n"
            "size = 16385 if mode == 'stderr_overflow' else 16384\n"
            "thread = threading.Thread(target=lambda: os.write(2, b'e' * size))\n"
            "thread.start()\n"
            "os.write(1, b'x' * (16385 if mode == 'stdout_overflow' else 16384))\n"
            "thread.join()\n"
            "sys.exit(7 if mode == 'reject' else 0)\n"
        )
    transport = transport_for(fake=fake_herdr, root=tmp_path)
    owner = RecordingAdmission()
    result = await transport.invoke(
        command=HerdrCliCommandDAO(argv=("pane", "split"), capture_json=True), admission=owner
    )
    expected = "ok" if mode == "exact" else "rejected" if mode == "reject" else "malformed"
    assert result.outcome.status == expected
    assert result.json_bytes == (b"x" * 16384 if mode == "exact" else None)
    assert transport.resources_drained and len(owner.results) == 1


async def test_signal_error_still_kills_and_reaps(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A termination failure must not exit before kill and wait."""
    transport = transport_for(fake=fake_herdr, root=tmp_path)
    calls: list[str] = []

    class Process:
        """Deterministic owned-process boundary for an OS permission failure."""

        returncode = None
        pid = 123

        async def wait(self) -> int:
            """Record mandatory reap."""
            calls.append("wait")
            return 0

    def signal_owned(*, process: object, force: bool) -> None:
        """Fail terminate only, without issuing any host signal."""
        calls.append("kill" if force else "terminate")
        if not force:
            raise PermissionError("private-signal-sentinel")

    monkeypatch.setattr(target=transport, name="_signal_owned", value=signal_owned)
    await transport._terminate_and_reap(process=cast(asyncio.subprocess.Process, Process()))
    assert calls == ["terminate", "kill", "wait"]


async def test_quarantine_final_drain(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed reap retains exact handles; final drain never reaccounts or reopens."""
    transport = transport_for(fake=fake_herdr, root=tmp_path)
    original = transport._terminate_and_reap
    attempts = 0

    async def failing_reap(*, process: asyncio.subprocess.Process) -> None:
        """Inject two cleanup defects, then allow actual owned reap."""
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise OSError("private-cleanup-sentinel")
        await original(process=process)

    monkeypatch.setattr(target=transport, name="_terminate_and_reap", value=failing_reap)
    owner = RecordingAdmission()
    result = await transport.invoke(command=HerdrCliCommandDAO(argv=("pane", "split")), admission=owner)
    assert result.outcome.status == "ok"
    assert transport.closed and not transport.resources_drained
    assert owner.results[0].outcome.status == "unavailable"
    assert (await transport.close()).resources == "retained"
    assert attempts == 2
    final = await transport.drain_retained_resources()
    assert final.replacement == "uncertain" and final.resources == "drained"
    assert final is await transport.drain_retained_resources()
    assert attempts == 3 and len(owner.results) == 1


async def test_accounting_diagnostic_cannot_interrupt_cleanup(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing diagnostic sink cannot expose callback text or skip drain."""
    import logging

    transport = transport_for(fake=fake_herdr, root=tmp_path)
    categories: list[str] = []

    class BrokenAdmission(RecordingAdmission):
        """Fail once at the mandatory terminal callback."""

        def complete(self, *, result) -> None:
            super().complete(result=result)
            raise ValueError("private-accounting-sentinel")

    def broken_warning(self, msg, *args, **kwargs) -> None:
        """Record fixed text then simulate a diagnostic sink failure."""
        categories.append(msg)
        raise OSError("private-logging-sentinel")

    monkeypatch.setattr(target=logging.Logger, name="warning", value=broken_warning)
    owner = BrokenAdmission()
    await transport.invoke(command=HerdrCliCommandDAO(argv=("pane", "split")), admission=owner)
    assert categories == ["herdr_accounting_failed"]
    assert transport.resources_drained and transport.closed and len(owner.results) == 1
    assert (await transport.close()).replacement == "uncertain"


async def test_ignores_term_timeout(fake_herdr: FakeHerdrFixture, tmp_path: Path) -> None:
    """Actual stubborn child receives group kill after the fixed grace interval."""
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    assert fake_herdr.executable.resolve().is_relative_to(tmp_path.resolve())
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as script:
        script.write("\nimport signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(30)\n")
    transport = transport_for(fake=fake_herdr, root=tmp_path)
    owner = RecordingAdmission()
    before = asyncio.get_running_loop().time()
    result = await transport.invoke(command=HerdrCliCommandDAO(argv=("pane", "split")), admission=owner)
    elapsed = asyncio.get_running_loop().time() - before
    assert result.outcome.status == "timeout" and result.admitted
    assert 1.2 <= elapsed < 3
    assert owner.results[0].outcome.status == "cancelled"
    assert transport.resources_drained
