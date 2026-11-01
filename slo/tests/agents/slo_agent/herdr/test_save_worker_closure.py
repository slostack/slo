"""Save/worker lifetime compositions; publications are manual until T5 wiring."""

import asyncio
import json
import threading
from pathlib import Path
from collections.abc import Callable

import pytest

from src.agents.slo_agent.herdr.dao import (
    HerdrDisplayTokenDAO,
    HerdrPublicationDAO,
    HerdrRestoreConfigDAO,
    HerdrRestoreReferenceDAO,
    HerdrRestoreUnavailableError,
)
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.state_isolation import FakeHerdrFixture
from tests.agents.slo_agent.herdr.test_reporter import SESSION, plain_slo, publication, reporter


class BarrierStore:
    """Hold the first off-loop save; keep immutable synthetic records in the test root."""

    def __init__(self, *, root: Path, fail: bool = False) -> None:
        """Create barriers before the worker starts; release belongs to the test."""
        self.root = root.resolve(strict=True)
        self.fail = fail
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.calls: list[HerdrRestoreConfigDAO] = []
        self.paths: list[Path] = []

    def save(self, *, config: HerdrRestoreConfigDAO) -> HerdrRestoreReferenceDAO:
        """Write only after the barrier; returning proves the finite thread finished."""
        self.calls.append(config)
        index = len(self.calls)
        if index == 1:
            self.entered.set()
            assert self.release.wait(timeout=10), "test did not release save"
        try:
            if self.fail:
                raise HerdrRestoreUnavailableError()
            path = self.root / f"record-{index}.json"
            assert not path.is_symlink() and path.resolve().parent == self.root
            with path.open(mode="x", encoding="utf-8") as stream:
                stream.write(config.model_dump_json())
            self.paths.append(path)
            return HerdrRestoreReferenceDAO(restore_reference=f"r1-{index:032x}")
        finally:
            self.finished.set()


async def wait_until(*, predicate: Callable[[], bool]) -> None:
    """Yield until a real owner reaches the asserted barrier, with bounded failure."""
    async with asyncio.timeout(delay=5):
        while not predicate():
            await asyncio.sleep(delay=0)


@pytest.mark.parametrize("change", ["rename", "capture"])
async def test_save_worker_continues_latest(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, plain_slo: Path, change: str
) -> None:
    """Real worker sends only newest display and the exact surviving saved policy."""
    owner = reporter(root=tmp_path)
    owner._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    owner._transport._config = owner._config
    store = BarrierStore(root=tmp_path)
    owner._restore_store = store
    initial = publication(eligible=True)
    owner.publish(publication=initial)
    await owner.start()
    try:
        await wait_until(predicate=store.entered.is_set)
        saved_task = owner._save_task
        assert saved_task is not None and not saved_task.done()
        assert len(store.calls) == 1
        if change == "rename":
            # No model is constructed or invoked by the real metadata-only rename.
            history = tmp_path / "history"
            assert history.resolve().parent == tmp_path.resolve() and not history.is_symlink()
            session = SloAgentSession.build(
                config=SessionConfigDAO(workdir=tmp_path, history_root=history, session_id=SESSION)
            )
            metadata = await session.rename_session(session_name="Private renamed session")
            assert metadata.session_name == session.session_name == "Private renamed session"
            assert metadata.session_id == SESSION
            capture = initial.restore_capture
        else:
            assert initial.restore_capture is not None
            capture = initial.restore_capture.model_copy(
                update={
                    "config": initial.restore_capture.config.model_copy(update={"reasoning_level": "high"})
                }
            )
        latest = initial.model_copy(
            update={
                "configuration_generation": int(change == "capture"),
                "restore_capture": capture,
                "snapshot": initial.snapshot.model_copy(
                    update={"tokens": (HerdrDisplayTokenDAO(key="turn", value="9"),)}
                ),
            }
        )
        owner.publish(publication=latest)
        assert owner._save_task is saved_task and not store.paths
        assert [json.loads(line)[1] for line in fake_herdr.capture.read_text().splitlines()] == [
            "release-agent"
        ]
        store.release.set()
        await wait_until(predicate=lambda: owner._display_ack_revision == 2)
        assert saved_task.done() and not saved_task._log_traceback
        assert owner._save_task is None and owner._pending is None and not owner._wake.is_set()
        assert owner._saved is not None and owner._restore_ack == owner._saved
        assert owner._saved.capture == capture
        assert owner._saved.configuration_generation == latest.configuration_generation
        expected_count = 2 if change == "capture" else 1
        assert len(store.calls) == len(store.paths) == expected_count
        assert store.paths[0].read_text() == initial.restore_capture.config.model_dump_json()
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        installs = [command for command in commands if "--herdr-restore" in command]
        assert len(installs) == 1
        assert installs[0][-1] == f"r1-{expected_count:032x}"
        assert sum("turn=9" in command for command in commands) == 1
        assert "Private renamed session" not in fake_herdr.capture.read_text()
        assert owner._binding is not None and owner._binding.capture == capture
    finally:
        store.release.set()
        await owner.close()
        await owner.close_transport()
    assert owner._worker.done() and owner._refresh_task.done()
    assert not owner.retains_external_resources


@pytest.mark.parametrize("cancel", [False, True], ids=["ordinary", "repeated_cancel"])
async def test_close_joins_worker_admitted_child(
    fake_herdr: FakeHerdrFixture, tmp_path: Path, cancel: bool
) -> None:
    """A pending real claim is reaped before one shutdown release; no stale display follows."""
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as script:
        script.write(
            "\nif sys.argv[2] == 'report-agent':\n"
            " import select\n"
            f" while not Path({str(fake_herdr.barrier)!r}).read_text(): select.select([], [], [], 0.001)\n"
        )
    owner = reporter(root=tmp_path)
    owner._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    owner._transport._config = owner._config
    owner.publish(publication=publication())
    await owner.start()
    try:
        await wait_until(predicate=lambda: "report-agent" in fake_herdr.capture.read_text())
        process = owner._transport._active
        worker = owner._worker
        assert process is not None and process.returncode is None and worker is not None
        closer = asyncio.create_task(coro=owner.close())
        await wait_until(predicate=lambda: owner._closing)
        if cancel:
            for _ in range(2):
                closer.cancel()
                await asyncio.sleep(delay=0)
            with pytest.raises(asyncio.CancelledError):
                await closer
        else:
            await closer
        assert worker.done() and not worker._log_traceback
        assert process.returncode is not None and owner._transport.resources_drained
        assert owner._shutdown_released and owner._binding is None
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        assert [command[1] for command in commands] == [
            "release-agent",
            "report-agent",
            "release-agent",
            "report-metadata",
            "report-metadata",
        ]
        before = fake_herdr.capture.read_text()
        owner.publish(publication=publication(generation=1))
        await owner.close()
        final = await owner.close_transport()
        assert final.resources == "drained" and final.replacement == "safe"
        assert fake_herdr.capture.read_text() == before
    finally:
        await owner.close()
        await owner.close_transport()
    assert not owner.retains_external_resources


@pytest.mark.parametrize("cancel", [False, True], ids=["ordinary", "repeated_cancel"])
@pytest.mark.parametrize("failure", ["none", "save", "worker"])
async def test_close_joins_pending_save_and_worker(
    fake_herdr: FakeHerdrFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
    failure: str,
) -> None:
    """Close joins the real worker and thread before returning or propagating cancellation."""
    owner = reporter(root=tmp_path)
    owner._config = owner._config.model_copy(update={"binary_path": fake_herdr.executable})
    owner._transport._config = owner._config
    store = BarrierStore(root=tmp_path, fail=failure == "save")
    owner._restore_store = store
    consume = owner._consume_publication

    async def consume_with_teardown_error(*, publication: HerdrPublicationDAO) -> None:
        """Inject a worker defect only after its real save join has drained."""
        try:
            await consume(publication=publication)
        except asyncio.CancelledError:
            raise RuntimeError("private-worker-sentinel") from None

    if failure == "worker":
        monkeypatch.setattr(target=owner, name="_consume_publication", value=consume_with_teardown_error)
    owner.publish(publication=publication(eligible=True))
    await owner.start()
    closer = None
    try:
        await wait_until(predicate=store.entered.is_set)
        worker, refresh, save = owner._worker, owner._refresh_task, owner._save_task
        assert worker is not None and refresh is not None and save is not None
        closer = asyncio.create_task(coro=owner.close())
        await wait_until(predicate=lambda: worker.cancelling() > 0)
        retained_close = owner._close_task
        assert owner._closing and owner._pending is None and owner._lease_held
        assert not closer.done() and not worker.done() and not save.done()
        if cancel:
            for _ in range(2):
                closer.cancel()
                await asyncio.sleep(delay=0)
            assert not closer.done() and not save.cancelled()
        owner.publish(publication=publication(generation=1, eligible=True))
        assert owner._pending is None
        store.release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await closer
        else:
            await closer
        assert store.finished.is_set()
        assert all(task.done() and not task._log_traceback for task in (worker, refresh, save))
        assert owner._save_task is None and owner._saved is None and owner._binding is None
        assert owner._lease_held and owner._transport.resources_drained
        assert len(store.calls) == 1
        assert len(store.paths) == (0 if failure == "save" else 1)
        await owner.close()
        assert owner._close_task is retained_close
        final = await owner.close_transport()
        assert final.resources == "drained"
        assert final.replacement == ("uncertain" if failure == "worker" else "safe")
        assert [json.loads(line)[1] for line in fake_herdr.capture.read_text().splitlines()] == [
            "release-agent"
        ]
    finally:
        store.release.set()
        if closer is not None:
            await asyncio.gather(closer, return_exceptions=True)
        await owner.close()
        await owner.close_transport()
    assert not owner.retains_external_resources
