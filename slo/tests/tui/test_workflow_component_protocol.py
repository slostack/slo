"""Workflow protocol journeys through the real app and temporary workflow captures."""

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest

from src.tui.app import SloTUI
from src.tui.components.protocols import AdapterProtocol, ComponentProtocol
from src.tui.components.workflow_progress.component import WorkflowProgressComponent
from src.tui.components.workflow_progress.commands import WorkflowProgressCommand, PresentSessionsDAO
from src.tui.components.workflow_progress.events import (
    WorkflowProgressUpdate,
    SessionsUpdatedDAO,
    ObservationFailedDAO,
    ProgressUpdatedDAO,
)
from src.tui.components.workflow_progress.adapters.workflow_progress import WorkflowProgressUpdatesAdapter
from tests.integration.test_workflow_progress_tui import _World, _settle, _open_child, _painted_log_text


async def test_real_capture_reaches_typed_workflow_component(tmp_path: Path) -> None:
    """Real observation paints capture text; awaited list commands finish before returning."""
    world = _World(tmp_path=tmp_path)
    world.start_child(lines=3)
    app = SloTUI(session=world.session)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(app=app, pilot=pilot)
        component = app.query_one(WorkflowProgressComponent)
        sink = app._workflow_progress_updates_adapter
        assert isinstance(sink, WorkflowProgressUpdatesAdapter)
        component_contract: ComponentProtocol[WorkflowProgressCommand] = component
        adapter_contract: AdapterProtocol[WorkflowProgressUpdate] = sink
        service = app._workflow_app_service
        assert service is not None
        snapshot = await service.load_session_snapshot()
        await component_contract.handle(command=PresentSessionsDAO(sink=sink, snapshot=snapshot))
        assert component.is_session_list_visible()
        await adapter_contract.handle(event=SessionsUpdatedDAO(snapshot=snapshot))
        screen = await _open_child(app=app, pilot=pilot)
        assert "child line 002" in _painted_log_text(screen=screen)
        assert (world.capture_dir / "stdout.jsonl").is_file()


async def test_progress_delivery_waits_for_mount(tmp_path: Path) -> None:
    """Opening and immediate progress delivery must apply before handle returns."""
    world = _World(tmp_path=tmp_path)
    world.start_child(lines=3)
    app = SloTUI(session=world.session)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(app=app, pilot=pilot)
        sink = app._workflow_progress_updates_adapter
        service = app._workflow_app_service
        coordinator = app._workflow_progress_coordinator
        assert isinstance(sink, WorkflowProgressUpdatesAdapter)
        assert service is not None and coordinator is not None
        await coordinator.close()
        sessions = await service.load_session_snapshot()
        key = sessions.rows[1].key
        snapshot = await service.load_session_progress(key=key)
        assert sink.open_progress(key=key)
        await sink.handle(event=ProgressUpdatedDAO(snapshot=snapshot))
        assert sink._screen is not None
        assert sink._screen._snapshot == snapshot


class GatedSessionPresenter:
    """Injected presentation boundary with deterministic failure and delivery barriers."""

    def __init__(self) -> None:
        """Create independent delivery barriers for this injected target."""
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.commands: list[PresentSessionsDAO] = []
        self.failure: Exception | None = None

    async def handle(self, *, command: PresentSessionsDAO) -> None:
        """Hold application until released, then record or fail."""
        self.entered.set()
        await self.release.wait()
        if self.failure is not None:
            raise self.failure
        self.commands.append(command)

    def call_after_refresh(self, callback: Callable[..., object], *args: object, **kwargs: object) -> bool:
        """No screen is opened in these delivery barrier tests."""
        return False


async def test_adapter_close_joins_delivery_despite_repeated_cancellation(tmp_path: Path) -> None:
    """A cancelled close cannot return while an admitted target mutation remains unfinished."""
    world = _World(tmp_path=tmp_path)
    app = SloTUI(session=world.session)
    presenter = GatedSessionPresenter()
    sink = WorkflowProgressUpdatesAdapter.register(host=app, presenter=presenter)
    from src.tui.workflows.dao import WorkflowSessionSnapshotDAO

    event = SessionsUpdatedDAO(snapshot=WorkflowSessionSnapshotDAO())
    delivery = asyncio.create_task(sink.handle(event=event))
    await presenter.entered.wait()
    closing = asyncio.create_task(sink.close())
    try:
        await asyncio.sleep(0)
        assert not closing.done()
        closing.cancel()
        await asyncio.sleep(0)
        closing.cancel()
        await asyncio.sleep(0)
        assert not closing.done()
        with pytest.raises(RuntimeError, match="closed"):
            await sink.handle(event=ObservationFailedDAO())
    finally:
        presenter.release.set()
        await delivery
        await asyncio.gather(closing, return_exceptions=True)
    assert closing.cancelled()
    assert len(presenter.commands) == 1
    await sink.close()
    with pytest.raises(RuntimeError, match="closed"):
        await sink.reset()


async def test_component_reset_is_reusable_and_close_keeps_native_pump_alive(tmp_path: Path) -> None:
    """Reset keeps observation binding; close rejects delivery without changing Textual's flag."""
    world = _World(tmp_path=tmp_path)
    world.start_child(lines=2)
    app = SloTUI(session=world.session)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(app=app, pilot=pilot)
        component = app.query_one(WorkflowProgressComponent)
        sink = app._workflow_progress_updates_adapter
        service = app._workflow_app_service
        coordinator = app._workflow_progress_coordinator
        assert sink is not None and service is not None and coordinator is not None
        await coordinator.close()
        snapshot = await service.load_session_snapshot()
        await component.reset()
        await component.reset()
        assert not component.is_session_list_visible()
        await sink.handle(event=SessionsUpdatedDAO(snapshot=snapshot))
        assert component.is_session_list_visible()
        await component.close()
        await component.close()
        assert component._closed is False
        assert (await service.load_session_snapshot()).rows
        with pytest.raises(RuntimeError, match="closed"):
            await component.handle(command=PresentSessionsDAO(sink=sink, snapshot=snapshot))
        with pytest.raises(RuntimeError, match="closed"):
            await component.reset()


async def test_adapter_reset_rejects_queued_old_update_and_propagates_target_failure(tmp_path: Path) -> None:
    """Reset joins admitted work; queued old delivery cannot repopulate reset state."""
    from src.tui.workflows.dao import WorkflowSessionSnapshotDAO

    world = _World(tmp_path=tmp_path)
    app = SloTUI(session=world.session)
    presenter = GatedSessionPresenter()
    sink = WorkflowProgressUpdatesAdapter.register(host=app, presenter=presenter)
    event = SessionsUpdatedDAO(snapshot=WorkflowSessionSnapshotDAO())
    delivery = asyncio.create_task(sink.handle(event=event))
    await presenter.entered.wait()
    queued = asyncio.create_task(sink.handle(event=event))
    await asyncio.sleep(0)
    resetting = asyncio.create_task(sink.reset())
    await asyncio.sleep(0)
    assert not resetting.done()
    presenter.release.set()
    await delivery
    with pytest.raises(RuntimeError, match="retired presentation"):
        await queued
    await resetting
    assert len(presenter.commands) == 1
    failure = ValueError("target failed")
    presenter.failure = failure
    with pytest.raises(ValueError) as caught:
        await sink.handle(event=event)
    assert caught.value is failure
    presenter.failure = None
    await sink.handle(event=event)
    assert len(presenter.commands) == 2
    with pytest.raises(TypeError, match="Unsupported"):
        await sink.handle(event=object())  # type: ignore[arg-type]
    await sink.close()
    await presenter.handle(command=PresentSessionsDAO(sink=sink, snapshot=event.snapshot))
    assert len(presenter.commands) == 3


async def test_component_rejects_foreign_loop_and_unsupported_command(tmp_path: Path) -> None:
    """Neither off-loop nor unsupported input mutates the mounted component."""
    world = _World(tmp_path=tmp_path)
    app = SloTUI(session=world.session)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(app=app, pilot=pilot)
        component = app.query_one(WorkflowProgressComponent)
        with pytest.raises(TypeError, match="Unsupported"):
            await component.handle(command=object())  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="UI loop"):
            await asyncio.to_thread(lambda: asyncio.run(component.reset()))
        sink = app._workflow_progress_updates_adapter
        assert sink is not None
        with pytest.raises(RuntimeError, match="UI loop"):
            await asyncio.to_thread(lambda: asyncio.run(sink.handle(event=ObservationFailedDAO())))


async def test_component_failed_retirement_is_retryable_before_successor_bind(tmp_path: Path) -> None:
    """Failed row cleanup reserves the exact binding; retry succeeds without closing service."""
    from src.tui.widgets.sub_agent_fleet_panel import SubAgentFleetPanel

    class FailingResetPanel(SubAgentFleetPanel):
        """A native panel with one explicit cleanup failure."""

        failure: Exception | None = None

        async def reset(self) -> None:
            """Fail before mutation when armed, otherwise use native cleanup."""
            if self.failure is not None:
                raise self.failure
            await super().reset()

    world = _World(tmp_path=tmp_path)
    app = SloTUI(session=world.session)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(app=app, pilot=pilot)
        panel = FailingResetPanel()
        component = WorkflowProgressComponent(host=app, panel=panel)
        await app.mount(component)
        sink = component.bind_observation()
        failure = ValueError("row cleanup failed")
        panel.failure = failure
        with pytest.raises(ValueError) as caught:
            await component.retire_observation(sink=sink)
        assert caught.value is failure
        with pytest.raises(RuntimeError):
            component.bind_observation()
        panel.failure = None
        await component.retire_observation(sink=sink)
        successor = component.bind_observation()
        assert successor is not sink
        panel.failure = failure
        with pytest.raises(ValueError) as caught:
            await component.close()
        assert caught.value is failure
        panel.failure = None
        await component.close()
        await component.close()
        assert component._bound_sink is None
        assert component._closed is False
        assert app._workflow_app_service is not None
        await app._workflow_app_service.load_session_snapshot()


async def test_reset_suppresses_old_confirmation_and_progress_callbacks(tmp_path: Path) -> None:
    """A same-key successor screen cannot receive old paint or captured abort confirmation."""
    from src.tui.components.workflow_progress.events import ConfirmAbortDAO

    world = _World(tmp_path=tmp_path)
    seam = world.enable_attached_control()
    world.start_child(lines=3)
    app = SloTUI(session=world.session)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(app=app, pilot=pilot)
        screen = await _open_child(app=app, pilot=pilot)
        sink = app._workflow_progress_updates_adapter
        service = app._workflow_app_service
        assert isinstance(sink, WorkflowProgressUpdatesAdapter) and service is not None
        snapshot = await service.load_session_progress(key=screen.key)
        assert snapshot.abort_target is not None
        await sink.handle(event=ConfirmAbortDAO(target=snapshot.abort_target))
        await pilot.pause()
        confirmation = sink._confirmation
        assert confirmation is not None
        callback = confirmation._result_callbacks[-1].callback
        assert callback is not None
        await sink.reset()
        await pilot.pause()
        assert sink.open_progress(key=screen.key)
        successor = sink._screen
        assert successor is not None and successor is not screen
        await sink.handle(event=ProgressUpdatedDAO(snapshot=snapshot))
        sink._deliver_progress(screen=screen, snapshot=snapshot.model_copy(update={"revision": "obsolete"}))
        callback(True)
        await pilot.pause()
        assert successor._snapshot == snapshot
        assert seam.calls == []
        # A queued native intent from the retired screen cannot minimize its successor.
        from src.tui.workflows.session_progress_screen import SessionProgressScreen

        await app.on_session_progress_screen_minimized(SessionProgressScreen.Minimized(screen=screen))
        assert sink._screen is successor


def test_static_workflow_contract_rejects_wrong_inputs_and_wrong_protocol(tmp_path: Path) -> None:
    """Existing mypy infrastructure checks both structural assignments and invalid consumers."""
    import subprocess
    import sys

    contract = (tmp_path / "workflow_contract.py").resolve()
    assert contract.is_relative_to(tmp_path.resolve())
    contract.write_text(
        """from src.tui.components.protocols import ComponentProtocol, AdapterProtocol
from src.tui.components.workflow_progress.commands import WorkflowProgressCommand, PresentSessionsDAO
from src.tui.components.workflow_progress.events import WorkflowProgressUpdate, SessionsUpdatedDAO
from src.tui.components.workflow_progress.component import WorkflowProgressComponent
from src.tui.components.workflow_progress.adapters.workflow_progress import WorkflowProgressUpdatesAdapter
from src.tui.workflows.progress_coordinator import WorkflowProgressSink

async def consumers(c: WorkflowProgressComponent, a: WorkflowProgressUpdatesAdapter, narrow: ComponentProtocol[PresentSessionsDAO]) -> None:
    good_component: ComponentProtocol[WorkflowProgressCommand] = c
    good_adapter: AdapterProtocol[WorkflowProgressUpdate] = a
    selection: WorkflowProgressSink = a
    await c.handle(command=object())
    await a.handle(event=object())
    broad: ComponentProtocol[WorkflowProgressCommand] = narrow
    await c.handle(object())
    lost_ack: ComponentProtocol[WorkflowProgressCommand] = a
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        args=[
            sys.executable,
            "-B",
            "-m",
            "mypy",
            "--cache-dir=/dev/null",
            "--follow-imports=silent",
            str(contract),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    diagnostics = [line for line in result.stdout.splitlines() if ": error:" in line]
    assert result.returncode == 1, result.stdout + result.stderr
    assert len(diagnostics) == 6, result.stdout
    assert all(str(contract) in line for line in diagnostics)
    assert sum("[arg-type]" in line for line in diagnostics) == 3
    assert sum("[assignment]" in line for line in diagnostics) == 2
    assert sum("[misc]" in line for line in diagnostics) == 1


async def test_component_close_joins_cancelled_reset_and_rejects_queued_delivery(tmp_path: Path) -> None:
    """A close waiter and unmount share cleanup, including an already running reset."""
    from src.tui.widgets.sub_agent_fleet_panel import SubAgentFleetPanel
    from src.tui.workflows.dao import WorkflowSessionSnapshotDAO

    class GatedResetPanel(SubAgentFleetPanel):
        """Hold native row cleanup at a deterministic barrier."""

        def __init__(self) -> None:
            """Build a native panel with a cleanup barrier."""
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def reset(self) -> None:
            """Join the barrier before native cleanup."""
            self.entered.set()
            await self.release.wait()
            await super().reset()

    world = _World(tmp_path=tmp_path)
    app = SloTUI(session=world.session)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(app=app, pilot=pilot)
        panel = GatedResetPanel()
        component = WorkflowProgressComponent(host=app, panel=panel)
        await app.mount(component)
        sink = component.bind_observation()
        resetting = asyncio.create_task(component.reset())
        await panel.entered.wait()
        queued = asyncio.create_task(
            component.handle(command=PresentSessionsDAO(sink=sink, snapshot=WorkflowSessionSnapshotDAO()))
        )
        closing = asyncio.create_task(component.close())
        await asyncio.sleep(0)
        closing.cancel()
        await asyncio.sleep(0)
        assert not closing.done()
        with pytest.raises(RuntimeError, match="closed"):
            component.bind_observation()
        panel.release.set()
        await resetting
        with pytest.raises(RuntimeError, match="closed"):
            await queued
        with pytest.raises(asyncio.CancelledError):
            await closing
        await component.on_unmount()
        assert component._bound_sink is None
        assert not component.is_session_list_visible()


async def test_adapter_mount_failure_propagates_and_owned_screen_can_close(tmp_path: Path) -> None:
    """A failed host presentation retains its exact screen for close cleanup."""
    from src.tui.workflows.dao import WorkflowSessionKeyDAO
    from src.tui.workflows.session_progress_screen import SessionProgressScreen

    class ScreenHost(SloTUI):
        """Inject a failed owned view at the existing screen presentation boundary."""

        CSS_PATH = str(Path(__file__).resolve().parents[2] / "src/tui/app.tcss")

        def present_progress(
            self, *, screen: SessionProgressScreen, on_closed: Callable[[None], None]
        ) -> asyncio.Future[None]:
            """Fail presentation before mounting; the adapter must still own cleanup."""
            raise ValueError("mount failed")

    world = _World(tmp_path=tmp_path)
    host = ScreenHost(session=world.session)
    presenter = GatedSessionPresenter()
    sink = WorkflowProgressUpdatesAdapter.register(host=host, presenter=presenter)
    # An actual host failure must propagate and keep the created view owned.
    async with host.run_test(size=(120, 40)) as pilot:
        await _settle(app=host, pilot=pilot)
        key = WorkflowSessionKeyDAO(orchestrator_session_id="owner", session_id="child")
        with pytest.raises(ValueError, match="mount failed"):
            sink.open_progress(key=key)
        assert sink._screen is not None
        await sink.close()
        assert sink._screen is None
        assert host.is_running


def test_progress_registration_is_inert_without_a_running_loop(tmp_path: Path) -> None:
    """Two inactive sinks borrow the same host/presenter without publishing a binding."""
    world = _World(tmp_path=tmp_path)
    app = SloTUI(session=world.session)
    presenter = GatedSessionPresenter()
    first = WorkflowProgressUpdatesAdapter.register(host=app, presenter=presenter)
    second = WorkflowProgressUpdatesAdapter.register(host=app, presenter=presenter)
    assert first is not second
    assert first._host is second._host is app
    assert first._presenter is second._presenter is presenter
    assert first._loop is second._loop is None
    assert first._screen is second._screen is None
    assert presenter.commands == []
    assert app._workflow_progress_updates_adapter is None
