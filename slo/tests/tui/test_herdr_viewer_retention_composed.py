"""Mounted enabled viewer ownership across replacement and retained cleanup faults."""

import asyncio
import gc
import weakref
from collections.abc import Awaitable, Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceStore, HerdrSequenceUnavailableError
from src.agents.slo_agent.herdr.service import HerdrCliTransport, HerdrTaskJoin
from src.agents.slo_agent.orchestrator.context_dao import OrchestratorContextDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from tests.state_isolation import FakeHerdrFixture
from tests.tui.test_herdr_activation_composed import commands, eventually, native_factory


async def mount_owner(*, root: Path) -> SloAgentSession:
    """Create eligible config-backed history with a real standard workflow context."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=root, model_name="gpt-5.4"))
    await session.rename_session(session_name=f"retained viewer {session.session_id}")
    assert session.history_root is not None
    context = session.history_root / session.session_id / "orchestrator_context.json"
    assert context.resolve().is_relative_to(root.resolve())
    context.write_text(
        OrchestratorContextDAO.build(
            system_prompt="private", user_prompt="private", model=None
        ).model_dump_json(),
        encoding="utf-8",
    )
    return session


async def test_registered_viewer_uses_enabled_transport(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, native_factory: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Establish actual mounted eligibility and one shared transport before fault tests."""
    monkeypatch.setenv(name="SLO_HOME", value=str(tmp_path))
    monkeypatch.setattr("src.agents.slo_agent.history.filesystem_store._CFG_SLO_HOME", tmp_path)
    session = await mount_owner(root=tmp_path)
    app = SloTUI(session=session)
    async with app.run_test():
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        await eventually(predicate=lambda: reporter._display_ack_revision is not None)
        assert session._herdr_visualizer is not None
        assert session._herdr_visualizer._transport is reporter._transport
        assert reporter._lease_held and commands(fake_herdr)


@pytest.mark.parametrize("persistent", [False, True])
async def test_new_registry_fault_retains_real_viewer(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: object,
    monkeypatch: pytest.MonkeyPatch,
    persistent: bool,
) -> None:
    """A registered split child survives failed cleanup, not successor admission."""
    if persistent:
        with pytest.raises(asyncio.CancelledError):
            await exercise_retained_viewer(
                root=tmp_path, fake=fake_herdr, monkeypatch=monkeypatch, persistent=True
            )
        return
    await exercise_retained_viewer(root=tmp_path, fake=fake_herdr, monkeypatch=monkeypatch, persistent=False)


async def exercise_retained_viewer(
    *,
    root: Path,
    fake: FakeHerdrFixture,
    monkeypatch: pytest.MonkeyPatch,
    persistent: bool,
    before_shutdown: Callable[[SloTUI], Awaitable[None]] | None = None,
    registry_fault: bool = True,
    multiple_workers: bool = False,
    cancel_replacement: bool = False,
) -> None:
    """Observe retention before fixture-only release of the child and pending sentinel."""
    tmp_path, fake_herdr = root, fake
    monkeypatch.setenv(name="SLO_HOME", value=str(tmp_path))
    monkeypatch.setenv(name="SLO_AUTO_VISUALIZE", value="1")
    monkeypatch.setattr("src.agents.slo_agent.history.filesystem_store._CFG_SLO_HOME", tmp_path)
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as stream:
        stream.write('if sys.argv[2] == "split":\n import time\n while True: time.sleep(0.05)\n')
    old = await mount_owner(root=tmp_path)
    other = await mount_owner(root=tmp_path) if multiple_workers else None
    app = SloTUI(session=old)
    entered, release = asyncio.Event(), asyncio.Event()
    finalizers_entered: set[str] = set()
    finalizers_done: set[str] = set()
    finalizers_release = asyncio.Event()
    original_worker = SloTUI._run_visualizer_launch

    async def worker(app: SloTUI, *, parent_session_id: str, session: SloAgentSession) -> None:
        """Run the real gateway before exercising a gate-dependent worker finalizer."""
        try:
            await original_worker(app, parent_session_id=parent_session_id, session=session)
        finally:
            async with app._prompt_submission_lock:
                finalizers_entered.add(parent_session_id)
            await finalizers_release.wait()
            async with app._prompt_submission_lock:
                finalizers_done.add(parent_session_id)

    if cancel_replacement:
        monkeypatch.setattr(target=SloTUI, name="_run_visualizer_launch", value=worker)
    attempts: list[asyncio.subprocess.Process] = []
    original_reap = HerdrCliTransport._terminate_and_reap

    async def reap(transport: HerdrCliTransport, *, process: asyncio.subprocess.Process) -> None:
        """Retain only the registered live split; allow all ordinary activation cleanup."""
        if process.returncode is not None:
            await original_reap(self=transport, process=process)
            return
        fake_herdr.guard.require_registered(path=transport._config.binary_path)
        attempts.append(process)
        if len(attempts) <= 2:
            raise OSError("synthetic reap fault")
        entered.set()
        await release.wait()
        if persistent:
            raise OSError("synthetic final reap fault")
        await original_reap(self=transport, process=process)

    async def rescue() -> None:
        """Bound test failure cleanup without altering successful barrier evidence."""
        await asyncio.sleep(20)
        release.set()
        finalizers_release.set()
        monkeypatch.setattr(target=HerdrCliTransport, name="_terminate_and_reap", value=original_reap)

    rescue_task = asyncio.create_task(coro=rescue())
    async with app.run_test():
        reporter = old._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        await eventually(predicate=lambda: reporter._display_ack_revision is not None)
        monkeypatch.setattr(target=HerdrCliTransport, name="_terminate_and_reap", value=reap)
        app._schedule_visualizer_launch(parent_session_id=old.session_id)
        viewer = app._visualizer_launch_tasks[old.session_id]
        await eventually(predicate=lambda: any(row[:2] == ["pane", "split"] for row in commands(fake_herdr)))
        assert old._herdr_visualizer is not None
        assert old._herdr_visualizer._transport is reporter._transport
        queued = None
        if multiple_workers:
            assert other is not None
            app._schedule_visualizer_launch(parent_session_id=other.session_id)
            queued = app._visualizer_launch_tasks[other.session_id]
            launcher = old._herdr_visualizer
            await eventually(predicate=lambda: other.session_id in launcher._attempt_by_parent)
            assert launcher._attempt_by_parent[other.session_id].admitted_operations == frozenset()
            assert not queued.done() and not viewer.done()
            assert reporter._transport._active is not None
            assert sum(row[:2] == ["pane", "split"] for row in commands(fake_herdr)) == 1
        original_join = HerdrTaskJoin.wait
        joins: list[asyncio.Task[object]] = []

        async def join(*, task: asyncio.Task[object]) -> bool:
            """Fail only the app registry join, after verifying synchronous revocation."""
            if task is queued:
                joins.append(task)
            if task is viewer and registry_fault:
                assert old._herdr_closing and not reporter.allows_viewer_admission()
                joins.append(task)
                raise RuntimeError("synthetic registry join fault")
            return await original_join(task=task)

        shutdown = None
        contender = HerdrSequenceStore(
            state_root=reporter._config.state_root,
            socket_namespace=reporter._config.socket_path or "default",
            pane_id=reporter._config.pane_id,
        )
        try:
            with patch.object(HerdrTaskJoin, "wait", side_effect=join):
                if cancel_replacement:
                    caller = asyncio.create_task(coro=app._dispatch_slash_command(line="/new"))
                    await eventually(predicate=lambda: len(finalizers_entered) == 2)
                    commit = app._session_replacement_task
                    assert commit is not None and not commit.done()
                    for _ in range(3):
                        caller.cancel()
                        await asyncio.sleep(0)
                        assert not caller.done() and not commit.done()
                        assert app._session is old and old._herdr_closing
                        assert old._herdr_close_task is None
                    finalizers_release.set()
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(fut=asyncio.shield(caller), timeout=10)
                    assert finalizers_done == finalizers_entered
                    assert commit.done() and not commit.cancelled()
                else:
                    await app._dispatch_slash_command(line="/new")
            assert joins == (([viewer] if registry_fault else []) + ([queued] if queued is not None else []))
            if queued is not None:
                assert queued.done() and viewer.done()
                assert not launcher._pending_by_parent
                assert other is not None
                assert launcher._attempt_by_parent[other.session_id].admitted_operations == frozenset()
            assert app._retired_herdr_session is old
            assert old._herdr_close_task is not None
            assert old._herdr_close_task.result().resources == "retained"
            assert reporter._close_task is not None and reporter._close_task.done()
            assert reporter._transport_close_task is not None and reporter._transport_close_task.done()
            assert app._session._herdr_suppressed and app._session._herdr_start_task is None
            assert app._session_replacement_task is None
            assert app._lease_store is not None
            assert await app._lease_store.read(session_id=old.session_id) is None
            process = reporter._transport._active
            assert process is not None and process.returncode is None
            assert attempts == [process, process]
            reference = weakref.ref(old)
            del old
            gc.collect()
            assert reference() is app._retired_herdr_session
            wire = commands(fake_herdr)
            await app._dispatch_slash_command(line="/new")
            assert app._retired_herdr_session is reference()
            assert app._session._herdr_suppressed and app._session._herdr_start_task is None
            assert commands(fake_herdr) == wire
            with pytest.raises(HerdrSequenceUnavailableError):
                contender.acquire()
            if before_shutdown is not None:
                await before_shutdown(app)
            shutdown = asyncio.create_task(coro=app.on_unmount())
            await asyncio.wait_for(fut=entered.wait(), timeout=10)
            selected = app._selected_herdr_drain_task
            assert selected is not None
            await asyncio.wait_for(fut=asyncio.shield(selected), timeout=5)
            assert app._session._herdr_close_task is not None
            assert app._session._herdr_close_task.done()
            assert app._retired_herdr_drain_task is not None
            assert not app._retired_herdr_drain_task.done()
            for _ in range(3):
                shutdown.cancel()
                await asyncio.sleep(0)
                assert not shutdown.done()
            release.set()
            retired = app._retired_herdr_session
            assert retired is not None and retired._herdr_retired_drain_task is not None
            final = await asyncio.wait_for(fut=asyncio.shield(retired._herdr_retired_drain_task), timeout=5)
            assert final.replacement == "uncertain"
            assert final.resources == ("retained" if persistent else "drained")
            assert await retired.drain_retained_external_resources() is final
            assert attempts == [process, process, process]
            assert commands(fake_herdr) == wire
            assert sum(row[:2] == ["pane", "split"] for row in wire) == 1
            assert not any(row[:2] in [["pane", "rename"], ["pane", "run"]] for row in wire)
            if persistent:
                for _ in range(3):
                    shutdown.cancel()
                    await asyncio.sleep(0)
                    assert not shutdown.done()
                gc.collect()
                assert app._retired_herdr_session is reference()
                assert process.returncode is None and reporter._lease_held
                with pytest.raises(HerdrSequenceUnavailableError):
                    contender.acquire()
            else:
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(fut=asyncio.shield(shutdown), timeout=5)
                assert app._retired_herdr_session is None
                assert reporter._transport.resources_drained and not reporter._lease_held
                contender.acquire()
        finally:
            release.set()
            monkeypatch.setattr(target=HerdrCliTransport, name="_terminate_and_reap", value=original_reap)
            if not reporter._transport.resources_drained:
                await reporter._transport._drain_quarantined_resources()
            await reporter._release_lease()
            retained = app._retired_herdr_session
            if retained is not None and retained._herdr_finish_cleanup_task is not None:
                retained._herdr_finish_cleanup_task.cancel()
            if shutdown is not None:
                await asyncio.wait_for(fut=asyncio.gather(shutdown, return_exceptions=True), timeout=5)
            contender.close()
        assert viewer.done()
    rescue_task.cancel()
    await asyncio.gather(rescue_task, return_exceptions=True)
