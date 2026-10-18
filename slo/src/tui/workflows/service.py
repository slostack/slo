"""Application service for the detached-workflow TUI receive path (spec 57.a.5).

Coordinates durable workflow handle lifecycle for the mounted TUI session:
startup reconcile, inbox lifecycle translation, launch-result translation,
and the live-state cache that backs the exit hint. Feature 94 extends the same
service with owner-scoped workflow observation: session-list snapshots and the
selected session's progress gateway. Emits typed UI effects and DTOs from
``dao.py`` — it never renders, never launches windows, and imports no Textual
modules.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, List, Optional, Protocol, TypeAlias
from uuid import uuid4

from config.logger import log_info, log_warning
from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol
from src.agents.slo_agent.orchestrator.child_abort import ChildAbortStore
from src.agents.slo_agent.orchestrator.dao import (
    TERMINAL_STATUSES,
    AttachedDispatchSnapshotDAO,
    ChildAbortOutcome,
    ChildAbortOutcomeDAO,
    ChildAbortRequestDAO,
    ChildControlCapabilityDAO,
    SubAgentStatusDAO,
)
from src.agents.slo_agent.orchestrator.workflow_registry import (
    OBSERVATION_MAX_HANDLES,
    OBSERVATION_UNAVAILABLE_MESSAGE,
    WorkflowHandleDAO,
    WorkflowHandleStore,
    WorkflowState,
)
from src.tui.workflows.abort_submission import ChildAbortSubmission
from src.tui.workflows.dao import (
    ChildAbortTargetDAO,
    DetachedWorkflowUiEffectDAO,
    HandleAdvanceOutcomeDAO,
    LaunchResultOutcome,
    LiveWorkflowLabelDAO,
    ParsedFleetUpdateDAO,
    ParsedLaunchResultDAO,
    ParsedWorkflowLifecycleMessageDAO,
    SessionProgressAvailability,
    SessionProgressSnapshotDAO,
    WorkflowListDismissOutcomeDAO,
    WorkflowSessionKeyDAO,
    WorkflowSessionRowDAO,
    WorkflowSessionSnapshotDAO,
    parse_fleet_update_message,
    parse_launch_workflow_result,
    parse_workflow_lifecycle_message,
)

if TYPE_CHECKING:
    # Runtime import is deferred to ``_loader``: the loader module imports
    # ``orchestrator.process``, whose ``src.cli`` import chain reaches ``src.tui.app``
    # and this module, so a module-level import would be circular.
    from src.tui.workflow_visualizer_loader import (
        ChildSessionSummaryDAO,
        WorkflowDataDAO,
        WorkflowVisualizerLoader,
    )

__all__ = ["AttachedChildAbort", "DetachedWorkflowAppService"]

LIST_UNAVAILABLE_NOTICE: str = "Workflow list unavailable; showing last known sessions."
"""Fixed snapshot notice while owned membership is retained rather than freshly read."""

SESSION_REMOVED_NOTICE: str = "Session removed from current workflow."
"""Fixed progress notice for authoritative membership removal."""

_ABORTABLE_STATUSES: frozenset[str] = frozenset({"pending", "running"})
"""Child statuses that may still be aborted; every other status is terminal or unknown."""

_AttachedBatchMembers: TypeAlias = frozenset[tuple[str, str, str]]
"""Identity of one attached batch: one (dispatch_id, session_id, execution_id) triple per row."""

_READABLE_PROGRESS: frozenset[str] = frozenset({"available", "empty"})
"""Progress availabilities whose status comes from a fresh, readable source."""


class ChildAbortRefused(Exception):
    """Signal an abort refusal that carries only a closed outcome (never error text).

    Raised by the abort revalidation helpers and caught by ``request_child_abort``;
    it is internal to this module and never escapes to callers.
    """

    def __init__(self, *, outcome: ChildAbortOutcome) -> None:
        """Capture the fixed outcome the service reports for this refusal.

        Args:
            outcome (ChildAbortOutcome): Closed refusal literal.
        """
        super().__init__(outcome)
        self.outcome: ChildAbortOutcome = outcome


class AttachedChildAbort(Protocol):
    """Keyword-call seam that submits one attached child abort (feature 94 a.4)."""

    async def __call__(self, *, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        """Submit one exact-incarnation abort request to the attached pool.

        Args:
            request (ChildAbortRequestDAO): Immutable confirmed target request.

        Returns:
            ChildAbortOutcomeDAO: Closed fixed-message outcome.
        """


class DetachedWorkflowAppService:
    """Coordinate detached-workflow lifecycle for one owning TUI session.

    Owns the ``WorkflowHandleStore`` reconcile/update calls, the legal
    durable transitions, and the ``workflow_id → state`` cache. Every public
    method translates untrusted input (inbox payloads, tool-result JSON) into
    typed domain objects first and returns typed outcomes — the caller never
    parses workflow JSON or lifecycle payloads itself.

    Feature 94 adds owner-scoped observation to the same service: session-list
    snapshots of the attached batch plus owned detached groups, explicit
    dismissal suppression, in-memory clearing of finished groups (a.5), and
    the selected session's progress gateway.
    Observation is read-only: it never reconciles, sweeps or advances durable
    state, and unreadable files are retained as stale, never treated as removal.
    """

    def __init__(
        self,
        *,
        workflow_handle_store: Optional[WorkflowHandleStore],
        owner_session_id: str,
        attached_snapshot: Callable[[], AttachedDispatchSnapshotDAO],
        history_store: Optional[SessionHistoryStoreProtocol] = None,
        attached_abort: Optional[AttachedChildAbort] = None,
        attached_capability: Optional[Callable[[], Optional[ChildControlCapabilityDAO]]] = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Bind the service to one owning session's adapters without starting I/O.

        WHAT: Stores injected collaborators and empty observation caches.
        WHO: SloTUI workflow delivery/observation initialization and tests.
        WHEN: Once per owning session; ``/new`` builds a fresh instance.

        Args:
            workflow_handle_store (Optional[WorkflowHandleStore]): Durable handle
                store; None for a no-history session (lifecycle methods no-op).
            owner_session_id (str): The TUI session that owns the workflows.
            attached_snapshot (Callable[[], AttachedDispatchSnapshotDAO]): Latest
                attached dispatch supplier; tests pass the explicit empty value.
            history_store (Optional[SessionHistoryStoreProtocol], optional): The
                session's actual history adapter; None disables file observation.
                Defaults to None.
            attached_abort (Optional[AttachedChildAbort], optional): Attached child
                abort seam; None means unavailable. Defaults to None.
            attached_capability (Optional[Callable[[], Optional[ChildControlCapabilityDAO]]], optional):
                Attached child-control capability supplier; None means unavailable.
                Defaults to None.
            monotonic (Callable[[], float], optional): Clock for the 30-second
                abort-confirmation notice; tests inject a fake. Defaults to
                ``time.monotonic``.
        """
        self._store: Optional[WorkflowHandleStore] = workflow_handle_store
        self._owner_session_id: str = owner_session_id
        self._workflow_states: dict[str, WorkflowState] = {}
        self._fleet_cache: dict[str, ParsedFleetUpdateDAO] = {}
        self._attached_snapshot: Callable[[], AttachedDispatchSnapshotDAO] = attached_snapshot
        self._history_store: Optional[SessionHistoryStoreProtocol] = history_store
        self._attached_abort: Optional[AttachedChildAbort] = attached_abort
        self._attached_capability: Optional[Callable[[], Optional[ChildControlCapabilityDAO]]] = (
            attached_capability
        )
        self._group_rows: dict[str, tuple[WorkflowSessionRowDAO, ...]] = {}
        self._loaders: dict[str, WorkflowVisualizerLoader] = {}
        self._handles: dict[str, WorkflowHandleDAO] = {}
        # Detached workflow ids hidden by /workflows dismiss or tui dismiss; resume clears one.
        self._dismissed: set[str] = set()
        self._attached_dispatch_id: str = ""
        # Members of the attached batch hidden by tui dismiss; None hides nothing.
        # A chain step registering in the same dispatch changes the members, so
        # the batch shows again while that step runs; a new dispatch shows normally.
        self._hidden_attached_batch: Optional[_AttachedBatchMembers] = None
        self._observation_notice: Optional[str] = None
        self._rows: dict[WorkflowSessionKeyDAO, WorkflowSessionRowDAO] = {}
        self._closed: bool = False
        self._monotonic: Callable[[], float] = monotonic
        # One request per confirmed target, allocated before any await; kept while pending.
        self._abort_requests: dict[ChildAbortTargetDAO, ChildAbortRequestDAO] = {}
        # Service-owned submissions, latest last; joined on close, never cancelled.
        self._abort_submissions: dict[ChildAbortTargetDAO, ChildAbortSubmission] = {}
        self._control_stores: dict[str, ChildAbortStore] = {}

    async def reconcile_snapshot(self) -> dict[str, WorkflowState]:
        """Refresh the cached workflow states from a pid-liveness reconcile pass.

        WHAT: re-reads every handle for the owning session and replaces the
            state cache with the reconciled truth.
        WHO: the TUI mount path, via the app's delivery initialization.
        WHEN: once at mount, so a resumed TUI shows accurate states before
            any lifecycle note is claimed.

        Returns:
            dict[str, WorkflowState]: The refreshed cache. The pre-existing
                cache is returned unchanged when the store call fails or no
                handle store exists — reconcile failures are logged, never raised.
        """
        if self._store is None:
            return self._workflow_states
        try:
            handles: List[WorkflowHandleDAO] = await self._store.reconcile(
                owner_session_id=self._owner_session_id,
            )
        except Exception as exc:  # noqa: BLE001 — mount must not fail on handle errors
            log_info(msg="workflow_reconcile_failed", error=str(exc))
            return self._workflow_states
        self._workflow_states = {handle.workflow_id: handle.state for handle in handles}
        return self._workflow_states

    async def advance_from_inbox_message(
        self,
        *,
        kind: str,
        payload: Optional[dict[str, object]],
    ) -> HandleAdvanceOutcomeDAO:
        """Translate one claimed inbox message into durable and UI effects.

        WHAT: parses the lifecycle payload, advances the durable handle
            through the legal transition table, updates the state cache, and
            emits the typed UI effects (resume-case visualizer launch on
            ``started``, launch-guard reset on ``terminal``).
        WHO: the TUI inbox claim path, for every claimed message.
        WHEN: before the message's delivery-mode rendering runs, so
            ``/workflows`` state stays truthful regardless of delivery mode.

        Args:
            kind (str): Inbox message kind.
            payload (Optional[dict[str, object]]): Raw opaque inbox payload.

        Returns:
            HandleAdvanceOutcomeDAO: Typed outcome. Non-workflow messages,
                invalid payloads, and handle-store failures all produce a
                no-effect outcome — inbox delivery never fails on them.
        """
        fleet_update: Optional[ParsedFleetUpdateDAO] = parse_fleet_update_message(
            kind=kind,
            payload=payload,
        )
        if fleet_update is not None:
            self._fleet_cache[fleet_update.workflow_id] = fleet_update
            return HandleAdvanceOutcomeDAO(workflow_id=fleet_update.workflow_id)
        parsed: Optional[ParsedWorkflowLifecycleMessageDAO] = parse_workflow_lifecycle_message(
            kind=kind,
            payload=payload,
        )
        if parsed is None:
            return HandleAdvanceOutcomeDAO()
        advanced: bool = await self._advance_durable_handle(parsed=parsed)
        if not advanced:
            return HandleAdvanceOutcomeDAO(workflow_id=parsed.workflow_id)
        self._workflow_states[parsed.workflow_id] = parsed.target_state
        return HandleAdvanceOutcomeDAO(
            effects=self._effects_for_lifecycle(parsed=parsed),
            advanced_handle=True,
            advanced_state=parsed.target_state,
            workflow_id=parsed.workflow_id,
        )

    def advance_from_launch_result(self, *, result_text: str) -> LaunchResultOutcome:
        """Translate one ``launch_workflow`` tool-result text into UI effects.

        WHAT: parses the handle JSON; a valid result seeds the state cache
            (so the exit hint lists the workflow before its ``workflow_started``
            note is claimed) and returns ``launched`` so the caller executes
            the visualizer effect. Anything else is a safe no-op.
        WHO: the TUI live render path on ``launch_workflow`` tool results.
        WHEN: during the launch turn, when the tool result streams through.

        Args:
            result_text (str): Raw ``launch_workflow`` tool-result text.

        Returns:
            LaunchResultOutcome: ``launched`` for a valid handle payload,
                ``ignored`` for malformed, error, or orchestrator-id-less JSON.
        """
        parsed: Optional[ParsedLaunchResultDAO] = parse_launch_workflow_result(
            result_text=result_text,
        )
        if parsed is None:
            return "ignored"
        if parsed.workflow_id:
            self._workflow_states[parsed.workflow_id] = parsed.state
        return "launched"

    def fleet_update_for(self, *, workflow_id: str) -> Optional[ParsedFleetUpdateDAO]:
        """Return the latest claimed fleet note for a workflow renderer.

        WHAT: Exposes progress-cache data without reading or advancing durable handles.
        WHO: Called by detached-workflow renderers that need recent note progress.
        WHEN: After the inbox claim path has parsed a fleet update.

        Args:
            workflow_id (str): Workflow whose cached fleet snapshot is requested.

        Returns:
            Optional[ParsedFleetUpdateDAO]: Latest note snapshot, or None.
        """
        return self._fleet_cache.get(workflow_id)

    def live_workflow_labels(self) -> List[LiveWorkflowLabelDAO]:
        """Return labels for workflows whose cached state is live.

        Returns:
            List[LiveWorkflowLabelDAO]: One label per ``launching``/``running``
                workflow, sorted by workflow id.
        """
        return [
            LiveWorkflowLabelDAO(workflow_id=workflow_id, state=state)
            for workflow_id, state in sorted(self._workflow_states.items())
            if state in ("launching", "running")
        ]

    def _effects_for_lifecycle(
        self,
        *,
        parsed: ParsedWorkflowLifecycleMessageDAO,
    ) -> List[DetachedWorkflowUiEffectDAO]:
        """Build the typed UI effects implied by one lifecycle advance.

        Args:
            parsed (ParsedWorkflowLifecycleMessageDAO): Validated lifecycle payload.

        Returns:
            List[DetachedWorkflowUiEffectDAO]: One effect per advance that
                carries an orchestrator session id — ``launch_visualizer``
                for ``started`` advances, ``reset_launch_guard`` for
                ``terminal`` advances; empty when the payload carries no
                orchestrator session id.
        """
        if not parsed.orchestrator_session_id:
            return []
        if parsed.target == "terminal":
            return [self._reset_launch_guard_effect(parsed=parsed)]
        return [self._launch_visualizer_effect(parsed=parsed)]

    @staticmethod
    def _launch_visualizer_effect(
        *,
        parsed: ParsedWorkflowLifecycleMessageDAO,
    ) -> DetachedWorkflowUiEffectDAO:
        """Build the launch effect for a ``started`` lifecycle advance.

        Args:
            parsed (ParsedWorkflowLifecycleMessageDAO): Validated lifecycle payload.

        Returns:
            DetachedWorkflowUiEffectDAO: The ``launch_visualizer`` effect.
        """
        return DetachedWorkflowUiEffectDAO(
            effect="launch_visualizer",
            orchestrator_session_id=parsed.orchestrator_session_id,
            state=parsed.target_state,
        )

    @staticmethod
    def _reset_launch_guard_effect(
        *,
        parsed: ParsedWorkflowLifecycleMessageDAO,
    ) -> DetachedWorkflowUiEffectDAO:
        """Build the reset-only effect for a ``terminal`` lifecycle advance.

        A terminal advance frees the renderer's launch guard so a re-run of
        the workflow opens a fresh window — it never emits a launch effect.

        Args:
            parsed (ParsedWorkflowLifecycleMessageDAO): Validated lifecycle payload.

        Returns:
            DetachedWorkflowUiEffectDAO: The ``reset_launch_guard`` effect.
        """
        return DetachedWorkflowUiEffectDAO(
            effect="reset_launch_guard",
            orchestrator_session_id=parsed.orchestrator_session_id,
            state=parsed.target_state,
        )

    async def _advance_durable_handle(self, *, parsed: ParsedWorkflowLifecycleMessageDAO) -> bool:
        """Advance the durable handle, tolerating store failures.

        Unknown workflows and illegal transitions (e.g. a late failure note
        on an aborted handle) are logged, never raised — inbox delivery must
        not fail because a handle file is missing or already terminal.

        Args:
            parsed (ParsedWorkflowLifecycleMessageDAO): Validated lifecycle payload.

        Returns:
            bool: ``True`` when the durable handle advanced to the target state;
                ``False`` on store failure or when no handle store exists.
        """
        if self._store is None:
            return False
        try:
            await self._store.update_state(
                owner_session_id=self._owner_session_id,
                workflow_id=parsed.workflow_id,
                state=parsed.target_state,
            )
        except Exception as exc:  # noqa: BLE001 — delivery must not fail on handle errors
            log_info(
                msg="workflow_handle_advance_failed",
                workflow_id=parsed.workflow_id,
                error=str(exc),
            )
            return False
        return True

    # ── feature 94 observation: public snapshot and lifecycle ───────────────

    async def load_session_snapshot(self) -> WorkflowSessionSnapshotDAO:
        """Assemble owner-scoped session-list rows without reconciling durable state.

        WHAT: Reads the attached supplier afresh (so a missed dispatch-start event
            is repaired by the next poll), the bounded owned handle list and each
            visible detached group, then returns attached-first, detached-by-start
            rows with duplicate keys removed. It never reconciles, sweeps, lists
            workflow text or loads full history, and has no process side effects.
        WHO: The a.3 refresh coordinator (immediate and five-second ticks).
        WHEN: On every observation refresh until ``close``.

        Returns:
            WorkflowSessionSnapshotDAO: Fresh rows, or explicitly stale retained rows
                with a fixed notice; empty once closed.
        """
        if self._closed:
            return WorkflowSessionSnapshotDAO()
        attached: AttachedDispatchSnapshotDAO = self._attached_snapshot()
        self._adopt_dispatch(attached=attached)
        self._release_attached_suppression(attached=attached)
        attached_rows: tuple[WorkflowSessionRowDAO, ...] = await self._project_attached_group(
            attached=attached
        )
        handles: tuple[WorkflowHandleDAO, ...] = await self._read_owned_handles()
        detached_rows: tuple[WorkflowSessionRowDAO, ...] = await self._project_detached_groups(
            handles=handles
        )
        snapshot: WorkflowSessionSnapshotDAO = self._commit_snapshot(
            rows=self._unique_rows(rows=(*attached_rows, *detached_rows))
        )
        await self._observe_abort_submissions(rows=snapshot.rows)
        return snapshot

    async def close(self) -> None:
        """Join submissions, clear observation caches and refuse new observation work.

        WHAT: Marks the service closed, then joins every service-owned child-abort
            submission without cancelling it (a possibly committing write must
            finish; accepted pool work is never withdrawn), then drops group,
            loader, handle, row, suppression, request and control-store caches;
            later snapshot and progress reads return empty. Lifecycle state
            (workflow states, fleet notes) is left untouched.
        WHO: SloTUI teardown, after the refresh coordinator is closed.
        WHEN: On ``/new`` session adoption and on unmount.
        """
        self._closed = True
        for submission in tuple(self._abort_submissions.values()):
            await submission.join()
        self._abort_submissions.clear()
        self._abort_requests.clear()
        self._control_stores.clear()
        self._group_rows.clear()
        self._loaders.clear()
        self._handles.clear()
        self._rows.clear()
        self._dismissed.clear()
        self._hidden_attached_batch = None

    def dismiss_group(self, *, workflow_id: str) -> None:
        """Suppress one explicitly dismissed workflow group for this TUI lifetime.

        WHAT: In-memory observation suppression only; the durable handle stays
            (dismissal itself is the durable ``stalled → failed`` transition).
            Drops the group's cached rows and loader.
        WHO: SloTUI, from a typed successful ``/workflows dismiss`` result.
        WHEN: Right after the slash command reports a successful dismissal.

        Args:
            workflow_id (str): Dismissed workflow.
        """
        self._dismissed.add(workflow_id)
        handle: Optional[WorkflowHandleDAO] = self._handles.get(workflow_id)
        if handle is None:
            return
        self._forget_group(orchestrator_session_id=handle.orchestrator_session_id)

    def resume_group(self, *, workflow_id: str) -> None:
        """Clear observation suppression after an explicit successful resume.

        Clears both a durable dismissal's and a ``tui dismiss`` suppression,
        because both share ``_dismissed``.

        Args:
            workflow_id (str): Resumed workflow.
        """
        self._dismissed.discard(workflow_id)

    def dismiss_from_list(self, *, target_id: Optional[str]) -> WorkflowListDismissOutcomeDAO:
        """Hide finished groups from the session list for this TUI lifetime (feature 94 a.5).

        WHAT: Classifies the groups of the last committed snapshot. Without a
            target it hides every finished group; with one it hides that group
            only when finished, else refuses it as running or unknown. Hiding is
            in-memory observation suppression: it writes no handle or history,
            signals nothing and never cancels or acknowledges an abort.
        WHO: SloTUI, from a typed ``/workflows tui dismiss [<id>]`` slash result.
        WHEN: Synchronously on the UI loop, before the app requests one coalesced
            refresh; suppression lives until resume, a change of the attached batch's
            members (a new dispatch or chain step) or ``close``.

        Args:
            target_id (Optional[str]): Detached workflow id or orchestrator session
                id of one group; None clears every finished group.

        Returns:
            WorkflowListDismissOutcomeDAO: What was hidden or refused; it owns the
                transcript line.
        """
        groups: dict[str, tuple[WorkflowSessionRowDAO, ...]] = self._committed_groups()
        if target_id is None:
            return self._clear_finished_groups(groups=groups)
        return self._clear_named_group(groups=groups, target_id=target_id)

    def _committed_groups(self) -> dict[str, tuple[WorkflowSessionRowDAO, ...]]:
        """Group the committed membership by orchestrator, in list order.

        Returns:
            dict[str, tuple[WorkflowSessionRowDAO, ...]]: Rows per orchestrator id,
                parent first; empty when nothing is listed.
        """
        groups: dict[str, list[WorkflowSessionRowDAO]] = {}
        for row in self._rows.values():
            groups.setdefault(row.key.orchestrator_session_id, []).append(row)
        return {orchestrator: tuple(rows) for orchestrator, rows in groups.items()}

    def _clear_finished_groups(
        self, *, groups: dict[str, tuple[WorkflowSessionRowDAO, ...]]
    ) -> WorkflowListDismissOutcomeDAO:
        """Hide every finished group and count the ones still running.

        Args:
            groups (dict[str, tuple[WorkflowSessionRowDAO, ...]]): Committed groups.

        Returns:
            WorkflowListDismissOutcomeDAO: Untargeted outcome.
        """
        finished: list[tuple[WorkflowSessionRowDAO, ...]] = [
            rows for rows in groups.values() if self._group_is_finished(rows=rows)
        ]
        return WorkflowListDismissOutcomeDAO(
            cleared=tuple(self._hide_group(rows=rows) for rows in finished),
            still_running=len(groups) - len(finished),
        )

    def _clear_named_group(
        self, *, groups: dict[str, tuple[WorkflowSessionRowDAO, ...]], target_id: str
    ) -> WorkflowListDismissOutcomeDAO:
        """Hide the one named group if it is listed and finished.

        Args:
            groups (dict[str, tuple[WorkflowSessionRowDAO, ...]]): Committed groups.
            target_id (str): Workflow id or orchestrator session id.

        Returns:
            WorkflowListDismissOutcomeDAO: Targeted clear, running refusal or unknown.
        """
        rows: Optional[tuple[WorkflowSessionRowDAO, ...]] = next(
            (
                rows
                for orchestrator, rows in groups.items()
                if target_id in (orchestrator, rows[0].workflow_id)
            ),
            None,
        )
        if rows is None:
            return WorkflowListDismissOutcomeDAO(target_id=target_id, unknown=target_id)
        if not self._group_is_finished(rows=rows):
            return WorkflowListDismissOutcomeDAO(target_id=target_id, refused_running=target_id)
        return WorkflowListDismissOutcomeDAO(target_id=target_id, cleared=(self._hide_group(rows=rows),))

    @staticmethod
    def _group_is_finished(*, rows: tuple[WorkflowSessionRowDAO, ...]) -> bool:
        """Return whether every row's last known status is terminal.

        Uses the shared ``TERMINAL_STATUSES`` owner, so pending, running (including
        an abort still pending), stalled, launching and unknown are unfinished.
        Stale and unavailable rows are judged by their last known status.

        Args:
            rows (tuple[WorkflowSessionRowDAO, ...]): One group's parent and children.

        Returns:
            bool: True when the whole group is terminal.
        """
        return all(row.status in TERMINAL_STATUSES for row in rows)

    def _hide_group(self, *, rows: tuple[WorkflowSessionRowDAO, ...]) -> str:
        """Suppress one finished group and forget its cached observation.

        Args:
            rows (tuple[WorkflowSessionRowDAO, ...]): Committed rows of the group.

        Returns:
            str: The group's name in the outcome: its workflow id, or the owner
                session id for the attached batch.
        """
        row: WorkflowSessionRowDAO = rows[0]
        self._forget_group(orchestrator_session_id=row.key.orchestrator_session_id)
        if row.workflow_id is None:
            # Only the owner's attached batch lacks a workflow id; its suppression
            # holds only while the batch keeps exactly the members judged finished.
            self._hidden_attached_batch = self._batch_members(rows=rows)
            return row.key.orchestrator_session_id
        self._dismissed.add(row.workflow_id)
        return row.workflow_id

    def _forget_group(self, *, orchestrator_session_id: str) -> None:
        """Drop one group's cached rows, loader and gateway membership.

        WHO: ``dismiss_group`` and ``_hide_group``, after recording the suppression.
        WHEN: Immediately, so a stale key can no longer open a progress view.

        Args:
            orchestrator_session_id (str): Group whose caches are dropped.
        """
        self._group_rows.pop(orchestrator_session_id, None)
        self._loaders.pop(orchestrator_session_id, None)
        self._rows = {
            key: row
            for key, row in self._rows.items()
            if key.orchestrator_session_id != orchestrator_session_id
        }

    @staticmethod
    def _batch_members(*, rows: tuple[WorkflowSessionRowDAO, ...]) -> _AttachedBatchMembers:
        """Return the identity of an attached batch's rows.

        Args:
            rows (tuple[WorkflowSessionRowDAO, ...]): Attached parent and children.

        Returns:
            _AttachedBatchMembers: One (dispatch, session, execution) triple per row.
        """
        return frozenset((row.dispatch_id, row.key.session_id, row.execution_id) for row in rows)

    def _hides_attached(self, *, rows: tuple[WorkflowSessionRowDAO, ...]) -> bool:
        """Return whether attached rows are still exactly the batch judged finished.

        The single suppression predicate for the attached projection, the commit
        filter and the progress gateway; a new member or incarnation fails it.

        Args:
            rows (tuple[WorkflowSessionRowDAO, ...]): Attached parent and children.

        Returns:
            bool: True only while the members equal the hidden batch.
        """
        return self._hidden_attached_batch == self._batch_members(rows=rows)

    def _release_attached_suppression(self, *, attached: AttachedDispatchSnapshotDAO) -> None:
        """Drop the attached suppression once the registry batch no longer matches it.

        WHO: ``load_session_snapshot``, right after capturing the registry batch.
        WHEN: Every refresh, so a batch that grew never hides again if it shrinks.

        Args:
            attached (AttachedDispatchSnapshotDAO): Captured registry batch.
        """
        if not self._hides_attached(rows=self._batch_rows(attached=attached)):
            self._hidden_attached_batch = None

    def _visible_rows(self, *, rows: tuple[WorkflowSessionRowDAO, ...]) -> tuple[WorkflowSessionRowDAO, ...]:
        """Drop the rows of the hidden attached batch and of dismissed workflows.

        Args:
            rows (tuple[WorkflowSessionRowDAO, ...]): Freshly projected rows.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: Rows of groups still shown, in order.
        """
        attached: tuple[WorkflowSessionRowDAO, ...] = tuple(
            row for row in rows if self._is_attached(key=row.key)
        )
        hidden: tuple[WorkflowSessionRowDAO, ...] = attached if self._hides_attached(rows=attached) else ()
        return tuple(row for row in rows if row not in hidden and row.workflow_id not in self._dismissed)

    def _commit_snapshot(self, *, rows: tuple[WorkflowSessionRowDAO, ...]) -> WorkflowSessionSnapshotDAO:
        """Publish rows as the membership the progress gateway validates against.

        Args:
            rows (tuple[WorkflowSessionRowDAO, ...]): Ordered unique rows.

        Returns:
            WorkflowSessionSnapshotDAO: Snapshot, or empty if closed while reading.
        """
        if self._closed:
            return WorkflowSessionSnapshotDAO()
        # Suppression may have changed while this refresh was reading; never resurrect.
        visible: tuple[WorkflowSessionRowDAO, ...] = self._visible_rows(rows=rows)
        self._rows = {row.key: row for row in visible}
        return WorkflowSessionSnapshotDAO(rows=visible, notice=self._observation_notice)

    @staticmethod
    def _unique_rows(*, rows: tuple[WorkflowSessionRowDAO, ...]) -> tuple[WorkflowSessionRowDAO, ...]:
        """Drop repeated composite keys, keeping the first (registry-precedence) row.

        Args:
            rows (tuple[WorkflowSessionRowDAO, ...]): Attached rows, then detached rows.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: Rows in first-seen order.
        """
        unique: dict[WorkflowSessionKeyDAO, WorkflowSessionRowDAO] = {}
        for row in rows:
            unique.setdefault(row.key, row)
        return tuple(unique.values())

    # ── feature 94 observation: progress gateway ────────────────────────────

    async def load_session_progress(self, *, key: WorkflowSessionKeyDAO) -> SessionProgressSnapshotDAO:
        """Read one member's bounded progress and reject results crossing a replacement.

        WHAT: Resolves the row from the latest snapshot (absent → removal), captures
            its execution/dispatch identity, delegates one bounded read to the
            cached loader, then re-reads membership through the bounded attached
            supplier or the exact owned handle's group. A changed incarnation
            returns stale with no new content; authoritative absence returns
            removal; unreadable evidence never means removal. Read-only.
        WHO: The a.3 refresh coordinator for the selected progress view.
        WHEN: On modal open and each refresh tick while a session is selected.

        Args:
            key (WorkflowSessionKeyDAO): Current owner-scoped selection.

        Returns:
            SessionProgressSnapshotDAO: Bounded content, a safe stale/unavailable
                notice, or a removal; carries an abort target only for an eligible
                current child (a.4) and the tracked request's fixed notice.
        """
        row: Optional[WorkflowSessionRowDAO] = None if self._closed else self._rows.get(key)
        if row is None:
            return self._progress_notice(key=key, removed=True)
        snapshot, current = await self._read_member_progress(row=row)
        return await self._with_abort_control(snapshot=snapshot, current=current)

    async def _read_member_progress(
        self, *, row: WorkflowSessionRowDAO
    ) -> tuple[SessionProgressSnapshotDAO, Optional[WorkflowSessionRowDAO]]:
        """Read one member's progress and its re-read current row, before abort control.

        Args:
            row (WorkflowSessionRowDAO): Row captured from the latest snapshot.

        Returns:
            tuple[SessionProgressSnapshotDAO, Optional[WorkflowSessionRowDAO]]: The
                accepted progress (or a fixed notice) and the authoritative current
                row; no-history sessions still re-read their attached registry row.
        """
        if self._history_store is None:
            unavailable = self._progress_notice(key=row.key, row=row, availability="unavailable")
            return unavailable, self._current_attached_row(key=row.key)
        try:
            snapshot: SessionProgressSnapshotDAO = await self._loader(
                parent_session_id=row.key.orchestrator_session_id
            ).load_session_progress(row=row)
            current: Optional[WorkflowSessionRowDAO] = await self._current_progress_row(key=row.key)
        except (OSError, ValueError):
            return self._progress_notice(key=row.key, row=row), None
        return self._accept_progress(row=row, current=current, snapshot=snapshot), current

    async def _current_progress_row(self, *, key: WorkflowSessionKeyDAO) -> Optional[WorkflowSessionRowDAO]:
        """Re-read authoritative membership for one key without touching UI caches.

        Args:
            key (WorkflowSessionKeyDAO): Key whose membership is re-checked.

        Returns:
            Optional[WorkflowSessionRowDAO]: Current row; None only for authoritative removal.

        Raises:
            OSError: When the detached group cannot be read.
            ValueError: When the detached group is unavailable or untrusted.
        """
        if self._is_attached(key=key):
            return self._current_attached_row(key=key)
        return await self._current_detached_row(key=key)

    def _current_attached_row(self, *, key: WorkflowSessionKeyDAO) -> Optional[WorkflowSessionRowDAO]:
        """Return the attached registry's current row for a key of this owner, without file reads.

        Args:
            key (WorkflowSessionKeyDAO): Requested key.

        Returns:
            Optional[WorkflowSessionRowDAO]: Current attached row; None for a detached
                key or a key the latest batch no longer holds.
        """
        if not self._is_attached(key=key):
            return None
        return self._find_row(rows=self._attached_rows(attached=self._attached_snapshot()), key=key)

    def _is_attached(self, *, key: WorkflowSessionKeyDAO) -> bool:
        """Return whether a key belongs to this owner's attached batch.

        Args:
            key (WorkflowSessionKeyDAO): Row key.

        Returns:
            bool: True when the owner session is the key's orchestrator.
        """
        return key.orchestrator_session_id == self._owner_session_id

    async def _current_detached_row(self, *, key: WorkflowSessionKeyDAO) -> Optional[WorkflowSessionRowDAO]:
        """Re-read one owned, undismissed detached group through the bounded loader.

        Args:
            key (WorkflowSessionKeyDAO): Detached key.

        Returns:
            Optional[WorkflowSessionRowDAO]: Current row, or None when the group is
                no longer owned/visible or its valid membership lacks the key.

        Raises:
            OSError: When the group cannot be read.
            ValueError: When the group is unavailable or untrusted.
        """
        handle: Optional[WorkflowHandleDAO] = self._visible_handle(
            orchestrator_session_id=key.orchestrator_session_id
        )
        if handle is None:
            return None
        group: WorkflowDataDAO = await self._loader(
            parent_session_id=handle.orchestrator_session_id
        ).load_observation_group()
        return self._authoritative_row(
            rows=self._project_group(handle=handle, group=group), group=group, key=key
        )

    @classmethod
    def _authoritative_row(
        cls,
        *,
        rows: tuple[WorkflowSessionRowDAO, ...],
        group: WorkflowDataDAO,
        key: WorkflowSessionKeyDAO,
    ) -> Optional[WorkflowSessionRowDAO]:
        """Return the fresh row for a known key; only valid fleet evidence proves absence.

        Args:
            rows (tuple[WorkflowSessionRowDAO, ...]): Fresh group projection.
            group (WorkflowDataDAO): The group that projection came from.
            key (WorkflowSessionKeyDAO): Previously listed key being re-checked.

        Returns:
            Optional[WorkflowSessionRowDAO]: Current row, or None when a present,
                valid fleet no longer lists the key.

        Raises:
            ValueError: The key is absent but the group has no fleet evidence, so a
                missing file must not be read as deletion.
        """
        row: Optional[WorkflowSessionRowDAO] = cls._find_row(rows=rows, key=key)
        if row is None and group.fleet_snapshot is None:
            raise ValueError(OBSERVATION_UNAVAILABLE_MESSAGE)
        return row

    def _visible_handle(self, *, orchestrator_session_id: str) -> Optional[WorkflowHandleDAO]:
        """Return the admitted, undismissed handle that owns one orchestrator.

        Args:
            orchestrator_session_id (str): Detached parent id.

        Returns:
            Optional[WorkflowHandleDAO]: Owning handle, or None.
        """
        return next(
            (
                handle
                for handle in self._handles.values()
                if handle.orchestrator_session_id == orchestrator_session_id
                and handle.workflow_id not in self._dismissed
            ),
            None,
        )

    @staticmethod
    def _find_row(
        *,
        rows: tuple[WorkflowSessionRowDAO, ...],
        key: WorkflowSessionKeyDAO,
    ) -> Optional[WorkflowSessionRowDAO]:
        """Return the row with ``key`` from one fresh projection.

        Args:
            rows (tuple[WorkflowSessionRowDAO, ...]): Fresh projection.
            key (WorkflowSessionKeyDAO): Requested key.

        Returns:
            Optional[WorkflowSessionRowDAO]: Matching row, or None.
        """
        return next((row for row in rows if row.key == key), None)

    @classmethod
    def _accept_progress(
        cls,
        *,
        row: WorkflowSessionRowDAO,
        current: Optional[WorkflowSessionRowDAO],
        snapshot: SessionProgressSnapshotDAO,
    ) -> SessionProgressSnapshotDAO:
        """Reject stale membership after a bounded loader read, before painting.

        Args:
            row (WorkflowSessionRowDAO): Identity captured before the read.
            current (Optional[WorkflowSessionRowDAO]): Authoritative membership reread.
            snapshot (SessionProgressSnapshotDAO): Uncommitted observation result.

        Returns:
            SessionProgressSnapshotDAO: Original matching result or a safe refusal.
        """
        if current is None:
            return cls._progress_notice(key=row.key, removed=True)
        if (row.execution_id, row.dispatch_id) != (current.execution_id, current.dispatch_id):
            return cls._progress_notice(key=row.key, row=row)
        return snapshot

    @staticmethod
    def _progress_notice(
        *,
        key: WorkflowSessionKeyDAO,
        removed: bool = False,
        row: Optional[WorkflowSessionRowDAO] = None,
        availability: SessionProgressAvailability = "stale",
    ) -> SessionProgressSnapshotDAO:
        """Return a content-free observation refusal without leaking adapter errors.

        Args:
            key (WorkflowSessionKeyDAO): Requested owner-scoped identity.
            removed (bool, optional): True only when authoritative membership is
                absent. Defaults to False.
            row (Optional[WorkflowSessionRowDAO], optional): Captured row whose
                identities the refusal carries; None for a removal. Defaults to None.
            availability (SessionProgressAvailability, optional): ``unavailable`` for
                a no-history session. Defaults to ``"stale"``.

        Returns:
            SessionProgressSnapshotDAO: No new content and no abort authority.
        """
        from src.tui.workflow_visualizer_loader import PROGRESS_UNAVAILABLE_NOTICE

        return SessionProgressSnapshotDAO(
            key=key,
            execution_id=row.execution_id if row is not None else "",
            dispatch_id=row.dispatch_id if row is not None else "",
            entries=(),
            revision="",
            source_generation="",
            availability=availability,
            observed_at=datetime.now(tz=timezone.utc).isoformat(),
            status="unknown",
            task_text="",
            task_text_complete=False,
            membership_removed=removed,
            notice=SESSION_REMOVED_NOTICE if removed else PROGRESS_UNAVAILABLE_NOTICE,
        )

    # ── feature 94 a.4: child-abort control ─────────────────────────────────

    def begin_child_abort(self, *, target: ChildAbortTargetDAO) -> None:
        """Retain one confirmed submission even if the progress screen minimizes.

        WHAT: Allocates the request once and starts one service-owned submission
            task; a request for the same incarnation that is still pending, or
            whose operation task still runs, absorbs repeats (double activation
            or a stale confirmation), so ``close`` always joins that task. Only
            a settled request with a finished task allows an explicit new
            request. The task's outcome and failures are always retrieved.
        WHO: SloTUI after the operator explicitly confirmed this exact target.
        WHEN: Once per confirmation; never retried automatically.

        Args:
            target (ChildAbortTargetDAO): Immutable identity captured at confirmation.
        """
        tracked: Optional[ChildAbortSubmission] = self._tracked_submission(
            key=target.key, execution_id=target.execution_id
        )
        if self._closed or (tracked is not None and tracked.blocks_new_request):
            return
        self._abort_requests.pop(target, None)
        self._abort_submissions.pop(target, None)
        try:
            request: ChildAbortRequestDAO = self._request_for(target=target)
        except ValueError:
            log_warning(msg="child_abort_target_invalid")
            return
        operation: asyncio.Task[ChildAbortOutcomeDAO] = asyncio.create_task(
            self.request_child_abort(target=target)
        )
        operation.add_done_callback(self._observe_submission)
        self._abort_submissions[target] = ChildAbortSubmission(
            target=target,
            request=request,
            operation=operation,
            started_at=self._monotonic(),
            attached=self._is_attached(key=target.key),
        )

    @staticmethod
    def _observe_submission(task: asyncio.Task[ChildAbortOutcomeDAO]) -> None:
        """Retrieve failures when a service-owned submission finishes off-screen.

        Args:
            task (asyncio.Task[ChildAbortOutcomeDAO]): Tracked submission task.
        """
        if not task.cancelled():
            task.exception()

    async def request_child_abort(self, *, target: ChildAbortTargetDAO) -> ChildAbortOutcomeDAO:
        """Revalidate the confirmed identity and submit exactly once to its owner.

        WHAT: Checks owner, membership, accepting capability/liveness, run,
            incarnation and terminal state afresh, then hands the request to the
            attached pool facade or commits it to the detached control store.
            Every refusal or adapter failure is a fixed outcome; nothing falls
            back to signals and nothing is retried.
        WHO: ``begin_child_abort``'s tracked task (UI callers never await it directly).
        WHEN: Right after confirmation.

        Args:
            target (ChildAbortTargetDAO): Captured key/run/incarnation, not a PID.

        Returns:
            ChildAbortOutcomeDAO: Requested after durable commit, the attached
                pool's observed outcome, or a fixed refusal.
        """
        request: ChildAbortRequestDAO = self._request_for(target=target)
        try:
            await self._require_abort_authority(target=target)
            return await self._submit_child_abort(request=request)
        except ChildAbortRefused as refusal:
            return ChildAbortOutcomeDAO.for_request(request=request, outcome=refusal.outcome)
        except (OSError, ValueError):
            return ChildAbortOutcomeDAO.for_request(request=request, outcome="unavailable")

    def _request_for(self, *, target: ChildAbortTargetDAO) -> ChildAbortRequestDAO:
        """Allocate once before any asynchronous validation or atomic submission.

        Args:
            target (ChildAbortTargetDAO): Confirmation identity.

        Returns:
            ChildAbortRequestDAO: Same request on every observation of this target.

        Raises:
            ValueError: The target's identities are unsafe for the control protocol.
        """
        if target not in self._abort_requests:
            self._abort_requests[target] = ChildAbortRequestDAO(
                request_id=str(uuid4()),
                owner_session_id=self._owner_session_id,
                orchestrator_session_id=target.key.orchestrator_session_id,
                session_id=target.key.session_id,
                run_id=target.run_id,
                execution_id=target.execution_id,
            )
        return self._abort_requests[target]

    async def _require_abort_authority(self, *, target: ChildAbortTargetDAO) -> None:
        """Refuse unless the target is still this owner's current, accepting, live child.

        Args:
            target (ChildAbortTargetDAO): Confirmed identity.

        Raises:
            ChildAbortRefused: not_owned, unavailable or already_terminal.
            OSError: A detached file read failed.
            ValueError: Detached evidence is unavailable or untrusted.
        """
        if self._closed:
            raise ChildAbortRefused(outcome="unavailable")
        if self._is_attached(key=target.key):
            self._require_attached_authority(target=target)
            return
        await self._require_detached_authority(target=target)

    def _require_attached_authority(self, *, target: ChildAbortTargetDAO) -> None:
        """Check the attached registry row and the pool's capability synchronously.

        Args:
            target (ChildAbortTargetDAO): Attached target.

        Raises:
            ChildAbortRefused: not_owned, unavailable or already_terminal.
        """
        row: Optional[WorkflowSessionRowDAO] = self._current_attached_row(key=target.key)
        if row is None:
            raise ChildAbortRefused(outcome="not_owned")
        self._require_same_execution(row=row, target=target, run_id=self._attached_run_id())

    async def _require_detached_authority(self, *, target: ChildAbortTargetDAO) -> None:
        """Check the owned live handle, capability and a fresh bounded group read.

        Ownership and liveness are re-checked after every await: a dismissal,
        close or orchestrator death while reading refuses rather than submitting
        for a group no longer owned or served.

        Args:
            target (ChildAbortTargetDAO): Detached target.

        Raises:
            ChildAbortRefused: not_owned, unavailable or already_terminal.
            OSError: A file read failed.
            ValueError: The group is unavailable or untrusted.
        """
        if self._history_store is None:
            raise ChildAbortRefused(outcome="unavailable")
        parent: str = target.key.orchestrator_session_id
        run_id: str = await self._detached_run_id(parent=parent)
        handle: WorkflowHandleDAO = self._live_owned_handle(parent=parent)
        group: WorkflowDataDAO = await self._loader(parent_session_id=parent).load_observation_group()
        rows: tuple[WorkflowSessionRowDAO, ...] = self._project_group(handle=handle, group=group)
        row: Optional[WorkflowSessionRowDAO] = self._authoritative_row(rows=rows, group=group, key=target.key)
        if row is None:
            raise ChildAbortRefused(outcome="not_owned")
        self._live_owned_handle(parent=parent)
        self._require_group_run(parent_row=rows[0], run_id=run_id)
        self._require_same_execution(row=row, target=target, run_id=run_id)

    @staticmethod
    def _require_same_execution(
        *, row: WorkflowSessionRowDAO, target: ChildAbortTargetDAO, run_id: str
    ) -> None:
        """Refuse another run or incarnation, then a terminal execution.

        Args:
            row (WorkflowSessionRowDAO): Current authoritative row of the target key.
            target (ChildAbortTargetDAO): Confirmed identity.
            run_id (str): Run of the current accepting capability.

        Raises:
            ChildAbortRefused: unavailable for a changed run/incarnation;
                already_terminal for a terminal row.
        """
        if (run_id, row.execution_id) != (target.run_id, target.execution_id):
            raise ChildAbortRefused(outcome="unavailable")
        if row.status in TERMINAL_STATUSES:
            raise ChildAbortRefused(outcome="already_terminal")

    @staticmethod
    def _require_group_run(*, parent_row: WorkflowSessionRowDAO, run_id: str) -> None:
        """Refuse a group whose execution index belongs to another runner invocation.

        Args:
            parent_row (WorkflowSessionRowDAO): Group parent row; its dispatch_id is the index run.
            run_id (str): Run of the current accepting capability.

        Raises:
            ChildAbortRefused: unavailable when the runs differ.
        """
        if parent_row.dispatch_id != run_id:
            raise ChildAbortRefused(outcome="unavailable")

    def _attached_run_id(self) -> str:
        """Return the attached pool's run while it accepts and a facade exists.

        Returns:
            str: Current attached run UUID.

        Raises:
            ChildAbortRefused: unavailable without facade, pool or accepting capability.
        """
        capability: Optional[ChildControlCapabilityDAO] = (
            self._attached_capability() if self._attached_capability is not None else None
        )
        if self._attached_abort is None or not self._accepts(
            capability=capability, parent=self._owner_session_id
        ):
            raise ChildAbortRefused(outcome="unavailable")
        assert capability is not None  # narrowed by _accepts
        return capability.run_id

    async def _detached_run_id(self, *, parent: str) -> str:
        """Return the run a live owned orchestrator currently accepts requests for.

        Args:
            parent (str): Detached orchestrator session.

        Returns:
            str: Accepting capability's run UUID.

        Raises:
            ChildAbortRefused: not_owned without an owned visible handle; unavailable
                without live evidence or a matching accepting capability.
            OSError: The capability read failed.
        """
        self._live_owned_handle(parent=parent)
        capability: Optional[ChildControlCapabilityDAO] = await self._control_store(
            parent=parent
        ).load_capability()
        if not self._accepts(capability=capability, parent=parent):
            raise ChildAbortRefused(outcome="unavailable")
        assert capability is not None  # narrowed by _accepts
        return capability.run_id

    def _live_owned_handle(self, *, parent: str) -> WorkflowHandleDAO:
        """Return the owned handle while the service is open and its orchestrator lives.

        WHO: Detached authority, before and again after each await.

        Args:
            parent (str): Detached orchestrator session.

        Returns:
            WorkflowHandleDAO: Owned, undismissed handle with live orchestrator evidence.

        Raises:
            ChildAbortRefused: not_owned once closed or without an owned visible
                handle; unavailable without live orchestrator evidence.
        """
        handle: Optional[WorkflowHandleDAO] = (
            None if self._closed else self._visible_handle(orchestrator_session_id=parent)
        )
        if handle is None:
            raise ChildAbortRefused(outcome="not_owned")
        if self._store is None or not self._store.is_live(handle=handle):
            raise ChildAbortRefused(outcome="unavailable")
        return handle

    def _accepts(self, *, capability: Optional[ChildControlCapabilityDAO], parent: str) -> bool:
        """Return whether a capability accepts requests from this owner for ``parent``.

        Args:
            capability (Optional[ChildControlCapabilityDAO]): Current capability, if any.
            parent (str): Expected orchestrator session.

        Returns:
            bool: True for an accepting capability naming this owner and parent.
        """
        if capability is None or not capability.accepting:
            return False
        return (capability.owner_session_id, capability.orchestrator_session_id) == (
            self._owner_session_id,
            parent,
        )

    async def _submit_child_abort(self, *, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        """Select the attached facade or detached atomic channel after validation.

        Args:
            request (ChildAbortRequestDAO): Validated immutable request.

        Returns:
            ChildAbortOutcomeDAO: Canonical attached result or durable admission receipt.

        Raises:
            ChildAbortRefused: unavailable without facade or history root.
            OSError: The detached write failed before commit.
            ValueError: The store refused (capability, conflict or capacity).
        """
        if request.orchestrator_session_id != self._owner_session_id:
            return await self._control_store(parent=request.orchestrator_session_id).submit(request=request)
        if self._attached_abort is None:
            raise ChildAbortRefused(outcome="unavailable")
        return await self._attached_outcome(attached_abort=self._attached_abort, request=request)

    @staticmethod
    async def _attached_outcome(
        *, attached_abort: AttachedChildAbort, request: ChildAbortRequestDAO
    ) -> ChildAbortOutcomeDAO:
        """Await the attached pool's outcome; an unexpected failure is unresolved.

        Args:
            attached_abort (AttachedChildAbort): Session → pool facade.
            request (ChildAbortRequestDAO): Validated request.

        Returns:
            ChildAbortOutcomeDAO: Pool outcome, or the fixed unresolved outcome.
        """
        try:
            return await attached_abort(request=request)
        except Exception:  # noqa: BLE001 - boundary: execution truth unknown, never claim abort
            log_warning(msg="child_abort_attached_unresolved")
            return ChildAbortOutcomeDAO.for_request(request=request, outcome="unresolved")

    def _control_store(self, *, parent: str) -> ChildAbortStore:
        """Reuse one same-root control adapter per detached parent.

        Args:
            parent (str): Detached orchestrator session.

        Returns:
            ChildAbortStore: Adapter bound to the session's history root.

        Raises:
            ChildAbortRefused: unavailable for a no-history session.
            ValueError: The parent identity is unsafe as a path component.
        """
        if self._history_store is None:
            raise ChildAbortRefused(outcome="unavailable")
        store: ChildAbortStore = self._control_stores.get(parent) or ChildAbortStore(
            history_root=self._history_store.root, orchestrator_session_id=parent
        )
        if not self._closed:
            self._control_stores[parent] = store
        return store

    async def _with_abort_control(
        self,
        *,
        snapshot: SessionProgressSnapshotDAO,
        current: Optional[WorkflowSessionRowDAO],
    ) -> SessionProgressSnapshotDAO:
        """Attach the eligible abort target and the tracked request's notice.

        Args:
            snapshot (SessionProgressSnapshotDAO): Accepted progress or fixed notice.
            current (Optional[WorkflowSessionRowDAO]): Authoritative current row.

        Returns:
            SessionProgressSnapshotDAO: Same content; target only when eligible and
                no request for this incarnation is pending.
        """
        if snapshot.membership_removed:
            return snapshot
        tracked: Optional[ChildAbortSubmission] = self._tracked_submission(
            key=snapshot.key, execution_id=snapshot.execution_id
        )
        blocked: bool = tracked is not None and tracked.blocks_new_request
        target: Optional[ChildAbortTargetDAO] = (
            None if blocked else await self._eligible_target(snapshot=snapshot, current=current)
        )
        return snapshot.model_copy(
            update={"abort_target": target, "notice": self._abort_notice(snapshot=snapshot, tracked=tracked)}
        )

    def _abort_notice(
        self, *, snapshot: SessionProgressSnapshotDAO, tracked: Optional[ChildAbortSubmission]
    ) -> Optional[str]:
        """Combine the observation notice with the tracked request's fixed notice.

        Args:
            snapshot (SessionProgressSnapshotDAO): Progress being decorated.
            tracked (Optional[ChildAbortSubmission]): Request for this incarnation.

        Returns:
            Optional[str]: Combined notice, or the original one without a request.
        """
        if tracked is None:
            return snapshot.notice
        notice: str = tracked.notice(now=self._monotonic())
        return notice if snapshot.notice is None else f"{snapshot.notice} · {notice}"

    async def _eligible_target(
        self,
        *,
        snapshot: SessionProgressSnapshotDAO,
        current: Optional[WorkflowSessionRowDAO],
    ) -> Optional[ChildAbortTargetDAO]:
        """Return the exact target for a current, abortable, accepting child, else None.

        Args:
            snapshot (SessionProgressSnapshotDAO): Progress being decorated.
            current (Optional[WorkflowSessionRowDAO]): Authoritative current row.

        Returns:
            Optional[ChildAbortTargetDAO]: Target bound to the current run and incarnation.
        """
        if current is None or not self._abortable(row=current, snapshot=snapshot):
            return None
        try:
            run_id: str = await self._accepting_run_id(key=current.key)
        except (ChildAbortRefused, OSError, ValueError):
            return None
        return ChildAbortTargetDAO(key=current.key, run_id=run_id, execution_id=current.execution_id)

    def _abortable(self, *, row: WorkflowSessionRowDAO, snapshot: SessionProgressSnapshotDAO) -> bool:
        """Return whether a fresh child row of the observed incarnation may be aborted.

        Detached status comes from files, so a stale or unavailable read disables
        Abort even though old content stays painted; attached status is the
        in-memory registry and needs no readable transcript.

        Args:
            row (WorkflowSessionRowDAO): Authoritative current row.
            snapshot (SessionProgressSnapshotDAO): Progress observed for it.

        Returns:
            bool: True for a nonterminal child with a modern identity matching the observation.
        """
        current: bool = (
            row.role == "child"
            and row.execution_id != ""
            and row.execution_id == snapshot.execution_id
            and row.status in _ABORTABLE_STATUSES
            and row.availability == "available"
        )
        return current and (self._is_attached(key=row.key) or snapshot.availability in _READABLE_PROGRESS)

    async def _accepting_run_id(self, *, key: WorkflowSessionKeyDAO) -> str:
        """Return the run currently accepting requests for the key's owner.

        Args:
            key (WorkflowSessionKeyDAO): Child key.

        Returns:
            str: Accepting run UUID; for detached groups it must match the listed index run.

        Raises:
            ChildAbortRefused: not_owned or unavailable.
            OSError: The capability read failed.
        """
        if self._is_attached(key=key):
            return self._attached_run_id()
        parent: str = key.orchestrator_session_id
        run_id: str = await self._detached_run_id(parent=parent)
        parent_row: Optional[WorkflowSessionRowDAO] = self._rows.get(
            WorkflowSessionKeyDAO(orchestrator_session_id=parent, session_id=parent)
        )
        if parent_row is None:
            raise ChildAbortRefused(outcome="not_owned")
        self._require_group_run(parent_row=parent_row, run_id=run_id)
        return run_id

    def _tracked_submission(
        self, *, key: WorkflowSessionKeyDAO, execution_id: str
    ) -> Optional[ChildAbortSubmission]:
        """Return the latest tracked request for one key and incarnation.

        Args:
            key (WorkflowSessionKeyDAO): Child key.
            execution_id (str): Incarnation; empty (legacy/parent) never matches.

        Returns:
            Optional[ChildAbortSubmission]: Latest request, or None.
        """
        return next(
            (
                submission
                for submission in reversed(self._abort_submissions.values())
                if execution_id
                and (submission.target.key, submission.target.execution_id) == (key, execution_id)
            ),
            None,
        )

    async def _observe_abort_submissions(self, *, rows: tuple[WorkflowSessionRowDAO, ...]) -> None:
        """Settle tracked requests from terminal rows first, then matching receipts.

        Runs on every list refresh, so requests settle even while no progress view
        is open. A row of another incarnation never settles or inherits a request.

        Args:
            rows (tuple[WorkflowSessionRowDAO, ...]): Rows just committed.
        """
        for submission in tuple(self._abort_submissions.values()):
            row: Optional[WorkflowSessionRowDAO] = self._find_row(rows=rows, key=submission.target.key)
            if row is None or not submission.concerns(row=row):
                continue
            submission.observe_row(row=row)
            if submission.awaits_receipt:
                submission.observe_receipt(receipt=await self._load_receipt(request=submission.request))

    async def _load_receipt(self, *, request: ChildAbortRequestDAO) -> Optional[ChildAbortOutcomeDAO]:
        """Read one detached receipt; unreadable storage keeps the request pending.

        Args:
            request (ChildAbortRequestDAO): Admitted detached request.

        Returns:
            Optional[ChildAbortOutcomeDAO]: Store-validated receipt, or None.
        """
        try:
            return await self._control_store(parent=request.orchestrator_session_id).load_receipt(
                request=request
            )
        except (ChildAbortRefused, OSError, ValueError):
            return None

    # ── feature 94 observation: attached projection ─────────────────────────

    async def _project_attached_group(
        self,
        *,
        attached: AttachedDispatchSnapshotDAO,
    ) -> tuple[WorkflowSessionRowDAO, ...]:
        """Project the latest registry batch; loader enrichment cannot add members.

        Args:
            attached (AttachedDispatchSnapshotDAO): Captured admitted batch.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: Parent and exact registry children in
                registration order; empty when the batch has no entries.
        """
        rows: tuple[WorkflowSessionRowDAO, ...] = self._attached_rows(attached=attached)
        if not rows:
            return ()
        return (rows[0], *await self._enrich_attached_rows(rows=rows[1:]))

    def _attached_rows(self, *, attached: AttachedDispatchSnapshotDAO) -> tuple[WorkflowSessionRowDAO, ...]:
        """Map a captured batch to its parent and registry children without file reads.

        Args:
            attached (AttachedDispatchSnapshotDAO): Captured admitted batch.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: Parent then children with registry
                previews; empty when the batch has no entries or is still hidden.
        """
        rows: tuple[WorkflowSessionRowDAO, ...] = self._batch_rows(attached=attached)
        return () if self._hides_attached(rows=rows) else rows

    def _batch_rows(self, *, attached: AttachedDispatchSnapshotDAO) -> tuple[WorkflowSessionRowDAO, ...]:
        """Map a captured batch to its parent and registry children, ignoring suppression.

        Args:
            attached (AttachedDispatchSnapshotDAO): Captured admitted batch.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: Parent then children; empty when the
                batch has no entries.
        """
        if not attached.entries:
            return ()
        children: tuple[WorkflowSessionRowDAO, ...] = tuple(
            self._attached_row(entry=entry, dispatch_id=attached.dispatch_id) for entry in attached.entries
        )
        return (self._attached_parent_row(attached=attached), *children)

    def _attached_parent_row(self, *, attached: AttachedDispatchSnapshotDAO) -> WorkflowSessionRowDAO:
        """Build the owner's parent row describing the displayed batch, not the inference session.

        Args:
            attached (AttachedDispatchSnapshotDAO): Nonempty captured batch.

        Returns:
            WorkflowSessionRowDAO: Parent row keyed by the owner session.
        """
        return WorkflowSessionRowDAO(
            key=WorkflowSessionKeyDAO(
                orchestrator_session_id=self._owner_session_id,
                session_id=self._owner_session_id,
            ),
            role="orchestrator",
            status=self._batch_status(entries=attached.entries),
            dispatch_id=attached.dispatch_id,
            task_text="Orchestrator",
            task_text_complete=True,
        )

    @staticmethod
    def _batch_status(*, entries: tuple[SubAgentStatusDAO, ...]) -> str:
        """Choose a display-only aggregate after attached membership is captured.

        Args:
            entries (tuple[SubAgentStatusDAO, ...]): Nonempty current batch.

        Returns:
            str: ``running`` while any child is pending/running, else ``failed`` if
                any failed, else ``aborted`` if any aborted, else ``completed``.
        """
        statuses: set[str] = {entry.status for entry in entries}
        if statuses & {"pending", "running"}:
            return "running"
        if "failed" in statuses:
            return "failed"
        return "aborted" if "aborted" in statuses else "completed"

    def _attached_row(self, *, entry: SubAgentStatusDAO, dispatch_id: str) -> WorkflowSessionRowDAO:
        """Translate registry data without fabricating full pending task text.

        Args:
            entry (SubAgentStatusDAO): Captured child execution.
            dispatch_id (str): Batch identity captured with it.

        Returns:
            WorkflowSessionRowDAO: Display-only row, not cancellation authority.
        """
        return WorkflowSessionRowDAO(
            key=WorkflowSessionKeyDAO(
                orchestrator_session_id=self._owner_session_id, session_id=entry.session_id
            ),
            role="child",
            task_id=entry.task_id,
            execution_id=entry.execution_id,
            dispatch_id=dispatch_id,
            status=entry.status,
            task_text=entry.prompt_preview,
            task_text_complete=False,
        )

    async def _enrich_attached_rows(
        self,
        *,
        rows: tuple[WorkflowSessionRowDAO, ...],
    ) -> tuple[WorkflowSessionRowDAO, ...]:
        """Ask the existing loader for matching task text without discovery.

        Args:
            rows (tuple[WorkflowSessionRowDAO, ...]): Registry-authorized rows.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: Same identities, order and statuses;
                original previews when no history adapter exists.
        """
        if self._history_store is None:
            return rows
        loader: WorkflowVisualizerLoader = self._loader(parent_session_id=self._owner_session_id)
        return tuple([await self._enrich_attached_row(loader=loader, row=row) for row in rows])

    @staticmethod
    async def _enrich_attached_row(
        *,
        loader: WorkflowVisualizerLoader,
        row: WorkflowSessionRowDAO,
    ) -> WorkflowSessionRowDAO:
        """Keep the registry row when its storage cannot be read.

        Args:
            loader (WorkflowVisualizerLoader): Owner-group loader.
            row (WorkflowSessionRowDAO): Registry-authorized row.

        Returns:
            WorkflowSessionRowDAO: Enriched copy, or the original row on storage failure.
        """
        try:
            return await loader.enrich_task_row(row=row)
        except (OSError, ValueError):
            return row

    def _loader(self, *, parent_session_id: str) -> WorkflowVisualizerLoader:
        """Reuse the bounded loader for one group at observation time.

        Args:
            parent_session_id (str): Already authorized exact parent, never a name.

        Returns:
            WorkflowVisualizerLoader: Same-root cached adapter; after ``close`` an
                uncached one, so in-flight work cannot repopulate the cache.

        Raises:
            ValueError: No history adapter is available for this session.
        """
        from src.tui.workflow_visualizer_loader import (
            HeadlessWorkflowVisualizerConfigDAO,
            WorkflowVisualizerLoader,
        )

        if self._history_store is None:
            raise ValueError("observation storage unavailable")
        loader: WorkflowVisualizerLoader = self._loaders.get(parent_session_id) or WorkflowVisualizerLoader(
            config=HeadlessWorkflowVisualizerConfigDAO(session_reference=parent_session_id),
            store=self._history_store,
        )
        if not self._closed:
            self._loaders[parent_session_id] = loader
        return loader

    # ── feature 94 observation: detached projection and retention ───────────

    async def _load_group(self, *, handle: WorkflowHandleDAO) -> tuple[WorkflowSessionRowDAO, ...]:
        """Read one owned detached group, keeping last-good rows when discovery fails.

        Args:
            handle (WorkflowHandleDAO): Previously validated owned handle.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: Fresh group, or stale/unavailable retention.
        """
        try:
            group: WorkflowDataDAO = await self._loader(
                parent_session_id=handle.orchestrator_session_id
            ).load_observation_group()
            rows: tuple[WorkflowSessionRowDAO, ...] = self._project_group(handle=handle, group=group)
        except (OSError, ValueError):
            return self._retain_failed_group(handle=handle)
        return self._cache_group(
            handle=handle, rows=self._retain_unconfirmed_children(handle=handle, group=group, rows=rows)
        )

    def _retain_unconfirmed_children(
        self,
        *,
        handle: WorkflowHandleDAO,
        group: WorkflowDataDAO,
        rows: tuple[WorkflowSessionRowDAO, ...],
    ) -> tuple[WorkflowSessionRowDAO, ...]:
        """Keep known children a group without fleet evidence no longer shows, marked stale.

        Only a present, valid fleet replaces child membership (a.2): a missing
        ``fleet.json`` or a vanished directory-only child is a missing file, not
        a deletion.

        Args:
            handle (WorkflowHandleDAO): Group owner.
            group (WorkflowDataDAO): Fresh available group.
            rows (tuple[WorkflowSessionRowDAO, ...]): Its fresh projection.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: Fresh rows, then retained stale children.
        """
        if group.fleet_snapshot is not None:
            return rows
        fresh_keys: set[WorkflowSessionKeyDAO] = {row.key for row in rows}
        previous: tuple[WorkflowSessionRowDAO, ...] = self._group_rows.get(handle.orchestrator_session_id, ())
        return (*rows, *self._mark_stale(rows=tuple(row for row in previous if row.key not in fresh_keys)))

    def _cache_group(
        self, *, handle: WorkflowHandleDAO, rows: tuple[WorkflowSessionRowDAO, ...]
    ) -> tuple[WorkflowSessionRowDAO, ...]:
        """Remember last-good group rows unless the service closed during the read.

        Args:
            handle (WorkflowHandleDAO): Group owner.
            rows (tuple[WorkflowSessionRowDAO, ...]): Rows to retain for later failures.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: The same rows.
        """
        if not self._closed:
            self._group_rows[handle.orchestrator_session_id] = rows
        return rows

    def _retain_failed_group(self, *, handle: WorkflowHandleDAO) -> tuple[WorkflowSessionRowDAO, ...]:
        """Never translate unreadable files into deletion during service refresh.

        Args:
            handle (WorkflowHandleDAO): Owner identity available despite failed data.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: Retained rows marked stale, or one
                unavailable parent row when no last-good rows exist.
        """
        previous: Optional[tuple[WorkflowSessionRowDAO, ...]] = self._group_rows.get(
            handle.orchestrator_session_id
        )
        if previous is not None:
            return self._mark_stale(rows=previous)
        return (
            WorkflowSessionRowDAO(
                key=WorkflowSessionKeyDAO(
                    orchestrator_session_id=handle.orchestrator_session_id,
                    session_id=handle.orchestrator_session_id,
                ),
                workflow_id=handle.workflow_id,
                role="orchestrator",
                status=handle.state,
                task_text=handle.brief,
                task_text_complete=True,
                availability="unavailable",
            ),
        )

    @staticmethod
    def _mark_stale(*, rows: tuple[WorkflowSessionRowDAO, ...]) -> tuple[WorkflowSessionRowDAO, ...]:
        """Mark retained fresh rows stale; unavailable rows keep their stronger state.

        Args:
            rows (tuple[WorkflowSessionRowDAO, ...]): Retained rows.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: Same rows with ``available`` → ``stale``.
        """
        return tuple(
            row.model_copy(update={"availability": "stale"}) if row.availability == "available" else row
            for row in rows
        )

    def _project_group(
        self,
        *,
        handle: WorkflowHandleDAO,
        group: WorkflowDataDAO,
    ) -> tuple[WorkflowSessionRowDAO, ...]:
        """Map a validated bounded detached group to literal display records.

        Args:
            handle (WorkflowHandleDAO): Owner-scoped handle.
            group (WorkflowDataDAO): Bounded existing-loader discovery result.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: Parent first, then children in the
                loader's fleet-registration-then-legacy order.

        Raises:
            ValueError: Group identity or availability cannot be trusted.
        """
        if group.parent_session_id != handle.orchestrator_session_id or group.availability == "unavailable":
            raise ValueError(OBSERVATION_UNAVAILABLE_MESSAGE)
        children: tuple[WorkflowSessionRowDAO, ...] = tuple(
            self._detached_child_row(handle=handle, child=child) for child in group.children
        )
        return (self._detached_parent_row(handle=handle, group=group), *children)

    @staticmethod
    def _detached_parent_row(*, handle: WorkflowHandleDAO, group: WorkflowDataDAO) -> WorkflowSessionRowDAO:
        """Choose parent display evidence after group validation, during projection.

        The parent row carries the current run identity in ``dispatch_id``: a
        detached parent has no dispatch of its own, and a.3 keys parent
        incarnation changes on the run (empty when unknown).

        Args:
            handle (WorkflowHandleDAO): Owned workflow identity and brief.
            group (WorkflowDataDAO): Bounded observation with optional self-report.

        Returns:
            WorkflowSessionRowDAO: Parent record; an absent or ``unknown``
                self-report keeps the handle state.
        """
        reported: str = group.orchestrator.state if group.orchestrator is not None else "unknown"
        return WorkflowSessionRowDAO(
            key=WorkflowSessionKeyDAO(
                orchestrator_session_id=handle.orchestrator_session_id,
                session_id=handle.orchestrator_session_id,
            ),
            workflow_id=handle.workflow_id,
            role="orchestrator",
            status=handle.state if reported == "unknown" else reported,
            task_text=handle.brief,
            task_text_complete=True,
            dispatch_id=group.run_id,
        )

    @staticmethod
    def _detached_child_row(
        *, handle: WorkflowHandleDAO, child: ChildSessionSummaryDAO
    ) -> WorkflowSessionRowDAO:
        """Copy public child summary fields without exposing paths or PIDs.

        Args:
            handle (WorkflowHandleDAO): Validated group owner.
            child (ChildSessionSummaryDAO): Existing loader's bounded public summary.

        Returns:
            WorkflowSessionRowDAO: Session-list row.
        """
        return WorkflowSessionRowDAO(
            key=WorkflowSessionKeyDAO(
                orchestrator_session_id=handle.orchestrator_session_id, session_id=child.session_id
            ),
            workflow_id=handle.workflow_id,
            task_id=child.task_id,
            role="child",
            execution_id=child.execution_id,
            dispatch_id=child.dispatch_id,
            status=child.status,
            task_text=child.task_text,
            task_text_complete=child.task_text_complete,
        )

    # ── feature 94 observation: owned membership ────────────────────────────

    def _adopt_dispatch(self, *, attached: AttachedDispatchSnapshotDAO) -> None:
        """Invalidate only attached cached content when polling sees a new batch.

        Args:
            attached (AttachedDispatchSnapshotDAO): Latest registry projection.
        """
        if attached.dispatch_id == self._attached_dispatch_id:
            return
        self._attached_dispatch_id = attached.dispatch_id
        self._group_rows.pop(self._owner_session_id, None)
        self._loaders.pop(self._owner_session_id, None)

    async def _read_owned_handles(self) -> tuple[WorkflowHandleDAO, ...]:
        """Read owned handles through the bounded API, retaining membership on failure.

        Returns:
            tuple[WorkflowHandleDAO, ...]: Admitted handles sorted by start then id;
                empty for a no-history session.
        """
        if self._history_store is None or self._store is None:
            return ()
        try:
            handles: tuple[WorkflowHandleDAO, ...] = await self._store.list_observation(
                owner_session_id=self._owner_session_id
            )
        except (OSError, ValueError):
            return self._retained_handles()
        return self._admit_handles(handles=handles)

    def _admit_handles(self, *, handles: tuple[WorkflowHandleDAO, ...]) -> tuple[WorkflowHandleDAO, ...]:
        """Merge a complete fresh listing; a vanished known handle is retention, not removal.

        Args:
            handles (tuple[WorkflowHandleDAO, ...]): Complete bounded owned listing.

        Returns:
            tuple[WorkflowHandleDAO, ...]: Admitted handles, sorted; empty once closed.
        """
        if self._closed:
            return ()
        admitted: dict[str, WorkflowHandleDAO] = {**self._handles, **{h.workflow_id: h for h in handles}}
        if len(admitted) > OBSERVATION_MAX_HANDLES:
            return self._retained_handles()
        self._handles = admitted
        self._set_observation_notice(notice=LIST_UNAVAILABLE_NOTICE if len(admitted) > len(handles) else None)
        return self._sorted_handles()

    def _retained_handles(self) -> tuple[WorkflowHandleDAO, ...]:
        """Keep last-known membership and flag the snapshot as stale.

        Returns:
            tuple[WorkflowHandleDAO, ...]: Previously admitted handles, sorted.
        """
        self._set_observation_notice(notice=LIST_UNAVAILABLE_NOTICE)
        return self._sorted_handles()

    def _sorted_handles(self) -> tuple[WorkflowHandleDAO, ...]:
        """Return admitted handles in detached group order.

        Returns:
            tuple[WorkflowHandleDAO, ...]: Sorted by ``started_at`` then ``workflow_id``.
        """
        return tuple(
            sorted(self._handles.values(), key=lambda handle: (handle.started_at, handle.workflow_id))
        )

    def _set_observation_notice(self, *, notice: Optional[str]) -> None:
        """Record the list notice, logging fixed reasons once per transition.

        Args:
            notice (Optional[str]): Fixed notice, or None for a fresh listing.
        """
        if notice != self._observation_notice:
            log_info(
                msg="workflow_observation_list_retained" if notice else "workflow_observation_list_fresh",
                owner_session_id=self._owner_session_id,
            )
        self._observation_notice = notice

    async def _project_detached_groups(
        self,
        *,
        handles: tuple[WorkflowHandleDAO, ...],
    ) -> tuple[WorkflowSessionRowDAO, ...]:
        """Read visible owned groups serially, yielding to the UI loop between groups.

        Args:
            handles (tuple[WorkflowHandleDAO, ...]): Admitted owner handles in order.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: Parent-first groups; dismissed groups omitted.
        """
        rows: list[WorkflowSessionRowDAO] = []
        for handle in (handle for handle in handles if handle.workflow_id not in self._dismissed):
            rows.extend(await self._observe_group(handle=handle))
            await asyncio.sleep(0)
        return tuple(rows)

    async def _observe_group(self, *, handle: WorkflowHandleDAO) -> tuple[WorkflowSessionRowDAO, ...]:
        """Load one group and mark it stale while owned membership is retained.

        Args:
            handle (WorkflowHandleDAO): Visible owned handle.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: Group rows; none once closed (no new reads).
        """
        if self._closed:
            return ()
        rows: tuple[WorkflowSessionRowDAO, ...] = await self._load_group(handle=handle)
        return rows if self._observation_notice is None else self._mark_stale(rows=rows)
