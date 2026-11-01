"""Platform signal and reap decisions without issuing any host signal."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Optional, cast

import pytest

from src.agents.slo_agent.herdr import service
from tests.agents.slo_agent.herdr.test_transport_lifetime import transport_for
from tests.state_isolation import FakeHerdrFixture


class ProcessBoundary:
    """Record only the process API used by the transport cleanup owner."""

    pid = 123

    def __init__(self, *, exited: bool = False, wait_error: bool = False) -> None:
        """Configure deterministic exit and wait refusal, without creating a child."""
        self.returncode: Optional[int] = 0 if exited else None
        self.wait_error = wait_error
        self.calls: list[str] = []

    def kill(self) -> None:
        """Record non-POSIX escalation."""
        self.calls.append("kill")

    def terminate(self) -> None:
        """Record non-POSIX graceful termination."""
        self.calls.append("terminate")

    async def wait(self) -> int:
        """Record reap and optionally reject it without claiming a terminal process."""
        self.calls.append("wait")
        if self.wait_error:
            raise OSError("private-wait-sentinel")
        self.returncode = 0
        return 0


@pytest.mark.parametrize(argnames="platform", argvalues=["posix", "nt"])
@pytest.mark.parametrize(argnames="force", argvalues=[False, True])
@pytest.mark.parametrize(argnames="vanished", argvalues=[False, True])
def test_signal_owned_platforms(
    fake_herdr: FakeHerdrFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    force: bool,
    vanished: bool,
) -> None:
    """Select the owned group or process API and tolerate a vanished target."""
    transport = transport_for(fake=fake_herdr, root=tmp_path)
    process = ProcessBoundary()
    groups: list[tuple[int, int]] = []

    def killpg(pid: int, signum: int) -> None:
        """Intercept the positional OS boundary; never signal a real process."""
        groups.append((pid, signum))
        if vanished:
            raise ProcessLookupError

    def vanished_process() -> None:
        """Simulate a process disappearing before the platform API call."""
        process.calls.append("kill" if force else "terminate")
        raise ProcessLookupError

    monkeypatch.setattr(target=service, name="os", value=SimpleNamespace(name=platform, killpg=killpg))
    if vanished:
        monkeypatch.setattr(target=process, name="kill" if force else "terminate", value=vanished_process)
    transport._signal_owned(process=cast(asyncio.subprocess.Process, process), force=force)
    if platform == "posix":
        assert groups == [(123, service.signal.SIGKILL if force else service.signal.SIGTERM)]
        assert process.calls == []
    else:
        assert groups == []
        assert process.calls == ["kill" if force else "terminate"]


@pytest.mark.parametrize(argnames="case", argvalues=["exited", "wait_error", "kill_error"])
async def test_reap_failure_remains_visible_to_owner(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Do not turn a failed reap into false drained evidence; exited children only wait."""
    transport = transport_for(fake=fake_herdr, root=tmp_path)
    process = ProcessBoundary(exited=case == "exited", wait_error=case == "wait_error")

    def signal_owned(*, process: object, force: bool) -> None:
        """Inject escalation failure without touching any system process."""
        boundary.calls.append("kill" if force else "terminate")
        if case == "kill_error":
            raise OSError("private-signal-sentinel")

    boundary = process
    monkeypatch.setattr(target=transport, name="_signal_owned", value=signal_owned)
    if case == "exited":
        await transport._terminate_and_reap(process=cast(asyncio.subprocess.Process, process))
        assert process.calls == ["wait"]
        return
    with pytest.raises(OSError):
        await transport._terminate_and_reap(process=cast(asyncio.subprocess.Process, process))
    assert process.calls == (["terminate", "wait"] if case == "wait_error" else ["terminate", "kill"])
    assert process.returncode is None
