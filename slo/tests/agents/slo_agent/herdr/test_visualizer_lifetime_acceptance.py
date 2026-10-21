"""Real CLI lifetime boundaries for the one-shot viewer owner."""

import asyncio
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.dao import (
    HerdrVisualizerRequestDAO,
    HerdrViewerOperation,
    HerdrVisualizerAttemptDAO,
)
from src.agents.slo_agent.history.atomic_io import AtomicFileWriter
from tests.agents.slo_agent.herdr.test_viewer_authority_closure import (
    active_reporter,
    AUTHORITY_CHANGES,
    change_authority,
)
from tests.agents.slo_agent.herdr.test_visualizer_lifecycle import PARENT
from tests.state_isolation import FakeHerdrFixture


def block_operation(*, fixture: FakeHerdrFixture, operation: HerdrViewerOperation) -> None:
    """Append a response barrier only to the registered temp-owned executable."""
    fixture.guard.require_registered(path=fixture.executable)
    with fixture.executable.open(mode="a", encoding="utf-8") as stream:
        stream.write(
            f"if sys.argv[2] == {operation!r}:\n import select\n"
            f" barrier = Path({str(fixture.barrier)!r})\n"
            " while not barrier.read_text(): select.select([], [], [], 0.001)\n"
            'if sys.argv[2] == \'split\': print(\'{"result":{"pane":{"pane_id":"pane-2"}}}\')\n'
        )


@pytest.mark.parametrize(argnames="operation", argvalues=["split", "rename", "run"])
async def test_public_timeout_retains_effect(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, operation: HerdrViewerOperation
) -> None:
    """A real command deadline reaps the CLI without granting a second attempt."""
    block_operation(fixture=fake_herdr, operation=operation)
    owner = active_reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    viewer = owner.build_visualizer()
    request = HerdrVisualizerRequestDAO(parent_session_id=PARENT, history_root=tmp_path)
    try:
        outcome = await viewer.invoke(request=request)
        assert outcome.status == ("submitted" if operation == "rename" else "failed")
        expected = ["split"] if operation == "split" else ["split", "rename", "run"]
        assert [json.loads(line)[1] for line in fake_herdr.capture.read_text().splitlines()] == expected
        assert owner._transport.resources_drained
        retained = await viewer.invoke(request=request)
        assert retained.status == ("failed" if operation == "split" else "reused")
        assert retained.pane_id == (None if operation == "split" else "pane-2")
        assert len(fake_herdr.capture.read_text().splitlines()) == len(expected)
    finally:
        await viewer.close()
        await owner._transport.close()


@pytest.mark.parametrize(argnames="operation", argvalues=["split", "rename", "run"])
@pytest.mark.parametrize(argnames="field,value", argvalues=AUTHORITY_CHANGES)
async def test_admitted_effect_survives_but_new_request_is_refused(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    operation: HerdrViewerOperation,
    field: str,
    value: bool,
) -> None:
    """Live revocation cannot undo committed input, but forbids each later operation."""
    block_operation(fixture=fake_herdr, operation=operation)
    owner = active_reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    viewer = owner.build_visualizer()
    request = HerdrVisualizerRequestDAO(parent_session_id=PARENT, history_root=tmp_path)
    launch = asyncio.create_task(coro=viewer.invoke(request=request))
    expected = ["split", "rename", "run"][: ["split", "rename", "run"].index(operation) + 1]
    try:
        async with asyncio.timeout(delay=0.5):
            while len(fake_herdr.capture.read_text().splitlines()) < len(expected):
                await asyncio.sleep(delay=0)
        owned = viewer._pending_by_parent[PARENT]
        change_authority(owner=owner, field=field, value=value)
        assert (await viewer.invoke(request=request)).status == "failed"
        assert viewer._pending_by_parent[PARENT] is owned and not owned.done()
        fake_herdr.guard.require_registered(path=fake_herdr.executable)
        fake_herdr.barrier.write_text("release")
        outcome = await launch
        assert outcome.status == ("submitted" if operation == "run" and field != "_closed" else "failed")
        attempt = viewer._attempt_by_parent[PARENT]
        assert attempt.state == "pane_known" and attempt.pane_id == "pane-2"
        assert attempt.admitted_operations == frozenset(expected)
        assert [json.loads(line)[1] for line in fake_herdr.capture.read_text().splitlines()] == expected
        assert owner._transport.resources_drained and not viewer._pending_by_parent
    finally:
        await viewer.close()
        await asyncio.gather(launch, return_exceptions=True)
        await owner._transport.close()


@pytest.mark.parametrize(argnames="operation", argvalues=["split", "rename", "run"])
@pytest.mark.parametrize(argnames="failure", argvalues=["write", "fsync", "overflow", "tmp_write"])
async def test_real_sequence_failure_revokes_queued_viewer(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    monkeypatch: pytest.MonkeyPatch,
    operation: HerdrViewerOperation,
    failure: str,
) -> None:
    """Actual reservation refusal revokes queued pane work without sealing transport."""
    owner = active_reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    owner._sequence_store.acquire()
    store = owner._sequence_store
    assert store._path.resolve().is_relative_to(tmp_path.resolve())
    if failure == "overflow":
        assert store._state is not None
        state = store._state.model_copy(update={"lifecycle_sequence": 2**63 - 1})
        AtomicFileWriter.write_text(path=store._path, text=state.model_dump_json())
        store._state = store._load()
    viewer = owner.build_visualizer()
    viewer._attempt_by_parent[PARENT] = HerdrVisualizerAttemptDAO(state="pane_known", pane_id="pane-2")
    lock = owner._transport._command_lock
    await lock.acquire()
    queued = asyncio.create_task(
        coro=viewer._send_viewer_operation(parent_session_id=PARENT, operation=operation)
    )
    real_fsync = os.fsync
    real_temporary_file = tempfile.NamedTemporaryFile
    write_attempts: list[Path] = []
    before = store._path.read_bytes() if store._path.exists() else None

    @contextmanager
    def failing_temporary_file(
        *, dir: Path, delete: bool, mode: str, encoding: str
    ) -> Iterator["tempfile._TemporaryFileWrapper[str]"]:
        """Use the real sibling file, failing precisely its write before flush/fsync."""
        assert dir.resolve().is_relative_to(tmp_path.resolve())
        with real_temporary_file(dir=dir, delete=delete, mode=mode, encoding=encoding) as temporary:
            target = Path(temporary.name)
            assert target.resolve().is_relative_to(tmp_path.resolve()) and not target.is_symlink()

            def fail_write(text: str) -> int:
                """Prove the writer reached tmp.write rather than a later sync boundary."""
                write_attempts.append(target)
                raise OSError("synthetic temporary write failure")

            monkeypatch.setattr(temporary, "write", fail_write)
            yield temporary

    def fail_sync(fd: int) -> None:
        """Fail the real writer before commit or at its directory durability boundary."""
        if failure == "write" or stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("synthetic sequence durability failure")
        real_fsync(fd)

    try:
        async with asyncio.timeout(delay=0.5):
            while not lock._waiters:
                await asyncio.sleep(delay=0)
        with monkeypatch.context() as patch:
            if failure == "tmp_write":
                patch.setattr(tempfile, "NamedTemporaryFile", failing_temporary_file)
            elif failure != "overflow":
                patch.setattr(os, "fsync", fail_sync)
            assert await owner._reserve_ticket(operation="claim") is None
        if failure == "tmp_write":
            assert len(write_attempts) == 1 and not write_attempts[0].exists()
            assert (store._path.read_bytes() if store._path.exists() else None) == before
        assert not owner.allows_viewer_admission() and not owner._transport.closed
        lock.release()
        result = await queued
        assert result.outcome.status == "suppressed" and not result.admitted
        assert not viewer._attempt_by_parent[PARENT].admitted_operations
        assert fake_herdr.capture.read_text() == ""
    finally:
        if lock.locked():
            lock.release()
        await asyncio.gather(queued, return_exceptions=True)
        await viewer.close()
        await owner._transport.close()
        store.close()


@pytest.mark.parametrize(argnames="operation", argvalues=["split", "rename", "run"])
async def test_repeated_close_cancellation_joins_all_parents(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    monkeypatch: pytest.MonkeyPatch,
    operation: HerdrViewerOperation,
) -> None:
    """Close retains real CLI cleanup and a queued parent despite repeated cancellation."""
    block_operation(fixture=fake_herdr, operation=operation)
    owner = active_reporter(root=tmp_path)
    transport = owner._transport
    transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    viewer = owner.build_visualizer()
    draining, release = asyncio.Event(), asyncio.Event()
    original = transport._terminate_and_reap

    async def delayed_reap(*, process: asyncio.subprocess.Process) -> None:
        """Delay cleanup at an explicit barrier, then use the real owned-process reap."""
        if process.returncode is None:
            draining.set()
            await release.wait()
        await original(process=process)

    monkeypatch.setattr(transport, "_terminate_and_reap", delayed_reap)
    first = asyncio.create_task(
        coro=viewer.invoke(request=HerdrVisualizerRequestDAO(parent_session_id=PARENT, history_root=tmp_path))
    )
    expected = ["split", "rename", "run"][: ["split", "rename", "run"].index(operation) + 1]
    second_parent = "b81d92fa-7a2e-4ccd-9975-445832a91d5e"
    second = None
    closer = None
    try:
        async with asyncio.timeout(delay=0.5):
            while len(fake_herdr.capture.read_text().splitlines()) < len(expected):
                await asyncio.sleep(delay=0)
            second = asyncio.create_task(
                coro=viewer.invoke(
                    request=HerdrVisualizerRequestDAO(parent_session_id=second_parent, history_root=tmp_path)
                )
            )
            while not transport._command_lock._waiters:
                await asyncio.sleep(delay=0)
        closer = asyncio.create_task(coro=viewer.close())
        await asyncio.wait_for(draining.wait(), timeout=0.5)
        close_owner = viewer._close_task
        for _ in range(3):
            closer.cancel()
            await asyncio.sleep(delay=0)
            assert not closer.done() and viewer._close_task is close_owner
            assert PARENT in viewer._pending_by_parent
        assert transport._command_lock.locked() and not transport.resources_drained
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await closer
        await viewer.close()
        assert not viewer._pending_by_parent and transport.resources_drained and not transport.closed
        assert viewer._attempt_by_parent[PARENT].pane_id == (None if operation == "split" else "pane-2")
        assert viewer._attempt_by_parent[second_parent].state == "uncertain"
        assert [json.loads(line)[1] for line in fake_herdr.capture.read_text().splitlines()] == expected
    finally:
        release.set()
        await viewer.close()
        await asyncio.gather(
            *(task for task in (first, second, closer) if task is not None), return_exceptions=True
        )
        await transport.close()


@pytest.mark.parametrize(argnames="operation", argvalues=["split", "rename", "run"])
async def test_ordinary_exception_retains_manual_recovery(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    monkeypatch: pytest.MonkeyPatch,
    operation: HerdrViewerOperation,
) -> None:
    """A defect escaping transport stops the launch without discarding prior effects."""
    from src.agents.slo_agent.herdr.dao import (
        HerdrCliCommandDAO,
        HerdrCommandAdmission,
        HerdrCommandResultDAO,
    )

    block_operation(fixture=fake_herdr, operation=operation)
    owner = active_reporter(root=tmp_path)
    owner._transport._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    viewer = owner.build_visualizer()
    original = owner._transport.invoke

    async def fail_operation(
        *, command: HerdrCliCommandDAO, admission: HerdrCommandAdmission
    ) -> HerdrCommandResultDAO:
        """Inject only the ordinary exception boundary; earlier operations use real CLI."""
        if command.argv[1] == operation:
            raise RuntimeError("private-viewer-sentinel")
        return await original(command=command, admission=admission)

    monkeypatch.setattr(owner._transport, "invoke", fail_operation)
    request = HerdrVisualizerRequestDAO(parent_session_id=PARENT, history_root=tmp_path)
    try:
        result = await viewer.invoke(request=request)
        assert result.status == "failed" and "private-viewer-sentinel" not in repr(result)
        expected = ["split", "rename", "run"][: ["split", "rename", "run"].index(operation)]
        assert [json.loads(line)[1] for line in fake_herdr.capture.read_text().splitlines()] == expected
        retained = await viewer.invoke(request=request)
        assert retained.status == ("failed" if operation == "split" else "reused")
        assert retained.pane_id == (None if operation == "split" else "pane-2")
        assert len(fake_herdr.capture.read_text().splitlines()) == len(expected)
    finally:
        await viewer.close()
        await owner._transport.close()
