"""Reader failure and cancellation retain real child ownership through reap."""

import asyncio
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO
from src.agents.slo_agent.herdr.service import HerdrOutputLimitError
from tests.agents.slo_agent.herdr.test_cli_transport import RecordingAdmission
from tests.agents.slo_agent.herdr.test_transport_lifetime import transport_for
from tests.state_isolation import FakeHerdrFixture


@pytest.mark.parametrize(argnames="case", argvalues=["pipe_error", "mixed_group", "cancel_read"])
async def test_reader_failure_joins_owned_tasks(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Inject reader faults after actual guarded spawn; never leak sibling readers."""
    transport = transport_for(fake=fake_herdr, root=tmp_path)
    both_entered = asyncio.Event()
    release = asyncio.Event()
    readers: list[asyncio.Task[object]] = []
    finished: list[int] = []
    processes: list[asyncio.subprocess.Process] = []
    original_spawn = transport._spawn

    async def spawn(*, command: HerdrCliCommandDAO) -> asyncio.subprocess.Process:
        """Observe the real guarded child without replacing its process lifetime."""
        process = await original_spawn(command=command)
        processes.append(process)
        return process

    async def read(*, stream: asyncio.StreamReader) -> bytes:
        """Hold both readers until the test injects simultaneous faults or cancellation."""
        task = asyncio.current_task()
        assert task is not None
        index = len(readers)
        readers.append(task)
        if len(readers) == 2:
            both_entered.set()
        try:
            await release.wait()
            if case == "mixed_group" and index == 0:
                raise HerdrOutputLimitError
            raise OSError("private-pipe-sentinel")
        finally:
            finished.append(index)

    monkeypatch.setattr(target=transport, name="_spawn", value=spawn)
    monkeypatch.setattr(target=transport, name="_read_bounded", value=read)
    owner = RecordingAdmission()
    invocation = asyncio.create_task(
        coro=transport.invoke(
            command=HerdrCliCommandDAO(argv=("pane", "split"), capture_json=True), admission=owner
        )
    )
    await asyncio.wait_for(fut=both_entered.wait(), timeout=2)
    if case == "cancel_read":
        invocation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await invocation
        expected = "cancelled"
    else:
        release.set()
        result = await invocation
        expected = "unavailable"
        assert result.outcome.status == expected
        assert result.json_bytes is None
    assert sorted(finished) == [0, 1]
    assert all(task.done() for task in readers)
    assert len(processes) == 1 and processes[0].returncode is not None
    assert len(owner.results) == 1 and owner.results[0].outcome.status == expected
    assert not owner.results[0].spawn_failed
    assert transport.resources_drained and not transport._command_lock.locked()
    assert transport._cleanup_task is None
    assert (await transport.close()).resources == "drained"
