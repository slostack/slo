"""Activation and close composition using real secure leases and guarded children."""

import asyncio
import json
import threading
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceStore
from tests.agents.slo_agent.herdr.test_reporter import reporter
from tests.state_isolation import FakeHerdrFixture


@pytest.mark.parametrize("case", ["repeat", "contention", "reject", "timeout", "cancel"])
async def test_activation_lifetime(fake_herdr: FakeHerdrFixture, tmp_path: Path, case: str) -> None:
    """Activation sends at most one release and drains failures without claims."""
    owner = reporter(root=tmp_path)
    owner._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    owner._transport._config = owner._config
    tmp_path.chmod(0o700)
    contender = HerdrSequenceStore(state_root=tmp_path, socket_namespace="default", pane_id="p")
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    if case in ("reject", "timeout", "cancel"):
        with fake_herdr.executable.open(mode="a", encoding="utf-8") as script:
            script.write("\nsys.exit(7)\n" if case == "reject" else "\nimport time\ntime.sleep(30)\n")
    if case == "contention":
        contender.acquire()
    start = asyncio.create_task(coro=owner.start())
    try:
        if case == "cancel":
            async with asyncio.timeout(delay=5):
                while not fake_herdr.capture.read_text():
                    await asyncio.sleep(delay=0)
            start.cancel()
            await asyncio.sleep(delay=0)
            start.cancel()
            with pytest.raises(asyncio.CancelledError):
                await start
        else:
            await asyncio.wait_for(fut=start, timeout=5)
        activation_task = owner._start_task
        await owner.start()
        assert owner._start_task is activation_task
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        assert len(commands) == (0 if case == "contention" else 1)
        assert all(command[1] == "release-agent" for command in commands)
        assert owner.allows_viewer_admission() is (case == "repeat")
        if case != "repeat":
            assert owner._worker is None and owner._refresh_task is None
        if case in ("contention", "reject", "timeout"):
            assert owner._disabled and owner._transport.closed
            assert not owner.retains_external_resources
    finally:
        if not start.done():
            start.cancel()
        await asyncio.gather(start, return_exceptions=True)
        await owner.close()
        final = await owner.close_transport()
        contender.close()
    assert final.resources == "drained"
    assert final.replacement == ("safe" if case == "repeat" else "uncertain")
    assert owner._transport.resources_drained and not owner._lease_held


async def test_close_during_acquire_joins_before_unlock(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated close cancellation cannot abandon the off-loop acquisition."""
    owner = reporter(root=tmp_path)
    owner._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    owner._transport._config = owner._config
    tmp_path.chmod(0o700)
    entered, release = threading.Event(), threading.Event()
    acquire = owner._sequence_store.acquire

    def held_acquire() -> None:
        """Acquire the real lease only after close has revoked admission."""
        entered.set()
        assert release.wait(timeout=5)
        acquire()

    monkeypatch.setattr(target=owner._sequence_store, name="acquire", value=held_acquire)
    start = asyncio.create_task(coro=owner.start())
    closer = None
    try:
        async with asyncio.timeout(delay=5):
            while not entered.is_set():
                await asyncio.sleep(delay=0)
        closer = asyncio.create_task(coro=owner.close())
        await asyncio.sleep(delay=0)
        retained = owner._close_task
        for _ in range(2):
            closer.cancel()
            await asyncio.sleep(delay=0)
        assert not closer.done() and not start.done()
        assert owner._ordinary_revoked and owner._closing
        release.set()
        await start
        with pytest.raises(asyncio.CancelledError):
            await closer
        assert owner._close_task is retained and retained is not None and retained.done()
        assert owner._lease_task is None and not owner._lease_held
        assert owner._worker is None and owner._refresh_task is None
        assert not fake_herdr.capture.read_text()
        assert (await owner.close()).replacement == "uncertain"
    finally:
        release.set()
        await asyncio.gather(start, return_exceptions=True)
        if closer is not None:
            await asyncio.gather(closer, return_exceptions=True)
        await owner.close()
        await owner.close_transport()
    assert owner._transport.closed and not owner.retains_external_resources
