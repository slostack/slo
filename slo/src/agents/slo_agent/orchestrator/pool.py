"""SubAgentPool — concurrency-capped lifecycle manager for child sub-agent processes.

One pool is owned by one orchestrator session and reused across
``spawn_sub_agents`` tool calls. A shared ``asyncio.Semaphore`` bounds how
many children run at once. The pool writes lifecycle events to both the
``ProcessRegistry`` and the orchestrator's subscriber relay.

Sub-spec 01-sub-agents 01.d.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional, Protocol
from uuid import uuid4

from pydantic import ValidationError

from config.cfg import SUBAGENT_MAX_CONCURRENCY, SUBAGENT_MAX_TASKS
from config.logger import log_warning
from src.agents.slo_agent.orchestrator.dao import (
    AttachedDispatchSnapshotDAO,
    ChildAbortOutcomeDAO,
    ChildAbortRequestDAO,
    ChildControlCapabilityDAO,
    DispatchIdentityDAO,
    OrchestratorResultDAO,
    ResolvedDispatchTaskDAO,
    lifecycle_kind_for_status,
    SubAgentMode,
    SubAgentResultDAO,
    SubAgentTaskDAO,
)
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.reaper import ReapOutcome
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry
from src.agents.slo_agent.orchestrator.task_preview import TaskPreview
from src.agents.slo_agent.sessions.dao import AgentEventSubscriber
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.filesystem_store import (
    FilesystemSessionHistoryStore,
    default_history_root,
)


class SubAgentProcessFactory(Protocol):
    """Construct an unstarted wrapper; the pool retains lifecycle ownership."""

    def __call__(
        self,
        *,
        task: SubAgentTaskDAO,
        session_id: str,
        model: Optional[str],
        relay: AgentEventSubscriber,
        registry: ProcessRegistry,
        execution_id: str,
        system_prompt: str,
        parent_session_id: str,
        history_root: Path,
    ) -> SubAgentProcess:
        """Bind the existing wrapper inputs without starting a process.

        Args:
            task: Validated task including its authored summary.
            session_id: Child session identity.
            model: Optional model override.
            relay: Event subscriber.
            registry: Pool-owned execution registry.
            execution_id: Current incarnation identity.
            system_prompt: Child system instructions.
            parent_session_id: Owning parent identity.
            history_root: Existing history root.

        Returns:
            SubAgentProcess: Unstarted wrapper; the pool owns its lifecycle.
        """
        ...


__all__ = ["SubAgentPool", "MAX_CONCURRENCY", "MAX_PARALLEL_TASKS"]


MAX_CONCURRENCY: int = SUBAGENT_MAX_CONCURRENCY
"""Maximum simultaneously running child processes per pool.

Overridable via the ``SLO_SUBAGENT_MAX_CONCURRENCY`` environment variable.
"""

MAX_PARALLEL_TASKS: int = SUBAGENT_MAX_TASKS
"""Maximum tasks accepted per ``dispatch()`` call.

Overridable via the ``SLO_SUBAGENT_MAX_TASKS`` environment variable.
"""

_DUPLICATE_SESSION_ERROR: str = "duplicate child session in dispatch; no sub-agents were started"
"""Fixed refusal when two tasks of one batch resolve to the same child session."""

_SESSION_BUSY_ERROR: str = "child session already executing in this pool; no sub-agents were started"
"""Fixed refusal when a batch names a reserved or nonterminal child session."""

_UNSAFE_SESSION_ERROR: str = "unsafe child session id; no sub-agents were started"
"""Fixed refusal when a resolved session id is unsafe as a path component."""

_SEALED_ERROR: str = "pool sealed by abort; no new sub-agents will be spawned"
"""Fixed refusal for any dispatch reaching a sealed pool."""


class _DispatchReservation:
    """Child sessions one admitted dispatch holds until each execution is torn down.

    Admission reserves every resolved session in the pool-owned set. ``_run_one``
    claims its session when it starts and releases it after its wrapper and
    terminal lifecycle event have settled; the dispatch ``finally`` releases the
    sessions no step ever claimed (a stopped chain, or cancellation before a
    child started). Every reserved session is released exactly once.
    """

    def __init__(self, *, reserved: set[str], session_ids: tuple[str, ...]) -> None:
        """Reserve ``session_ids`` in the pool's shared set.

        Args:
            reserved (set[str]): Pool-owned set of sessions held by any dispatch.
            session_ids (tuple[str, ...]): Distinct sessions of this batch.
        """
        self._reserved: set[str] = reserved
        self._unclaimed: set[str] = set(session_ids)
        reserved.update(session_ids)

    def claim(self, *, session_id: str) -> None:
        """Hand one session's release to the ``_run_one`` that starts it."""
        self._unclaimed.discard(session_id)

    def release(self, *, session_id: str) -> None:
        """Release a claimed session after its execution teardown settled."""
        self._reserved.discard(session_id)

    def release_unclaimed(self) -> None:
        """Release every session no step claimed; called once by dispatch teardown."""
        self._reserved.difference_update(self._unclaimed)
        self._unclaimed.clear()


class SubAgentPool:
    """Owns the batch lifecycle for one orchestrator session's sub-agent runs.

    One pool is built per orchestrator session and reused across
    ``spawn_sub_agents`` tool calls. A shared ``asyncio.Semaphore`` bounds
    how many children run at once. The pool writes lifecycle events to both
    the ``ProcessRegistry`` and the orchestrator's subscriber relay.

    Attributes:
        _orchestrator_session_id (str): Parent session id, threaded into child
            identity for tracing.
        _default_model (Optional[str]): Orchestrator model, inherited by tasks
            that do not carry their own ``model`` override.
        _relay (AgentEventSubscriber): Orchestrator session dispatch; child
            events and lifecycle events are forwarded here.
        _child_system_prompt (str): Assembled system prompt passed to each child
            process and written to ``spawn_context.json``.
        _semaphore (asyncio.Semaphore): Concurrency cap.
        _registry (ProcessRegistry): Lifecycle registry for this pool; its
            ``commit_terminal`` winner is the only terminal truth the pool emits.
        _active_by_session_id (dict[str, SubAgentProcess]): Current wrapper per
            reserved child session, installed before the spawned event and removed
            at teardown; dispatch reservation makes the session key unambiguous.
        _child_completion (dict[tuple[str, str], asyncio.Future[SubAgentResultDAO]]):
            Per-incarnation ``(session_id, execution_id)`` completion, settled once
            by ``_run_reserved``; execution synchronization, not a status model.
        _child_abort_events (dict[tuple[str, str], asyncio.Event]): Per-incarnation
            abort-reservation events, created at registration.
        _child_abort_tasks (dict[tuple[str, str], asyncio.Task[ChildAbortOutcomeDAO]]):
            Pool-owned targeted cancellation per incarnation, retained for idempotency.
        _abort_requested_children (set[tuple[str, str]]): Incarnations reserved by a
            targeted abort; a reserved pending child never enters run.
        _reserved_session_ids (set[str]): Child sessions held by admitted
            dispatches from admission until each execution's teardown settled.
        _owner_session_id (str): Immutable owner identity from the composition root.
        _run_id (str): Immutable UUID of this pool composition.
        _history_root (Path): History root shared by fleet, evidence and child files.
    """

    def __init__(
        self,
        *,
        orchestrator_session_id: str,
        default_model: Optional[str],
        relay: AgentEventSubscriber,
        owner_session_id: str,
        run_id: str,
        history_root: Path,
        child_system_prompt: str = "",
        process_factory: Optional[SubAgentProcessFactory] = None,
    ) -> None:
        """Initialise the pool with its identity, model, relay, and fresh registry.

        WHAT: Binds immutable owner/run/history identity supplied by the composition
            root (no request or hidden global supplies these) and builds the
            registry mirrored to a run-bound FleetStore under that history root.
        WHO: Called by OrchestratorSessionBootstrap._build_pool and by tests with
            explicit synthetic identities.
        WHEN: Once per orchestrator session attachment.

        Args:
            orchestrator_session_id (str): Parent session identifier.
            default_model (Optional[str]): Inherited model for tasks without an override.
            relay (AgentEventSubscriber): Orchestrator relay callable.
            owner_session_id (str): Owner session resolved by the composition root.
            run_id (str): Fresh UUID for this pool composition.
            history_root (Path): Session history root shared with child files.
            child_system_prompt (str): Assembled system prompt shared by all child
                processes. Written to ``spawn_context.json`` via each
                ``SubAgentProcess``. Defaults to empty string for backwards compat.
        """
        self._process_factory: SubAgentProcessFactory = process_factory or SubAgentProcess
        self._orchestrator_session_id: str = orchestrator_session_id
        self._default_model: Optional[str] = default_model
        self._relay: AgentEventSubscriber = relay
        self._owner_session_id: str = owner_session_id
        self._run_id: str = run_id
        self._history_root: Path = history_root
        self._child_system_prompt: str = child_system_prompt
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        fleet_store: FleetStore = FleetStore(
            history_root=history_root,
            orchestrator_session_id=orchestrator_session_id,
            workflow_id=os.environ.get("SLO_WORKFLOW_ID"),
            run_id=run_id,
        )
        self._registry: ProcessRegistry = ProcessRegistry(fleet_store=fleet_store)
        self._active_by_session_id: dict[str, SubAgentProcess] = {}
        self._child_completion: dict[tuple[str, str], asyncio.Future[SubAgentResultDAO]] = {}
        self._child_abort_events: dict[tuple[str, str], asyncio.Event] = {}
        self._child_abort_tasks: dict[tuple[str, str], asyncio.Task[ChildAbortOutcomeDAO]] = {}
        self._abort_requested_children: set[tuple[str, str]] = set()
        self._sealed: bool = False
        self._abort_and_drain_task: Optional[asyncio.Task[None]] = None
        self._cancel_outcomes: dict[str, ReapOutcome] = {}
        self._reserved_session_ids: set[str] = set()

    @property
    def registry(self) -> ProcessRegistry:
        """Return the pool-owned process registry for external observers.

        Returns:
            ProcessRegistry: The live process registry for this pool.
        """
        return self._registry

    @property
    def owner_session_id(self) -> str:
        """Return the immutable owner session bound by the composition root."""
        return self._owner_session_id

    @property
    def run_id(self) -> str:
        """Return the immutable UUID of this pool composition."""
        return self._run_id

    @property
    def history_root(self) -> Path:
        """Return the history root bound by the composition root.

        WHO: HeadlessRunner, to bind its ChildAbortStore to the same root as the
            fleet and child files of this pool.

        Returns:
            Path: Immutable history root of this pool.
        """
        return self._history_root

    def attached_dispatch_snapshot(self) -> AttachedDispatchSnapshotDAO:
        """Return the latest admitted batch's entries for session observers.

        WHAT: Delegates to the registry's explicit dispatch projection; observers
            never inspect pool or registry internals.
        WHO: Called by SloAgentSession.attached_dispatch_snapshot.
        WHEN: On every TUI observation poll; it has no side effects.

        Returns:
            AttachedDispatchSnapshotDAO: Latest batch, or the explicit empty value.
        """
        return self._registry.attached_snapshot()

    def child_control_capability(self) -> ChildControlCapabilityDAO:
        """Return this pool's typed child-control identity for attached callers.

        WHAT: Builds the capability from the composition root's immutable owner,
            parent and run identity; accepting is withdrawn once the pool seals.
        WHO: Called by SloAgentSession.child_control_capability for the TUI.
        WHEN: On demand at confirmation and submission time; no side effects.

        Returns:
            ChildControlCapabilityDAO: Current attached child-control capability.
        """
        return ChildControlCapabilityDAO(
            run_id=self._run_id,
            owner_session_id=self._owner_session_id,
            orchestrator_session_id=self._orchestrator_session_id,
            accepting=not self._sealed,
        )

    async def dispatch(
        self,
        *,
        mode: SubAgentMode,
        tasks: list[SubAgentTaskDAO],
    ) -> OrchestratorResultDAO:
        """Admit one batch explicitly, then run it under the requested mode.

        WHAT: Refuses sealed or oversized batches, resolves every task's session
            once, then (with no await) rechecks the seal and duplicate/reserved/live
            sessions, reserves the batch and begins a new registry dispatch. The
            stream-only ``sub_agent_dispatch_started`` event precedes every child
            lifecycle event. Rejected batches begin nothing; an empty valid batch
            still replaces the displayed group.
        WHO: Called by the ``spawn_sub_agents`` tool for the orchestrator.
        WHEN: Once per tool call; concurrent calls are admitted in the order their
            preparation completes, not the order they were invoked.

        Args:
            mode (SubAgentMode): ``"parallel"``, ``"chain"``, or ``"single"``.
            tasks (list[SubAgentTaskDAO]): Ordered task list.

        Returns:
            OrchestratorResultDAO: Aggregated batch result, or a refusal with no results.
        """
        intake_refusal: Optional[OrchestratorResultDAO] = self._intake_refusal(mode=mode, tasks=tasks)
        if intake_refusal is not None:
            return intake_refusal
        resolved: Optional[tuple[ResolvedDispatchTaskDAO, ...]] = await self._resolve_dispatch_tasks(
            tasks=tasks
        )
        if resolved is None:
            return self._refusal(mode=mode, tasks=tasks, error=_UNSAFE_SESSION_ERROR)
        admission_refusal: Optional[OrchestratorResultDAO] = self._admission_refusal(
            mode=mode, tasks=tasks, resolved=resolved
        )
        if admission_refusal is not None:
            return admission_refusal
        dispatch, reservation = self._admit(resolved=resolved)
        try:
            results: list[SubAgentResultDAO] = await self._run_admitted_batch(
                mode=mode, resolved=resolved, dispatch=dispatch, reservation=reservation
            )
        finally:
            reservation.release_unclaimed()
            self._registry.retire_dispatch(dispatch_id=dispatch.dispatch_id)
        return self._aggregate(mode=mode, results=results)

    def _intake_refusal(
        self, *, mode: SubAgentMode, tasks: list[SubAgentTaskDAO]
    ) -> Optional[OrchestratorResultDAO]:
        """Refuse a batch that cannot be prepared at all.

        Args:
            mode (SubAgentMode): Requested dispatch mode.
            tasks (list[SubAgentTaskDAO]): Requested tasks.

        Returns:
            Optional[OrchestratorResultDAO]: Sealed or oversize refusal, else None.
        """
        if self._sealed:
            return self._refusal(mode=mode, tasks=tasks, error=_SEALED_ERROR)
        if len(tasks) > MAX_PARALLEL_TASKS:
            return OrchestratorResultDAO(
                mode=mode,
                all_completed=False,
                failed_task_ids=[t.task_id for t in tasks],
            )
        return None

    async def _resolve_dispatch_tasks(
        self, *, tasks: list[SubAgentTaskDAO]
    ) -> Optional[tuple[ResolvedDispatchTaskDAO, ...]]:
        """Resolve every task's session reference exactly once, before admission.

        WHAT: Bounded preparation: one resolution per task, in task order.
            Cancellation here leaves nothing reserved or registered.
        WHO: Called only by ``dispatch``.
        WHEN: After intake checks and before the no-await admission section.

        Args:
            tasks (list[SubAgentTaskDAO]): Requested tasks.

        Returns:
            Optional[tuple[ResolvedDispatchTaskDAO, ...]]: Resolved tasks, or None
                when a resolved session id is unsafe as a path component.
        """
        session_ids: list[str] = [await self._resolve_child_session_id(task=task) for task in tasks]
        try:
            return tuple(
                ResolvedDispatchTaskDAO(task=task, session_id=session_id)
                for task, session_id in zip(tasks, session_ids)
            )
        except ValidationError:
            return None

    def _admission_refusal(
        self,
        *,
        mode: SubAgentMode,
        tasks: list[SubAgentTaskDAO],
        resolved: tuple[ResolvedDispatchTaskDAO, ...],
    ) -> Optional[OrchestratorResultDAO]:
        """Recheck seal and session identities after preparation, without awaiting.

        Args:
            mode (SubAgentMode): Requested dispatch mode.
            tasks (list[SubAgentTaskDAO]): Requested tasks, for refusal ids.
            resolved (tuple[ResolvedDispatchTaskDAO, ...]): Prepared batch.

        Returns:
            Optional[OrchestratorResultDAO]: Refusal for a sealed pool, a duplicate
                session or a busy session; None when the batch may be admitted.
        """
        session_ids: list[str] = [item.session_id for item in resolved]
        if self._sealed:
            return self._refusal(mode=mode, tasks=tasks, error=_SEALED_ERROR)
        if len(set(session_ids)) != len(session_ids):
            return self._refusal(mode=mode, tasks=tasks, error=_DUPLICATE_SESSION_ERROR)
        if any(not self._session_admissible(session_id=session_id) for session_id in session_ids):
            return self._refusal(mode=mode, tasks=tasks, error=_SESSION_BUSY_ERROR)
        return None

    def _session_admissible(self, *, session_id: str) -> bool:
        """Return whether no dispatch holds the session and it has no live incarnation."""
        if session_id in self._reserved_session_ids:
            return False
        return self._registry.accepts_new_execution(session_id=session_id)

    def _admit(
        self, *, resolved: tuple[ResolvedDispatchTaskDAO, ...]
    ) -> tuple[DispatchIdentityDAO, _DispatchReservation]:
        """Reserve the batch and begin its registry dispatch in one synchronous step.

        Args:
            resolved (tuple[ResolvedDispatchTaskDAO, ...]): Admitted batch.

        Returns:
            tuple[DispatchIdentityDAO, _DispatchReservation]: Captured identity and
                the reservation that dispatch teardown must settle.
        """
        reservation = _DispatchReservation(
            reserved=self._reserved_session_ids, session_ids=tuple(item.session_id for item in resolved)
        )
        dispatch_id: str = str(uuid4())
        sequence: int = self._registry.begin_dispatch(dispatch_id=dispatch_id)
        return DispatchIdentityDAO(dispatch_id=dispatch_id, dispatch_sequence=sequence), reservation

    async def _run_admitted_batch(
        self,
        *,
        mode: SubAgentMode,
        resolved: tuple[ResolvedDispatchTaskDAO, ...],
        dispatch: DispatchIdentityDAO,
        reservation: _DispatchReservation,
    ) -> list[SubAgentResultDAO]:
        """Announce the admitted batch, then run its children under ``mode``.

        Args:
            mode (SubAgentMode): Admitted dispatch mode.
            resolved (tuple[ResolvedDispatchTaskDAO, ...]): Admitted batch.
            dispatch (DispatchIdentityDAO): Identity captured at admission.
            reservation (_DispatchReservation): The batch's session reservation.

        Returns:
            list[SubAgentResultDAO]: Results for the children that ran.
        """
        await self._emit_dispatch_started(dispatch=dispatch)
        if mode == "chain":
            return await self._run_chain(resolved=resolved, dispatch=dispatch, reservation=reservation)
        return list(
            await asyncio.gather(
                *[
                    self._run_one(resolved=item, dispatch=dispatch, reservation=reservation)
                    for item in resolved
                ]
            )
        )

    @staticmethod
    def _refusal(*, mode: SubAgentMode, tasks: list[SubAgentTaskDAO], error: str) -> OrchestratorResultDAO:
        """Build a batch refusal that started no child.

        Args:
            mode (SubAgentMode): Requested dispatch mode.
            tasks (list[SubAgentTaskDAO]): Refused tasks.
            error (str): Fixed refusal message.

        Returns:
            OrchestratorResultDAO: No results; every task id marked failed.
        """
        return OrchestratorResultDAO(
            mode=mode,
            results=[],
            all_completed=False,
            failed_task_ids=[task.task_id for task in tasks],
            error=error,
        )

    async def _resolve_child_session_id(self, *, task: SubAgentTaskDAO) -> str:
        """Determine the session id for one child task.

        Priority (highest to lowest):

        1. ``task.session_id`` — explicit id supplied by the orchestrator agent.
        2. ``task.resume_session_reference`` — a reference (session id prefix or
           normalized name) resolved via the history store.
        3. Fresh ``uuid4()`` — no identity constraint; normal new-session case.

        When ``task.resume_session_reference`` is provided but cannot be
        resolved (the referenced session no longer exists), a fresh id is
        generated and the failure is logged rather than propagated, so the
        remaining batch continues.

        Args:
            task (SubAgentTaskDAO): The task whose identity to resolve.

        Returns:
            str: The resolved or freshly generated session id string.
        """
        if task.session_id is not None:
            return task.session_id
        if task.resume_session_reference is not None:
            store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(
                root=default_history_root(),
            )
            try:
                return await store.resolve_session_reference(
                    reference=task.resume_session_reference,
                )
            except (ValueError, OSError):
                from config.logger import log_info  # noqa: PLC0415

                log_info(
                    msg="sub_agent_resume_reference_unresolvable",
                    task_id=task.task_id,
                    reference=task.resume_session_reference,
                )
        return str(uuid4())

    async def _run_one(
        self,
        *,
        resolved: ResolvedDispatchTaskDAO,
        dispatch: DispatchIdentityDAO,
        reservation: _DispatchReservation,
    ) -> SubAgentResultDAO:
        """Own one admitted child's session reservation around its execution.

        WHAT: Claims the session from the dispatch reservation, runs the child and
            releases the session only after its wrapper and terminal lifecycle
            event have settled, on every return, error and cancellation path.
        WHO: Called by dispatch for each task (parallel/single) or step (chain).
        WHEN: Once per admitted task; session references were resolved at
            preparation and are never resolved again here.

        Args:
            resolved (ResolvedDispatchTaskDAO): Task and its admitted session.
            dispatch (DispatchIdentityDAO): Batch identity captured at admission.
            reservation (_DispatchReservation): The batch's session reservation.

        Returns:
            SubAgentResultDAO: The registry winner for this task's incarnation.
        """
        reservation.claim(session_id=resolved.session_id)
        try:
            return await self._run_reserved(resolved=resolved, dispatch=dispatch)
        finally:
            reservation.release(session_id=resolved.session_id)

    async def _run_reserved(
        self, *, resolved: ResolvedDispatchTaskDAO, dispatch: DispatchIdentityDAO
    ) -> SubAgentResultDAO:
        """Register, spawn and await one reserved child under the concurrency semaphore.

        WHAT: register into the captured dispatch (fresh execution_id) → install
            the wrapper, abort event and completion future → emit spawned → race
            the slot against a targeted abort → run, or publish a sealed/targeted
            pending abort without spawning → emit exactly one terminal lifecycle
            from the returned registry winner → return that winner. The
            incarnation's completion future settles exactly once in finally. No
            terminal state is reconciled or written here; the process gateway owns
            publication.
        WHO: Called only by ``_run_one`` while it holds the session reservation.
        WHEN: Once per admitted task; a pool sealed after admission returns the
            sealed result without registering.

        Args:
            resolved (ResolvedDispatchTaskDAO): Task and its admitted session.
            dispatch (DispatchIdentityDAO): Batch identity captured at admission.

        Returns:
            SubAgentResultDAO: The registry winner for this task's incarnation.
        """
        task: SubAgentTaskDAO = resolved.task
        session_id: str = resolved.session_id
        if self._sealed:
            return self._sealed_task_result(task=task, session_id=session_id)
        execution_id: str = self._registry.register(
            dispatch_id=dispatch.dispatch_id, task_id=task.task_id, session_id=session_id, task=task
        )
        process: SubAgentProcess = self._process_factory(
            task=task,
            session_id=session_id,
            model=task.model or self._default_model,
            relay=self._relay,
            registry=self._registry,
            execution_id=execution_id,
            system_prompt=self._child_system_prompt,
            parent_session_id=self._orchestrator_session_id,
            history_root=self._history_root,
        )
        completion: asyncio.Future[SubAgentResultDAO] = self._install_incarnation(process=process)
        winner: Optional[SubAgentResultDAO] = None
        try:
            await self._emit_lifecycle(
                kind="sub_agent_spawned",
                task_id=task.task_id,
                session_id=session_id,
                metadata=dispatch.lifecycle_metadata(execution_id=execution_id),
                prompt_preview=TaskPreview.encode_summary(task_summary=task.task_summary),
            )
            winner = await self._run_with_slot(process=process, task=task)
            await self._emit_lifecycle(
                kind=lifecycle_kind_for_status(status=winner.status),
                task_id=task.task_id,
                session_id=session_id,
                metadata=dispatch.lifecycle_metadata(execution_id=execution_id),
            )
            return winner
        finally:
            del self._active_by_session_id[session_id]
            self._settle_completion(completion=completion, process=process, winner=winner)

    def _install_incarnation(self, *, process: SubAgentProcess) -> asyncio.Future[SubAgentResultDAO]:
        """Install one incarnation's wrapper, abort event and completion future.

        WHAT: Drops the session's previous incarnation entries (its teardown has
            settled, so no old completion can settle the new future), then records
            the wrapper by session and the event/future by ``(session_id,
            execution_id)``. Synchronous, so no callback observes a partial install.
        WHO: Called only by ``_run_reserved`` right after registry registration.
        WHEN: Before the spawned event; wrapper creation itself never spawns.

        Args:
            process (SubAgentProcess): Freshly registered wrapper.

        Returns:
            asyncio.Future[SubAgentResultDAO]: The incarnation's completion future.
        """
        self._forget_previous_incarnations(session_id=process.session_id)
        identity: tuple[str, str] = (process.session_id, process.execution_id)
        completion: asyncio.Future[SubAgentResultDAO] = asyncio.get_running_loop().create_future()
        completion.add_done_callback(self._retrieve_completion_error)
        self._active_by_session_id[process.session_id] = process
        self._child_abort_events[identity] = asyncio.Event()
        self._child_completion[identity] = completion
        return completion

    def _forget_previous_incarnations(self, *, session_id: str) -> None:
        """Drop synchronization entries of a reused session's finished incarnations.

        Args:
            session_id (str): Session about to start a new incarnation.
        """
        stale: list[tuple[str, str]] = [
            identity for identity in self._child_completion if identity[0] == session_id
        ]
        for identity in stale:
            self._child_completion.pop(identity, None)
            self._child_abort_events.pop(identity, None)
            self._child_abort_tasks.pop(identity, None)
            self._abort_requested_children.discard(identity)

    def _settle_completion(
        self,
        *,
        completion: asyncio.Future[SubAgentResultDAO],
        process: SubAgentProcess,
        winner: Optional[SubAgentResultDAO],
    ) -> None:
        """Settle one incarnation's completion exactly once on every exit path.

        WHAT: Uses the runner's returned winner, else the registry's committed
            winner, else an explicit interruption error; never a fabricated result.
        WHO: Called only from ``_run_reserved``'s finally.
        WHEN: After the wrapper left ``_active_by_session_id``.

        Args:
            completion (asyncio.Future[SubAgentResultDAO]): Incarnation future.
            process (SubAgentProcess): The incarnation's wrapper.
            winner (Optional[SubAgentResultDAO]): Winner returned by run, if any.
        """
        committed: Optional[SubAgentResultDAO] = winner or self._registry.terminal_result(
            session_id=process.session_id, execution_id=process.execution_id
        )
        if committed is not None:
            completion.set_result(committed)
            return
        completion.set_exception(RuntimeError("child execution ended without a terminal result"))

    @staticmethod
    def _retrieve_completion_error(completion: asyncio.Future[SubAgentResultDAO]) -> None:
        """Mark a completion error retrieved; awaiting cancellers translate it themselves.

        Args:
            completion (asyncio.Future[SubAgentResultDAO]): Settled completion future.
        """
        if not completion.cancelled():
            completion.exception()

    async def _run_with_slot(self, *, process: SubAgentProcess, task: SubAgentTaskDAO) -> SubAgentResultDAO:
        """Acquire this incarnation's slot, run it, and release only a transferred permit.

        WHAT: A targeted abort that wins the slot race leaves no permit held and
            the wrapper publishes its pending abort; otherwise the transferred
            permit is held for the run and released exactly once.
        WHO: Called only by ``_run_reserved``.
        WHEN: After the spawned event; acquisition may wait for capacity.

        Args:
            process (SubAgentProcess): Registered wrapper for this incarnation.
            task (SubAgentTaskDAO): Task the wrapper executes.

        Returns:
            SubAgentResultDAO: Registry winner for the incarnation.
        """
        transferred: bool = await self._acquire_child_slot(
            session_id=process.session_id, execution_id=process.execution_id
        )
        try:
            return await self._run_admitted(process=process, task=task)
        finally:
            if transferred:
                self._semaphore.release()

    async def _acquire_child_slot(self, *, session_id: str, execution_id: str) -> bool:
        """Transfer one semaphore permit to the runner unless abort wins the race.

        WHAT: Races semaphore acquisition against the incarnation's abort event,
            joins both waiters, then decides transfer with no further await. An
            abort admitted before that final check wins, including one admitted
            during waiter cleanup; any permit acquired but not transferred is
            released here exactly once. "Same loop turn" is not an atomicity
            guarantee: the synchronously installed reservation event is.
        WHO: Called only by ``_run_with_slot``.
        WHEN: Once per incarnation, before run entry.

        Args:
            session_id (str): Registered session reserved by the dispatch.
            execution_id (str): Incarnation owning the abort event.

        Returns:
            bool: True transfers a held permit; False means no permit remains held.

        Raises:
            asyncio.CancelledError: Runner cancellation, after both waiters are joined.
        """
        event: asyncio.Event = self._child_abort_events[(session_id, execution_id)]
        if event.is_set():
            return False
        acquire: asyncio.Task[bool] = asyncio.create_task(self._semaphore.acquire())
        abort: asyncio.Task[bool] = asyncio.create_task(event.wait())
        transferred: bool = False
        try:
            try:
                await asyncio.wait({acquire, abort}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                await self._join_slot_waiters(acquire=acquire, abort=abort)
            transferred = self._slot_was_acquired(acquire=acquire) and not event.is_set()
            return transferred
        finally:
            if not transferred and self._slot_was_acquired(acquire=acquire):
                self._semaphore.release()

    @staticmethod
    def _slot_was_acquired(*, acquire: asyncio.Task[bool]) -> bool:
        """Identify a held permit after waiter cleanup, before transfer or rollback.

        Args:
            acquire (asyncio.Task[bool]): Semaphore acquisition task.

        Returns:
            bool: True only for a completed successful acquire, never a cancelled waiter.
        """
        if not acquire.done() or acquire.cancelled():
            return False
        return acquire.exception() is None and acquire.result() is True

    @staticmethod
    async def _join_slot_waiters(*, acquire: asyncio.Task[bool], abort: asyncio.Task[bool]) -> None:
        """Join both slot waiters before a permit is transferred or rolled back.

        WHAT: Cancels unfinished waiters and waits until both settle; repeated
            runner cancellation cannot abandon cleanup and is re-raised once both
            have joined. Waiter exceptions are retrieved, never propagated.
        WHO: Called from ``_acquire_child_slot``'s finally.
        WHEN: After the first waiter completes or the runner is cancelled.

        Args:
            acquire (asyncio.Task[bool]): Semaphore waiter, possibly holding a permit.
            abort (asyncio.Task[bool]): Reservation-event waiter.

        Raises:
            asyncio.CancelledError: Cleanup was interrupted, after both waiters settled.
        """
        for waiter in (acquire, abort):
            if not waiter.done():
                waiter.cancel()
        joined: asyncio.Future[tuple[bool | BaseException, bool | BaseException]] = asyncio.gather(
            acquire, abort, return_exceptions=True
        )
        interrupted: bool = False
        while not joined.done():
            try:
                await asyncio.shield(joined)
            except asyncio.CancelledError:
                interrupted = True
        joined.result()
        if interrupted:
            raise asyncio.CancelledError

    async def _run_admitted(self, *, process: SubAgentProcess, task: SubAgentTaskDAO) -> SubAgentResultDAO:
        """Run the admitted wrapper, or publish its sealed or targeted pending abort.

        WHAT: With no await between these checks and run entry, a sealed pool or a
            targeted abort reservation publishes the aborted pending candidate
            through the wrapper's ``finish_without_spawn`` (never spawning);
            otherwise the wrapper runs to its winner.
        WHO: Called only by ``_run_with_slot``.
        WHEN: Immediately after the slot decision.

        Args:
            process (SubAgentProcess): Registered wrapper for this incarnation.
            task (SubAgentTaskDAO): Task the wrapper executes.

        Returns:
            SubAgentResultDAO: Registry winner for the incarnation.
        """
        if self._sealed:
            return await process.finish_without_spawn(
                result=self._sealed_task_result(task=task, session_id=process.session_id).model_copy(
                    update={"execution_id": process.execution_id}
                ),
                terminal_reason="operator_abort",
                terminated_by="abort",
            )
        if (process.session_id, process.execution_id) in self._abort_requested_children:
            return await process.finish_without_spawn(
                result=self._child_abort_pending_result(task=task, process=process),
                terminal_reason="operator_abort",
                terminated_by="abort",
            )
        return await process.run()

    @staticmethod
    def _sealed_task_result(*, task: SubAgentTaskDAO, session_id: str) -> SubAgentResultDAO:
        """Build the terminal result for work blocked by the pool seal."""
        return SubAgentResultDAO(
            task_id=task.task_id,
            session_id=session_id,
            status="aborted",
            answer="pool sealed by abort before child spawn",
            exit_code=2,
        )

    @staticmethod
    def _child_abort_pending_result(*, task: SubAgentTaskDAO, process: SubAgentProcess) -> SubAgentResultDAO:
        """Build the aborted exit-2 candidate for a targeted abort that prevented spawn.

        Args:
            task (SubAgentTaskDAO): Task the incarnation would have run.
            process (SubAgentProcess): Never-entered wrapper of the incarnation.

        Returns:
            SubAgentResultDAO: Complete aborted candidate carrying the execution identity.
        """
        return SubAgentResultDAO(
            task_id=task.task_id,
            session_id=process.session_id,
            status="aborted",
            answer="aborted by operator before child spawn",
            exit_code=2,
            execution_id=process.execution_id,
        )

    async def _run_chain(
        self,
        *,
        resolved: tuple[ResolvedDispatchTaskDAO, ...],
        dispatch: DispatchIdentityDAO,
        reservation: _DispatchReservation,
    ) -> list[SubAgentResultDAO]:
        """Run steps sequentially, substituting ``{previous}`` and stopping on noncompletion.

        Each step's prompt may contain ``{previous}``, which is replaced with the
        prior step's final answer before the child is spawned. A step that does
        not complete stops the chain with no automatic retry; the remaining steps'
        reserved sessions are released by dispatch teardown. Every step joins the
        dispatch captured at admission, even when a newer batch is displayed.

        Args:
            resolved (tuple[ResolvedDispatchTaskDAO, ...]): Ordered admitted steps.
            dispatch (DispatchIdentityDAO): Batch identity captured at admission.
            reservation (_DispatchReservation): The batch's session reservation.

        Returns:
            list[SubAgentResultDAO]: Results for the steps that were run.
        """
        results: list[SubAgentResultDAO] = []
        previous_answer: str = ""
        for step in resolved:
            stepped: ResolvedDispatchTaskDAO = step.model_copy(
                update={
                    "task": step.task.model_copy(
                        update={"prompt": step.task.prompt.replace("{previous}", previous_answer)}
                    )
                }
            )
            result: SubAgentResultDAO = await self._run_one(
                resolved=stepped, dispatch=dispatch, reservation=reservation
            )
            results.append(result)
            if result.status != "completed":
                break
            previous_answer = result.answer
        return results

    async def abort_and_drain(self) -> None:
        """Seal the pool and await one shared ordered abort shutdown.

        WHAT: Makes concurrent abort callers join the same seal, cancel, and record work.
        WHO: Called by session abort and HeadlessRunner terminal cleanup paths.
        WHEN: After the first cooperative abort request; later callers wait for completion.
        """
        if self._abort_and_drain_task is None:
            if self._sealed:
                return
            self._abort_and_drain_task = asyncio.create_task(self._run_abort_and_drain())
        await asyncio.shield(self._abort_and_drain_task)

    async def _run_abort_and_drain(self) -> None:
        """Perform the pool-owned ordered abort sequence.

        WHAT: Seals new dispatches, cancels active children (confirmed reaps commit
            canonical aborted winners inside each wrapper), then publishes pending
            aborts for never-started wrappers and reports hard reaps.
        WHO: Started exactly once by abort_and_drain.
        WHEN: During the pool's first cooperative abort request.
        """
        self._sealed = True
        await self.cancel_all()
        await self._record_abort_outcomes()

    async def cancel_all(self) -> None:
        """Cancel every active child and retain its shared-reaper outcome.

        WHAT: Delegates each wrapper cancellation without allowing one failure to block peers.
        WHO: Called by abort_and_drain during the ordered pool shutdown.
        WHEN: After the pool is sealed and before terminal fleet records are written.
        """
        processes: list[SubAgentProcess] = list(self._active_by_session_id.values())
        outcomes: list[object] = await asyncio.gather(
            *[process.cancel() for process in processes],
            return_exceptions=True,
        )
        for process, outcome in zip(processes, outcomes):
            if isinstance(outcome, BaseException):
                self._cancel_outcomes[process.session_id] = "unresolved"
                continue
            if outcome in {"graceful", "killed", "already_dead", "recycled_pid", "unresolved"}:
                self._cancel_outcomes[process.session_id] = outcome  # type: ignore[assignment]

    async def _record_abort_outcomes(self) -> None:
        """Publish sealed pending aborts and report hard reaps without writing terminal state.

        WHAT: Never-started wrappers latched by cancel_all publish their pending
            abort through the wrapper gateway, so the fleet shows them aborted at
            drain time; their ``_run_one`` later returns that same winner and emits
            the single lifecycle. Killed children get a ``sub_agent_reaped`` event.
            Running, unresolved or wrapper-less entries are never terminalized here.
        WHO: Called by abort_and_drain after child cancellation returns.
        WHEN: Once after a pool has completed its ordered shutdown.
        """
        for process in list(self._active_by_session_id.values()):
            if process.awaiting_pending_abort:
                await process.finish_without_spawn(
                    result=self._sealed_task_result(
                        task=process.task, session_id=process.session_id
                    ).model_copy(update={"execution_id": process.execution_id}),
                    terminal_reason="operator_abort",
                    terminated_by="abort",
                )
        for entry in self._registry.snapshot():
            if self._cancel_outcomes.get(entry.session_id) != "killed":
                continue
            await self._emit_lifecycle(
                kind="sub_agent_reaped",
                task_id=entry.task_id,
                session_id=entry.session_id,
                metadata=self._reaped_metadata(session_id=entry.session_id, execution_id=entry.execution_id),
            )

    async def abort_child(self, *, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        """Stop one owned child without sealing the pool or cancelling siblings.

        WHAT: Revalidates owner, parent, run and exact incarnation, then joins the
            incarnation's accepted cancellation or starts one. The pool owns that
            cancellation through terminal cleanup even if this caller stops
            waiting. A natural terminal winner already recorded stays authoritative.
        WHO: Called by the session facade or the runner's child-control consumer
            after operator confirmation.
        WHEN: Any time during the pool's life; repeated requests join one operation.

        Args:
            request (ChildAbortRequestDAO): Exact current-run child identity.

        Returns:
            ChildAbortOutcomeDAO: Observed terminal or refusal outcome carrying this
                request's id; never optimistic success.

        Raises:
            asyncio.CancelledError: The waiting caller was cancelled; the owned
                cancellation continues.
        """
        refusal: Optional[ChildAbortOutcomeDAO] = self._child_abort_refusal(request=request)
        if refusal is not None:
            return refusal
        task: asyncio.Task[ChildAbortOutcomeDAO] = self._join_or_start_child_abort(request=request)
        outcome: ChildAbortOutcomeDAO = await asyncio.shield(task)
        return outcome.model_copy(update={"request_id": request.request_id})

    def _child_abort_refusal(self, *, request: ChildAbortRequestDAO) -> Optional[ChildAbortOutcomeDAO]:
        """Return the refusal for a request the pool must not execute, else None.

        WHAT: not_owned for a foreign owner/parent/run or a stale or absent
            incarnation; None to join an accepted cancellation; already_terminal
            for a recorded winner; unavailable while closing or without an owning
            wrapper. Has no side effects.
        WHO: Called only by ``abort_child``.
        WHEN: Before any reservation, on every request.

        Args:
            request (ChildAbortRequestDAO): Untrusted-until-checked request.

        Returns:
            Optional[ChildAbortOutcomeDAO]: Refusal outcome, or None to proceed.
        """
        identity: tuple[str, str] = (request.session_id, request.execution_id)
        if not self._names_current_incarnation(request=request):
            return ChildAbortOutcomeDAO.for_request(request=request, outcome="not_owned")
        if self._child_abort_joinable(identity=identity):
            return None
        terminal: Optional[SubAgentResultDAO] = self._registry.terminal_result(
            session_id=request.session_id, execution_id=request.execution_id
        )
        if terminal is not None:
            return ChildAbortOutcomeDAO.for_request(
                request=request, outcome="already_terminal", terminal_status=terminal.status
            )
        if self._sealed or identity not in self._child_abort_events:
            return ChildAbortOutcomeDAO.for_request(request=request, outcome="unavailable")
        return None

    def _names_current_incarnation(self, *, request: ChildAbortRequestDAO) -> bool:
        """Return whether the request names this pool's identity and a current member.

        Registry membership is required; a capture directory alone never makes
        a session a member.

        Args:
            request (ChildAbortRequestDAO): Request under validation.

        Returns:
            bool: True when owner, parent, run and current execution all match.
        """
        composed: tuple[str, str, str] = (self._owner_session_id, self._orchestrator_session_id, self._run_id)
        if (request.owner_session_id, request.orchestrator_session_id, request.run_id) != composed:
            return False
        entry = self._registry.get(session_id=request.session_id)
        return entry is not None and entry.execution_id == request.execution_id

    def _child_abort_joinable(self, *, identity: tuple[str, str]) -> bool:
        """Return whether an accepted cancellation exists that a new request joins.

        A retained unresolved outcome is joined (no repeated reap) until natural
        terminal evidence changes eligibility.

        Args:
            identity (tuple[str, str]): ``(session_id, execution_id)`` incarnation.

        Returns:
            bool: True for an in-flight task or a retained settled outcome.
        """
        task: Optional[asyncio.Task[ChildAbortOutcomeDAO]] = self._child_abort_tasks.get(identity)
        if task is None or task.cancelled():
            return False
        if not task.done():
            return True
        terminal: Optional[SubAgentResultDAO] = self._registry.terminal_result(
            session_id=identity[0], execution_id=identity[1]
        )
        return not (task.result().outcome == "unresolved" and terminal is not None)

    def _join_or_start_child_abort(
        self, *, request: ChildAbortRequestDAO
    ) -> asyncio.Task[ChildAbortOutcomeDAO]:
        """Reserve the incarnation before yielding so every caller shares one cancellation.

        WHAT: Returns the joinable accepted task, or synchronously reserves the
            incarnation, sets its abort event (waking a capacity waiter) and starts
            the tracked pool-owned cancellation task. Never seals the pool.
        WHO: Called only by ``abort_child`` after validation.
        WHEN: With no await between validation and reservation.

        Args:
            request (ChildAbortRequestDAO): Validated current-run member.

        Returns:
            asyncio.Task[ChildAbortOutcomeDAO]: Pool-owned tracked cancellation task.
        """
        identity: tuple[str, str] = (request.session_id, request.execution_id)
        if self._child_abort_joinable(identity=identity):
            return self._child_abort_tasks[identity]
        self._abort_requested_children.add(identity)
        self._child_abort_events[identity].set()
        task: asyncio.Task[ChildAbortOutcomeDAO] = asyncio.create_task(
            self._cancel_owned_child(request=request)
        )
        task.add_done_callback(self._retrieve_child_abort_error)
        self._child_abort_tasks[identity] = task
        return task

    async def _cancel_owned_child(self, *, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        """Run one admitted cancellation, translating wrapper failures to unresolved.

        WHAT: The owned-task boundary: ordinary failures become a fixed
            unresolved outcome (never failed/aborted fiction) with a fixed log
            reason; cancellation of the pool itself propagates.
        WHO: Runs once as the pool-owned task created by ``_join_or_start_child_abort``.
        WHEN: Immediately after reservation; ``abort_child`` shields it.

        Args:
            request (ChildAbortRequestDAO): Validated current execution identity.

        Returns:
            ChildAbortOutcomeDAO: Canonical terminal observation or unresolved refusal.
        """
        try:
            return await self._observe_owned_cancellation(request=request)
        except Exception:  # noqa: BLE001 - owned-task boundary; no exception text escapes
            log_warning(msg="child_abort_operation_unresolved", session_id=request.session_id)
            return ChildAbortOutcomeDAO.for_request(request=request, outcome="unresolved")

    async def _observe_owned_cancellation(self, *, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        """Cancel the exact wrapper, then observe the incarnation's canonical winner.

        WHAT: A pending wrapper latches without a reaper and the set event wakes
            its runner; a spawned one joins its shared identity-checked reaper. An
            unresolved or recycled reap returns unresolved at once, leaving the
            completion future to normal cleanup. Otherwise the completion future's
            winner decides aborted versus already_terminal. Never awaits run itself.
        WHO: Called only by ``_cancel_owned_child``.
        WHEN: Once per admitted cancellation.

        Args:
            request (ChildAbortRequestDAO): Validated current execution identity.

        Returns:
            ChildAbortOutcomeDAO: Outcome derived from canonical evidence only.
        """
        identity: tuple[str, str] = (request.session_id, request.execution_id)
        process: Optional[SubAgentProcess] = self._active_by_session_id.get(request.session_id)
        if process is not None and process.execution_id == request.execution_id:
            reap_outcome: Optional[ReapOutcome] = await process.cancel()
            if reap_outcome in {"unresolved", "recycled_pid"}:
                return ChildAbortOutcomeDAO.for_request(request=request, outcome="unresolved")
        winner: SubAgentResultDAO = await asyncio.shield(self._child_completion[identity])
        return ChildAbortOutcomeDAO.for_request(
            request=request,
            outcome="aborted" if winner.status == "aborted" else "already_terminal",
            terminal_status=winner.status,
        )

    @staticmethod
    def _retrieve_child_abort_error(task: asyncio.Task[ChildAbortOutcomeDAO]) -> None:
        """Retrieve a cancellation task's exception so none is reported unobserved.

        Args:
            task (asyncio.Task[ChildAbortOutcomeDAO]): Finished cancellation task.
        """
        if not task.cancelled():
            task.exception()

    def _reaped_metadata(self, *, session_id: str, execution_id: str) -> dict[str, object]:
        """Return the dispatch metadata of a reaped child's current incarnation.

        Args:
            session_id (str): Reaped child session.
            execution_id (str): Its current incarnation.

        Returns:
            dict[str, object]: The registering batch's lifecycle metadata, or only
                the execution identity when no batch registered it.
        """
        dispatch: Optional[DispatchIdentityDAO] = self._registry.dispatch_of(
            session_id=session_id, execution_id=execution_id
        )
        if dispatch is None:
            return {"execution_id": execution_id}
        return dispatch.lifecycle_metadata(execution_id=execution_id)

    async def _emit_dispatch_started(self, *, dispatch: DispatchIdentityDAO) -> None:
        """Emit the stream-only start event of one admitted batch.

        WHAT: Relays ``sub_agent_dispatch_started`` with exactly the orchestrator
            session, dispatch id and sequence. It has no ``sub_agent_id``, so the
            session history subscriber never persists it.
        WHO: Called by ``_run_admitted_batch``.
        WHEN: Immediately after admission, before any child is registered.

        Args:
            dispatch (DispatchIdentityDAO): Identity captured at admission.
        """
        await self._relay(
            AgentStreamEventDAO(
                kind="sub_agent_dispatch_started",
                metadata=dispatch.started_metadata(orchestrator_session_id=self._orchestrator_session_id),
            )
        )

    async def _emit_lifecycle(
        self,
        *,
        kind: str,
        task_id: str,
        session_id: str,
        metadata: dict[str, object],
        prompt_preview: str = "",
    ) -> None:
        """Emit one orchestrator-level lifecycle event to the relay.

        Called at the start and end of each sub-agent run so the TUI (and
        history) can track spawned / completed / failed events.

        Args:
            kind (str): One of ``sub_agent_spawned``, ``sub_agent_completed``,
                ``sub_agent_failed``, ``sub_agent_aborted``, ``sub_agent_reaped``.
            task_id (str): The task the event concerns.
            session_id (str): The child session identifier.
            metadata (dict[str, object]): Captured dispatch identity plus the
                child's execution_id; the history subscriber copies it into the
                existing audit records.
            prompt_preview (str): TaskPreview label carried on ``sub_agent_spawned``
                events so the TUI can show meaningful fleet-row text before the
                first ``text_delta`` arrives. Empty string for other events.
        """
        await self._relay(
            AgentStreamEventDAO(
                kind=kind,  # type: ignore[arg-type]
                sub_agent_id=session_id,
                task_id=task_id,
                content=prompt_preview if prompt_preview else None,
                metadata=metadata,
            )
        )

    def _aggregate(
        self,
        *,
        mode: SubAgentMode,
        results: list[SubAgentResultDAO],
    ) -> OrchestratorResultDAO:
        """Aggregate per-task results into the orchestrator return value.

        Args:
            mode (SubAgentMode): The mode the batch ran under.
            results (list[SubAgentResultDAO]): Per-task terminal results.

        Returns:
            OrchestratorResultDAO: Aggregated batch result.
        """
        failed: list[str] = [r.task_id for r in results if r.status != "completed"]
        return OrchestratorResultDAO(
            mode=mode,
            results=results,
            all_completed=not failed,
            failed_task_ids=failed,
        )
