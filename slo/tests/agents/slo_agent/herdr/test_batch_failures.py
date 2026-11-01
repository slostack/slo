"""Real guarded executable batch ordering and metadata refresh evidence."""

import json
from pathlib import Path

import pytest

from tests.agents.slo_agent.herdr.test_reporter import publication, reporter
from tests.state_isolation import FakeHerdrFixture


@pytest.mark.parametrize("failure", ["claim", "display", "none"])
async def test_batch_failure_cutoffs_and_refresh(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, failure: str
) -> None:
    """Claim refusal stops all work; failed display does not prevent settlement."""
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    initial = publication()
    working = initial.model_copy(
        update={"snapshot": initial.snapshot.model_copy(update={"state": "working"})}
    )
    owner.publish(publication=working)
    try:
        if failure != "claim":
            await owner._publish_batch(publication=working, revision=1)
        assert fake_herdr.executable.resolve().parent == tmp_path.resolve()
        assert not fake_herdr.executable.is_symlink()
        command_name = "report-agent" if failure == "claim" else "report-metadata"
        if failure != "none":
            fake_herdr.executable.write_text(
                fake_herdr.executable.read_text() + f"\nif sys.argv[2] == {command_name!r}: sys.exit(7)\n"
            )
        before = len(fake_herdr.capture.read_text().splitlines())
        owner.publish(publication=initial)
        revision = owner._revision
        await owner._publish_batch(publication=initial, revision=revision)
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()][before:]
        if failure == "claim":
            assert len(commands) == 1 and commands[0][1] == "report-agent"
            assert owner._lifecycle_ack is None
        else:
            assert commands[0][1] == "report-metadata"
            assert commands[-1][1] == "report-agent"
            assert commands[-1][commands[-1].index("--state") + 1] == "idle"
            assert owner._lifecycle_ack is not None and owner._lifecycle_ack.state == "idle"
            assert (owner._display_ack_revision == revision) == (failure == "none")
        if failure == "none":
            before = len(fake_herdr.capture.read_text().splitlines())
            await owner._publish_batch(publication=initial, revision=revision)
            refreshed = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()][before:]
            assert len(refreshed) == 2
            assert all(command[1] == "report-metadata" for command in refreshed)
            assert all(command[command.index("--ttl-ms") + 1] == "5000" for command in refreshed)
            assert owner._revision == revision
            assert int(refreshed[0][-1]) > int(commands[-2][-1])
    finally:
        await owner.close()
        await owner.close_transport()
