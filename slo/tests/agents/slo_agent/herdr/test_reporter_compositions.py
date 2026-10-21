"""Real command and owned-save cancellation compositions for T2."""

import asyncio
import json
from pathlib import Path

import pytest

from tests.state_isolation import FakeHerdrFixture

from src.agents.slo_agent.herdr.dao import (
    HerdrDisplayTokenDAO,
    HerdrSavedRestoreDAO,
    HerdrRestoreConfigDAO,
    HerdrRestoreReferenceDAO,
)
from tests.agents.slo_agent.herdr.test_reporter import publication, reporter, plain_slo


@pytest.mark.parametrize("changed_generation", [False, True])
async def test_already_admitted_a_accounts_without_followup(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, changed_generation: bool
) -> None:
    """A finishes its actual claim but cannot acknowledge B or send stale display."""
    assert fake_herdr.executable.resolve().parent == tmp_path.resolve()
    assert not fake_herdr.executable.is_symlink()
    fake_herdr.executable.write_text(
        fake_herdr.executable.read_text()
        + f"\nif sys.argv[2] == 'report-agent':\n import select\n barrier = Path({str(fake_herdr.barrier)!r})\n while not barrier.read_text(): select.select([], [], [], 0.001)\n"
    )
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    first = publication()
    owner.publish(publication=first)
    task = asyncio.create_task(coro=owner._publish_batch(publication=first, revision=1))
    try:
        async with asyncio.timeout(0.5):
            while not fake_herdr.capture.read_text():
                await asyncio.sleep(0)
        ticket = owner._admitted_ticket
        assert ticket is not None and owner._binding is not None
        newer = first.model_copy(
            update={
                "configuration_generation": int(changed_generation),
                "snapshot": first.snapshot.model_copy(
                    update={"tokens": (HerdrDisplayTokenDAO(key="turn", value="9"),)}
                ),
            }
        )
        owner.publish(publication=newer)
        assert (
            fake_herdr.barrier.resolve().parent == tmp_path.resolve() and not fake_herdr.barrier.is_symlink()
        )
        fake_herdr.barrier.write_text("release")
        await task
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        assert len(commands) == 1 and commands[0][1] == "report-agent"
        assert owner._binding.configuration_generation == 0
        assert owner._binding.certainty == "confirmed"
        assert owner._admitted_ticket is None
        assert owner._lifecycle_ack is None and owner._display_ack_revision is None
        assert owner._pending is newer
        await owner._publish_batch(publication=newer, revision=2)
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        assert all(
            int(command[command.index("--seq") + 1]) > ticket.sequence
            for command in commands[1:]
            if "report-metadata" not in command
        )
        assert commands[1][1] == ("release-agent" if changed_generation else "report-metadata")
        assert owner._display_ack_revision == 2
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await owner.close()
        await owner.close_transport()


async def test_failed_save_uncertain_release_blocks_replacement(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, plain_slo: Path
) -> None:
    """Installed old reference survives uncertain withdrawal; no replacement leaks."""
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    first = publication(eligible=True)
    owner.publish(publication=first)
    try:
        await owner._consume_publication(publication=first)
        old_binding = owner._binding
        assert old_binding is not None and old_binding.reference is not None

        class FailedStore:
            """Refuse subsequent immutable saves without rewriting anything."""

            def save(self, *, config: HerdrRestoreConfigDAO) -> HerdrRestoreReferenceDAO:
                raise OSError("private-save-sentinel")

        owner._restore_store = FailedStore()
        newer = publication(generation=1, eligible=True)
        owner.publish(publication=newer)
        assert (
            fake_herdr.executable.resolve().parent == tmp_path.resolve()
            and not fake_herdr.executable.is_symlink()
        )
        script = fake_herdr.executable.read_text()
        fake_herdr.executable.write_text(script + "\nif sys.argv[2] == 'release-agent': sys.exit(1)\n")
        count = len(fake_herdr.capture.read_text().splitlines())
        await owner._consume_publication(publication=newer)
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()][count:]
        assert len(commands) == 1 and commands[0][1] == "release-agent"
        assert owner._binding == old_binding and owner._withdrawal_pending
        assert owner._saved is None and owner._save_task is None
        assert (
            fake_herdr.executable.resolve().parent == tmp_path.resolve()
            and not fake_herdr.executable.is_symlink()
        )
        fake_herdr.executable.write_text(script)
        await owner._consume_publication(publication=newer)
        assert owner._binding is not None and owner._binding.reference is None
        assert not owner._withdrawal_pending
        assert owner._binding.configuration_generation == 1
    finally:
        await owner.close()
        await owner.close_transport()
    assert not owner.retains_external_resources


@pytest.mark.parametrize("error", [False, True])
async def test_save_join_repeated_cancel_drains_and_retrieves(tmp_path: Path, error: bool) -> None:
    """Repeated cancellation waits for the owned save, even when it then fails."""
    owner = reporter(root=tmp_path)
    release = asyncio.Event()
    entered = asyncio.Event()

    async def save() -> HerdrSavedRestoreDAO:
        """Hold the owned operation until the test releases its terminal result."""
        entered.set()
        await release.wait()
        if error:
            raise OSError("private-save-sentinel")
        return await owner._save_capture(publication=publication(eligible=True))

    owned = asyncio.create_task(coro=save())
    owner._save_task = owned
    waiter = asyncio.create_task(coro=owner._join_save())
    await entered.wait()
    waiter.cancel()
    await asyncio.sleep(0)
    waiter.cancel()
    await asyncio.sleep(0)
    assert not waiter.done() and not owned.cancelled()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert owned.done() and not owned._log_traceback
    assert owner._save_task is None
