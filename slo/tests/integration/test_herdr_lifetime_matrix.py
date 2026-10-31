"""C section 8 lifetime acceptance, built incrementally with real mounted owners.

Queued/admitted reporter and viewer families use distinct lock/child barriers.
Capture/save families use real pending publications and filesystem writes.
Platform families retain independently selected platform work, never Herdr fallback.
"""

import asyncio
import logging
import threading
from contextlib import ExitStack
from dataclasses import dataclass

from textual.timer import Timer
from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest

from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO, HerdrCommandResultDAO
from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.herdr.dao import HerdrLifecycleAcknowledgementDAO, HerdrSavedRestoreDAO
from src.agents.slo_agent.history.inbox.lease import SessionOwnershipLeaseStore
from src.agents.slo_agent.history.inbox.dao import SessionInboxMessageDAO
from tests.tui.test_herdr_inbox_disposition import inbox_file
from src.agents.slo_agent.herdr.restore import HerdrRestoreStore
from src.agents.slo_agent.herdr.dao import HerdrRestoreConfigDAO, HerdrRestoreReferenceDAO
from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceUnavailableError
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.visualizer_launcher import VisualizerLauncher
from tests.state_isolation import FakeHerdrFixture
from tests.tui.test_herdr_activation_composed import commands, eventually, native_factory
from tests.tui.test_herdr_viewer_retention_composed import mount_owner


@dataclass(frozen=True)
class MatrixOwnershipFacts:
    """Captured mounted owners, compared before teardown rather than from callbacks."""

    session: SloAgentSession
    lease_store: SessionOwnershipLeaseStore
    owner_id: str
    timers: tuple[Timer, Timer]
    preparation: asyncio.Task[None] | None
    claimed_path: Path
    claimed_bytes: bytes

    @classmethod
    async def capture(cls, *, app: SloTUI) -> "MatrixOwnershipFacts":
        """Require real delivery owners before the phase acquires its barrier."""
        assert app._lease_store is not None and app._inbox_store is not None
        assert app._lease_timer is not None and app._inbox_timer is not None
        assert app._retired_herdr_session is None
        lease = await app._lease_store.read(session_id=app._session.session_id)
        assert lease is not None and lease.owner_id == app._session_owner_id
        assert app._render_event in app._session._subscribers
        assert app._in_flight_task is None
        # A previously retained claim is not pending work. Normal polls, including
        # an open integration-only stop, must never acknowledge or replay it.
        async with app._prompt_submission_lock:
            message = SessionInboxMessageDAO(
                session_id=app._session.session_id,
                schedule_id="matrix-retained",
                run_id="matrix",
                kind="scheduled_prompt",
                delivery_mode="chat_turn",
                text="must remain claimed",
            )
            await app._inbox_store.enqueue(message=message)
            assert await app._inbox_store.claim_next(session_id=message.session_id) == message
        root = app._session.history_root
        assert root is not None
        claimed_path = inbox_file(root=root, message=message)
        assert claimed_path.parent.name == "claimed"
        return cls(
            session=app._session,
            lease_store=app._lease_store,
            owner_id=app._session_owner_id,
            timers=(app._lease_timer, app._inbox_timer),
            preparation=app._preparation_task,
            claimed_path=claimed_path,
            claimed_bytes=claimed_path.read_bytes(),
        )

    async def assert_settled(self, *, app: SloTUI, trigger: str) -> None:
        """Check captured identity, delivery and task ownership after the phase joins."""
        assert not app._visualizer_launch_tasks
        assert app._retired_herdr_session is None
        assert app._in_flight_task is None
        lease = await self.lease_store.read(session_id=self.session.session_id)
        if trigger in {"new", "unmount"}:
            assert lease is None
            assert app._render_event not in self.session._subscribers
            assert all(timer._task is None for timer in self.timers)
            assert self.preparation is None or self.preparation.done()
            assert self.session._herdr_close_task is not None
            assert self.session._herdr_close_task.done()
            assert self.session._herdr_close_task.result().resources == "drained"
        else:
            assert app._session is self.session
            assert lease is not None and lease.owner_id == self.owner_id
            assert app._render_event in self.session._subscribers
            assert app._lease_timer is self.timers[0] and app._inbox_timer is self.timers[1]
            assert all(timer._task is not None for timer in self.timers)
        await self._assert_selected_delivery(app=app, trigger=trigger)

    async def _assert_selected_delivery(self, *, app: SloTUI, trigger: str) -> None:
        """Distinguish a closed app from an open integration-only stop or successor."""
        assert app._inbox_store is not None
        await app._poll_session_inbox()
        assert self.claimed_path.read_bytes() == self.claimed_bytes
        assert self.claimed_path.parent.name == "claimed"
        assert app._in_flight_task is None
        assert await app._inbox_store.list_done(session_id=self.session.session_id) == []
        assert await app._inbox_store.list_pending(session_id=self.session.session_id) == []
        if trigger == "unmount":
            assert app._app_closing and app._delivery_quiescing
            assert app._lease_timer is None and app._inbox_timer is None
            assert app._app_shutdown_task is not None and app._app_shutdown_task.done()
            assert app._selected_herdr_drain_task is not None and app._selected_herdr_drain_task.done()
            return
        assert not app._app_closing and not app._delivery_quiescing
        assert app._render_event in app._session._subscribers
        lease = await self.lease_store.read(session_id=app._session.session_id)
        assert lease is not None and lease.owner_id == self.owner_id
        if trigger == "new":
            assert app._session is not self.session
            assert app._lease_timer is not self.timers[0] and app._inbox_timer is not self.timers[1]


@dataclass(frozen=True)
class MatrixAcknowledgementFacts:
    """Semantic acknowledgements at revocation, not remote binding speculation."""

    display: int | None
    lifecycle: HerdrLifecycleAcknowledgementDAO | None
    restore: HerdrSavedRestoreDAO | None

    @classmethod
    def capture(cls, *, reporter: HerdrReporter) -> "MatrixAcknowledgementFacts":
        """Snapshot immutable acknowledgement facts before releasing held work."""
        return cls(
            display=reporter._display_ack_revision,
            lifecycle=reporter._lifecycle_ack,
            restore=reporter._restore_ack,
        )

    def assert_no_late_credit(self, *, reporter: HerdrReporter) -> None:
        """Permit stale semantic invalidation, but never advancement after revocation."""
        assert reporter._display_ack_revision == self.display
        assert reporter._lifecycle_ack is None or reporter._lifecycle_ack == self.lifecycle
        assert reporter._restore_ack is None or reporter._restore_ack == self.restore
        assert reporter._admitted_ticket is None
        assert reporter._save_task is None and reporter._reservation_task is None
        assert reporter._transport.resources_drained


@pytest.mark.parametrize("trigger", ["runtime_disable", "session_close", "new", "unmount"])
@pytest.mark.parametrize(
    "phase",
    [
        "queued_viewer",
        "queued_report",
        "admitted_viewer",
        "admitted_report",
        "running_save",
        "queued_capture",
        "precommit_platform",
        "committed_platform",
    ],
)
@pytest.mark.parametrize("diagnostic", ["healthy", "raising"])
async def test_lifetime_cutoff_matrix(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    trigger: str,
    phase: str,
    diagnostic: str,
) -> None:
    """Revoke mounted reporter/viewer work across queued and admitted CLI boundaries."""
    if phase.endswith("_platform"):
        await _matrix139_platform(
            root=tmp_path,
            fake=fake_herdr,
            monkeypatch=monkeypatch,
            trigger=trigger,
            phase=phase,
            diagnostic=diagnostic,
        )
        return
    if phase == "queued_capture":
        await _matrix138_queued_capture(
            root=tmp_path, fake=fake_herdr, monkeypatch=monkeypatch, trigger=trigger, diagnostic=diagnostic
        )
        return
    if phase == "running_save":
        await _matrix138_running_save(
            root=tmp_path, fake=fake_herdr, monkeypatch=monkeypatch, trigger=trigger, diagnostic=diagnostic
        )
        return
    monkeypatch.setenv(name="SLO_HOME", value=str(tmp_path))
    monkeypatch.setenv(name="SLO_AUTO_VISUALIZE", value="1")
    monkeypatch.setattr("src.agents.slo_agent.history.filesystem_store._CFG_SLO_HOME", tmp_path)
    session = await mount_owner(root=tmp_path)
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        await eventually(predicate=lambda: reporter._display_ack_revision == reporter._revision)
        assert session._herdr_visualizer is not None
        assert session._herdr_visualizer._transport is reporter._transport
        assert app._inbox_store is not None and app._lease_store is not None
        owners = await MatrixOwnershipFacts.capture(app=app)
        transport = reporter._transport
        admitted = phase.startswith("admitted_")
        entered, release = asyncio.Event(), asyncio.Event()
        original_collect = transport._collect_result

        async def collect(*, command: HerdrCliCommandDAO) -> HerdrCommandResultDAO:
            """Hold a real tracked child after admission, before terminal accounting."""
            entered.set()
            await release.wait()
            return await original_collect(command=command)

        seams = ExitStack()
        if admitted:
            seams.enter_context(patch.object(transport, "_collect_result", side_effect=collect))
        else:
            await transport._command_lock.acquire()
        boundary = len(commands(fake_herdr))
        viewer: asyncio.Task[None] | None = None
        closing: asyncio.Task[None] | None = None
        try:
            if phase.endswith("viewer"):
                app._schedule_visualizer_launch(parent_session_id=session.session_id)
                viewer = app._visualizer_launch_tasks[session.session_id]
            else:
                session.set_operator_attention(reason="Authentication required")
            if admitted:
                await asyncio.wait_for(entered.wait(), timeout=10)
                assert transport._active is not None
                await eventually(predicate=lambda: len(commands(fake_herdr)) > boundary)
            else:
                await eventually(predicate=lambda: bool(transport._command_lock._waiters))
            if viewer is not None:
                assert not viewer.done()
            else:
                if admitted:
                    assert reporter._admitted_ticket is not None
                else:
                    assert reporter._reserved_ticket is not None
                    assert reporter._admitted_ticket is None
            logger = logging.getLogger("src.agents.slo_agent.herdr.reporter")
            with (
                patch.object(
                    logger,
                    "warning",
                    side_effect=(
                        RuntimeError("synthetic matrix diagnostic") if diagnostic == "raising" else None
                    ),
                    wraps=logger.warning if diagnostic == "healthy" else None,
                ) as diagnostic_sink,
                patch.object(
                    reporter, "_shutdown_release", side_effect=OSError("synthetic withdrawal refusal")
                ),
            ):
                if trigger == "runtime_disable":
                    with patch.object(
                        reporter._sequence_store, "reserve", side_effect=HerdrSequenceUnavailableError()
                    ):
                        await reporter._reserve_ticket(operation="clear")
                    assert reporter._disabled
                else:
                    closing = asyncio.create_task(
                        coro=_matrix136_stop(app=app, session=session, trigger=trigger)
                    )
                    await eventually(predicate=lambda: reporter._ordinary_revoked)
                acknowledgements = MatrixAcknowledgementFacts.capture(reporter=reporter)
                if admitted:
                    release.set()
                else:
                    transport._command_lock.release()
                if viewer is not None:
                    results = await asyncio.wait_for(
                        asyncio.gather(viewer, return_exceptions=True), timeout=10
                    )
                    assert results[0] is None or isinstance(results[0], asyncio.CancelledError)
                if closing is not None:
                    await asyncio.wait_for(asyncio.shield(closing), timeout=10)
                assert diagnostic_sink.call_count >= 1
                await eventually(predicate=lambda: transport.resources_drained)
                effects = [
                    row
                    for row in commands(fake_herdr)[boundary:]
                    if row[:2] in (["pane", "split"], ["pane", "report-agent"], ["pane", "report-metadata"])
                ]
                assert len(effects) == int(admitted)
                if admitted:
                    expected = "split" if phase.endswith("viewer") else "report-metadata"
                    assert effects[0][:2] == ["pane", expected]
                assert reporter._admitted_ticket is None
                if closing is not None:
                    assert session._herdr_close_task is not None
                    outcome = session._herdr_close_task.result()
                    assert outcome.resources == "drained" and outcome.replacement == "uncertain"
                    assert transport.closed and transport.resources_drained
                    assert not reporter._lease_held and not reporter.retains_external_resources
                    assert app._retired_herdr_session is None
                    if trigger == "new":
                        assert app._session._herdr_suppressed
                else:
                    assert reporter._lease_held and not transport.closed
                assert reporter._save_task is None and reporter._reservation_task is None
                assert not app._visualizer_launch_tasks
                assert (app._session is not session) == (trigger == "new")
                acknowledgements.assert_no_late_credit(reporter=reporter)
                await owners.assert_settled(app=app, trigger=trigger)
        finally:
            release.set()
            if not admitted and transport._command_lock.locked():
                transport._command_lock.release()
            seams.close()
            await asyncio.gather(
                *([viewer] if viewer is not None else []),
                *([closing] if closing is not None else []),
                return_exceptions=True,
            )


async def _matrix139_platform(
    *,
    root: Path,
    fake: FakeHerdrFixture,
    monkeypatch: pytest.MonkeyPatch,
    trigger: str,
    phase: str,
    diagnostic: str,
) -> None:
    """Join real synchronous platform work independently of a real pane owner cutoff."""
    monkeypatch.setenv(name="SLO_HOME", value=str(root))
    monkeypatch.setenv(name="SLO_AUTO_VISUALIZE", value="1")
    monkeypatch.setattr("src.agents.slo_agent.history.filesystem_store._CFG_SLO_HOME", root)
    # A separate enabled owner supplies genuine runtime-disable/close semantics.
    # The mounted platform session is classified disabled at activation, not patched
    # from an enabled Herdr destination into a fallback.
    pane_session = await mount_owner(root=root)
    await pane_session.start_external_reporting(interactive=True)
    reporter = pane_session._herdr_reporter
    assert isinstance(reporter, HerdrReporter)
    await eventually(predicate=lambda: reporter._display_ack_revision == reporter._revision)
    monkeypatch.setenv(name="SLO_HERDR_DISABLED", value="1")
    session = await mount_owner(root=root)
    app = SloTUI(session=session)
    if phase == "precommit_platform":
        await _matrix140_precommit_platform(
            app=app, pane_session=pane_session, reporter=reporter, trigger=trigger, diagnostic=diagnostic
        )
        return
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    draining = asyncio.Event()
    spawns: list[list[str]] = []
    guarded_spawn = VisualizerLauncher._default_spawn
    assert getattr(guarded_spawn, "__test_stub__", False)

    def discover() -> str:
        """Hold actual Linux discovery after synchronous policy admission."""
        return "test-terminal"

    def spawn(argv: list[str]) -> object:
        """Count actual submission before blocking; delegate only to the test guard."""
        spawns.append(argv)
        if phase == "committed_platform":
            entered.set()
            release.wait(timeout=20)
        result = guarded_spawn(argv)
        finished.set()
        return result

    original_drain = app._cancel_visualizer_launches

    async def drain() -> None:
        """Observe the real app drain without replacing cancellation/join mechanics."""
        draining.set()
        await original_drain()

    logger = logging.getLogger("src.agents.slo_agent.herdr.reporter")
    viewer: asyncio.Task[None] | None = None
    closing: asyncio.Task[None] | None = None
    try:
        async with app.run_test() as pilot:
            await pilot.pause()
            owners = await MatrixOwnershipFacts.capture(app=app)
            assert session.workflow_visualizer_destination == "platform"
            lease_store = app._lease_store
            assert lease_store is not None
            lease = await lease_store.read(session_id=session.session_id)
            assert lease is not None and lease.owner_id == app._session_owner_id
            boundary = len(commands(fake))
            with (
                patch("src.tui.visualizer_launcher.sys.platform", "linux"),
                patch.object(VisualizerLauncher, "_resolve_linux_terminal", side_effect=discover),
                patch.object(VisualizerLauncher, "_default_spawn", side_effect=spawn),
                patch.object(app, "_cancel_visualizer_launches", side_effect=drain),
                patch.object(app._ensure_workflow_renderer(), "write_launch_outcome") as notice,
                patch.object(
                    logger,
                    "warning",
                    side_effect=(
                        RuntimeError("synthetic matrix diagnostic") if diagnostic == "raising" else None
                    ),
                    wraps=logger.warning if diagnostic == "healthy" else None,
                ) as sink,
                patch.object(reporter, "_shutdown_release", side_effect=OSError("withdrawal refusal")),
            ):
                app._schedule_visualizer_launch(parent_session_id=session.session_id)
                viewer = app._visualizer_launch_tasks[session.session_id]
                assert await asyncio.to_thread(entered.wait, 5)
                assert len(spawns) == int(phase == "committed_platform")
                app._schedule_visualizer_launch(parent_session_id=session.session_id)
                assert app._visualizer_launch_tasks == {session.session_id: viewer}
                if trigger == "runtime_disable":
                    with patch.object(
                        reporter._sequence_store, "reserve", side_effect=HerdrSequenceUnavailableError()
                    ):
                        await reporter._reserve_ticket(operation="clear")
                    assert reporter._disabled and reporter._lease_held
                else:
                    await pane_session.close_external_reporting()
                    assert reporter._transport.closed and reporter._transport.resources_drained
                    assert not reporter._lease_held
                assert sink.call_count >= 1
                acknowledgement = MatrixAcknowledgementFacts.capture(reporter=reporter)
                cutoff_commands = len(commands(fake))
                assert pane_session.workflow_visualizer_destination == "unavailable"
                if trigger in {"new", "unmount"}:
                    closing = asyncio.create_task(
                        coro=_matrix136_stop(app=app, session=session, trigger=trigger)
                    )
                    await asyncio.wait_for(draining.wait(), timeout=5)
                    app._schedule_visualizer_launch(parent_session_id="rejected-parent")
                    assert "rejected-parent" not in app._visualizer_launch_tasks
                else:
                    if trigger == "session_close":
                        await session.close_external_reporting()
                    # Integration close/disable does not cancel independently selected
                    # platform work. Explicit caller cancellation must still join it.
                    assert not viewer.done() and session.workflow_visualizer_destination == "platform"
                    viewer.cancel()
                for _ in range(3):
                    viewer.cancel()
                    checkpoint = asyncio.Event()
                    asyncio.get_running_loop().call_soon(checkpoint.set)
                    await checkpoint.wait()
                    assert not viewer.done() and not finished.is_set()
                    assert app._session is session
                    if closing is not None:
                        assert not closing.done()
                assert len(spawns) == int(phase == "committed_platform")
                release.set()
                await asyncio.wait_for(asyncio.gather(viewer, return_exceptions=True), timeout=10)
                if closing is not None:
                    await asyncio.wait_for(asyncio.shield(closing), timeout=10)
                assert viewer.cancelled() and finished.is_set()
                acknowledgement.assert_no_late_credit(reporter=reporter)
                assert not [
                    row
                    for row in commands(fake)[cutoff_commands:]
                    if row[:2] in (["pane", "report-agent"], ["pane", "report-metadata"], ["pane", "split"])
                ]
                assert len(spawns) == 1 and session.session_id in spawns[0][-1]
                assert not app._visualizer_launch_tasks
                notice.assert_not_called()
                assert (app._session is not session) == (trigger == "new")
                assert not reporter._transport._active and reporter._admitted_ticket is None
                assert reporter._save_task is None and reporter._reservation_task is None
                assert not app._retired_herdr_session
                assert not [row for row in commands(fake)[boundary:] if row[:2] == ["pane", "split"]]
                if closing is not None:
                    assert await lease_store.read(session_id=session.session_id) is None
                else:
                    assert await lease_store.read(session_id=session.session_id) == lease
                await owners.assert_settled(app=app, trigger=trigger)
    finally:
        release.set()
        await asyncio.gather(
            *([viewer] if viewer else []), *([closing] if closing else []), return_exceptions=True
        )
        await pane_session.close_external_reporting()


async def _matrix140_precommit_platform(
    *,
    app: SloTUI,
    pane_session: SloAgentSession,
    reporter: HerdrReporter,
    trigger: str,
    diagnostic: str,
) -> None:
    """Hold the registered app worker before its real lifetime check/thread commit."""
    entered, release = asyncio.Event(), asyncio.Event()
    original = app._run_visualizer_launch

    async def worker(*, parent_session_id: str, session: SloAgentSession) -> None:
        """Record entry only; all policy remains in the original worker."""
        entered.set()
        await release.wait()
        await original(parent_session_id=parent_session_id, session=session)

    logger = logging.getLogger("src.agents.slo_agent.herdr.reporter")
    viewer: asyncio.Task[None] | None = None
    try:
        async with app.run_test() as pilot:
            await pilot.pause()
            owners = await MatrixOwnershipFacts.capture(app=app)
            session = app._session
            with (
                patch.object(app, "_run_visualizer_launch", side_effect=worker),
                patch.object(VisualizerLauncher, "_resolve_linux_terminal", return_value="test-terminal"),
                patch("src.tui.visualizer_launcher.sys.platform", "linux"),
                patch.object(
                    VisualizerLauncher, "_default_spawn", wraps=VisualizerLauncher._default_spawn
                ) as spawn,
                patch.object(app._ensure_workflow_renderer(), "write_launch_outcome") as notice,
                patch.object(
                    logger,
                    "warning",
                    side_effect=RuntimeError("synthetic diagnostic") if diagnostic == "raising" else None,
                ) as sink,
                patch.object(reporter, "_shutdown_release", side_effect=OSError("withdrawal refusal")),
            ):
                app._schedule_visualizer_launch(parent_session_id=session.session_id)
                viewer = app._visualizer_launch_tasks[session.session_id]
                await asyncio.wait_for(entered.wait(), timeout=5)
                spawn.assert_not_called()
                if trigger == "runtime_disable":
                    with patch.object(
                        reporter._sequence_store, "reserve", side_effect=HerdrSequenceUnavailableError()
                    ):
                        await reporter._reserve_ticket(operation="clear")
                else:
                    await pane_session.close_external_reporting()
                acknowledgements = MatrixAcknowledgementFacts.capture(reporter=reporter)
                assert sink.call_count > 0
                if trigger in {"new", "unmount"}:
                    await _matrix136_stop(app=app, session=session, trigger=trigger)
                    assert viewer.cancelled()
                    spawn.assert_not_called()
                    notice.assert_not_called()
                else:
                    if trigger == "session_close":
                        await session.close_external_reporting()
                    assert session.workflow_visualizer_destination == "platform"
                    release.set()
                    await asyncio.wait_for(viewer, timeout=5)
                    spawn.assert_called_once()
                    notice.assert_called_once()
                if trigger == "runtime_disable":
                    # The independent platform viewer does not join an already
                    # admitted periodic report. Disable fences credit immediately;
                    # the transport holds its lock through reap and accounting.
                    async with asyncio.timeout(10):
                        async with reporter._transport._command_lock:
                            pass
                acknowledgements.assert_no_late_credit(reporter=reporter)
                await owners.assert_settled(app=app, trigger=trigger)
    finally:
        release.set()
        if viewer is not None:
            await asyncio.gather(viewer, return_exceptions=True)
        await pane_session.close_external_reporting()


async def _matrix136_stop(*, app: SloTUI, session: SloAgentSession, trigger: str) -> None:
    """Exercise the selected production lifetime gateway, never assign cutoff flags."""
    if trigger == "session_close":
        await session.close_external_reporting()
        return
    if trigger == "new":
        await app._start_new_session(requested_name=None)
        return
    assert trigger == "unmount"
    await app.on_unmount()


async def _matrix138_running_save(
    *,
    root: Path,
    fake: FakeHerdrFixture,
    monkeypatch: pytest.MonkeyPatch,
    trigger: str,
    diagnostic: str,
) -> None:
    """Hold the real immutable filesystem save while the mounted owner stops."""
    monkeypatch.setenv(name="SLO_HOME", value=str(root))
    monkeypatch.setattr("src.agents.slo_agent.history.filesystem_store._CFG_SLO_HOME", root)
    session = await mount_owner(root=root)
    app = SloTUI(session=session)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    async with app.run_test() as pilot:
        await pilot.pause()
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        await eventually(predicate=lambda: reporter._display_ack_revision == reporter._revision)
        owners = await MatrixOwnershipFacts.capture(app=app)
        original_save = reporter._restore_store.save
        before = {path: path.read_bytes() for path in root.rglob("r1-*.json")}
        saved_configs: list[HerdrRestoreConfigDAO] = []
        references: list[HerdrRestoreReferenceDAO] = []

        def save(*, config: HerdrRestoreConfigDAO) -> HerdrRestoreReferenceDAO:
            """Pause before real store locking/writing, then preserve its return value."""
            saved_configs.append(config)
            entered.set()
            release.wait(timeout=15)
            result = original_save(config=config)
            references.append(result)
            finished.set()
            return result

        closing: asyncio.Task[None] | None = None
        logger = logging.getLogger("src.agents.slo_agent.herdr.reporter")
        with (
            patch.object(reporter._restore_store, "save", side_effect=save),
            patch.object(
                logger,
                "warning",
                side_effect=RuntimeError("synthetic diagnostic") if diagnostic == "raising" else None,
                wraps=logger.warning if diagnostic == "healthy" else None,
            ) as sink,
            patch.object(reporter, "_shutdown_release", side_effect=OSError("synthetic withdrawal refusal")),
        ):
            try:
                previous_capture = session._herdr_capture
                assert previous_capture is not None
                target: Literal["low", "high"] = (
                    "low" if previous_capture.config.reasoning_level == "high" else "high"
                )
                session.switch_reasoning_level(reasoning_level=target)
                assert session._herdr_capture != previous_capture
                await eventually(predicate=entered.is_set)
                assert reporter._save_task is not None and not reporter._save_task.done()
                capture = saved_configs[0].model_dump_json()
                boundary = len(commands(fake))
                if trigger == "runtime_disable":
                    with patch.object(
                        reporter._sequence_store, "reserve", side_effect=HerdrSequenceUnavailableError()
                    ):
                        await reporter._reserve_ticket(operation="clear")
                    assert reporter._disabled
                else:
                    closing = asyncio.create_task(
                        coro=_matrix136_stop(app=app, session=session, trigger=trigger)
                    )
                    await eventually(predicate=lambda: reporter._ordinary_revoked)
                    assert not closing.done()
                acknowledgements = MatrixAcknowledgementFacts.capture(reporter=reporter)
                assert not finished.is_set()
                session.set_operator_attention(reason="Authentication required")
                release.set()
                await eventually(predicate=finished.is_set)
                if closing is not None:
                    await asyncio.wait_for(asyncio.shield(closing), timeout=10)
                await eventually(predicate=lambda: reporter._save_task is None)
                assert sink.call_count > 0
                assert saved_configs[0].model_dump_json() == capture
                assert all(path.read_bytes() == contents for path, contents in before.items())
                assert len(references) == 1
                reference = references[0].restore_reference
                assert isinstance(reporter._restore_store, HerdrRestoreStore)
                loaded = reporter._restore_store.load(
                    restore_reference=reference, session_id=session.session_id
                )
                assert loaded == saved_configs[0]
                assert reporter._saved is None or reporter._saved.reference.restore_reference != reference
                assert not any(reference in row for row in commands(fake)[boundary:])
                assert reporter._reservation_task is None
                assert not app._visualizer_launch_tasks
                if closing is not None:
                    assert reporter._transport.closed and reporter._transport.resources_drained
                    assert not reporter.retains_external_resources
                    assert session._herdr_close_task is not None
                    assert session._herdr_close_task.result().resources == "drained"
                    assert (app._session is not session) == (trigger == "new")
                acknowledgements.assert_no_late_credit(reporter=reporter)
                await owners.assert_settled(app=app, trigger=trigger)
            finally:
                release.set()
                if closing is not None:
                    await asyncio.wait_for(asyncio.gather(closing, return_exceptions=True), timeout=10)


async def _matrix138_queued_capture(
    *,
    root: Path,
    fake: FakeHerdrFixture,
    monkeypatch: pytest.MonkeyPatch,
    trigger: str,
    diagnostic: str,
) -> None:
    """Queue policy behind real shared-lock work, then revoke before a save starts."""
    monkeypatch.setenv(name="SLO_HOME", value=str(root))
    monkeypatch.setattr("src.agents.slo_agent.history.filesystem_store._CFG_SLO_HOME", root)
    session = await mount_owner(root=root)
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        await eventually(predicate=lambda: reporter._display_ack_revision == reporter._revision)
        owners = await MatrixOwnershipFacts.capture(app=app)
        transport = reporter._transport
        await transport._command_lock.acquire()
        closing: asyncio.Task[None] | None = None
        logger = logging.getLogger("src.agents.slo_agent.herdr.reporter")
        before = {path: path.read_bytes() for path in root.rglob("r1-*.json")}
        with (
            patch.object(reporter._restore_store, "save", wraps=reporter._restore_store.save) as save,
            patch.object(
                logger,
                "warning",
                side_effect=RuntimeError("synthetic diagnostic") if diagnostic == "raising" else None,
                wraps=logger.warning if diagnostic == "healthy" else None,
            ) as sink,
            patch.object(reporter, "_shutdown_release", side_effect=OSError("synthetic withdrawal refusal")),
        ):
            try:
                session.set_operator_attention(reason="Authentication required")
                await eventually(predicate=lambda: bool(transport._command_lock._waiters))
                previous = session._herdr_capture
                assert previous is not None
                session.switch_reasoning_level(
                    reasoning_level="low" if previous.config.reasoning_level == "high" else "high"
                )
                pending = reporter._pending
                assert pending is not None and pending.restore_capture != previous
                assert reporter._save_task is None
                boundary = len(commands(fake))
                if trigger == "runtime_disable":
                    with patch.object(
                        reporter._sequence_store, "reserve", side_effect=HerdrSequenceUnavailableError()
                    ):
                        await reporter._reserve_ticket(operation="clear")
                    assert reporter._disabled
                else:
                    closing = asyncio.create_task(
                        coro=_matrix136_stop(app=app, session=session, trigger=trigger)
                    )
                    await eventually(predicate=lambda: reporter._ordinary_revoked)
                acknowledgements = MatrixAcknowledgementFacts.capture(reporter=reporter)
                transport._command_lock.release()
                if closing is not None:
                    await asyncio.wait_for(asyncio.shield(closing), timeout=10)
                await eventually(predicate=lambda: reporter._worker is None or reporter._worker.done())
                assert sink.call_count > 0
                save.assert_not_called()
                assert reporter._save_task is None
                assert {path: path.read_bytes() for path in root.rglob("r1-*.json")} == before
                assert not any(
                    row[:2] in (["pane", "report-agent"], ["pane", "report-metadata"])
                    for row in commands(fake)[boundary:]
                )
                assert reporter._admitted_ticket is None
                if closing is not None:
                    assert transport.closed and transport.resources_drained
                    assert not reporter.retains_external_resources
                    assert (app._session is not session) == (trigger == "new")
                acknowledgements.assert_no_late_credit(reporter=reporter)
                await owners.assert_settled(app=app, trigger=trigger)
            finally:
                if transport._command_lock.locked():
                    transport._command_lock.release()
                if closing is not None:
                    await asyncio.wait_for(asyncio.gather(closing, return_exceptions=True), timeout=10)
