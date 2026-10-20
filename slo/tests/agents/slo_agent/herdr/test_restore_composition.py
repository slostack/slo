"""Actual restore-store failures composed with reporter and guarded CLI transport."""

import json
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.restore import HerdrRestoreStore
from tests.agents.slo_agent.herdr.test_reporter import plain_slo, publication, reporter
from tests.state_isolation import FakeHerdrFixture


@pytest.mark.parametrize("release_fails", [False, True])
async def test_real_store_failure_withdrawal(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, plain_slo: Path, release_fails: bool
) -> None:
    """An unsafe real store never advertises or acknowledges replacement policy."""
    assert tmp_path.resolve() == tmp_path
    owner = reporter(root=tmp_path)
    owner._restore_store = HerdrRestoreStore(state_root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    owner._sequence_store.acquire()
    owner._lease_held = True
    first = publication(eligible=True)
    owner.publish(publication=first)
    script = fake_herdr.executable.read_text()
    try:
        await owner._consume_publication(publication=first)
        assert owner._restore_ack is not None
        old_binding = owner._binding
        old_ack = owner._restore_ack
        old_bytes = {path.name: path.read_bytes() for path in (tmp_path / "restore-v1").iterdir()}
        offset = len(fake_herdr.capture.read_text().splitlines())
        if release_fails:
            fake_herdr.guard.require_registered(path=fake_herdr.executable)
            fake_herdr.executable.write_text(script + "\nif 'release-agent' in sys.argv: sys.exit(9)\n")
        (tmp_path / "restore-v1").chmod(0o755)
        newer = publication(generation=1, eligible=True)
        owner.publish(publication=newer)
        await owner._consume_publication(publication=newer)
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()][offset:]
        assert commands and commands[0][1] == "release-agent"
        assert all("--herdr-restore" not in command for command in commands)
        if release_fails:
            assert owner._restore_ack == old_ack
            assert owner._restore_ack.configuration_generation == 0
            assert owner._binding == old_binding
            assert len(commands) == 1
        else:
            assert owner._restore_ack is None
            assert owner._binding is not None and owner._binding.reference is None
        assert {path.name: path.read_bytes() for path in (tmp_path / "restore-v1").iterdir()} == old_bytes
    finally:
        fake_herdr.guard.require_registered(path=fake_herdr.executable)
        fake_herdr.executable.write_text(script)
        (tmp_path / "restore-v1").chmod(0o700)
        await owner.close()
        await owner.close_transport()
