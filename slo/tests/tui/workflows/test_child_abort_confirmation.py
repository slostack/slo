"""Child-abort confirmation and service-owned submission tracking (feature 94 a.4, ticket T11).

Categories: mounted TUI (``App.run_test``) for the confirmation screen's paint,
focus and result; orchestration unit for the service's authority checks,
submission lifetime and receipt/terminal observation, using a recording attached
facade, Events and an injected monotonic clock; adapter integration through a
real ``ChildAbortStore`` below ``tmp_path`` for the detached branch. No test
signals a process, runs a provider or opens a terminal.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Optional
from unittest.mock import patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from src.agents.slo_agent.history.atomic_io import AtomicFileWriter, AtomicWriteOutcomeDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.child_abort import ChildAbortStore
from src.agents.slo_agent.orchestrator.context_dao import SpawnContextDAO, dump_json_bytes
from src.agents.slo_agent.orchestrator.dao import (
    AttachedDispatchSnapshotDAO,
    ChildAbortOutcome,
    ChildAbortOutcomeDAO,
    ChildAbortRequestDAO,
    ChildControlCapabilityDAO,
    ChildExecutionEvidenceDAO,
    StdoutCaptureIdentityDAO,
    SubAgentResultDAO,
    SubAgentStatusDAO,
)
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleDAO, WorkflowHandleStore
from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME
from src.tui.workflow_visualizer_loader import WorkflowVisualizerLoader
from src.tui.workflows.abort_confirmation_screen import AbortConfirmationScreen
from src.tui.workflows.abort_submission import (
    ABORT_NOT_CONFIRMED_NOTICE,
    ABORT_SUBMITTING_NOTICE,
    ChildAbortSubmission,
)
from src.tui.workflows.dao import (
    ChildAbortTargetDAO,
    SessionProgressSnapshotDAO,
    WorkflowSessionKeyDAO,
    WorkflowSessionRowDAO,
)
from src.tui.workflows.service import DetachedWorkflowAppService

_OWNER: str = "owner-1"
_ORCH_A: str = "orch-a"
_RUN: str = "7a8b9c0d-1e2f-4a3b-8c4d-5e6f7a8b9c0d"
_RUN_OLD: str = "9c0d1e2f-3a4b-4c5d-8e6f-7a8b9c0d1e2f"
_EXEC_A: str = "5e6f7a8b-9c0d-4e1f-a2b3-c4d5e6f7a8b9"
_EXEC_B: str = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
_DISPATCH: str = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"


def _target(
    *,
    orchestrator_session_id: str = _ORCH_A,
    session_id: str = "child-a",
    run_id: str = _RUN,
    execution_id: str = _EXEC_A,
) -> ChildAbortTargetDAO:
    """Build one captured confirmation target.

    Args:
        orchestrator_session_id (str, optional): Parent. Defaults to ``_ORCH_A``.
        session_id (str, optional): Child. Defaults to ``"child-a"``.
        run_id (str, optional): Run. Defaults to ``_RUN``.
        execution_id (str, optional): Incarnation. Defaults to ``_EXEC_A``.

    Returns:
        ChildAbortTargetDAO: Target.
    """
    return ChildAbortTargetDAO(
        key=WorkflowSessionKeyDAO(orchestrator_session_id=orchestrator_session_id, session_id=session_id),
        run_id=run_id,
        execution_id=execution_id,
    )


class _ConfirmationHost(App[None]):
    """Push one confirmation and record every result its callback receives."""

    def __init__(self, *, target: ChildAbortTargetDAO) -> None:
        """Bind the target to confirm.

        Args:
            target (ChildAbortTargetDAO): Captured target.
        """
        super().__init__()
        self.target: ChildAbortTargetDAO = target
        self.results: list[Optional[bool]] = []
        self.confirmation: Optional[AbortConfirmationScreen] = None

    def compose(self) -> ComposeResult:
        """Yield a base widget under the modal."""
        yield Static(content="base")

    def on_mount(self) -> None:
        """Push the confirmation with a recording callback."""
        self.confirmation = AbortConfirmationScreen(target=self.target)
        self.push_screen(screen=self.confirmation, callback=self.results.append)


class TestAbortConfirmationScreen:
    """The modal names the exact child, defaults to safety and returns only a bool."""

    async def test_shows_literal_identities_and_consequence(self) -> None:
        """Parent and child IDs are painted literally, with the scope sentence."""
        app = _ConfirmationHost(target=_target(session_id="child-[b]a[/b]"))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            texts: list[str] = [str(static.render()) for static in app.screen.query(Static)]

            assert "Abort this sub-agent?" in texts
            assert _ORCH_A in texts
            assert "child-[b]a[/b]" in texts
            assert any("Stops only this child" in text for text in texts)

    async def test_keep_running_has_default_focus(self) -> None:
        """The safe choice is focused when the confirmation appears."""
        app = _ConfirmationHost(target=_target())
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()

            assert app.focused is app.screen.query_one("#keep-running", Button)

    @pytest.mark.parametrize(
        ("action", "expected"),
        [("escape", False), ("keep", False), ("enter-default", False), ("confirm", True)],
    )
    async def test_result_is_true_only_for_explicit_abort(self, action: str, expected: bool) -> None:
        """Escape, Keep running and Enter on the default return False; only Abort child returns True."""
        app = _ConfirmationHost(target=_target())
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            if action == "escape":
                await pilot.press("escape")
            elif action == "keep":
                await pilot.click("#keep-running")
            elif action == "enter-default":
                await pilot.press("enter")
            else:
                await pilot.click("#confirm-abort")
            await pilot.pause()

            assert app.results == [expected]
            assert not isinstance(app.screen, AbortConfirmationScreen)

    async def test_double_activation_returns_one_result(self) -> None:
        """Two queued activations of Abort child dismiss once and report one True."""
        app = _ConfirmationHost(target=_target())
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            confirm: Button = app.screen.query_one("#confirm-abort", Button)
            confirm.press()
            confirm.press()
            await pilot.pause()
            await pilot.pause()

            assert app.results == [True]

    async def test_withdraw_closes_with_false_without_popping_other_screens(self) -> None:
        """Withdrawal answers False once; when covered it waits until it is on top again."""
        app = _ConfirmationHost(target=_target())
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            confirmation: Optional[AbortConfirmationScreen] = app.confirmation
            assert confirmation is not None
            other: AbortConfirmationScreen = AbortConfirmationScreen(target=_target(session_id="other"))
            app.push_screen(screen=other)
            await pilot.pause()

            confirmation.withdraw()
            await pilot.pause()
            assert app.screen is other
            assert app.results == []

            other.withdraw()
            await pilot.pause()
            await pilot.pause()
            assert app.results == [False]
            assert not isinstance(app.screen, AbortConfirmationScreen)

    @pytest.mark.parametrize("size", [(60, 20), (80, 24), (120, 40)])
    @pytest.mark.parametrize("theme", [SLO_DEFAULT_THEME.name, SLO_DARK_THEME.name])
    async def test_buttons_reachable_at_every_size_and_theme(self, size: tuple[int, int], theme: str) -> None:
        """Both buttons are painted inside the terminal at 60x20, 80x24 and 120x40 in both themes."""
        app = _ConfirmationHost(target=_target())
        async with app.run_test(size=size) as pilot:
            app.register_theme(SLO_DEFAULT_THEME)
            app.register_theme(SLO_DARK_THEME)
            app.theme = theme
            await pilot.pause()
            width, height = size
            for selector in ("#keep-running", "#confirm-abort"):
                region = app.screen.query_one(selector, Button).region
                assert region.width > 0 and region.height > 0
                assert region.right <= width and region.bottom <= height


_REQUEST_ID: str = "4d5e6f70-8192-4a3b-8c4d-5e6f708192a3"


def _request(*, target: ChildAbortTargetDAO, request_id: str = _REQUEST_ID) -> ChildAbortRequestDAO:
    """Build the request the service would allocate for ``target``.

    Args:
        target (ChildAbortTargetDAO): Confirmed target.
        request_id (str, optional): Request UUID. Defaults to ``_REQUEST_ID``.

    Returns:
        ChildAbortRequestDAO: Request.
    """
    return ChildAbortRequestDAO(
        request_id=request_id,
        owner_session_id=_OWNER,
        orchestrator_session_id=target.key.orchestrator_session_id,
        session_id=target.key.session_id,
        run_id=target.run_id,
        execution_id=target.execution_id,
    )


def _outcome(*, request: ChildAbortRequestDAO, outcome: ChildAbortOutcome) -> ChildAbortOutcomeDAO:
    """Build the fixed-message outcome for ``request``.

    Args:
        request (ChildAbortRequestDAO): Request.
        outcome (ChildAbortOutcome): Literal.

    Returns:
        ChildAbortOutcomeDAO: Outcome.
    """
    return ChildAbortOutcomeDAO.for_request(request=request, outcome=outcome)


def _row(
    *, target: ChildAbortTargetDAO, status: str, execution_id: Optional[str] = None
) -> WorkflowSessionRowDAO:
    """Build the list row observed for the target's key.

    Args:
        target (ChildAbortTargetDAO): Target whose key the row carries.
        status (str): Row status.
        execution_id (Optional[str], optional): Incarnation; the target's when None.

    Returns:
        WorkflowSessionRowDAO: Row.
    """
    return WorkflowSessionRowDAO(
        key=target.key,
        role="child",
        execution_id=execution_id or target.execution_id,
        dispatch_id=_DISPATCH,
        status=status,
        task_text="task",
        task_text_complete=False,
    )


class _Submission:
    """Build one tracked submission over a controllable future."""

    def __init__(self, *, attached: bool = False) -> None:
        """Create the target, request and pending operation.

        Args:
            attached (bool, optional): Attached branch. Defaults to False (detached).
        """
        self.target: ChildAbortTargetDAO = _target()
        self.request: ChildAbortRequestDAO = _request(target=self.target)
        self.result: asyncio.Future[ChildAbortOutcomeDAO] = asyncio.get_running_loop().create_future()
        self.task: asyncio.Task[ChildAbortOutcomeDAO] = asyncio.ensure_future(self._wait())
        self.submission: ChildAbortSubmission = ChildAbortSubmission(
            target=self.target, request=self.request, operation=self.task, started_at=100.0, attached=attached
        )

    async def _wait(self) -> ChildAbortOutcomeDAO:
        """Return the controlled result.

        Returns:
            ChildAbortOutcomeDAO: Result.
        """
        return await self.result

    async def settle(self, *, outcome: ChildAbortOutcome) -> None:
        """Finish the operation with ``outcome`` and let the task complete.

        Args:
            outcome (ChildAbortOutcome): Operation result.
        """
        self.result.set_result(_outcome(request=self.request, outcome=outcome))
        await self.task


class TestChildAbortSubmission:
    """One tracked request: truthful notice, settlement precedence, no retry while pending."""

    async def test_pending_notices_never_claim_abort(self) -> None:
        """Before admission: submitting (detached) or requested (attached); never aborted."""
        detached = _Submission()
        attached = _Submission(attached=True)

        assert detached.submission.notice(now=101.0) == ABORT_SUBMITTING_NOTICE
        assert (
            attached.submission.notice(now=101.0)
            == _outcome(request=attached.request, outcome="requested").safe_message
        )
        assert detached.submission.blocks_new_request and attached.submission.blocks_new_request
        detached.result.cancel()
        attached.result.cancel()
        await asyncio.gather(detached.task, attached.task, return_exceptions=True)

    async def test_requested_waits_for_receipt_then_settles(self) -> None:
        """A durable admission keeps blocking and awaits a receipt; the receipt settles it."""
        tracked = _Submission()
        await tracked.settle(outcome="requested")

        assert tracked.submission.awaits_receipt is True
        assert tracked.submission.blocks_new_request is True
        assert tracked.submission.notice(now=101.0).startswith("Abort requested")

        tracked.submission.observe_receipt(receipt=None)
        assert tracked.submission.awaits_receipt is True
        tracked.submission.observe_receipt(receipt=_outcome(request=tracked.request, outcome="aborted"))

        assert tracked.submission.awaits_receipt is False
        assert tracked.submission.blocks_new_request is False
        assert tracked.submission.notice(now=101.0) == "Child aborted."

    async def test_thirty_seconds_without_receipt_changes_notice_only(self) -> None:
        """At 30 s of fake monotonic time the notice changes; request and waiting stay."""
        tracked = _Submission()
        await tracked.settle(outcome="requested")

        assert tracked.submission.notice(now=129.9).startswith("Abort requested")
        assert tracked.submission.notice(now=130.0) == ABORT_NOT_CONFIRMED_NOTICE
        assert tracked.submission.awaits_receipt is True
        assert tracked.submission.request.request_id == _REQUEST_ID

    async def test_terminal_truth_wins_over_receipt_and_operation(self) -> None:
        """A terminal row settles without a receipt and overrides an earlier unresolved receipt."""
        tracked = _Submission()
        await tracked.settle(outcome="requested")
        tracked.submission.observe_receipt(receipt=_outcome(request=tracked.request, outcome="unresolved"))

        tracked.submission.observe_row(row=_row(target=tracked.target, status="aborted"))

        assert tracked.submission.notice(now=200.0) == "Child aborted."
        assert tracked.submission.awaits_receipt is False

    async def test_natural_completion_reports_nothing_aborted(self) -> None:
        """A completed row settles as already terminal, never as aborted."""
        tracked = _Submission()
        await tracked.settle(outcome="requested")

        tracked.submission.observe_row(row=_row(target=tracked.target, status="completed"))

        assert tracked.submission.notice(now=101.0) == "Child already finished; nothing was aborted."

    async def test_running_or_other_incarnation_rows_do_not_settle(self) -> None:
        """Only a terminal row of the same incarnation settles the request."""
        tracked = _Submission()
        await tracked.settle(outcome="requested")

        tracked.submission.observe_row(row=_row(target=tracked.target, status="running"))
        tracked.submission.observe_row(
            row=_row(target=tracked.target, status="aborted", execution_id=_EXEC_B)
        )

        assert tracked.submission.awaits_receipt is True
        assert tracked.submission.concerns(row=_row(target=tracked.target, status="running")) is True
        assert (
            tracked.submission.concerns(
                row=_row(target=tracked.target, status="running", execution_id=_EXEC_B)
            )
            is False
        )

    @pytest.mark.parametrize(
        "outcome", ["aborted", "unavailable", "not_owned", "unresolved", "already_terminal"]
    )
    async def test_settling_operation_result_is_final(self, outcome: ChildAbortOutcome) -> None:
        """A non-admission operation result settles at once with its fixed message."""
        tracked = _Submission(attached=True)
        await tracked.settle(outcome=outcome)

        assert tracked.submission.awaits_receipt is False
        assert tracked.submission.blocks_new_request is False
        assert (
            tracked.submission.notice(now=500.0)
            == _outcome(request=tracked.request, outcome=outcome).safe_message
        )

    async def test_cancelled_operation_is_unresolved(self) -> None:
        """A cancelled operation is reported as unresolved, never aborted."""
        tracked = _Submission(attached=True)
        tracked.result.cancel()
        await asyncio.gather(tracked.task, return_exceptions=True)

        assert (
            tracked.submission.notice(now=101.0)
            == _outcome(request=tracked.request, outcome="unresolved").safe_message
        )

    async def test_join_awaits_without_cancelling(self) -> None:
        """Joining waits for the operation to finish on its own and retrieves its result."""
        tracked = _Submission()
        joining: asyncio.Task[None] = asyncio.ensure_future(tracked.submission.join())
        await asyncio.sleep(0)
        assert not joining.done()

        tracked.result.set_result(_outcome(request=tracked.request, outcome="requested"))
        await joining

        assert not tracked.task.cancelled()

    async def test_cancelled_join_never_cancels_the_operation(self) -> None:
        """Cancelling the joiner (e.g. a cancelled close) leaves the possibly committing write running."""
        tracked = _Submission()
        joining: asyncio.Task[None] = asyncio.ensure_future(tracked.submission.join())
        await asyncio.sleep(0)

        joining.cancel()
        await asyncio.gather(joining, return_exceptions=True)

        assert joining.cancelled()
        assert not tracked.task.done()
        await tracked.settle(outcome="aborted")
        assert not tracked.task.cancelled()

    async def test_terminal_row_does_not_release_a_running_operation(self) -> None:
        """Terminal list truth settles the notice, but a still-running operation keeps blocking."""
        tracked = _Submission(attached=True)
        tracked.submission.observe_row(row=_row(target=tracked.target, status="aborted"))

        assert tracked.submission.notice(now=101.0) == "Child aborted."
        assert tracked.submission.blocks_new_request is True

        await tracked.settle(outcome="aborted")
        assert tracked.submission.blocks_new_request is False


# ---------------------------------------------------------------------------
# Service: eligibility, authority, submission lifetime
# ---------------------------------------------------------------------------


class _AttachedAbort:
    """Recording attached facade (the session → pool seam); optionally gated or failing."""

    def __init__(self, *, outcome: ChildAbortOutcome = "aborted", error: Optional[Exception] = None) -> None:
        """Seed the facade's behaviour.

        Args:
            outcome (ChildAbortOutcome, optional): Returned outcome. Defaults to ``"aborted"``.
            error (Optional[Exception], optional): Raised instead when set.
        """
        self.outcome: ChildAbortOutcome = outcome
        self.error: Optional[Exception] = error
        self.calls: list[ChildAbortRequestDAO] = []
        self.gate: asyncio.Event = asyncio.Event()
        self.gate.set()
        self.entered: asyncio.Event = asyncio.Event()

    async def __call__(self, *, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        """Record the request, wait at the gate, then answer.

        Args:
            request (ChildAbortRequestDAO): Submitted request.

        Returns:
            ChildAbortOutcomeDAO: Seeded outcome.
        """
        self.calls.append(request)
        self.entered.set()
        await self.gate.wait()
        if self.error is not None:
            raise self.error
        return ChildAbortOutcomeDAO.for_request(request=request, outcome=self.outcome)


class _Clock:
    """Injected monotonic clock advanced explicitly by tests."""

    def __init__(self) -> None:
        """Start at a fixed time."""
        self.now: float = 1000.0

    def __call__(self) -> float:
        """Return the current fake monotonic time.

        Returns:
            float: Seconds.
        """
        return self.now


def _capability(
    *,
    run_id: str = _RUN,
    owner_session_id: str = _OWNER,
    orchestrator_session_id: str = _OWNER,
    accepting: bool = True,
) -> ChildControlCapabilityDAO:
    """Build one child-control capability.

    Args:
        run_id (str, optional): Run. Defaults to ``_RUN``.
        owner_session_id (str, optional): Owner. Defaults to ``_OWNER``.
        orchestrator_session_id (str, optional): Parent. Defaults to ``_OWNER`` (attached).
        accepting (bool, optional): Accepting flag. Defaults to True.

    Returns:
        ChildControlCapabilityDAO: Capability.
    """
    return ChildControlCapabilityDAO(
        run_id=run_id,
        owner_session_id=owner_session_id,
        orchestrator_session_id=orchestrator_session_id,
        accepting=accepting,
    )


class _Attached:
    """Attached-session world: registry batch, capability and recording facade."""

    def __init__(self, *, root: Optional[Path] = None) -> None:
        """Build a service owned by ``_OWNER`` with one running attached child.

        Args:
            root (Optional[Path], optional): History root; None is the no-history session.
        """
        self.status: str = "running"
        self.execution_id: str = _EXEC_A
        self.capability: Optional[ChildControlCapabilityDAO] = _capability()
        self.abort: _AttachedAbort = _AttachedAbort()
        self.clock: _Clock = _Clock()
        self.service: DetachedWorkflowAppService = DetachedWorkflowAppService(
            workflow_handle_store=None,
            owner_session_id=_OWNER,
            attached_snapshot=self._snapshot,
            history_store=None if root is None else FilesystemSessionHistoryStore(root=root),
            attached_abort=self.abort,
            attached_capability=lambda: self.capability,
            monotonic=self.clock,
        )
        self.key: WorkflowSessionKeyDAO = WorkflowSessionKeyDAO(
            orchestrator_session_id=_OWNER, session_id="child-1"
        )

    def _snapshot(self) -> AttachedDispatchSnapshotDAO:
        """Return the current registry batch.

        Returns:
            AttachedDispatchSnapshotDAO: One child.
        """
        return AttachedDispatchSnapshotDAO(
            dispatch_id=_DISPATCH,
            dispatch_sequence=1,
            entries=(
                SubAgentStatusDAO(
                    task_id="task-1",
                    session_id="child-1",
                    status=self.status,  # type: ignore[arg-type]
                    execution_id=self.execution_id,
                    prompt_preview="preview",
                ),
            ),
        )

    def target(self, *, run_id: str = _RUN, execution_id: str = _EXEC_A) -> ChildAbortTargetDAO:
        """Build a target for the attached child.

        Args:
            run_id (str, optional): Run. Defaults to ``_RUN``.
            execution_id (str, optional): Incarnation. Defaults to ``_EXEC_A``.

        Returns:
            ChildAbortTargetDAO: Target.
        """
        return ChildAbortTargetDAO(key=self.key, run_id=run_id, execution_id=execution_id)

    async def progress(self) -> SessionProgressSnapshotDAO:
        """Refresh the list, then read the child's progress.

        Returns:
            SessionProgressSnapshotDAO: Progress with abort control.
        """
        await self.service.load_session_snapshot()
        return await self.service.load_session_progress(key=self.key)


_DETACHED_CHILD: str = "child-a"


class _Detached:
    """Detached world over real temp files: handle, fleet, evidence and capability."""

    def __init__(self, *, root: Path) -> None:
        """Create the root and bind the stores.

        Args:
            root (Path): History root below the test's tmp_path.
        """
        root.mkdir(parents=True, exist_ok=True)
        self.root: Path = root
        self.alive: bool = True
        self.handles: WorkflowHandleStore = WorkflowHandleStore(
            history_root=root, pid_alive=lambda pid: self.alive
        )
        self.control: ChildAbortStore = ChildAbortStore(history_root=root, orchestrator_session_id=_ORCH_A)
        self.abort: _AttachedAbort = _AttachedAbort()
        self.clock: _Clock = _Clock()
        self.service: DetachedWorkflowAppService = DetachedWorkflowAppService(
            workflow_handle_store=self.handles,
            owner_session_id=_OWNER,
            attached_snapshot=AttachedDispatchSnapshotDAO.empty,
            history_store=FilesystemSessionHistoryStore(root=root),
            attached_abort=self.abort,
            attached_capability=lambda: None,
            monotonic=self.clock,
        )
        self.key: WorkflowSessionKeyDAO = WorkflowSessionKeyDAO(
            orchestrator_session_id=_ORCH_A, session_id=_DETACHED_CHILD
        )

    async def seed(
        self,
        *,
        status: str = "running",
        execution_id: str = _EXEC_A,
        capability: Optional[ChildControlCapabilityDAO] = None,
        handle_state: str = "running",
    ) -> None:
        """Write the owned handle, the run-bound fleet, running evidence and the capability.

        Args:
            status (str, optional): Child fleet status. Defaults to ``"running"``.
            execution_id (str, optional): Incarnation. Defaults to ``_EXEC_A``.
            capability (Optional[ChildControlCapabilityDAO], optional): Capability to
                publish; the accepting detached one when None.
            handle_state (str, optional): Handle state. Defaults to ``"running"``.
        """
        await self.handles.write(
            handle=WorkflowHandleDAO(
                workflow_id="wf-a",
                owner_session_id=_OWNER,
                orchestrator_session_id=_ORCH_A,
                pid=4242,
                brief="brief",
                cwd="/repo",
                state=handle_state,  # type: ignore[arg-type]
            )
        )
        self.child(status=status, execution_id=execution_id)
        await self.control.write_capability(
            capability=capability or _capability(orchestrator_session_id=_ORCH_A)
        )

    def child(self, *, status: str, execution_id: str = _EXEC_A) -> None:
        """Publish the child's files exactly where the wrapper would write them.

        A ``pending`` child has only pending evidence and its fleet row (it has
        not started, so no spawn context or capture exists yet).

        Args:
            status (str): Fleet status.
            execution_id (str, optional): Incarnation. Defaults to ``_EXEC_A``.
        """
        if status == "pending":
            self._publish(
                status=status,
                evidence=ChildExecutionEvidenceDAO.pending(
                    session_id=_DETACHED_CHILD, execution_id=execution_id, dispatch_id=_DISPATCH
                ),
            )
            return
        self._started_child(status=status, execution_id=execution_id)

    def _started_child(self, *, status: str, execution_id: str) -> None:
        """Publish a started child's spawn context, capture and evidence.

        Writes the spawn context, one public capture line and running evidence
        bound to that capture; a terminal ``status`` also writes ``status.json``
        and terminal evidence (the registry winner), then the fleet row.

        Args:
            status (str): Fleet status (running or terminal).
            execution_id (str): Incarnation.
        """
        directory: Path = OrchestrationLayout.child_capture_dir(
            history_root=self.root, parent_session_id=_ORCH_A, child_session_id=_DETACHED_CHILD
        )
        directory.mkdir(parents=True, exist_ok=True)
        context: bytes = dump_json_bytes(
            SpawnContextDAO.build(
                task_id="task-a",
                prompt="FULL TASK",
                system_prompt="SYSTEM-PRIVATE",
                inactivity_timeout_seconds=1.0,
                model=None,
                reasoning_level=None,
                cwd=None,
                execution_id=execution_id,
            )
        )
        (directory / "spawn_context.json").write_bytes(context)
        capture: Path = directory / "stdout.jsonl"
        capture.write_text(
            json.dumps({"kind": "text_delta", "delta": "child line"})
            + "\n"
            + json.dumps({"kind": "text_end"})
            + "\n",
            encoding="utf-8",
        )
        stat = os.stat(capture)
        evidence: ChildExecutionEvidenceDAO = ChildExecutionEvidenceDAO.pending(
            session_id=_DETACHED_CHILD, execution_id=execution_id, dispatch_id=_DISPATCH
        ).running(
            stdout_identity=StdoutCaptureIdentityDAO(device=stat.st_dev, inode=stat.st_ino),
            spawn_context_sha256=hashlib.sha256(context).hexdigest(),
        )
        if status in {"completed", "failed", "aborted"}:
            result: bytes = (
                SubAgentResultDAO(
                    task_id="task-a",
                    session_id=_DETACHED_CHILD,
                    status=status,  # type: ignore[arg-type]
                    exit_code=0 if status == "completed" else 2,
                )
                .model_dump_json()
                .encode()
            )
            (directory / "status.json").write_bytes(result)
            evidence = evidence.terminal(
                status=status, status_sha256=hashlib.sha256(result).hexdigest()  # type: ignore[arg-type]
            )
        self._publish(status=status, evidence=evidence)

    def _publish(self, *, status: str, evidence: ChildExecutionEvidenceDAO) -> None:
        """Publish the execution evidence, then the run-bound fleet row.

        Args:
            status (str): Fleet status.
            evidence (ChildExecutionEvidenceDAO): Evidence of the row's incarnation.
        """
        fleet: FleetStore = FleetStore(history_root=self.root, orchestrator_session_id=_ORCH_A, run_id=_RUN)
        fleet.publish_execution(evidence=evidence)
        fleet.persist(
            entries=[
                SubAgentStatusDAO(
                    task_id="task-a",
                    session_id=_DETACHED_CHILD,
                    status=status,  # type: ignore[arg-type]
                    execution_id=evidence.execution_id,
                    prompt_preview="preview",
                )
            ]
        )

    def target(self, *, run_id: str = _RUN, execution_id: str = _EXEC_A) -> ChildAbortTargetDAO:
        """Build a target for the detached child.

        Args:
            run_id (str, optional): Run. Defaults to ``_RUN``.
            execution_id (str, optional): Incarnation. Defaults to ``_EXEC_A``.

        Returns:
            ChildAbortTargetDAO: Target.
        """
        return ChildAbortTargetDAO(key=self.key, run_id=run_id, execution_id=execution_id)

    async def progress(self) -> SessionProgressSnapshotDAO:
        """Refresh the list, then read the child's progress.

        Returns:
            SessionProgressSnapshotDAO: Progress with abort control.
        """
        await self.service.load_session_snapshot()
        return await self.service.load_session_progress(key=self.key)

    def request_files(self) -> list[Path]:
        """Return committed request files of the run.

        Returns:
            list[Path]: Request files.
        """
        directory: Path = self.root / _ORCH_A / "child-control.v1" / _RUN / "requests"
        return sorted(directory.glob("*.json")) if directory.is_dir() else []


class _GatedGroupRead:
    """Holds every bounded group read at an Event so a test can act mid-read."""

    def __init__(self) -> None:
        """Create the entered and release events."""
        self.entered: asyncio.Event = asyncio.Event()
        self.release: asyncio.Event = asyncio.Event()

    def installed(self) -> Any:
        """Patch the loader's group read with the gated one.

        Returns:
            Any: Context manager restoring the real read.
        """
        real: Callable[..., Any] = WorkflowVisualizerLoader.load_observation_group
        gate: _GatedGroupRead = self

        async def gated(loader: WorkflowVisualizerLoader) -> Any:
            gate.entered.set()
            await gate.release.wait()
            return await real(loader)

        return patch.object(WorkflowVisualizerLoader, "load_observation_group", gated)


class TestAbortEligibility:
    """Progress snapshots carry an abort target only for an eligible current child."""

    @pytest.mark.parametrize("status", ["pending", "running"])
    async def test_attached_unfinished_child_is_eligible(self, status: str) -> None:
        """A queued or running attached child's progress carries its exact run and incarnation."""
        world = _Attached()
        world.status = status

        progress = await world.progress()

        assert progress.abort_target == world.target()
        assert world.abort.calls == []

    @pytest.mark.parametrize("status", ["pending", "running"])
    async def test_no_history_attached_child_is_eligible_with_unavailable_progress(self, status: str) -> None:
        """A no-history session cannot read progress yet can still target its attached child."""
        world = _Attached(root=None)
        world.status = status

        progress = await world.progress()

        assert progress.availability == "unavailable"
        assert progress.abort_target == world.target()

    @pytest.mark.parametrize("history", [False, True])
    async def test_attached_incarnation_change_between_reads_offers_no_target(
        self, history: bool, tmp_path: Path
    ) -> None:
        """Abort never targets an attached incarnation the displayed view did not capture.

        The list captures incarnation A, the registry then reuses the child as B
        before the progress read. Attached keys skip the readable-progress gate,
        so only the incarnation match keeps Abort off the unseen run B.
        """
        root = tmp_path / "history"
        root.mkdir()
        world = _Attached(root=root if history else None)
        await world.service.load_session_snapshot()
        world.execution_id = _EXEC_B

        progress = await world.service.load_session_progress(key=world.key)

        assert progress.execution_id == _EXEC_A
        assert progress.abort_target is None
        assert world.abort.calls == []

    async def test_parent_row_is_never_eligible(self) -> None:
        """The orchestrator's own row never carries an abort target."""
        world = _Attached()
        await world.service.load_session_snapshot()

        progress = await world.service.load_session_progress(
            key=WorkflowSessionKeyDAO(orchestrator_session_id=_OWNER, session_id=_OWNER)
        )

        assert progress.abort_target is None

    @pytest.mark.parametrize("status", ["completed", "failed", "aborted"])
    async def test_terminal_child_is_not_eligible(self, status: str) -> None:
        """A terminal child has nothing to abort."""
        world = _Attached()
        world.status = status

        assert (await world.progress()).abort_target is None

    @pytest.mark.parametrize(
        "capability",
        [
            None,
            _capability(accepting=False),
            _capability(owner_session_id="someone-else"),
            _capability(orchestrator_session_id="other-parent"),
        ],
    )
    async def test_attached_capability_must_accept_for_this_owner(
        self, capability: Optional[ChildControlCapabilityDAO]
    ) -> None:
        """No pool, a sealed pool or a foreign identity disables Abort."""
        world = _Attached()
        world.capability = capability

        assert (await world.progress()).abort_target is None

    async def test_absent_facade_disables_abort(self) -> None:
        """A service without an attached abort seam never offers attached abort."""
        world = _Attached()
        world.service._attached_abort = None

        assert (await world.progress()).abort_target is None

    async def test_detached_running_child_is_eligible(self, tmp_path: Path) -> None:
        """An owned live handle with a matching accepting capability enables Abort."""
        world = _Detached(root=tmp_path / "history")
        await world.seed()

        progress = await world.progress()

        assert progress.abort_target == world.target()

    async def test_detached_pending_child_is_eligible_with_empty_progress(self, tmp_path: Path) -> None:
        """A queued detached child has no capture yet (empty progress) but can be targeted."""
        world = _Detached(root=tmp_path / "history")
        await world.seed(status="pending")

        progress = await world.progress()

        assert progress.availability == "empty"
        assert progress.abort_target == world.target()

    @pytest.mark.parametrize(
        "capability",
        [
            _capability(orchestrator_session_id=_ORCH_A, accepting=False),
            _capability(orchestrator_session_id=_ORCH_A, owner_session_id="someone-else"),
            _capability(orchestrator_session_id=_ORCH_A, run_id=_RUN_OLD),
        ],
    )
    async def test_detached_capability_must_match_owner_and_run(
        self, tmp_path: Path, capability: ChildControlCapabilityDAO
    ) -> None:
        """A withdrawn, foreign-owner or other-run capability disables Abort."""
        world = _Detached(root=tmp_path / "history")
        await world.seed(capability=capability)

        assert (await world.progress()).abort_target is None

    async def test_detached_missing_capability_disables_abort(self, tmp_path: Path) -> None:
        """An old orchestrator that publishes no capability is inspectable but not abortable."""
        world = _Detached(root=tmp_path / "history")
        await world.seed()
        (tmp_path / "history" / _ORCH_A / "child-control.v1" / "capability.json").unlink()

        assert (await world.progress()).abort_target is None

    async def test_detached_dead_orchestrator_disables_abort(self, tmp_path: Path) -> None:
        """Without live orchestrator evidence the child cannot be targeted."""
        world = _Detached(root=tmp_path / "history")
        await world.seed()
        world.alive = False

        assert (await world.progress()).abort_target is None

    async def test_detached_stale_progress_disables_abort(self, tmp_path: Path) -> None:
        """An unreadable detached progress read (stale) never carries an abort target."""
        world = _Detached(root=tmp_path / "history")
        await world.seed()
        await world.service.load_session_snapshot()

        with patch(
            "src.tui.workflow_visualizer_loader.WorkflowVisualizerLoader.load_session_progress",
            side_effect=OSError("unreadable"),
        ):
            progress = await world.service.load_session_progress(key=world.key)

        assert progress.availability == "stale"
        assert progress.abort_target is None

    async def test_detached_stale_row_disables_abort(self, tmp_path: Path) -> None:
        """A row retained as stale after a failed group read is not abort authority."""
        world = _Detached(root=tmp_path / "history")
        await world.seed()
        await world.service.load_session_snapshot()

        with patch(
            "src.tui.workflow_visualizer_loader.WorkflowVisualizerLoader.load_observation_group",
            side_effect=OSError("unreadable"),
        ):
            snapshot = await world.service.load_session_snapshot()
            progress = await world.service.load_session_progress(key=world.key)

        assert {row.availability for row in snapshot.rows} == {"stale"}
        assert progress.abort_target is None

    async def test_detached_legacy_child_is_not_eligible(self, tmp_path: Path) -> None:
        """A legacy row without execution identity (no execution index) is read-only."""
        world = _Detached(root=tmp_path / "history")
        await world.seed()
        OrchestrationLayout.execution_index_path(
            history_root=world.root, orchestrator_session_id=_ORCH_A
        ).unlink()
        FleetStore(history_root=world.root, orchestrator_session_id=_ORCH_A, run_id=None).persist(
            entries=[
                SubAgentStatusDAO(
                    task_id="task-a", session_id=_DETACHED_CHILD, status="running", prompt_preview="legacy"
                )
            ]
        )

        assert (await world.progress()).abort_target is None


class TestRequestAuthority:
    """Every refusal is independent, fixed and makes zero submit or cancel calls."""

    @pytest.mark.parametrize("status", ["pending", "running"])
    async def test_attached_submit_calls_facade_with_exact_request(self, status: str) -> None:
        """A valid queued or running attached target reaches the facade once with its exact identity."""
        world = _Attached()
        world.status = status
        await world.service.load_session_snapshot()

        outcome = await world.service.request_child_abort(target=world.target())

        assert outcome.outcome == "aborted"
        [request] = world.abort.calls
        assert (request.owner_session_id, request.orchestrator_session_id, request.session_id) == (
            _OWNER,
            _OWNER,
            "child-1",
        )
        assert (request.run_id, request.execution_id, outcome.request_id) == (
            _RUN,
            _EXEC_A,
            request.request_id,
        )

    @pytest.mark.parametrize("status", ["pending", "running"])
    async def test_detached_submit_commits_one_request_and_no_facade_call(
        self, tmp_path: Path, status: str
    ) -> None:
        """A valid queued or running detached target commits one durable request; no facade call."""
        world = _Detached(root=tmp_path / "history")
        await world.seed(status=status)
        await world.service.load_session_snapshot()

        outcome = await world.service.request_child_abort(target=world.target())

        assert outcome.outcome == "requested"
        [path] = world.request_files()
        stored = ChildAbortRequestDAO.model_validate_json(path.read_bytes())
        assert (stored.request_id, stored.session_id, stored.execution_id) == (
            outcome.request_id,
            _DETACHED_CHILD,
            _EXEC_A,
        )
        assert world.abort.calls == []
        assert not (tmp_path / "history" / _ORCH_A / "abort_request.json").exists()

    @pytest.mark.parametrize(
        ("change", "expected"),
        [
            ("not_member", "not_owned"),
            ("no_capability", "unavailable"),
            ("not_accepting", "unavailable"),
            ("old_run", "unavailable"),
            ("old_incarnation", "unavailable"),
            ("terminal", "already_terminal"),
            ("no_facade", "unavailable"),
        ],
    )
    async def test_attached_refusals(self, change: str, expected: ChildAbortOutcome) -> None:
        """Each attached authority failure returns its fixed outcome without calling the pool."""
        world = _Attached()
        await world.service.load_session_snapshot()
        target: ChildAbortTargetDAO = world.target()
        if change == "not_member":
            target = ChildAbortTargetDAO(
                key=WorkflowSessionKeyDAO(orchestrator_session_id=_OWNER, session_id="ghost"),
                run_id=_RUN,
                execution_id=_EXEC_A,
            )
        elif change == "no_capability":
            world.capability = None
        elif change == "not_accepting":
            world.capability = _capability(accepting=False)
        elif change == "old_run":
            target = world.target(run_id=_RUN_OLD)
        elif change == "old_incarnation":
            world.execution_id = _EXEC_B
        elif change == "terminal":
            world.status = "completed"
        else:
            world.service._attached_abort = None

        outcome = await world.service.request_child_abort(target=target)

        assert outcome.outcome == expected
        assert (
            outcome.safe_message
            == ChildAbortOutcomeDAO.for_request(
                request=_request(target=target, request_id=outcome.request_id), outcome=expected
            ).safe_message
        )
        assert world.abort.calls == []

    @pytest.mark.parametrize(
        ("change", "expected"),
        [
            ("not_owned_group", "not_owned"),
            ("dismissed", "not_owned"),
            ("not_member", "not_owned"),
            ("dead", "unavailable"),
            ("no_capability", "unavailable"),
            ("not_accepting", "unavailable"),
            ("old_run", "unavailable"),
            ("old_incarnation", "unavailable"),
            ("terminal", "already_terminal"),
        ],
    )
    async def test_detached_refusals(self, tmp_path: Path, change: str, expected: ChildAbortOutcome) -> None:
        """Each detached authority failure is fixed and commits no request file."""
        world = _Detached(root=tmp_path / "history")
        await world.seed()
        await world.service.load_session_snapshot()
        target: ChildAbortTargetDAO = world.target()
        if change == "not_owned_group":
            target = ChildAbortTargetDAO(
                key=WorkflowSessionKeyDAO(orchestrator_session_id="orch-x", session_id=_DETACHED_CHILD),
                run_id=_RUN,
                execution_id=_EXEC_A,
            )
        elif change == "dismissed":
            world.service.dismiss_group(workflow_id="wf-a")
        elif change == "not_member":
            target = ChildAbortTargetDAO(
                key=WorkflowSessionKeyDAO(orchestrator_session_id=_ORCH_A, session_id="ghost"),
                run_id=_RUN,
                execution_id=_EXEC_A,
            )
        elif change == "dead":
            world.alive = False
        elif change == "no_capability":
            (world.root / _ORCH_A / "child-control.v1" / "capability.json").unlink()
        elif change == "not_accepting":
            await world.control.write_capability(
                capability=_capability(orchestrator_session_id=_ORCH_A, accepting=False)
            )
        elif change == "old_run":
            target = world.target(run_id=_RUN_OLD)
        elif change == "old_incarnation":
            world.child(status="running", execution_id=_EXEC_B)
        else:
            world.child(status="aborted")
        with patch.object(ChildAbortStore, "submit", wraps=world.control.submit) as submit:
            outcome = await world.service.request_child_abort(target=target)

        assert outcome.outcome == expected
        submit.assert_not_called()
        assert world.request_files() == []
        assert world.abort.calls == []

    @pytest.mark.parametrize(
        ("change", "expected"),
        [("dismissed", "not_owned"), ("dead", "unavailable")],
    )
    async def test_authority_is_rechecked_after_the_group_read(
        self, tmp_path: Path, change: str, expected: ChildAbortOutcome
    ) -> None:
        """A dismissal or orchestrator death during the bounded group read refuses without a commit."""
        world = _Detached(root=tmp_path / "history")
        await world.seed()
        await world.service.load_session_snapshot()
        read = _GatedGroupRead()

        with (
            read.installed(),
            patch.object(ChildAbortStore, "submit", wraps=world.control.submit) as submit,
        ):
            request = asyncio.create_task(world.service.request_child_abort(target=world.target()))
            await read.entered.wait()
            if change == "dismissed":
                world.service.dismiss_group(workflow_id="wf-a")
            else:
                world.alive = False
            read.release.set()
            outcome = await request

        assert outcome.outcome == expected
        submit.assert_not_called()
        assert world.request_files() == []

    async def test_close_during_the_group_read_refuses_without_commit(self, tmp_path: Path) -> None:
        """``close`` started while a confirmed submission reads the group joins it and nothing commits."""
        world = _Detached(root=tmp_path / "history")
        await world.seed()
        await world.service.load_session_snapshot()
        read = _GatedGroupRead()
        outcomes: list[ChildAbortOutcomeDAO] = []
        request_child_abort = world.service.request_child_abort

        async def recorded(*, target: ChildAbortTargetDAO) -> ChildAbortOutcomeDAO:
            outcome: ChildAbortOutcomeDAO = await request_child_abort(target=target)
            outcomes.append(outcome)
            return outcome

        with (
            read.installed(),
            patch.object(world.service, "request_child_abort", side_effect=recorded),
            patch.object(ChildAbortStore, "submit", wraps=world.control.submit) as submit,
        ):
            world.service.begin_child_abort(target=world.target())
            await read.entered.wait()
            closing = asyncio.create_task(world.service.close())
            await asyncio.sleep(0)  # let close mark the service closed before the read finishes
            read.release.set()
            await closing

        assert [outcome.outcome for outcome in outcomes] == ["not_owned"]
        submit.assert_not_called()
        assert world.request_files() == []

    async def test_no_history_detached_request_is_unavailable(self) -> None:
        """Without a history adapter a detached request is refused as unavailable."""
        world = _Attached(root=None)

        outcome = await world.service.request_child_abort(
            target=ChildAbortTargetDAO(
                key=WorkflowSessionKeyDAO(orchestrator_session_id=_ORCH_A, session_id=_DETACHED_CHILD),
                run_id=_RUN,
                execution_id=_EXEC_A,
            )
        )

        assert outcome.outcome == "unavailable"
        assert world.abort.calls == []

    async def test_storage_error_before_commit_is_unavailable(self, tmp_path: Path) -> None:
        """An OSError before commit reports unavailable and leaves no request file."""
        world = _Detached(root=tmp_path / "history")
        await world.seed()
        await world.service.load_session_snapshot()

        with patch.object(AtomicFileWriter, "write_text_with_outcome", side_effect=OSError("disk SECRET")):
            outcome = await world.service.request_child_abort(target=world.target())

        assert outcome.outcome == "unavailable"
        assert "SECRET" not in outcome.safe_message
        assert world.request_files() == []

    async def test_durability_warning_after_commit_is_still_requested(self, tmp_path: Path) -> None:
        """A committed write with an unconfirmed fsync is requested with the fixed warning."""
        world = _Detached(root=tmp_path / "history")
        await world.seed()
        await world.service.load_session_snapshot()
        real_write: Callable[..., AtomicWriteOutcomeDAO] = AtomicFileWriter.write_text_with_outcome

        def warn(**kwargs: object) -> AtomicWriteOutcomeDAO:
            outcome: AtomicWriteOutcomeDAO = real_write(**kwargs)  # type: ignore[arg-type]
            return outcome.model_copy(update={"durability_warning": True})

        with patch.object(AtomicFileWriter, "write_text_with_outcome", side_effect=warn):
            outcome = await world.service.request_child_abort(target=world.target())

        assert outcome.outcome == "requested"
        assert "durability not confirmed" in outcome.safe_message
        assert len(world.request_files()) == 1

    async def test_facade_failure_is_unresolved(self) -> None:
        """An unexpected attached facade error becomes the fixed unresolved outcome."""
        world = _Attached()
        world.abort.error = RuntimeError("SECRET detail")
        await world.service.load_session_snapshot()

        outcome = await world.service.request_child_abort(target=world.target())

        assert outcome.outcome == "unresolved"
        assert "SECRET" not in outcome.safe_message


async def _settled(*, service: DetachedWorkflowAppService) -> None:
    """Let every tracked submission task finish (they run without a UI waiter).

    Args:
        service (DetachedWorkflowAppService): Service whose submissions to await.
    """
    for submission in tuple(service._abort_submissions.values()):
        await submission.join()


class TestSubmissionLifetime:
    """The service tracks one submission per target, joins it on close and settles it on refresh."""

    async def test_double_begin_submits_once(self) -> None:
        """Two confirmations of the same target make one facade call with one request id."""
        world = _Attached()
        world.abort.gate.clear()
        await world.service.load_session_snapshot()

        world.service.begin_child_abort(target=world.target())
        world.service.begin_child_abort(target=world.target())
        await world.abort.entered.wait()
        world.service.begin_child_abort(target=world.target())
        world.abort.gate.set()
        await _settled(service=world.service)

        assert len(world.abort.calls) == 1

    async def test_pending_request_disables_abort_and_shows_requested(self) -> None:
        """While the attached pool works the view says requested, never aborted, and Abort is disabled."""
        world = _Attached()
        world.abort.gate.clear()
        await world.service.load_session_snapshot()
        world.service.begin_child_abort(target=world.target())
        await world.abort.entered.wait()

        progress = await world.progress()

        assert progress.abort_target is None
        assert progress.notice is not None and "Abort requested" in progress.notice
        assert "aborted" not in progress.notice.lower().replace("abort requested", "")
        world.abort.gate.set()
        await _settled(service=world.service)

    async def test_thirty_second_notice_keeps_request_without_retry(self) -> None:
        """After 30 fake seconds the notice changes; no second request is made."""
        world = _Attached()
        world.abort.gate.clear()
        await world.service.load_session_snapshot()
        world.service.begin_child_abort(target=world.target())
        await world.abort.entered.wait()

        world.clock.now += 29.0
        assert "Abort requested" in str((await world.progress()).notice)
        world.clock.now += 1.0
        progress = await world.progress()

        assert progress.notice is not None and ABORT_NOT_CONFIRMED_NOTICE in progress.notice
        assert len(world.abort.calls) == 1
        world.abort.gate.set()
        await _settled(service=world.service)

    async def test_attached_result_settles_and_terminal_row_wins(self) -> None:
        """The pool's aborted result settles; the terminal registry row then shows Child aborted."""
        world = _Attached()
        await world.service.load_session_snapshot()
        world.service.begin_child_abort(target=world.target())
        await _settled(service=world.service)
        world.status = "aborted"

        progress = await world.progress()

        assert progress.notice is not None and "Child aborted." in progress.notice
        assert progress.abort_target is None

    async def test_settled_refusal_allows_an_explicit_new_request(self) -> None:
        """After an unavailable refusal a new explicit confirmation gets a fresh request id."""
        world = _Attached()
        world.abort.outcome = "unavailable"
        await world.service.load_session_snapshot()
        world.service.begin_child_abort(target=world.target())
        await _settled(service=world.service)

        assert (await world.progress()).abort_target == world.target()
        world.service.begin_child_abort(target=world.target())
        await _settled(service=world.service)

        first, second = world.abort.calls
        assert first.request_id != second.request_id

    async def test_new_incarnation_never_inherits_a_request(self) -> None:
        """A same-key new execution shows no old notice and is eligible on its own."""
        world = _Attached()
        world.abort.gate.clear()
        await world.service.load_session_snapshot()
        world.service.begin_child_abort(target=world.target())
        await world.abort.entered.wait()
        world.execution_id = _EXEC_B

        progress = await world.progress()

        assert progress.notice is None or "Abort" not in progress.notice
        assert progress.abort_target == world.target(execution_id=_EXEC_B)
        world.abort.gate.set()
        await _settled(service=world.service)

    async def test_close_joins_submission_without_cancelling(self) -> None:
        """Service close waits for the accepted attached operation; it is never cancelled."""
        world = _Attached()
        world.abort.gate.clear()
        await world.service.load_session_snapshot()
        world.service.begin_child_abort(target=world.target())
        await world.abort.entered.wait()
        [submission] = world.service._abort_submissions.values()
        operation = submission._operation

        closing: asyncio.Task[None] = asyncio.ensure_future(world.service.close())
        await asyncio.sleep(0)
        assert not closing.done()
        world.abort.gate.set()
        await closing

        assert operation.done() and not operation.cancelled()
        assert operation.result().outcome == "aborted"
        world.service.begin_child_abort(target=world.target())
        assert world.service._abort_submissions == {}

    async def test_close_joins_operation_settled_by_terminal_row(self) -> None:
        """A terminal row before the facade returns never lets a stale confirmation orphan the operation."""
        world = _Attached()
        world.abort.gate.clear()
        try:
            await world.service.load_session_snapshot()
            target: ChildAbortTargetDAO = world.target()
            world.service.begin_child_abort(target=target)
            await world.abort.entered.wait()
            [submission] = world.service._abort_submissions.values()
            operation = submission._operation
            world.status = "aborted"
            await world.service.load_session_snapshot()

            world.service.begin_child_abort(target=target)
            closing: asyncio.Task[None] = asyncio.ensure_future(world.service.close())
            await asyncio.sleep(0)

            assert len(world.abort.calls) == 1
            assert world.service._abort_submissions[target] is submission
            assert not closing.done()
        finally:
            world.abort.gate.set()
        await closing

        assert operation.done() and not operation.cancelled()

    async def test_detached_receipt_settles_on_list_refresh(self, tmp_path: Path) -> None:
        """A requested detached abort settles from the runner's receipt on the next list refresh."""
        world = _Detached(root=tmp_path / "history")
        await world.seed()
        await world.service.load_session_snapshot()
        world.service.begin_child_abort(target=world.target())
        await _settled(service=world.service)
        [submission] = world.service._abort_submissions.values()
        assert "Abort requested" in str((await world.progress()).notice)

        await world.control.write_receipt(
            request=submission.request,
            outcome=ChildAbortOutcomeDAO.for_request(request=submission.request, outcome="aborted"),
        )
        await world.service.load_session_snapshot()

        assert submission.awaits_receipt is False
        assert "Child aborted." in str((await world.progress()).notice)

    async def test_receipt_mismatch_never_settles_as_aborted(self, tmp_path: Path) -> None:
        """A receipt naming another child loads as unavailable, never Child aborted."""
        world = _Detached(root=tmp_path / "history")
        await world.seed()
        await world.service.load_session_snapshot()
        world.service.begin_child_abort(target=world.target())
        await _settled(service=world.service)
        [submission] = world.service._abort_submissions.values()
        receipts: Path = world.root / _ORCH_A / "child-control.v1" / _RUN / "receipts"
        receipts.mkdir(mode=0o700)
        foreign = ChildAbortOutcomeDAO.for_request(request=submission.request, outcome="aborted").model_copy(
            update={"session_id": "other-child"}
        )
        (receipts / f"{submission.request.request_id}.json").write_text(
            foreign.model_dump_json(), encoding="utf-8"
        )

        notice: str = str((await world.progress()).notice)

        assert "Child abort unavailable for this run." in notice
        assert "Child aborted." not in notice

    async def test_terminal_before_receipt_settles_and_stops_receipt_reads(self, tmp_path: Path) -> None:
        """Terminal fleet truth settles a requested abort without a receipt; receipts are no longer read."""
        world = _Detached(root=tmp_path / "history")
        await world.seed()
        await world.service.load_session_snapshot()
        world.service.begin_child_abort(target=world.target())
        await _settled(service=world.service)
        world.child(status="aborted")

        with patch.object(ChildAbortStore, "load_receipt", wraps=world.control.load_receipt) as reads:
            await world.service.load_session_snapshot()
            await world.service.load_session_snapshot()

        reads.assert_not_called()
        progress = await world.service.load_session_progress(key=world.key)
        assert "Child aborted." in str(progress.notice)
        assert progress.abort_target is None

    async def test_unreadable_receipt_keeps_request_pending(self, tmp_path: Path) -> None:
        """A receipt read error keeps the request pending; nothing is resubmitted."""
        world = _Detached(root=tmp_path / "history")
        await world.seed()
        await world.service.load_session_snapshot()
        world.service.begin_child_abort(target=world.target())
        await _settled(service=world.service)
        [submission] = world.service._abort_submissions.values()

        with patch.object(ChildAbortStore, "load_receipt", side_effect=OSError("SECRET")):
            await world.service.load_session_snapshot()

        assert submission.awaits_receipt is True
        assert len(world.request_files()) == 1

    async def test_unsafe_target_identity_starts_nothing(self) -> None:
        """A target whose ids are unsafe for the control protocol is refused before any task."""
        world = _Attached()

        world.service.begin_child_abort(
            target=ChildAbortTargetDAO(
                key=WorkflowSessionKeyDAO(orchestrator_session_id=_OWNER, session_id="../escape"),
                run_id=_RUN,
                execution_id=_EXEC_A,
            )
        )

        assert world.service._abort_submissions == {}
        assert world.abort.calls == []
