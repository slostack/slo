"""Reporter timeout isolation against an independently owned shared-lock holder."""

import asyncio
import json
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO
from tests.agents.slo_agent.herdr.test_cli_transport import RecordingAdmission
from tests.agents.slo_agent.herdr.test_reporter import publication, reporter
from tests.state_isolation import FakeHerdrFixture


async def test_reporter_timeout_does_not_drain_independent_viewer(
    fake_herdr: FakeHerdrFixture, tmp_path: Path
) -> None:
    """A real viewer child stays alive and locked past a queued reporter deadline.

    The holder enters the shared locked primitive directly, so its lifetime has
    no reporter timeout. T4's actual viewer adapter is deliberately not claimed.
    """
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as script:
        script.write(
            "\nif sys.argv[2] == 'split':\n"
            " import select\n"
            f" barrier = Path({str(fake_herdr.barrier)!r})\n"
            " while not barrier.read_text(): select.select([], [], [], 0.001)\n"
        )
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    facts = publication()
    owner.publish(publication=facts)
    admission = RecordingAdmission()
    holder = asyncio.create_task(
        coro=owner._transport._invoke_locked(
            command=HerdrCliCommandDAO(argv=("pane", "split")), admission=admission
        )
    )
    try:
        async with asyncio.timeout(delay=5):
            while not fake_herdr.capture.read_text() or owner._transport._active is None:
                await asyncio.sleep(delay=0)
        process = owner._transport._active
        assert process is not None
        result = await owner._send_report_operation(operation="claim", publication=facts, revision=1)
        assert result is False
        assert not holder.done() and process.returncode is None
        assert owner._transport._command_lock.locked()
        assert owner._transport._active is process
        assert owner._lease_held and not admission.results
        assert owner._binding is None and owner._admitted_ticket is None
        assert [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()] == [
            ["pane", "split"]
        ]
        fake_herdr.guard.require_registered(path=fake_herdr.executable)
        fake_herdr.barrier.write_text("release", encoding="utf-8")
        assert (await holder).outcome.status == "ok"
        assert process.returncode == 0 and len(admission.results) == 1
        assert owner._transport.resources_drained
        assert await owner._send_report_operation(operation="claim", publication=facts, revision=1)
        assert owner._binding is not None and owner._binding.certainty == "confirmed"
    finally:
        if not holder.done():
            holder.cancel()
        await asyncio.gather(holder, return_exceptions=True)
        await owner.close()
        await owner.close_transport()
    assert not owner.retains_external_resources
