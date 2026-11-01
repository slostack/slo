"""Owned-task and real-subprocess contracts for the shared Herdr transport."""

import asyncio
from pathlib import Path

from tests.state_isolation import FakeHerdrFixture

import pytest

from src.agents.slo_agent.herdr.dao import HerdrCommandOutcomeDAO, HerdrCommandResultDAO
from src.agents.slo_agent.herdr.service import HerdrTaskJoin, HerdrTransportAdmission


@pytest.mark.parametrize(argnames="cancel", argvalues=[False, True])
async def test_unexpected_finalizer_defect_seals_and_accounts(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    """A defective finalizer retains ownership and cannot authorize a successor."""
    from src.agents.slo_agent.herdr.service import HerdrCliTransport
    from src.agents.slo_agent.herdr.dao import HerdrReporterConfigDAO, HerdrCliCommandDAO

    transport = HerdrCliTransport(
        config=HerdrReporterConfigDAO(
            pane_id="p",
            binary_path=fake_herdr.executable,
            state_root=tmp_path,
            metadata_profile="compact",
        ),
        environment={},
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def defective(**kwargs: object) -> None:
        """Fail after an explicit cancellation opportunity, without touching the child."""
        entered.set()
        await release.wait()
        raise RuntimeError("private-finalizer-sentinel")

    monkeypatch.setattr(target=transport, name="_finish_admitted", value=defective)
    owner = RecordingAdmission()
    command = HerdrCliCommandDAO(argv=("pane", "split"))
    invocation = asyncio.create_task(coro=transport.invoke(command=command, admission=owner))
    await entered.wait()
    if cancel:
        invocation.cancel()
        await asyncio.sleep(delay=0)
        invocation.cancel()
    release.set()
    try:
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await invocation
        else:
            assert (await invocation).outcome.status == "ok"
        assert transport.closed and transport._cleanup_failed
        assert transport._cleanup_task is None
        assert len(owner.results) == 1
        assert owner.results[0].outcome.status == "unavailable"
        assert not transport.resources_drained
        refused = RecordingAdmission()
        assert (await transport.invoke(command=command, admission=refused)).outcome.status == "suppressed"
        assert refused.attempts == 0
    finally:
        outcome = await transport.close()
        assert transport.resources_drained
    assert outcome.replacement == "uncertain"
    assert len(owner.results) == 1


class RecordingAdmission:
    """Record one command's authority and terminal accounting."""

    def __init__(self, *, allowed: bool = True) -> None:
        """Capture mutable authority for queued-command tests."""
        self.allowed = allowed
        self.attempts = 0
        self.results: list[HerdrCommandResultDAO] = []

    def try_admit(self) -> bool:
        """Record synchronous admission attempts."""
        self.attempts += 1
        return self.allowed

    def complete(self, *, result: HerdrCommandResultDAO) -> None:
        """Retain safe terminal evidence."""
        self.results.append(result)


@pytest.mark.parametrize(argnames="allowed", argvalues=[True, False])
def test_transport_admission_is_one_shot(allowed: bool) -> None:
    """Rejected and accepted capabilities cannot be reused."""
    owner = RecordingAdmission(allowed=allowed)
    tracked = HerdrTransportAdmission(delegate=owner)
    assert tracked.try_admit() is allowed
    assert not tracked.try_admit()
    result = HerdrCommandResultDAO(outcome=HerdrCommandOutcomeDAO(status="ok"), admitted=True)
    tracked.complete(result=result)
    tracked.complete(result=result)
    assert owner.attempts == 1
    assert owner.results == ([result] if allowed else [])


@pytest.mark.parametrize(
    argnames="case",
    argvalues=["complete", "pending", "error", "single_cancel", "repeated_cancel", "owned_cancel"],
)
async def test_join_drains_before_return(case: str) -> None:
    """Joining never cancels retained work, even under repeated caller cancellation."""
    started, release = asyncio.Event(), asyncio.Event()

    async def owned() -> None:
        """Wait for explicit test release, optionally failing privately."""
        started.set()
        await release.wait()
        if case == "error":
            raise ValueError("private-sentinel")

    task = asyncio.create_task(coro=owned())
    await started.wait()
    if case in ("complete", "error"):
        release.set()
        await asyncio.sleep(delay=0)
    if case == "owned_cancel":
        task.cancel()
        await asyncio.sleep(delay=0)
    waiter = asyncio.create_task(coro=HerdrTaskJoin.wait(task=task))
    await asyncio.sleep(delay=0)
    for _ in range({"single_cancel": 1, "repeated_cancel": 2}.get(case, 0)):
        waiter.cancel()
        await asyncio.sleep(delay=0)
        assert not task.cancelled() and not waiter.done()
    release.set()
    assert await waiter is (case in ("single_cancel", "repeated_cancel"))
    assert task.done()
    assert task.cancelled() is (case == "owned_cancel")
    assert not task._log_traceback


async def test_spawn_boundary_refuses_unregistered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment activation alone never grants executable permission."""
    from src.agents.slo_agent.herdr.service import HerdrCliTransport
    from src.agents.slo_agent.herdr.dao import HerdrReporterConfigDAO, HerdrCliCommandDAO

    transport = HerdrCliTransport(
        config=HerdrReporterConfigDAO(
            pane_id="p",
            binary_path=tmp_path / "never-created",
            state_root=tmp_path,
            metadata_profile="compact",
        ),
        environment={"HERDR_ENV": "1"},
    )
    with pytest.raises(AssertionError, match="Unregistered"):
        await transport._spawn(command=HerdrCliCommandDAO(argv=("pane", "split")))


async def test_registered_spawn_is_real_and_environment_is_allowlisted(
    fake_herdr: FakeHerdrFixture, tmp_path: Path
) -> None:
    """Actual subprocess entry uses only the registered new regular executable."""
    import json
    from src.agents.slo_agent.herdr.service import HerdrCliTransport
    from src.agents.slo_agent.herdr.dao import HerdrReporterConfigDAO, HerdrCliCommandDAO

    environment = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "HERDR_ENV": "1",
        "OPENAI_API_KEY": "private-sentinel",
        "PYTHONPATH": "private-sentinel",
    }
    transport = HerdrCliTransport(
        config=HerdrReporterConfigDAO(
            pane_id="p",
            binary_path=fake_herdr.executable,
            state_root=tmp_path,
            socket_path="synthetic-socket",
            metadata_profile="compact",
        ),
        environment=environment,
    )
    environment["HOME"] = "changed-after-capture"
    assert transport._environment == {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "HERDR_ENV": "1",
        "HERDR_PANE_ID": "p",
        "HERDR_BIN_PATH": str(fake_herdr.executable),
        "HERDR_SOCKET_PATH": "synthetic-socket",
    }
    process = await transport._spawn(command=HerdrCliCommandDAO(argv=("pane", "split")))
    assert await process.wait() == 0
    assert json.loads(fake_herdr.capture.read_text()) == ["pane", "split"]


@pytest.mark.parametrize(argnames="size", argvalues=[0, 16384, 16385])
async def test_bounded_reader(size: int) -> None:
    """Read no more than one excess byte and refuse the entire overflow."""
    from src.agents.slo_agent.herdr.service import HerdrCliTransport, HerdrOutputLimitError

    stream = asyncio.StreamReader()
    stream.feed_data(b"x" * size)
    stream.feed_eof()
    if size > 16384:
        with pytest.raises(HerdrOutputLimitError, match="^$"):
            await HerdrCliTransport._read_bounded(stream=stream)
    else:
        assert await HerdrCliTransport._read_bounded(stream=stream) == b"x" * size


@pytest.mark.parametrize(argnames="capture_json", argvalues=[False, True])
async def test_collect_result(fake_herdr: FakeHerdrFixture, tmp_path: Path, capture_json: bool) -> None:
    """Real pipes are concurrently joined and only successful stdout is retained."""
    from src.agents.slo_agent.herdr.service import HerdrCliTransport
    from src.agents.slo_agent.herdr.dao import HerdrReporterConfigDAO, HerdrCliCommandDAO

    transport = HerdrCliTransport(
        config=HerdrReporterConfigDAO(
            pane_id="p", binary_path=fake_herdr.executable, state_root=tmp_path, metadata_profile="compact"
        ),
        environment={},
    )
    command = HerdrCliCommandDAO(argv=("pane", "split"), capture_json=capture_json)
    transport._active = await transport._spawn(command=command)
    result = await transport._collect_result(command=command)
    assert result.outcome.status == "ok" and result.outcome.exit_code == 0
    assert result.admitted and result.json_bytes == (b"" if capture_json else None)
    assert transport._active.returncode == 0


@pytest.mark.parametrize(argnames="running", argvalues=[False, True])
async def test_terminate_and_reap(fake_herdr: FakeHerdrFixture, tmp_path: Path, running: bool) -> None:
    """The owned new-session process is reaped whether running or already exited."""
    from src.agents.slo_agent.herdr.service import HerdrCliTransport
    from src.agents.slo_agent.herdr.dao import HerdrReporterConfigDAO, HerdrCliCommandDAO

    transport = HerdrCliTransport(
        config=HerdrReporterConfigDAO(
            pane_id="p", binary_path=fake_herdr.executable, state_root=tmp_path, metadata_profile="compact"
        ),
        environment={},
    )
    process = await transport._spawn(command=HerdrCliCommandDAO(argv=("pane", "split")))
    if not running:
        await process.wait()
    await transport._terminate_and_reap(process=process)
    assert process.returncode is not None


@pytest.mark.parametrize(argnames="failure", argvalues=[False, True])
async def test_observe_and_drain_spawn(fake_herdr: FakeHerdrFixture, tmp_path: Path, failure: bool) -> None:
    """Definitive spawn refusal is distinct from admitted remote uncertainty."""
    from src.agents.slo_agent.herdr.service import HerdrCliTransport
    from src.agents.slo_agent.herdr.dao import HerdrReporterConfigDAO, HerdrCliCommandDAO

    transport = HerdrCliTransport(
        config=HerdrReporterConfigDAO(
            pane_id="p", binary_path=fake_herdr.executable, state_root=tmp_path, metadata_profile="compact"
        ),
        environment={},
    )
    command = HerdrCliCommandDAO(argv=("pane", "split"))

    async def refused() -> asyncio.subprocess.Process:
        """Model a kernel refusal without creating a process."""
        raise OSError("private-spawn-sentinel")

    assert callable(transport._observe_admitted) and callable(transport._drain_admitted)
    transport._spawn_task = asyncio.create_task(
        coro=refused() if failure else transport._spawn(command=command)
    )
    result = await transport._observe_admitted(command=command)
    terminal = await transport._drain_admitted(result=result)
    assert terminal.spawn_failed is failure
    assert terminal.outcome.status == ("unavailable" if failure else "ok")
    assert "private-spawn-sentinel" not in repr(terminal)


async def test_finish_accounts_once_after_drain(fake_herdr: FakeHerdrFixture, tmp_path: Path) -> None:
    """Terminal accounting follows real reap and clears owned slots."""
    from src.agents.slo_agent.herdr.service import HerdrCliTransport
    from src.agents.slo_agent.herdr.dao import HerdrReporterConfigDAO, HerdrCliCommandDAO

    transport = HerdrCliTransport(
        config=HerdrReporterConfigDAO(
            pane_id="p", binary_path=fake_herdr.executable, state_root=tmp_path, metadata_profile="compact"
        ),
        environment={},
    )
    assert callable(transport._finish_admitted)
    command = HerdrCliCommandDAO(argv=("pane", "split"))
    owner = RecordingAdmission()
    transport._spawn_task = asyncio.create_task(coro=transport._spawn(command=command))
    result = await transport._observe_admitted(command=command)
    await transport._finish_admitted(admission=owner, result=result)
    assert owner.results == [result]
    assert transport._active is None and transport._spawn_task is None


async def test_close_seals_and_caches_drain(fake_herdr: FakeHerdrFixture, tmp_path: Path) -> None:
    """Local close cannot reopen transport or issue remote commands."""
    from src.agents.slo_agent.herdr.service import HerdrCliTransport
    from src.agents.slo_agent.herdr.dao import HerdrReporterConfigDAO, HerdrCliCommandDAO

    transport = HerdrCliTransport(
        config=HerdrReporterConfigDAO(
            pane_id="p", binary_path=fake_herdr.executable, state_root=tmp_path, metadata_profile="compact"
        ),
        environment={},
    )
    first = await transport.close()
    assert first is await transport.close()
    assert transport.closed and transport.resources_drained
    assert first.replacement == "safe" and first.resources == "drained"
    assert (await transport.drain_retained_resources()).resources == "drained"
    owner = RecordingAdmission()
    assert (
        await transport.invoke(command=HerdrCliCommandDAO(argv=("pane", "split")), admission=owner)
    ).outcome.status == "suppressed"
    assert owner.attempts == 0 and not fake_herdr.capture.read_text()


@pytest.mark.parametrize(argnames="allowed", argvalues=[True, False])
async def test_invoke_admission(fake_herdr: FakeHerdrFixture, tmp_path: Path, allowed: bool) -> None:
    """Real invocation has mandatory owner admission and terminal local evidence."""
    from src.agents.slo_agent.herdr.service import HerdrCliTransport
    from src.agents.slo_agent.herdr.dao import HerdrReporterConfigDAO, HerdrCliCommandDAO

    transport = HerdrCliTransport(
        config=HerdrReporterConfigDAO(
            pane_id="p", binary_path=fake_herdr.executable, state_root=tmp_path, metadata_profile="compact"
        ),
        environment={},
    )
    owner = RecordingAdmission(allowed=allowed)
    result = await transport.invoke(command=HerdrCliCommandDAO(argv=("pane", "split")), admission=owner)
    assert result.admitted is allowed
    assert result.outcome.status == ("ok" if allowed else "suppressed")
    assert len(owner.results) == int(allowed)
    assert bool(fake_herdr.capture.read_text()) is allowed
    assert transport._active is None and transport._spawn_task is None
