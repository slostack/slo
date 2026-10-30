"""Extraction boundary tests for the WorkflowProgress component (feature 96.f.1).

The component owns the fleet panel, one observation-lifetime adapter per bind
and the apply/reset presentation mechanics that used to live on ``SloTUI``.
These tests mount the real app: rows flow through the real service and
coordinator into the composed panel, and binding/retirement rules hold against
the real widget. No test touches files outside ``tmp_path``, providers,
processes or terminals.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest
from textual.pilot import Pilot

from src.tui.app import SloTUI
from src.tui.components.workflow_progress.component import WorkflowProgress
from src.tui.components.workflow_progress.adapters.workflow_progress import (
    WorkflowProgressUpdatesAdapter,
)
from src.tui.widgets.sub_agent_fleet_panel import SubAgentFleetPanel
from src.tui.workflows.abort_confirmation_screen import AbortConfirmationScreen
from src.tui.workflows.dao import ChildAbortTargetDAO, WorkflowSessionSnapshotDAO
from src.tui.workflows.progress_coordinator import WorkflowProgressCoordinator, WorkflowProgressSink
from tests.tui.test_workflow_session_list import (
    _build_session,
    _coordinator,
    _populated_app,
    _refresh,
    _rows,
    _settle,
    _supplier,
)


class TestComponentCompositionAndBinding:
    """One wrapper owns the panel; one adapter per observation lifetime."""

    @pytest.mark.asyncio
    async def test_wrapper_owns_one_panel_and_empty_starts_hidden(self, tmp_path: Path) -> None:
        """The mounted wrapper composes exactly one fleet panel and starts hidden."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)

            wrapper: WorkflowProgress = app.query_one(WorkflowProgress)
            assert len(app.query(WorkflowProgress)) == 1
            assert len(app.query(SubAgentFleetPanel)) == 1
            assert len(wrapper.query(SubAgentFleetPanel)) == 1
            assert wrapper.display is False
            assert wrapper.has_visible_sessions() is False
            assert wrapper.sessions_hold_focus() is False

    @pytest.mark.asyncio
    async def test_bind_returns_fresh_sink_and_rejects_a_second_bind(self, tmp_path: Path) -> None:
        """Mount binds one adapter sink; a concurrent bind raises without mutation."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            wrapper: WorkflowProgress = app.query_one(WorkflowProgress)
            sink: WorkflowProgressSink = app._workflow_progress_updates_adapter  # type: ignore[assignment]
            assert isinstance(sink, WorkflowProgressUpdatesAdapter)

            with pytest.raises(RuntimeError):
                wrapper.bind_observation()

            assert wrapper._bound_sink is sink

    @pytest.mark.asyncio
    async def test_retire_releases_the_binding_and_a_new_observation_gets_a_new_sink(
        self, tmp_path: Path
    ) -> None:
        """Retiring the exact sink empties the panel and permits a distinct successor bind."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            wrapper: WorkflowProgress = app.query_one(WorkflowProgress)
            await _populated_app(app=app, pilot=pilot, children=2)
            sink: WorkflowProgressSink = app._workflow_progress_updates_adapter  # type: ignore[assignment]
            assert isinstance(sink, WorkflowProgressUpdatesAdapter)

            await wrapper.retire_observation(sink=sink)

            assert wrapper._bound_sink is None
            assert app.query_one(SubAgentFleetPanel).display is False
            successor: WorkflowProgressSink = wrapper.bind_observation()
            assert isinstance(successor, WorkflowProgressUpdatesAdapter)
            assert successor is not sink

    @pytest.mark.asyncio
    async def test_retire_ignores_a_stale_or_foreign_sink(self, tmp_path: Path) -> None:
        """A sink that is not the bound one retires nothing and clears no rows."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            wrapper: WorkflowProgress = app.query_one(WorkflowProgress)
            await _populated_app(app=app, pilot=pilot, children=2)
            bound: WorkflowProgressSink = app._workflow_progress_updates_adapter  # type: ignore[assignment]
            # The foreign sink comes from a second real component's public bind,
            # never from direct adapter construction outside the owning component.
            foreign_wrapper: WorkflowProgress = WorkflowProgress(host=app)
            foreign: WorkflowProgressSink = foreign_wrapper.bind_observation()

            await wrapper.retire_observation(sink=foreign)

            assert wrapper._bound_sink is bound
            assert set(_rows(app=app)) == {app._session.session_id, "child-00", "child-01"}

    @pytest.mark.asyncio
    async def test_retired_sink_paints_nothing_and_reopens_nothing(self, tmp_path: Path) -> None:
        """After retirement the old adapter drops every paint and open request."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            wrapper: WorkflowProgress = app.query_one(WorkflowProgress)
            await _populated_app(app=app, pilot=pilot, children=2)
            sink: WorkflowProgressSink = app._workflow_progress_updates_adapter  # type: ignore[assignment]
            assert isinstance(sink, WorkflowProgressUpdatesAdapter)
            service = app._workflow_app_service
            assert service is not None
            snapshot: WorkflowSessionSnapshotDAO = await service.load_session_snapshot()
            assert snapshot.rows

            await wrapper.retire_observation(sink=sink)
            assert _rows(app=app) == {}
            await sink.apply_sessions(snapshot=snapshot)

            assert _rows(app=app) == {}
            assert app.query_one(SubAgentFleetPanel).display is False


class TestConfirmationIdentityGate:
    """The adapter's callback gate (spec §5.3, A5): exact object, exact target, at most once."""

    def _captured_sink(self, *, app: SloTUI) -> WorkflowProgressUpdatesAdapter:
        """Return the mounted app's bound adapter, asserted as the real class."""
        sink: WorkflowProgressSink = app._workflow_progress_updates_adapter  # type: ignore[assignment]
        assert isinstance(sink, WorkflowProgressUpdatesAdapter)
        return sink

    async def _mounted_sink_with_open_view(
        self, *, app: SloTUI, pilot: Pilot[None]
    ) -> tuple[WorkflowProgressUpdatesAdapter, ChildAbortTargetDAO]:
        """Populate the list, open the child progress view, and return sink plus target."""
        await _populated_app(app=app, pilot=pilot, children=2)
        sink: WorkflowProgressUpdatesAdapter = self._captured_sink(app=app)
        key = next(key for key in sink._identities if not key.is_parent)
        _coordinator(app=app).select(key=key)
        await _settle(app=app, pilot=pilot)
        assert sink._screen is not None and sink._screen.is_live
        return sink, ChildAbortTargetDAO(
            key=key,
            run_id="7a0e6a54-2f43-4d5c-9b1e-0c6f4a3d2e10",
            execution_id="11111111-1111-4111-8111-111111111111",
        )

    def _record_submissions(self, *, app: SloTUI) -> tuple[list[ChildAbortTargetDAO], object]:
        """Patch the host's control entry to record every submitted target.

        Returns:
            tuple[list[ChildAbortTargetDAO], object]: The recording list and the patcher.
        """
        submissions: list[ChildAbortTargetDAO] = []
        real_child_abort_confirmed = SloTUI.child_abort_confirmed

        def recording_child_abort_confirmed(self: SloTUI, *, target: ChildAbortTargetDAO) -> None:
            submissions.append(target)
            real_child_abort_confirmed(self, target=target)

        return submissions, patch.object(SloTUI, "child_abort_confirmed", new=recording_child_abort_confirmed)

    @pytest.mark.asyncio
    async def test_confirmation_callback_identity_and_at_most_once(self, tmp_path: Path) -> None:
        """A repeated, stale or superseded callback never submits; each True submits once."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))
        submissions, patcher = self._record_submissions(app=app)

        with patcher:
            async with app.run_test(size=(120, 40)) as pilot:
                sink, target = await self._mounted_sink_with_open_view(app=app, pilot=pilot)

                # The real confirmation path submits exactly one host call for the captured target.
                sink.confirm_abort(target=target)
                await pilot.pause()
                first: AbortConfirmationScreen = sink._confirmation  # type: ignore[assignment]
                assert first is not None
                first_callback = first._result_callbacks[-1].callback
                assert first_callback is not None
                first.dismiss(result=True)
                await pilot.pause()
                assert submissions == [target]
                assert sink._confirmation is None

                # A repeated True from the consumed callback is absorbed; nothing is re-submitted.
                first_callback(True)
                assert submissions == [target]

                # A fresh confirmation opens; the old callback cannot act while it is stored.
                sink.confirm_abort(target=target)
                await pilot.pause()
                second: AbortConfirmationScreen = sink._confirmation  # type: ignore[assignment]
                assert second is not None and second is not first
                second_callback = second._result_callbacks[-1].callback
                assert second_callback is not None
                first_callback(True)
                assert submissions == [target]

                # The stored confirmation submits once for its own captured target.
                second.dismiss(result=True)
                await pilot.pause()
                assert submissions == [target, target]
                second_callback(True)
                assert submissions == [target, target]

                # Disposal retires the sink; every later callback is a no-op.
                sink.dispose()
                second_callback(True)
                first_callback(True)
                assert submissions == [target, target]

    @pytest.mark.asyncio
    async def test_confirmation_withdrawn_before_callback_submits_nothing(self, tmp_path: Path) -> None:
        """A callback arriving after ``_withdraw_confirmation`` submits no control request."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))
        submissions, patcher = self._record_submissions(app=app)

        with patcher:
            async with app.run_test(size=(120, 40)) as pilot:
                sink, target = await self._mounted_sink_with_open_view(app=app, pilot=pilot)

                sink.confirm_abort(target=target)
                await pilot.pause()
                confirmation: AbortConfirmationScreen = sink._confirmation  # type: ignore[assignment]
                assert confirmation is not None
                callback = confirmation._result_callbacks[-1].callback
                assert callback is not None

                sink._withdraw_confirmation()
                await pilot.pause()
                assert sink._confirmation is None
                callback(True)
                assert submissions == []

                # The withdrawn confirmation cannot act even when invoked with True later.
                callback(True)
                assert submissions == []


class TestComponentPresentationThroughTheApp:
    """The production refresh path paints through the moved adapter and wrapper."""

    @pytest.mark.asyncio
    async def test_rows_paint_and_emptying_returns_focus_through_the_component(self, tmp_path: Path) -> None:
        """Rows arrive through the real coordinator; emptying hides the wrapper."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            wrapper: WorkflowProgress = app.query_one(WorkflowProgress)
            await _populated_app(app=app, pilot=pilot, children=2)

            assert set(_rows(app=app)) == {app._session.session_id, "child-00", "child-01"}
            assert wrapper.display is True
            assert wrapper.has_visible_sessions() is True

            _supplier(app=app).snapshot = _supplier(app=app).snapshot.model_copy(update={"entries": ()})
            await _refresh(app=app, pilot=pilot)

            assert _rows(app=app) == {}
            assert wrapper.display is False
            # Zero-height layout proof: an empty wrapper consumes no vertical space.
            assert wrapper.region.height == 0
            assert app.focused is app._input


class TestCancellationReconciliation:
    """A cancelled apply waiter still leaves wrapper and panel consistent (EF-03, A6)."""

    @pytest.mark.asyncio
    async def test_cancelled_apply_reconciles_display_and_close_settles_successor(
        self, tmp_path: Path
    ) -> None:
        """Cancelling the sink's waiter keeps wrapper display truthful; close joins the panel work."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            wrapper: WorkflowProgress = app.query_one(WorkflowProgress)
            await _populated_app(app=app, pilot=pilot, children=2)
            sink: WorkflowProgressSink = app._workflow_progress_updates_adapter  # type: ignore[assignment]
            assert isinstance(sink, WorkflowProgressUpdatesAdapter)
            service = app._workflow_app_service
            assert service is not None
            snapshot: WorkflowSessionSnapshotDAO = await service.load_session_snapshot()
            assert snapshot.rows
            panel: SubAgentFleetPanel = app.query_one(SubAgentFleetPanel)

            # Gate the panel's row application so the wrapper's waiter can be
            # cancelled mid-apply; the shielded panel work continues regardless
            # and is joined by retirement's reset.
            apply_gate: asyncio.Event = asyncio.Event()
            apply_entered: asyncio.Event = asyncio.Event()
            real_apply_rows = panel._apply_rows

            async def gated_apply_rows(*, rows: object) -> None:
                apply_entered.set()
                await apply_gate.wait()
                await real_apply_rows(rows=rows)

            # Diverge the wrapper's display first: without the BaseException
            # reconciliation the cancelled waiter would leave this stale value
            # behind; with it, the wrapper tracks the panel's actual display.
            wrapper.display = False
            assert panel.display is True

            with patch.object(panel, "_apply_rows", new=gated_apply_rows):
                apply_task: asyncio.Task[None] = asyncio.create_task(sink.apply_sessions(snapshot=snapshot))
                await pilot.pause()
                apply_task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await apply_task

                # Cancellation reconciled the wrapper against the panel's actual
                # display before the CancelledError escaped.
                assert wrapper.display == panel.display is True

                # A fresh snapshot for a later successor proves late old delivery
                # cannot paint into a populated successor.
                successor_supplier = _supplier(app=app)
                successor_supplier.publish(children=1)
                successor_snapshot: WorkflowSessionSnapshotDAO = await service.load_session_snapshot()
                assert successor_snapshot.rows

                # Hold the accepted apply gate WHILE close starts: the panel's
                # shielded apply is accepted but unfinished, so the retirement
                # reset must wait on it and no successor bind may sneak in.
                successor_apply_gate: asyncio.Event = asyncio.Event()
                successor_apply_entered: asyncio.Event = asyncio.Event()
                successor_apply_task: Optional[asyncio.Task[None]] = None
                close_task: asyncio.Task[None] = asyncio.create_task(app._close_workflow_observation())
                try:
                    await pilot.pause()
                    assert not close_task.done()
                    # Binding stays reserved while the close joins the gated apply.
                    assert wrapper._bound_sink is sink
                    with pytest.raises(RuntimeError):
                        wrapper.bind_observation()
                    apply_gate.set()
                    await close_task
                finally:
                    if not close_task.done():
                        apply_gate.set()
                        await close_task

                assert _rows(app=app) == {}
                assert panel.display is False
                assert wrapper.display is False
                assert wrapper._bound_sink is None
                assert wrapper._retirement_task is None
                assert app.focused is app._input

                # The released binding admits a distinct successor.
                successor: WorkflowProgressSink = wrapper.bind_observation()
                assert isinstance(successor, WorkflowProgressUpdatesAdapter)
                assert successor is not sink
                assert successor._screen is None

                # Stale deferred delivery from the retired sink is inert against
                # the populated successor: only the successor's own paint lands.
                await sink.apply_sessions(snapshot=snapshot)
                assert _rows(app=app) == {}

                async def gated_successor_apply_rows(*, rows: object) -> None:
                    successor_apply_entered.set()
                    await successor_apply_gate.wait()
                    await real_apply_rows(rows=rows)

                with patch.object(panel, "_apply_rows", new=gated_successor_apply_rows):
                    successor_apply_task = asyncio.create_task(
                        successor.apply_sessions(snapshot=successor_snapshot)
                    )
                    try:
                        await asyncio.wait_for(successor_apply_entered.wait(), timeout=5)
                        # While the successor's accepted apply is pending, the
                        # retired sink still cannot paint and the binding is
                        # reserved exactly once.
                        await sink.apply_sessions(snapshot=snapshot)
                        assert _rows(app=app) == {}
                        with pytest.raises(RuntimeError):
                            wrapper.bind_observation()
                        successor_apply_gate.set()
                        await successor_apply_task
                    finally:
                        if successor_apply_task is not None and not successor_apply_task.done():
                            successor_apply_gate.set()
                            await successor_apply_task
                assert set(_rows(app=app)) == {app._session.session_id, "child-00"}


class TestBindStartupFailures:
    """Factory/start failures propagate the original error and retire the partial owner (EF-06, A9).

    Each case names the injected failure, asserts the exact initiating
    exception identity, the absence of a published observation session ID and
    surviving coordinator work, and the fixed acquisition order: service →
    sink → coordinator → start.
    """

    @pytest.mark.asyncio
    async def test_factory_failure_preserves_identity_and_retires_acquired_owner(
        self, tmp_path: Path
    ) -> None:
        """The exact factory error propagates; service, sink and coordinator refs retire once."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            wrapper: WorkflowProgress = app.query_one(WorkflowProgress)
            events: list[str] = []
            recording: list[bool] = [False]
            real_dispose = WorkflowProgressUpdatesAdapter.dispose
            real_close = WorkflowProgressCoordinator.close

            def recorded_dispose(self: WorkflowProgressUpdatesAdapter) -> None:
                if recording[0]:
                    events.append("sink-dispose")
                real_dispose(self)

            async def recorded_close(self: WorkflowProgressCoordinator) -> None:
                if recording[0]:
                    events.append("coordinator-close")
                await real_close(self)

            factory_error: ValueError = ValueError("factory boom")

            def failing_factory(*, service, sink, schedule):  # type: ignore[no-untyped-def]
                raise factory_error

            app._workflow_coordinator_factory = failing_factory  # type: ignore[assignment]
            with (
                patch.object(WorkflowProgressUpdatesAdapter, "dispose", new=recorded_dispose),
                patch.object(WorkflowProgressCoordinator, "close", new=recorded_close),
                pytest.raises(ValueError) as caught,
            ):
                recording[0] = True
                await app._bind_workflow_observation()

            assert caught.value is factory_error
            # Fixed acquisition/cleanup order for the failed bind: the previous
            # owner's coordinator closes, its sink retires, then the newly
            # acquired sink retires; the factory raised before any new
            # coordinator existed, so no second coordinator-close is recorded.
            assert events == ["coordinator-close", "sink-dispose", "sink-dispose"]
            assert app._workflow_progress_coordinator is None
            assert app._workflow_app_service is None
            assert app._workflow_progress_updates_adapter is None
            assert app._workflow_observation_session_id is None
            assert app._workflow_observation_close_task is not None
            assert wrapper._bound_sink is None
            assert _rows(app=app) == {}

    @pytest.mark.asyncio
    async def test_partial_start_failure_joins_acquired_work_and_preserves_identity(
        self, tmp_path: Path
    ) -> None:
        """A start that raises after acquiring the timer propagates; the started coordinator closes."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            wrapper: WorkflowProgress = app.query_one(WorkflowProgress)
            events: list[str] = []
            recording: list[bool] = [False]
            real_close = WorkflowProgressCoordinator.close
            real_dispose = WorkflowProgressUpdatesAdapter.dispose

            async def recorded_close(self: WorkflowProgressCoordinator) -> None:
                if recording[0]:
                    events.append("coordinator-close")
                await real_close(self)

            def recorded_dispose(self: WorkflowProgressUpdatesAdapter) -> None:
                if recording[0]:
                    events.append("sink-dispose")
                real_dispose(self)

            real_factory = app._workflow_coordinator_factory
            start_error: RuntimeError = RuntimeError("start boom")
            started_coordinators: list[WorkflowProgressCoordinator] = []

            def partial_start_factory(*, service, sink, schedule):  # type: ignore[no-untyped-def]
                coordinator = real_factory(service=service, sink=sink, schedule=schedule)
                started_coordinators.append(coordinator)

                def partial_start() -> None:
                    # The timer was acquired (registered on the app) before the
                    # failure: cleanup must stop it, not leave a live reader.
                    coordinator._timer = app._schedule_workflow_refresh(5.0, coordinator.request_refresh)
                    raise start_error

                coordinator.start = partial_start  # type: ignore[method-assign]
                return coordinator

            app._workflow_coordinator_factory = partial_start_factory  # type: ignore[assignment]
            with (
                patch.object(WorkflowProgressCoordinator, "close", new=recorded_close),
                patch.object(WorkflowProgressUpdatesAdapter, "dispose", new=recorded_dispose),
                pytest.raises(RuntimeError) as caught,
            ):
                recording[0] = True
                await app._bind_workflow_observation()

            assert caught.value is start_error
            # Fixed order: the previous owner's coordinator closes and its sink
            # retires, then the partially started coordinator closes and the
            # acquired sink retires, exactly once.
            assert events == ["coordinator-close", "sink-dispose", "coordinator-close", "sink-dispose"]
            assert len(started_coordinators) == 1
            assert started_coordinators[0]._closed is True
            assert started_coordinators[0]._timer is None
            assert started_coordinators[0]._task is None
            assert app._workflow_progress_coordinator is None
            assert app._workflow_observation_session_id is None
            assert app._workflow_observation_close_task is not None
            assert wrapper._bound_sink is None
            assert _rows(app=app) == {}

    @pytest.mark.asyncio
    async def test_cleanup_failure_is_reported_and_chained_behind_the_startup_error(
        self, tmp_path: Path
    ) -> None:
        """A failing close reports the lifecycle diagnostic and chains, never replacing the error."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            wrapper: WorkflowProgress = app.query_one(WorkflowProgress)
            factory_error: ValueError = ValueError("factory boom")
            cleanup_error: RuntimeError = RuntimeError("cleanup boom")
            real_dispose = SloTUI._dispose_workflow_observation
            invoked: list[bool] = []

            def failing_factory(*, service, sink, schedule):  # type: ignore[no-untyped-def]
                raise factory_error

            async def failing_dispose(self: SloTUI) -> None:
                if invoked:
                    raise cleanup_error
                invoked.append(True)
                await real_dispose(self)

            app._workflow_coordinator_factory = failing_factory  # type: ignore[assignment]
            with (
                patch.object(SloTUI, "_dispose_workflow_observation", new=failing_dispose),
                patch.object(
                    app._chat_transcript,
                    "write_transcript_line",
                    wraps=app._chat_transcript.write_transcript_line,
                ) as notice,
                pytest.raises(ValueError) as caught,
            ):
                await app._bind_workflow_observation()
            # The initiating factory error is primary; the cleanup failure is its
            # chained context, reported through the fixed lifecycle diagnostic.
            assert caught.value is factory_error
            assert caught.value.__context__ is cleanup_error
            notice.assert_called_with(content="Session cleanup incomplete.", classes="tool-result")
            # The failed close task stays published and permanently blocks reuse:
            # a completed failed task is re-raised, never retried.
            assert app._workflow_observation_close_task is not None
            assert app._workflow_observation_close_task.done()
            with pytest.raises(RuntimeError) as rebound:
                await app._close_workflow_observation()
            assert rebound.value is cleanup_error
            # The failed cleanup never cleared the bound sink, so the component
            # still reserves its binding against any rebind attempt.
            assert wrapper._bound_sink is not None
            with pytest.raises(RuntimeError):
                wrapper.bind_observation()
            # Clear the failed close task so run_test teardown can complete its
            # own observation close without re-raising the injected fault.
            app._workflow_observation_close_task = None


class TestComponentStylesAndSizeLimits:
    """Component CSS scoping: wrapper display follows the panel; no styling leak (EF-04, A8)."""

    @pytest.mark.asyncio
    async def test_unrelated_row_outside_wrapper_is_not_styled_by_fleet_rules(self, tmp_path: Path) -> None:
        """A fleet-shaped row outside WorkflowProgress does not receive wrapper-scoped rules."""
        from textual.containers import Vertical
        from textual.widgets import Static
        from src.tui.widgets.sub_agent_fleet_row import SubAgentFleetRow
        from src.tui.workflows.dao import WorkflowSessionKeyDAO, WorkflowSessionRowDAO

        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        class OutsideHost(Vertical):
            """An unrelated container that mounts a fleet-shaped row outside the wrapper."""

            def compose(self):
                key = WorkflowSessionKeyDAO(
                    orchestrator_session_id="outside",
                    session_id="outside-child",
                    attached_dispatch_id="0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d",
                )
                row_dao = WorkflowSessionRowDAO(
                    key=key,
                    task_id="outside-task",
                    status="running",
                    task_text="outside",
                    task_text_complete=True,
                    role="child",
                )
                yield SubAgentFleetRow(row=row_dao)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            wrapper: WorkflowProgress = app.query_one(WorkflowProgress)
            outside_host = OutsideHost()
            await app.mount(outside_host)
            await pilot.pause()
            outside_row = outside_host.query_one(SubAgentFleetRow)
            # The wrapper-scoped row rule `WorkflowProgress SubAgentFleetRow` must
            # not match this row: it has no WorkflowProgress ancestor.
            assert wrapper not in outside_row.ancestors
            # The wrapper's own panel remains the only fleet panel inside it.
            assert len(wrapper.query(SubAgentFleetRow)) == 0
            # Computed-style proof: the wrapper-scoped rule
            # `WorkflowProgress SubAgentFleetRow { height: 1; }` does not apply
            # to the outside row, whose height stays at the default auto.
            assert outside_row.styles.height != 1
            # The wrapper-scoped row Static rule
            # `WorkflowProgress SubAgentFleetRow > Static { padding: 0 1; }`
            # does not apply to the outside row's Static child either.
            outside_static = outside_row.query_one(Static)
            assert outside_static.styles.padding == (0, 0, 0, 0)


class TestRunAsyncShutdownIntegration:
    """The production runner (run_async) dispatches the same subclass _shutdown seam (EF-02)."""

    @pytest.mark.asyncio
    async def test_run_async_exit_joins_observation_before_superclass_pruning(self, tmp_path: Path) -> None:
        """Headless run_async exit retires observation before framework pruning; no false success."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))
        events: list[str] = []
        real_dispose = WorkflowProgressUpdatesAdapter.dispose
        real_close = WorkflowProgressCoordinator.close

        def recorded_dispose(self: WorkflowProgressUpdatesAdapter) -> None:
            events.append("sink-dispose")
            real_dispose(self)

        async def recorded_close(self: WorkflowProgressCoordinator) -> None:
            events.append("coordinator-close")
            await real_close(self)

        async def autopilot(pilot) -> None:  # type: ignore[no-untyped-def]
            await pilot.pause()
            await _populated_app(app=app, pilot=pilot, children=2)
            await pilot.pause()
            assert app._workflow_progress_updates_adapter is not None
            app.exit()

        with (
            patch.object(WorkflowProgressUpdatesAdapter, "dispose", new=recorded_dispose),
            patch.object(WorkflowProgressCoordinator, "close", new=recorded_close),
        ):
            await app.run_async(headless=True, size=(120, 40), auto_pilot=autopilot)

        # The real subclass _shutdown seam joined the observation close (coordinator
        # then sink) before superclass pruning; the published trio is absent.
        assert events == ["coordinator-close", "sink-dispose"]
        assert app._workflow_progress_updates_adapter is None
        assert app._workflow_progress_coordinator is None
        assert app._workflow_app_service is None
        assert app._workflow_observation_session_id is None


class TestClosedWidgetRejection:
    """A closed (unmounted) widget never binds again (EF-07, A10)."""

    @pytest.mark.asyncio
    async def test_closed_widget_rejects_binding(self, tmp_path: Path) -> None:
        """Removing the component sets the closed flag and blocks any later bind."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            wrapper: WorkflowProgress = app.query_one(WorkflowProgress)
            # Component-only removal triggers the safety cutoff and closes it.
            await wrapper.remove()
            await pilot.pause()
            assert wrapper._closed is True
            with pytest.raises(RuntimeError):
                wrapper.bind_observation()
