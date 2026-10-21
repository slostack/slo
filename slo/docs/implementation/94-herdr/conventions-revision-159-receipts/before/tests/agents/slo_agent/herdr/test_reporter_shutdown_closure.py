"""Reporter shutdown closure using real pane leases and guarded CLI children."""

import asyncio
import json
from pathlib import Path

import pytest

from tests.agents.slo_agent.herdr.test_reporter import publication, reporter


@pytest.mark.parametrize("case", ["corrupt", "overflow", "unsafe_mode"])
async def test_counter_activation_refuses_without_send(fake_herdr, tmp_path: Path, case: str) -> None:
    """Invalid persisted counters disable activation without reset or executable entry."""
    owner = reporter(root=tmp_path)
    owner._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    owner._transport._config = owner._config
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._sequence_store.reserve(source="custom:slo")
    owner._sequence_store.close()
    (path,) = (tmp_path / "sequence-v1").glob("*.json")
    assert path.resolve().is_relative_to(tmp_path.resolve()) and not path.is_symlink()
    text = json.dumps(
        dict(
            schema_version=1, lifecycle_sequence=True if case == "corrupt" else 2**63 - 1, display_sequence=0
        )
    )
    path.write_text(text)
    if case == "unsafe_mode":
        path.chmod(0o644)
    owner.publish(publication=publication())
    await owner.start()
    await owner.start()
    assert owner._disabled and owner._worker is None and owner._refresh_task is None
    assert fake_herdr.capture.read_text() == ""
    assert path.read_text() == text
    assert (await owner.close()).replacement == "uncertain"
    assert (await owner.close_transport()).resources == "drained"
    assert not owner.retains_external_resources


@pytest.mark.parametrize("case", ["release_timeout", "first_clear_failure", "stale_between_patches"])
async def test_shutdown_and_patch_cutoffs(fake_herdr, tmp_path: Path, case: str) -> None:
    """Actual command entry stops on timeout, first clear failure or supersession."""
    owner = reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    facts = publication()
    owner.publish(publication=facts)
    await owner._send_report_operation(operation="claim", publication=facts, revision=1)
    before = len(fake_herdr.capture.read_text().splitlines())
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    script = fake_herdr.executable.read_text()
    target = "release-agent" if case == "release_timeout" else "report-metadata"
    suffix = f"\nif sys.argv[2] == {target!r}:\n"
    if case == "first_clear_failure":
        suffix += " sys.exit(1)\n"
    else:
        suffix += f" import select\n while not Path({str(fake_herdr.barrier)!r}).read_text(): select.select([], [], [], 0.001)\n"
    fake_herdr.executable.write_text(script + suffix)
    task = asyncio.create_task(
        coro=(
            owner._report_metadata(publication=facts, revision=1)
            if case == "stale_between_patches"
            else owner.close()
        )
    )
    try:
        if case == "stale_between_patches":
            async with asyncio.timeout(delay=0.8):
                while len(fake_herdr.capture.read_text().splitlines()) == before:
                    await asyncio.sleep(delay=0)
            owner.publish(publication=publication(generation=1))
            fake_herdr.guard.require_registered(path=fake_herdr.executable)
            fake_herdr.barrier.write_text("release")
        await task
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()][before:]
        assert [command[1] for command in commands] == (
            ["release-agent", "report-metadata"] if case == "first_clear_failure" else [target]
        )
        assert owner._display_ack_revision is None
        assert owner._shutdown_released is (case == "first_clear_failure")
        assert owner._transport.resources_drained
    finally:
        fake_herdr.guard.require_registered(path=fake_herdr.executable)
        fake_herdr.executable.write_text(script)
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await owner.close()
        await owner.close_transport()
    assert not owner.retains_external_resources
