"""Mounted shutdown barriers exercise the real app and session lifetime."""

import asyncio
from collections.abc import Callable
from textual.pilot import Pilot
from src.tui.components.chat_transcript.component import ChatTranscript

from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO
from src.agents.slo_agent.herdr.service import NullHerdrReporter
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceStore, HerdrSequenceUnavailableError
from tests.state_isolation import FakeHerdrFixture


async def test_persistent_real_lease_keeps_app_shutdown_pending(
    tmp_path: Path, fake_herdr: FakeHerdrFixture
) -> None:
    """A genuine failed unlock retains the retired owner, not an invented mock flag."""
    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path))
    reporter = await old._prepare_herdr_reporter()
    assert isinstance(reporter, HerdrReporter)
    # This fixture tests an inactive reporter's failed unlock, not activation.
    # Keep mount inert, then attach the fixture-owned lease after mount settles.
    old.suppress_external_reporting()
    lease = reporter._sequence_store
    lease.acquire()
    reporter._lease_held = True
    contender = HerdrSequenceStore(
        state_root=reporter._config.state_root,
        socket_namespace=reporter._config.socket_path or "default",
        pane_id=reporter._config.pane_id,
    )
    app = SloTUI(session=old)
    final_attempt = asyncio.Event()
    attempts = 0

    def failed_unlock() -> None:
        """Fail both actual unlock attempts and identify the final attempt."""
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            final_attempt.set()
        raise OSError("synthetic persistent unlock failure")

    # Fixture-only cancellation propagates through Textual's repeated unmount.
    with pytest.raises(asyncio.CancelledError):
        async with app.run_test() as pilot:
            await _exercise_persistent_lease_shutdown(
                app=app,
                pilot=pilot,
                old=old,
                reporter=reporter,
                lease=lease,
                contender=contender,
                final_attempt=final_attempt,
                failed_unlock=failed_unlock,
                fake_herdr=fake_herdr,
            )
    assert attempts == 2


async def _exercise_persistent_lease_shutdown(
    *,
    app: SloTUI,
    pilot: Pilot,
    old: SloAgentSession,
    reporter: HerdrReporter,
    lease: HerdrSequenceStore,
    contender: HerdrSequenceStore,
    final_attempt: asyncio.Event,
    failed_unlock: Callable[[], None],
    fake_herdr: FakeHerdrFixture,
) -> None:
    """Observe real retention, then explicitly free only fixture-owned resources."""
    await pilot.pause()
    old._herdr_reporter = reporter
    with patch.object(lease, "close", side_effect=failed_unlock):
        shutdown = None
        try:
            await app._start_new_session(requested_name=None)
            assert app._retired_herdr_session is old
            assert app._session._herdr_suppressed
            shutdown = asyncio.create_task(coro=app.on_unmount())
            await asyncio.wait_for(final_attempt.wait(), timeout=5)
            final = old._herdr_retired_drain_task
            assert final is not None
            assert (await asyncio.shield(final)).resources == "retained"
            for _ in range(3):
                shutdown.cancel()
                await asyncio.sleep(0)
                assert not shutdown.done()
            assert app._retired_herdr_session is old
            assert reporter._sequence_store is lease and reporter._lease_held
            with pytest.raises(HerdrSequenceUnavailableError):
                contender.acquire()
            assert fake_herdr.capture.read_text() == ""
        finally:
            # Only after proving persistent failure, release the fixture's actual
            # lease and cancel its private pending sentinel. Never fake success.
            HerdrSequenceStore.close(lease)
            reporter._lease_held = False
            pending = old._herdr_finish_cleanup_task
            if pending is not None and not pending.done():
                pending.cancel()
            if shutdown is not None:
                await asyncio.wait_for(asyncio.gather(shutdown, return_exceptions=True), timeout=5)
            contender.close()


async def test_pending_retired_drain_does_not_starve_selected(tmp_path: Path) -> None:
    """Both final owners start before either pending local drain is joined."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    retired = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    entered = asyncio.Event()
    selected_entered = asyncio.Event()
    release = asyncio.Event()

    async def retired_drain() -> HerdrReporterCloseOutcomeDAO:
        """Model persistent retention until fixture-controlled teardown."""
        entered.set()
        await release.wait()
        return HerdrReporterCloseOutcomeDAO(replacement="uncertain", resources="drained")

    async def selected_drain() -> HerdrReporterCloseOutcomeDAO:
        """Observe independent admission of the selected owner."""
        selected_entered.set()
        await release.wait()
        return HerdrReporterCloseOutcomeDAO(replacement="safe", resources="drained")

    async with app.run_test() as pilot:
        await pilot.pause()
        app._retired_herdr_session = retired
        with (
            patch.object(retired, "finish_retired_reporting_cleanup", side_effect=retired_drain),
            patch.object(session, "finish_retired_reporting_cleanup", side_effect=selected_drain),
        ):
            shutdown = asyncio.create_task(coro=app.on_unmount())
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                await asyncio.wait_for(selected_entered.wait(), timeout=1)
                shutdown.cancel()
                await asyncio.sleep(0)
                assert not shutdown.done()
                assert app._retired_herdr_session is retired
                assert app._app_shutdown_task is not None and not app._app_shutdown_task.done()
            finally:
                release.set()
                await asyncio.gather(shutdown, return_exceptions=True)


async def test_unmount_joins_replacement_outside_gate(tmp_path: Path) -> None:
    """A committed replacement settles before shutdown closes the selected owner."""
    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history"))
    app = SloTUI(session=old)
    entered = asyncio.Event()
    release = asyncio.Event()
    original_close = NullHerdrReporter.close

    async def close(self: NullHerdrReporter) -> HerdrReporterCloseOutcomeDAO:
        """Hold the actual predecessor close, not a replacement imitation."""
        if self is old._herdr_reporter:
            entered.set()
            await release.wait()
        return await original_close(self)

    async with app.run_test() as pilot:
        await pilot.pause()
        with patch.object(NullHerdrReporter, "close", new=close):
            replacement = asyncio.create_task(coro=app._start_new_session(requested_name=None))
            shutdown = None
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                retained = app._session_replacement_task
                shutdown = asyncio.create_task(coro=app.on_unmount())
                await asyncio.sleep(0)
                assert getattr(app, "_app_closing", False)
                assert not shutdown.done()
                assert app._session_replacement_task is retained
                release.set()
                await asyncio.wait_for(asyncio.gather(replacement, shutdown), timeout=5)
                # Commit remains irreversible, but the adopted candidate cannot reopen runtime.
                assert app._session is not old
                assert app._session._herdr_closing
                assert app._session._herdr_suppressed
                assert app._render_event not in app._session._subscribers
                assert app._lease_timer is None and app._inbox_timer is None
                assert app._delivery_quiescing
                assert app._lease_store is not None
                assert await app._lease_store.read(session_id=app._session.session_id) is None
                selected = app._session
                await app._start_new_session(requested_name=None)
                assert app._session is selected
            finally:
                release.set()
                await asyncio.gather(replacement, *([shutdown] if shutdown else []), return_exceptions=True)


@pytest.mark.parametrize("failure", ["preparation", "viewer", "unsubscribe", "close", "release"])
async def test_shutdown_attempts_each_owner(tmp_path: Path, failure: str) -> None:
    """One faulty owner and a throwing notice never prevent the other cleanup owners."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    retired = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        app._retired_herdr_session = retired
        target, name = {
            "preparation": (app, "_cancel_session_preparation"),
            "viewer": (app, "_cancel_visualizer_launches"),
            "unsubscribe": (session, "unsubscribe"),
            "close": (session, "close_external_reporting"),
            "release": (app, "_release_replaced_session_lease"),
        }[failure]
        original_close = session.close_external_reporting
        close_failed = False

        async def fail_first_close() -> HerdrReporterCloseOutcomeDAO:
            """Fail the initial close; let the independent final attempt prove drain."""
            nonlocal close_failed
            if not close_failed:
                close_failed = True
                raise RuntimeError("private cleanup defect")
            return await original_close()

        fault = fail_first_close if failure == "close" else RuntimeError("private cleanup defect")
        with (
            patch.object(target, name, side_effect=fault),
            patch.object(
                app._chat_transcript, "write_transcript_line", side_effect=RuntimeError("notice defect")
            ),
            patch.object(
                session, "finish_retired_reporting_cleanup", wraps=session.finish_retired_reporting_cleanup
            ) as current_drain,
            patch.object(
                retired, "finish_retired_reporting_cleanup", wraps=retired.finish_retired_reporting_cleanup
            ) as retired_drain,
        ):
            await app.on_unmount()
            assert current_drain.await_count == 1
            assert retired_drain.await_count == 1
        assert app._lease_timer is None and app._inbox_timer is None
        assert session._herdr_closing and retired._herdr_closing
        assert app._retired_herdr_session is None


@pytest.mark.parametrize("phase", ["mount_hydration", "replacement_usage", "preparation"])
async def test_late_runtime_continuation_is_silent(tmp_path: Path, phase: str) -> None:
    """A captured runtime callback cannot repaint or start work after shutdown."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def barrier(**kwargs: object) -> None:
        """Pause one actual app await seam until shutdown completes."""
        entered.set()
        await release.wait()

    async with app.run_test() as pilot:
        await pilot.pause()
        target, name = {
            "mount_hydration": (app._chat_transcript, "hydrate"),
            "replacement_usage": (session, "refresh_context_window_snapshot"),
            "preparation": (session, "prepare_startup"),
        }[phase]
        with patch.object(target, name, side_effect=barrier):
            operation = {
                "mount_hydration": app.on_mount,
                "replacement_usage": app._finish_replacement_ui,
                "preparation": lambda: app._prepare_mounted_session(session=session),
            }[phase]
            task = asyncio.create_task(coro=operation())
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                await app.on_unmount()
                with (
                    patch.object(app._chat_transcript, "write_transcript_line") as notice,
                    patch.object(app, "_refresh_usage_status_bar") as usage,
                    patch.object(app, "_initialize_session_delivery") as initialize,
                ):
                    release.set()
                    await asyncio.wait_for(task, timeout=5)
                    notice.assert_not_called()
                    usage.assert_not_called()
                    initialize.assert_not_called()
                assert app._render_event not in session._subscribers
                assert app._delivery_quiescing
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)


async def test_viewer_helper_fault_retains_shutdown_until_worker_terminal(tmp_path: Path) -> None:
    """Independent real owners close, but an unjoined viewer still prevents shutdown."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history")
    )
    app = SloTUI(session=session)
    release = asyncio.Event()

    async def wait_for_release() -> None:
        """Retain fixture work until the shutdown assertions finish."""
        await release.wait()

    async with app.run_test() as pilot:
        await pilot.pause()
        viewer = asyncio.create_task(coro=wait_for_release())
        app._visualizer_launch_tasks["retained"] = viewer
        with (
            patch.object(app, "_cancel_visualizer_launches", side_effect=RuntimeError("private")),
            patch.object(app._chat_transcript, "write_transcript_line", side_effect=RuntimeError("notice")),
        ):
            shutdown = asyncio.create_task(coro=app.on_unmount())
            try:
                while app._selected_herdr_drain_task is None:
                    await asyncio.sleep(0)
                await app._selected_herdr_drain_task
                await asyncio.sleep(0)
                assert session._herdr_close_task is not None and session._herdr_close_task.done()
                assert app._lease_store is not None
                assert await app._lease_store.read(session_id=session.session_id) is None
                assert not shutdown.done()
                assert app._visualizer_launch_tasks["retained"] is viewer
                shutdown.cancel()
                await asyncio.sleep(0)
                assert not shutdown.done()
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await shutdown
            finally:
                release.set()
                await asyncio.gather(viewer, shutdown, return_exceptions=True)
