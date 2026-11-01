"""Short-read refusal reaches reporter reservation and queued real viewer admission."""

import asyncio
import os
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.dao import HerdrVisualizerRequestDAO
from tests.agents.slo_agent.herdr.test_reporter import reporter, SESSION
from tests.state_isolation import FakeHerdrFixture


@pytest.mark.parametrize(argnames="case", argvalues=["suffix", "overflow", "error"])
async def test_short_read_refusal_blocks_report_and_queued_viewer(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """No sendable ticket or executable entry follows corrupt reservation-time reads."""
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    owner._sequence_store.acquire()
    owner._sequence_store.reserve(source="custom:slo")
    owner._lease_held = owner._activation_released = True
    viewer = owner.build_visualizer()
    path = owner._sequence_store._path
    valid = path.read_bytes()
    content = valid + (b"INVALID" if case == "suffix" else b"")
    if case == "overflow":
        content += b" " * (4097 - len(content))
    assert path.resolve().is_relative_to(tmp_path.resolve()) and not path.is_symlink()
    path.write_bytes(content)
    real_read = os.read
    reads = 0

    def short_read(fd: int, size: int) -> bytes:
        """Return a valid prefix before exposing corruption, overflow or read failure."""
        nonlocal reads
        reads += 1
        if case == "error" and reads > 1:
            raise OSError("private-read-sentinel")
        return real_read(fd, min(size, len(valid)))

    lock = owner._transport._command_lock
    await lock.acquire()
    task = asyncio.create_task(
        coro=viewer.invoke(
            request=HerdrVisualizerRequestDAO(parent_session_id=SESSION, history_root=tmp_path)
        )
    )
    try:
        async with asyncio.timeout(delay=2):
            while not lock._waiters:
                await asyncio.sleep(delay=0)
        with monkeypatch.context() as patch:
            patch.setattr(target=os, name="read", value=short_read)
            ticket = await owner._reserve_ticket(operation="activation_release")
        assert ticket is None and not owner._sequence_safe and owner._disabled
        assert not owner.allows_viewer_admission()
        lock.release()
        assert (await task).status == "failed"
        await owner._send_release(operation="shutdown_release")
        assert path.read_bytes() == content
        assert fake_herdr.capture.read_text() == ""
        assert reads > 1
    finally:
        if lock.locked():
            lock.release()
        await viewer.close()
        await task
        await owner.close()
        await owner.close_transport()
