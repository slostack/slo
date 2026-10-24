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

from src.agents.slo_agent.orchestrator.task_preview import TaskPreview

import asyncio
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, List, Optional, Protocol, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

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
    LiveWorkflowLabelDAO,
    ParsedFleetUpdateDAO,
    ParsedLaunchResultDAO,
    ParsedWorkflowLifecycleMessageDAO,
    SessionProgressAvailability,
    SessionProgressSnapshotDAO,
    WorkflowListGroupDAO,
    WorkflowListGroupKeyDAO,
    WorkflowListVisibilityRequestDAO,
    WorkflowListVisibilityOutcomeDAO,
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


class WorkflowObservationLoader(Protocol):
    """Bounded read adapter borrowed by one observation owner."""

    async def load_observation_group(self) -> WorkflowDataDAO:
        """Read bounded parent and child membership without repairing files.

        Returns:
            WorkflowDataDAO: Bounded observation evidence.
        """

    async def enrich_task_row(self, *, row: WorkflowSessionRowDAO) -> WorkflowSessionRowDAO:
        """Enrich only the supplied current incarnation.

        Args:
            row: Authorized current row.

        Returns:
            WorkflowSessionRowDAO: Row with matching task detail.
        """

    async def load_session_progress(self, *, row: WorkflowSessionRowDAO) -> SessionProgressSnapshotDAO:
        """Read bounded progress for the authorized incarnation.

        Args:
            row: Authorized current row.

        Returns:
            SessionProgressSnapshotDAO: Bounded progress evidence.
        """


class WorkflowObservationLoaderFactory(Protocol):
    """Construct the bounded file adapter only when observation needs it."""

    def __call__(
        self, *, parent_session_id: str, history_store: SessionHistoryStoreProtocol
    ) -> WorkflowObservationLoader:
        """Return an adapter bound to the authorized parent and history root.

        Args:
            parent_session_id: Authorized parent identity.
            history_store: Borrowed bounded history adapter.

        Returns:
            WorkflowObservationLoader: Lazy read-only adapter.
        """


class _OwnedHandlesCandidateDAO(BaseModel):
    """Carry bounded ownership evidence without publishing membership."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    handles: tuple[WorkflowHandleDAO, ...] = Field(description="Owned union of retained and fresh handles.")
    fresh_ids: frozenset[str] = Field(default=frozenset(), description="IDs admitted by this complete read.")
    notice: Optional[str] = Field(default=None, description="Fixed retention warning.")


class _ObservationCandidateDAO(BaseModel):
    """Carry a complete unpublished observation transaction."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    visibility_revision: int = Field(ge=0, description="Revision captured before reading.")
    attached: AttachedDispatchSnapshotDAO = Field(description="Deep captured registry evidence.")
    handles: _OwnedHandlesCandidateDAO = Field(description="Unpublished ownership admission.")
    groups: tuple[WorkflowListGroupDAO, ...] = Field(description="Complete retained group candidates.")
    next_group_order: int = Field(ge=0, description="Unpublished ordering counter.")


class DetachedWorkflowAppService:
    """Coordinate detached-workflow lifecycle for one owning TUI session.

    Owns the ``WorkflowHandleStore`` reconcile/update calls, the legal
    durable transitions, and the ``workflow_id → state`` cache. Every public
    method translates untrusted input (inbox payloads, tool-result JSON) into
    typed domain objects first and returns typed outcomes — the caller never
    parses workflow JSON or lifecycle payloads itself.

    Feature 94 adds owner-scoped observation to the same service: session-list
    snapshots of the attached batch plus owned detached groups, explicit
    reversible in-memory visibility for running and finished groups, and
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
        loader_factory: Optional[WorkflowObservationLoaderFactory] = None,
        control_store_factory: Callable[..., ChildAbortStore] = ChildAbortStore,
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
            loader_factory (Optional[WorkflowObservationLoaderFactory]): Lazy bounded-loader
                construction seam; None selects the production adapter.
            control_store_factory: Existing child-control adapter constructor; tests may
                inject a gated real-file adapter. Defaults to ChildAbortStore.
            monotonic (Callable[[], float], optional): Clock for the 30-second
                abort-confirmation notice; tests inject a fake. Defaults to
                ``time.monotonic``.
        """
        self._control_store_factory = control_store_factory
        self._loader_factory: WorkflowObservationLoaderFactory = (
            loader_factory or self._build_observation_loader
        )
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
        self._list_groups: dict[WorkflowListGroupKeyDAO, WorkflowListGroupDAO] = {}
        self._next_group_order: int = 0
        self._visibility_revision: int = 0
        self._observation_lock = asyncio.Lock()
        self._loaders: dict[str, WorkflowObservationLoader] = {}
        self._handles: dict[str, WorkflowHandleDAO] = {}
        self._attached_dispatch_id: str = ""
        self._observation_notice: Optional[str] = None
        self._rows: dict[WorkflowSessionKeyDAO, WorkflowSessionRowDAO] = {}
        self._closed: bool = False
        self._close_task: Optional[asyncio.Task[None]] = None
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

    def advance_from_launch_result(self, *, result_text: str) -> HandleAdvanceOutcomeDAO:
        """Translate one ``launch_workflow`` tool-result text into UI effects.

        WHAT: parses the handle JSON; a valid result seeds the state cache
            (so the exit hint lists the workflow before its ``workflow_started``
            note is claimed) and returns one typed visualizer effect.
            Anything else is a safe no-op; no durable advance is claimed.
        WHO: the TUI live render path on ``launch_workflow`` tool results.
        WHEN: during the launch turn, when the tool result streams through.

        Args:
            result_text (str): Raw ``launch_workflow`` tool-result text.

        Returns:
            HandleAdvanceOutcomeDAO: Launch effect for a valid handle payload,
                empty effects for malformed, error, or orchestrator-id-less JSON.
        """
        parsed: Optional[ParsedLaunchResultDAO] = parse_launch_workflow_result(
            result_text=result_text,
        )
        if parsed is None:
            return HandleAdvanceOutcomeDAO()
        if parsed.workflow_id:
            self._workflow_states[parsed.workflow_id] = parsed.state
        return HandleAdvanceOutcomeDAO(
            workflow_id=parsed.workflow_id,
            effects=[
                DetachedWorkflowUiEffectDAO(
                    effect="launch_visualizer",
                    orchestrator_session_id=parsed.orchestrator_session_id,
                    state=parsed.state,
                )
            ],
        )

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
            owned detached group (including hidden membership), then projects visible
            attached-first, detached-by-start
            rows with duplicate keys removed. It never reconciles, sweeps, lists
            workflow text or loads full history, and has no process side effects.
        WHO: The a.3 refresh coordinator (immediate and five-second ticks).
        WHEN: On every observation refresh until ``close``.

        Returns:
            WorkflowSessionSnapshotDAO: Fresh rows, or explicitly stale retained rows
                with a fixed notice; empty once closed.
        """
        async with self._observation_lock:
            if self._closed:
                return WorkflowSessionSnapshotDAO()
            candidate = await self._gather_observation(
                visibility_revision=self._visibility_revision,
                retained=tuple(self._list_groups.values()),
            )
            if candidate is not None:
                self._commit_observation(candidate=candidate)
            self._release_hidden_detached_loaders()
            evidence = tuple(
                row
                for group in self._list_groups.values()
                if not group.retained_only
                for row in group.rows
                if row.availability == "available"
            )
        await self._observe_abort_submissions(rows=evidence)
        return self.current_list_snapshot()

    def _observation_invalid(self, *, revision: int) -> bool:
        """Reject work captured before a local change or disposal."""
        return self._closed or revision != self._visibility_revision

    async def _gather_observation(
        self, *, visibility_revision: int, retained: tuple[WorkflowListGroupDAO, ...]
    ) -> Optional[_ObservationCandidateDAO]:
        """Gather local records only; invalidated reads never publish partial state."""
        attached = self._attached_snapshot().model_copy(deep=True)
        groups = {group.key: group for group in retained}
        order = self._next_group_order
        attached_rows = await self._project_attached_group(attached=attached)
        if self._observation_invalid(revision=visibility_revision):
            return None
        handles = await self._read_owned_handles()
        if self._observation_invalid(revision=visibility_revision):
            return None
        order = await self._gather_detached_groups(
            groups=groups, order=order, admission=handles, visibility_revision=visibility_revision
        )
        if order is None:
            return None
        order = self._gather_attached_group(groups=groups, order=order, attached=attached, rows=attached_rows)
        return _ObservationCandidateDAO(
            visibility_revision=visibility_revision,
            attached=attached,
            handles=handles,
            groups=tuple(groups.values()),
            next_group_order=order,
        )

    async def _gather_detached_groups(
        self,
        *,
        groups: dict[WorkflowListGroupKeyDAO, WorkflowListGroupDAO],
        order: int,
        admission: _OwnedHandlesCandidateDAO,
        visibility_revision: int,
    ) -> Optional[int]:
        """Gather detached records in owned-handle order without publishing them.

        Args:
            groups: Candidate-local records; never the committed visibility map.
            order: Next unallocated first-seen ordinal.
            admission: Captured ownership and freshness evidence.
            visibility_revision: Revision checked after each asynchronous read.
        Returns:
            Optional[int]: Next ordinal, or None when gathering was invalidated.
        """
        for handle in admission.handles:
            key = WorkflowListGroupKeyDAO(kind="detached", group_id=handle.workflow_id)
            previous = groups.get(key)
            if previous is None:
                previous = WorkflowListGroupDAO(key=key, first_seen=order)
                order += 1
            rows = await self._gather_detached_rows(
                handle=handle,
                admission=admission,
                retained=previous.rows,
                visibility_revision=visibility_revision,
            )
            if rows is None:
                return None
            groups[key] = previous.model_copy(
                update={
                    "orchestrator_session_id": handle.orchestrator_session_id,
                    "started_at": handle.started_at,
                    "rows": rows,
                }
            )
        return order

    def _gather_attached_group(
        self,
        *,
        groups: dict[WorkflowListGroupKeyDAO, WorkflowListGroupDAO],
        order: int,
        attached: AttachedDispatchSnapshotDAO,
        rows: tuple[WorkflowSessionRowDAO, ...],
    ) -> int:
        """Merge the captured attached batch into unpublished candidate records.

        Args:
            groups: Candidate-local records, retaining existing visibility flags.
            order: Next unallocated first-seen ordinal.
            attached: Deep-copied registry evidence captured before any await.
            rows: Enrichment of that captured batch, never a later supplier read.
        Returns:
            int: Next ordinal after allocating a previously unseen batch.
        """
        if attached.dispatch_id:
            key = WorkflowListGroupKeyDAO(kind="attached", group_id=attached.dispatch_id)
            previous = groups.get(key)
            if previous is None:
                previous = WorkflowListGroupDAO(
                    key=key, first_seen=order, orchestrator_session_id=self._owner_session_id
                )
                order += 1
            groups[key] = previous.model_copy(
                update={
                    "orchestrator_session_id": self._owner_session_id,
                    "rows": rows,
                    "retained_only": False,
                }
            )
        return order

    async def _gather_detached_rows(
        self,
        *,
        handle: WorkflowHandleDAO,
        admission: _OwnedHandlesCandidateDAO,
        retained: tuple[WorkflowSessionRowDAO, ...],
        visibility_revision: int,
    ) -> Optional[tuple[WorkflowSessionRowDAO, ...]]:
        """Load fresh ownership or retain stale rows, abandoning invalidated reads.

        Args:
            handle: Captured owned workflow identity.
            admission: Bounded ownership read and its freshness evidence.
            retained: Previously committed rows for this group.
            visibility_revision: Revision whose candidate is being gathered.
        Returns:
            Optional[tuple[WorkflowSessionRowDAO, ...]]: Unpublished rows, or None
                when a local operation or close invalidated the read.
        """
        if handle.workflow_id not in admission.fresh_ids:
            return self._mark_stale(rows=retained)
        rows = await self._load_group(handle=handle, retained=retained)
        if self._observation_invalid(revision=visibility_revision):
            return None
        await asyncio.sleep(0)
        return None if self._observation_invalid(revision=visibility_revision) else rows

    def _commit_observation(self, *, candidate: _ObservationCandidateDAO) -> None:
        """Publish all observation state synchronously after the final authority check."""
        if self._observation_invalid(revision=candidate.visibility_revision):
            return
        latest = self._attached_snapshot().model_copy(deep=True)
        self._list_groups = {group.key: group for group in candidate.groups}
        self._next_group_order = candidate.next_group_order
        if latest != candidate.attached and latest.dispatch_id:
            self._remember_group(
                key=WorkflowListGroupKeyDAO(kind="attached", group_id=latest.dispatch_id),
                parent=self._owner_session_id,
                rows=self._batch_rows(attached=latest),
            )
        self._adopt_dispatch(attached=latest)
        self._handles = {handle.workflow_id: handle for handle in candidate.handles.handles}
        self._set_observation_notice(notice=candidate.handles.notice)
        self.current_list_snapshot()

    def _release_hidden_detached_loaders(self) -> None:
        """Release completed-read adapters using committed visibility, never candidate flags.

        Shared parents remain cached while any visible current group needs them;
        hidden membership and accepted receipt observation continue independently.
        """
        hidden_parents = {
            group.orchestrator_session_id
            for group in self._list_groups.values()
            if group.key.kind == "detached" and group.hidden
        }
        visible_parents = {
            group.orchestrator_session_id
            for group in self._list_groups.values()
            if not group.hidden and not group.retained_only
        }
        for parent in hidden_parents - visible_parents:
            self._loaders.pop(parent, None)

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
        if self._close_task is None:
            self._closed = True
            self._visibility_revision += 1
            self._close_task = asyncio.create_task(self._close_submissions())
        cancelled: bool = False
        while not self._close_task.done():
            try:
                await asyncio.shield(self._close_task)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                break
        if cancelled:
            if not self._close_task.cancelled():
                self._close_task.exception()
            raise asyncio.CancelledError()
        self._close_task.result()

    async def _close_submissions(self) -> None:
        """Join accepted operations once before dropping observation references."""
        for submission in tuple(self._abort_submissions.values()):
            await submission.join()
        self._abort_submissions.clear()
        self._abort_requests.clear()
        self._control_stores.clear()
        self._list_groups.clear()
        self._loaders.clear()
        self._handles.clear()
        self._rows.clear()

    def apply_list_visibility(
        self, *, request: WorkflowListVisibilityRequestDAO
    ) -> WorkflowListVisibilityOutcomeDAO:
        """Commit local flags without I/O; the app paints before acknowledging.

        Args:
            request: Validated display command.
        Returns:
            WorkflowListVisibilityOutcomeDAO: Committed projection or fixed refusal.
        """
        if self._closed:
            return self._visibility_outcome(request=request, outcome="unavailable")
        groups = self._visibility_targets(request=request)
        if request.target_id is not None and not groups:
            return self._visibility_outcome(request=request, outcome="unknown")
        if self._ambiguous_targets(request=request, groups=groups):
            return self._visibility_outcome(request=request, outcome="ambiguous")
        hidden: bool = request.action == "dismiss"
        changed = tuple(group for group in groups if group.hidden != hidden)
        for group in changed:
            self._list_groups[group.key] = group.model_copy(
                update={
                    "hidden": hidden,
                    "restored": group.restored or not hidden,
                    "rows": group.rows if hidden else self._mark_stale(rows=group.rows),
                }
            )
        if changed:
            self._visibility_revision += 1
        return self._visibility_outcome(
            request=request, outcome="changed" if changed else "unchanged", count=len(changed)
        )

    def _visibility_targets(
        self, *, request: WorkflowListVisibilityRequestDAO
    ) -> tuple[WorkflowListGroupDAO, ...]:
        """Resolve exact workflow identity before parent aliases, without mutation."""
        groups = tuple(self._list_groups.values())
        if request.action == "show":
            return tuple(group for group in groups if group.hidden)
        if request.target_id is None:
            return tuple(group for group in groups if group.rows and not group.hidden)
        exact = self._list_groups.get(WorkflowListGroupKeyDAO(kind="detached", group_id=request.target_id))
        if exact is not None:
            return (exact,)
        return tuple(group for group in groups if group.orchestrator_session_id == request.target_id)

    @staticmethod
    def _ambiguous_targets(
        *, request: WorkflowListVisibilityRequestDAO, groups: tuple[WorkflowListGroupDAO, ...]
    ) -> bool:
        """Multiple attached batches intentionally share the owner alias."""
        return (
            request.target_id is not None
            and len(groups) > 1
            and any(group.key.kind == "detached" for group in groups)
        )

    def _visibility_outcome(
        self,
        *,
        request: WorkflowListVisibilityRequestDAO,
        outcome: Literal["changed", "unchanged", "unknown", "ambiguous", "unavailable"],
        count: int = 0,
    ) -> WorkflowListVisibilityOutcomeDAO:
        """Project the committed flags into the command result."""
        return WorkflowListVisibilityOutcomeDAO(
            action=request.action,
            outcome=outcome,
            changed_groups=count,
            target_id=request.target_id,
            snapshot=self.current_list_snapshot(),
        )

    def current_list_snapshot(self) -> WorkflowSessionSnapshotDAO:
        """Return retained visible rows without reads; empty after close.

        Returns:
            WorkflowSessionSnapshotDAO: Current owner-scoped projection.
        """
        rows = (
            ()
            if self._closed
            else self._unique_rows(
                rows=tuple(row for group in self._ordered_groups() if not group.hidden for row in group.rows)
            )
        )
        self._rows = {row.key: row for row in rows}
        return WorkflowSessionSnapshotDAO(rows=rows, notice=self._observation_notice)

    def _ordered_groups(self) -> tuple[WorkflowListGroupDAO, ...]:
        """Project current attached, retained attached, then chronological detached groups."""

        def order(group: WorkflowListGroupDAO) -> tuple[int, datetime, str]:
            """Keep pending durable identities after timestamped detached groups."""
            if group.key.kind == "attached":
                rank = 0 if group.key.group_id == self._attached_dispatch_id else 1
                return (rank, datetime.min.replace(tzinfo=timezone.utc), f"{group.first_seen:020d}")
            return (
                2 if group.started_at is not None else 3,
                group.started_at or datetime.max.replace(tzinfo=timezone.utc),
                group.key.group_id,
            )

        return tuple(sorted(self._list_groups.values(), key=order))

    def dismiss_group(self, *, workflow_id: str) -> None:
        """Retain a successfully durably dismissed identity in the same display owner."""
        self._set_durable_visibility(workflow_id=workflow_id, hidden=True)

    def resume_group(self, *, workflow_id: str) -> None:
        """Restore the same record after a successful durable resume."""
        self._set_durable_visibility(workflow_id=workflow_id, hidden=False)

    def _set_durable_visibility(self, *, workflow_id: str, hidden: bool) -> None:
        """Apply a lifecycle display signal without altering durable state."""
        if self._closed:
            return
        key = WorkflowListGroupKeyDAO(kind="detached", group_id=workflow_id)
        group = self._list_groups.get(key)
        if group is None:
            group = WorkflowListGroupDAO(key=key, first_seen=self._next_group_order)
            self._next_group_order += 1
        self._list_groups[key] = group.model_copy(
            update={
                "hidden": hidden,
                "rows": self._mark_stale(rows=group.rows),
            }
        )
        self._visibility_revision += 1
        self.current_list_snapshot()

    def _remember_group(
        self,
        *,
        key: WorkflowListGroupKeyDAO,
        parent: str,
        rows: tuple[WorkflowSessionRowDAO, ...],
        started_at: Optional[datetime] = None,
    ) -> None:
        """Adopt observed display rows while preserving the group's visibility flags."""
        group = self._list_groups.get(key)
        if group is None:
            group = WorkflowListGroupDAO(
                key=key, first_seen=self._next_group_order, orchestrator_session_id=parent
            )
            self._next_group_order += 1
        self._list_groups[key] = group.model_copy(
            update={
                "orchestrator_session_id": parent,
                "rows": rows,
                "started_at": started_at,
            }
        )

    def _retained_rows(self, *, workflow_id: str) -> tuple[WorkflowSessionRowDAO, ...]:
        """Read last committed detached rows from the single retention owner."""
        group = self._list_groups.get(WorkflowListGroupKeyDAO(kind="detached", group_id=workflow_id))
        return () if group is None else group.rows

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
        if row.retained_batch:
            return SessionProgressSnapshotDAO(
                key=row.key,
                execution_id=row.execution_id,
                dispatch_id=row.dispatch_id,
                entries=(),
                revision="",
                source_generation="",
                availability="unavailable",
                observed_at=datetime.now(tz=timezone.utc).isoformat(),
                status=row.status,
                task_text=row.task_text,
                task_text_complete=row.task_text_complete,
                notice=f"Retained batch; live progress unavailable. Dispatch: {row.dispatch_id}",
            )
        if row.availability != "available":
            return self._progress_notice(key=row.key, row=row, availability=row.availability)
        revision: int = self._visibility_revision
        snapshot, current = await self._read_member_progress(row=row, revision=revision)
        refused = self._progress_invalidation(row=row, revision=revision)
        if refused is not None:
            return refused
        controlled = await self._with_abort_control(snapshot=snapshot, current=current)
        return self._progress_invalidation(row=row, revision=revision) or controlled

    def _progress_invalidation(
        self, *, row: WorkflowSessionRowDAO, revision: int
    ) -> Optional[SessionProgressSnapshotDAO]:
        """Refuse old content when visibility, projected ownership or scope changed.

        Args:
            row: Visible identity captured before reading.
            revision: Visibility revision captured with that identity.
        Returns:
            Optional[SessionProgressSnapshotDAO]: Fixed refusal, or None while current.
        """
        visible = None if self._closed else self._rows.get(row.key)
        if visible is None:
            return self._progress_notice(key=row.key, removed=True)
        if (
            revision != self._visibility_revision
            or visible.workflow_id != row.workflow_id
            or visible.execution_id != row.execution_id
            or visible.dispatch_id != row.dispatch_id
            or visible.retained_batch
        ):
            return self._progress_notice(key=row.key, row=row)
        if self._is_attached(key=row.key):
            current = self._current_attached_row(key=row.key)
            if current is None:
                return self._progress_notice(key=row.key, removed=True)
            if current.execution_id != row.execution_id or current.status != row.status:
                return self._progress_notice(key=row.key, row=row)
        return None

    async def _read_member_progress(
        self, *, row: WorkflowSessionRowDAO, revision: int
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
            refused = self._progress_invalidation(row=row, revision=revision)
            if refused is not None:
                return refused, None
            current: Optional[WorkflowSessionRowDAO] = await self._current_progress_row(key=row.key)
            refused = self._progress_invalidation(row=row, revision=revision)
            if refused is not None:
                return refused, None
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
        return bool(key.attached_dispatch_id) and key.orchestrator_session_id == self._owner_session_id

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
        row = self._rows.get(key)
        handle = None if row is None else self._handles.get(row.workflow_id)
        if handle is None or row is None:
            return None
        revision: int = self._visibility_revision
        admission = await self._read_owned_handles()
        if self._progress_invalidation(row=row, revision=revision) is not None:
            raise ValueError(OBSERVATION_UNAVAILABLE_MESSAGE)
        if handle.workflow_id not in admission.fresh_ids:
            raise ValueError(OBSERVATION_UNAVAILABLE_MESSAGE)
        group: WorkflowDataDAO = await self._loader(
            parent_session_id=handle.orchestrator_session_id
        ).load_observation_group()
        if self._progress_invalidation(row=row, revision=revision) is not None:
            raise ValueError(OBSERVATION_UNAVAILABLE_MESSAGE)
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
                and any(row.workflow_id == handle.workflow_id for row in self._rows.values())
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

    async def _detached_run_id(
        self, *, parent: str, progress_row: Optional[WorkflowSessionRowDAO] = None
    ) -> str:
        """Return the run a live owned orchestrator currently accepts requests for.

        Args:
            parent (str): Detached orchestrator session.
            progress_row: Optional progress identity requiring a post-await cutoff.

        Returns:
            str: Accepting capability's run UUID.

        Raises:
            ChildAbortRefused: not_owned without an owned visible handle; unavailable
                without live evidence or a matching accepting capability.
            OSError: The capability read failed.
        """
        revision: int = self._visibility_revision
        self._live_owned_handle(parent=parent)
        capability: Optional[ChildControlCapabilityDAO] = await self._control_store(
            parent=parent
        ).load_capability()
        if self._observation_invalid(revision=revision):
            raise ChildAbortRefused(outcome="unavailable")
        if progress_row is not None and self._progress_invalidation(row=progress_row, revision=revision):
            raise ChildAbortRefused(outcome="unavailable")
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
        store: ChildAbortStore = self._control_stores.get(parent) or self._control_store_factory(
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
            run_id: str = await self._accepting_run_id(row=current)
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

    async def _accepting_run_id(self, *, row: WorkflowSessionRowDAO) -> str:
        """Return the run currently accepting requests for the key's owner.

        Args:
            row (WorkflowSessionRowDAO): Captured child identity.

        Returns:
            str: Accepting run UUID; for detached groups it must match the listed index run.

        Raises:
            ChildAbortRefused: not_owned or unavailable.
            OSError: The capability read failed.
        """
        if self._is_attached(key=row.key):
            return self._attached_run_id()
        revision: int = self._visibility_revision
        parent: str = row.key.orchestrator_session_id
        run_id: str = await self._detached_run_id(parent=parent, progress_row=row)
        if self._progress_invalidation(row=row, revision=revision) is not None:
            raise ChildAbortRefused(outcome="unavailable")
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
            if row is not None and row.availability == "available" and submission.concerns(row=row):
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
        return rows

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
                attached_dispatch_id=attached.dispatch_id,
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
                orchestrator_session_id=self._owner_session_id,
                session_id=entry.session_id,
                attached_dispatch_id=dispatch_id,
            ),
            role="child",
            task_id=entry.task_id,
            execution_id=entry.execution_id,
            dispatch_id=dispatch_id,
            status=entry.status,
            task_text=entry.prompt_preview,
            task_summary=TaskPreview.project_summary(prompt_preview=entry.prompt_preview),
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
        revision: int = self._visibility_revision
        loader: WorkflowObservationLoader = self._loader(parent_session_id=self._owner_session_id)
        enriched: list[WorkflowSessionRowDAO] = []
        for row in rows:
            enriched.append(await self._enrich_attached_row(loader=loader, row=row))
            if self._observation_invalid(revision=revision):
                return ()
        return tuple(enriched)

    @staticmethod
    async def _enrich_attached_row(
        *,
        loader: WorkflowObservationLoader,
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

    @staticmethod
    def _build_observation_loader(
        *, parent_session_id: str, history_store: SessionHistoryStoreProtocol
    ) -> WorkflowObservationLoader:
        """Construct the real read adapter lazily, avoiding the CLI/TUI import cycle."""
        from src.tui.workflow_visualizer_loader import (
            HeadlessWorkflowVisualizerConfigDAO,
            WorkflowVisualizerLoader,
        )

        return WorkflowVisualizerLoader(
            config=HeadlessWorkflowVisualizerConfigDAO(session_reference=parent_session_id),
            store=history_store,
        )

    def _loader(self, *, parent_session_id: str) -> WorkflowObservationLoader:
        """Reuse a bounded read adapter; never construct one without history.

        Args:
            parent_session_id: Authorized exact parent identity.
        Returns:
            WorkflowObservationLoader: Cached adapter, or uncached after close.
        Raises:
            ValueError: No history adapter is available.
        """
        if self._history_store is None:
            raise ValueError("observation storage unavailable")
        loader = self._loaders.get(parent_session_id)
        if loader is None:
            loader = self._loader_factory(
                parent_session_id=parent_session_id, history_store=self._history_store
            )
        if not self._closed:
            self._loaders[parent_session_id] = loader
        return loader

    # ── feature 94 observation: detached projection and retention ───────────

    async def _load_group(
        self, *, handle: WorkflowHandleDAO, retained: tuple[WorkflowSessionRowDAO, ...]
    ) -> tuple[WorkflowSessionRowDAO, ...]:
        """Project read evidence without publishing rows or ownership."""
        try:
            group = await self._loader(
                parent_session_id=handle.orchestrator_session_id
            ).load_observation_group()
            rows = self._project_group(handle=handle, group=group)
        except (OSError, ValueError):
            return self._retain_failed_group(handle=handle, retained=retained)
        if group.fleet_snapshot is None and retained:
            return (rows[0], *self._mark_stale(rows=retained[1:]))
        previous_by_key = {row.key: row for row in retained}
        children_by_id = {child.session_id: child for child in group.children}
        return tuple(
            self._retain_missing_child_capture(
                row=row, previous=previous_by_key.get(row.key), child=children_by_id.get(row.key.session_id)
            )
            for row in rows
        )

    @staticmethod
    def _retain_missing_child_capture(
        *,
        row: WorkflowSessionRowDAO,
        previous: Optional[WorkflowSessionRowDAO],
        child: Optional[ChildSessionSummaryDAO],
    ) -> WorkflowSessionRowDAO:
        """Keep known detail stale when its previously observed capture disappears.

        Args:
            row: Newly projected fleet member.
            previous: Last observed member, if any.
            child: Bounded child capture evidence.
        Returns:
            WorkflowSessionRowDAO: Fresh row or retained stale detail.
        """
        if (
            previous is None
            or child is None
            or not previous.task_text_complete
            or row.execution_id != previous.execution_id
        ):
            return row
        if child.has_spawn_context or child.has_stdout_capture or child.has_stderr_capture:
            return row
        return previous.model_copy(update={"availability": "stale"})

    def _retain_failed_group(
        self, *, handle: WorkflowHandleDAO, retained: tuple[WorkflowSessionRowDAO, ...]
    ) -> tuple[WorkflowSessionRowDAO, ...]:
        """Never translate unreadable files into deletion during service refresh.

        Args:
            handle (WorkflowHandleDAO): Owner identity available despite failed data.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: Retained rows marked stale, or one
                unavailable parent row when no last-good rows exist.
        """
        previous = retained
        if previous:
            return tuple(
                (
                    row.model_copy(
                        update={"status": self._detached_parent_status(handle=handle, reported=row.status)}
                    )
                    if row.role == "orchestrator"
                    else row
                )
                for row in self._mark_stale(rows=previous)
            )
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
        fleet_ids = (
            None
            if group.fleet_snapshot is None
            else {entry.session_id for entry in group.fleet_snapshot.entries}
        )
        children: tuple[WorkflowSessionRowDAO, ...] = tuple(
            self._detached_child_row(handle=handle, child=child)
            for child in group.children
            if fleet_ids is None or child.session_id in fleet_ids
        )
        return (self._detached_parent_row(handle=handle, group=group), *children)

    @staticmethod
    def _detached_parent_status(*, handle: WorkflowHandleDAO, reported: str) -> str:
        """Resolve fresh or retained parent status without undoing an explicit abort.

        Called during list projection; the durable abort wins even if the runner
        exited before updating its self-report. Child execution evidence is separate.

        Args:
            handle (WorkflowHandleDAO): Latest owned workflow control state.
            reported (str): Runner self-report or retained parent status.

        Returns:
            str: Confirmed abort, otherwise the known report or handle fallback.
        """
        if handle.state == "aborted" or reported == "unknown":
            return handle.state
        return reported

    @classmethod
    def _detached_parent_row(
        cls, *, handle: WorkflowHandleDAO, group: WorkflowDataDAO
    ) -> WorkflowSessionRowDAO:
        """Choose parent display evidence after group validation, during projection.

        The parent row carries the current run identity in ``dispatch_id``: a
        detached parent has no dispatch of its own, and a.3 keys parent
        incarnation changes on the run (empty when unknown).

        Args:
            handle (WorkflowHandleDAO): Owned workflow identity and brief.
            group (WorkflowDataDAO): Bounded observation with optional self-report.

        Returns:
            WorkflowSessionRowDAO: Parent record; a confirmed abort wins over
                any self-report. An absent or unknown report uses the handle state.
        """
        reported: str = group.orchestrator.state if group.orchestrator is not None else "unknown"
        return WorkflowSessionRowDAO(
            key=WorkflowSessionKeyDAO(
                orchestrator_session_id=handle.orchestrator_session_id,
                session_id=handle.orchestrator_session_id,
            ),
            workflow_id=handle.workflow_id,
            role="orchestrator",
            status=cls._detached_parent_status(handle=handle, reported=reported),
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
            task_summary=child.task_summary,
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
        self._list_groups = {
            key: group
            for key, group in self._list_groups.items()
            if key.kind != "attached"
            or group.hidden
            or group.restored
            or key.group_id == attached.dispatch_id
        }
        for key, group in tuple(self._list_groups.items()):
            if key.kind == "attached" and key.group_id != attached.dispatch_id:
                self._list_groups[key] = group.model_copy(
                    update={
                        "retained_only": True,
                        "rows": tuple(
                            row.model_copy(update={"retained_batch": True})
                            for row in self._mark_stale(rows=group.rows)
                        ),
                    }
                )
        self._loaders.pop(self._owner_session_id, None)

    async def _read_owned_handles(self) -> _OwnedHandlesCandidateDAO:
        """Read bounded ownership without mutating the committed union or notice."""
        retained = tuple(self._handles.values())
        if self._history_store is None or self._store is None:
            return _OwnedHandlesCandidateDAO(handles=())
        try:
            fresh = await self._store.list_observation(owner_session_id=self._owner_session_id)
        except (OSError, ValueError):
            return _OwnedHandlesCandidateDAO(handles=retained, notice=LIST_UNAVAILABLE_NOTICE)
        admitted = {**self._handles, **{handle.workflow_id: handle for handle in fresh}}
        if len(admitted) > OBSERVATION_MAX_HANDLES:
            return _OwnedHandlesCandidateDAO(handles=retained, notice=LIST_UNAVAILABLE_NOTICE)
        return _OwnedHandlesCandidateDAO(
            handles=tuple(
                sorted(admitted.values(), key=lambda handle: (handle.started_at, handle.workflow_id))
            ),
            fresh_ids=frozenset(handle.workflow_id for handle in fresh),
            notice=LIST_UNAVAILABLE_NOTICE if len(admitted) > len(fresh) else None,
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
