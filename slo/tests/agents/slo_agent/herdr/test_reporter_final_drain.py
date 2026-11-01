"""Persistent reporter quarantine retains its lease and exactly one final drain."""

import asyncio
from pathlib import Path

import pytest

from tests.agents.slo_agent.herdr.test_reporter import reporter


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
async def test_final_reporter_drain_is_retained_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: bool,
    cancel: bool,
) -> None:
    """Cancellation joins final local drain; persistent failure never unlocks or retries."""
    owner = reporter(root=tmp_path)
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def drain() -> None:
        """Hold local cleanup independently of caller cancellation."""
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        if failure:
            raise RuntimeError("private-drain-sentinel")
        owner._transport._closed = True

    monkeypatch.setattr(target=owner._transport, name="drain_retained_resources", value=drain)
    task = asyncio.create_task(coro=owner.drain_retained_external_resources())
    await entered.wait()
    if cancel:
        for _ in range(2):
            task.cancel()
            await asyncio.sleep(delay=0)
            assert not task.done()
    release.set()
    try:
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
        result = await owner.drain_retained_external_resources()
        assert calls == 1
        assert result.replacement == "uncertain"
        assert result.resources == ("retained" if failure else "drained")
        assert owner._lease_held is failure
        assert owner._retired_reporter_drain_task is not None
        assert owner._retired_reporter_drain_task.done()
        assert not owner._retired_reporter_drain_task._log_traceback
        assert owner._shutdown_admitted is False
        assert "private-drain-sentinel" not in caplog.text
        if failure:
            assert "herdr_cleanup_unavailable" in caplog.text
    finally:
        # Only test teardown releases this test's real lease after asserting retention.
        owner._transport._closed = True
        await owner._release_lease()
