"""Real transport restore uncertainty through the complete reporter batch."""

import asyncio
import json
from pathlib import Path

import pytest

from tests.agents.slo_agent.herdr.test_reporter import publication, reporter, plain_slo
from tests.state_isolation import FakeHerdrFixture


@pytest.mark.parametrize("case", ["rejected", "timeout", "current_ok", "stale_ok", "stale_timeout"])
async def test_restore_uncertainty_batch(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, plain_slo: Path, case: str
) -> None:
    """An install failure retains identity; stale installs cannot send any old follow-up."""
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    assert tmp_path.resolve() == tmp_path and not tmp_path.is_symlink()
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    script = fake_herdr.executable.read_text()
    suffix = "\nif '--herdr-restore' in sys.argv:\n"
    if case == "rejected":
        suffix += " sys.exit(9)\n"
    elif case == "current_ok":
        suffix += " pass\n"
    else:
        suffix += (
            " import select\n"
            f" while not Path({str(fake_herdr.barrier)!r}).read_text(): select.select([], [], [], 0.001)\n"
        )
    fake_herdr.executable.write_text(script + suffix)
    task = asyncio.create_task(coro=owner._consume_publication(publication=facts))
    try:
        if case.startswith("stale"):
            async with asyncio.timeout(delay=0.8):
                while "--herdr-restore" not in fake_herdr.capture.read_text():
                    await asyncio.sleep(delay=0)
            owner.publish(publication=publication(generation=1, eligible=True))
            if case == "stale_ok":
                fake_herdr.guard.require_registered(path=fake_herdr.executable)
                fake_herdr.barrier.write_text("release")
        await asyncio.wait_for(fut=task, timeout=3)
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        assert sum("--herdr-restore" in command for command in commands) == 1
        assert owner._binding is not None and owner._binding.certainty == "confirmed"
        assert owner._binding.configuration_generation == 0
        assert owner._binding.reference is not None
        assert owner._transport.resources_drained
        if case.startswith("stale"):
            assert [command[1] for command in commands] == ["report-agent", "report-agent"]
            assert owner._restore_ack is None and owner._lifecycle_ack is None
            assert owner._display_ack_revision is None
        else:
            assert commands[2][1] == "report-metadata"
            assert owner._display_ack_revision == 1
            assert owner._lifecycle_ack is not None and owner._lifecycle_ack.state == "idle"
            assert (owner._restore_ack is not None) == (case == "current_ok")
            if case != "current_ok":
                assert commands[-1][1] == "report-agent" and "--herdr-restore" not in commands[-1]
        fake_herdr.guard.require_registered(path=fake_herdr.executable)
        fake_herdr.executable.write_text(script)
        before = len(commands)
        assert owner._latest is not None
        await owner._consume_publication(publication=owner._latest)
        later = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()][before:]
        assert sum("--herdr-restore" in command for command in later) == (case != "current_ok")
        if case.startswith("stale"):
            assert later[0][1] == "release-agent"
        assert owner._restore_ack == owner._saved
    finally:
        fake_herdr.guard.require_registered(path=fake_herdr.executable)
        fake_herdr.executable.write_text(script)
        if not task.done():
            task.cancel()
        await asyncio.wait_for(fut=asyncio.gather(task, return_exceptions=True), timeout=3)
        await owner.close()
        await owner.close_transport()
