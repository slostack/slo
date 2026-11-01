"""Retained real transport handles keep the actual pane lease until final drain."""

import asyncio
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO
from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceStore, HerdrSequenceUnavailableError
from tests.agents.slo_agent.herdr.test_cli_transport import RecordingAdmission
from tests.agents.slo_agent.herdr.test_reporter import reporter
from tests.state_isolation import FakeHerdrFixture


@pytest.mark.parametrize("cancel", [False, True])
async def test_retained_real_transport_drains_before_lease_release(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    """Final local drain joins a real child, never reaccounts or resends release."""
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    original = owner._transport._terminate_and_reap
    entered, release = asyncio.Event(), asyncio.Event()
    attempts = 0

    async def held_reap(*, process: asyncio.subprocess.Process) -> None:
        """Fail two local attempts, then hold the final real reap for cancellation."""
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise OSError("synthetic-private-reap")
        entered.set()
        await release.wait()
        await original(process=process)

    monkeypatch.setattr(target=owner._transport, name="_terminate_and_reap", value=held_reap)
    admission = RecordingAdmission()
    contender = HerdrSequenceStore(state_root=tmp_path, socket_namespace="default", pane_id="p")
    final_task = None
    try:
        await owner._transport.invoke(command=HerdrCliCommandDAO(argv=("pane", "split")), admission=admission)
        process = owner._transport._active
        assert process is not None and owner._transport.closed
        assert (await owner.close_transport()).resources == "retained"
        assert attempts == 2 and owner._lease_held
        with pytest.raises(HerdrSequenceUnavailableError):
            contender.acquire()
        final_task = asyncio.create_task(coro=owner.drain_retained_external_resources())
        await asyncio.wait_for(fut=entered.wait(), timeout=2)
        retained = owner._retired_reporter_drain_task
        if cancel:
            for _ in range(2):
                final_task.cancel()
                await asyncio.sleep(delay=0)
            assert not final_task.done()
        assert owner._lease_held and len(admission.results) == 1
        with pytest.raises(HerdrSequenceUnavailableError):
            contender.acquire()
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await final_task
        else:
            assert (await final_task).resources == "drained"
        result = await owner.drain_retained_external_resources()
        assert result.replacement == "uncertain" and result.resources == "drained"
        assert retained is owner._retired_reporter_drain_task and attempts == 3
        assert process.returncode is not None and owner._transport.resources_drained
        assert not owner._lease_held and len(admission.results) == 1
        assert len(fake_herdr.capture.read_text().splitlines()) == 1
        contender.acquire()
    finally:
        release.set()
        if final_task is not None:
            await asyncio.gather(final_task, return_exceptions=True)
        monkeypatch.setattr(target=owner._transport, name="_terminate_and_reap", value=original)
        if not owner._transport.resources_drained:
            await owner._transport._drain_quarantined_resources()
        await owner._release_lease()
        contender.close()
