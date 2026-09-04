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
from typing import Optional
from uuid import uuid4

from config.cfg import SLO_HOME, SUBAGENT_MAX_CONCURRENCY, SUBAGENT_MAX_TASKS
from src.agents.slo_agent.orchestrator.dao import (
    OrchestratorResultDAO,
    lifecycle_kind_for_status,
    terminal_reason_for_status,
    SubAgentMode,
    SubAgentResultDAO,
    SubAgentStatusDAO,
    SubAgentTaskDAO,
)
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.reaper import ReapOutcome
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry
from src.agents.slo_agent.sessions.dao import AgentEventSubscriber
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.filesystem_store import (
    FilesystemSessionHistoryStore,
    default_history_root,
)

__all__ = ["SubAgentPool", "MAX_CONCURRENCY", "MAX_PARALLEL_TASKS"]


MAX_CONCURRENCY: int = SUBAGENT_MAX_CONCURRENCY
"""Maximum simultaneously running child processes per pool.

Overridable via the ``SLO_SUBAGENT_MAX_CONCURRENCY`` environment variable.
"""

MAX_PARALLEL_TASKS: int = SUBAGENT_MAX_TASKS
"""Maximum tasks accepted per ``dispatch()`` call.

Overridable via the ``SLO_SUBAGENT_MAX_TASKS`` environment variable.
"""


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
        _registry (ProcessRegistry): Lifecycle registry for this pool.
        _active (list[SubAgentProcess]): Currently active process wrappers;
            used by ``cancel_all()``.
    """

    def __init__(
        self,
        *,
        orchestrator_session_id: str,
        default_model: Optional[str],
        relay: AgentEventSubscriber,
        child_system_prompt: str = "",
    ) -> None:
        """Initialise the pool with its identity, model, relay, and fresh registry.

        Args:
            orchestrator_session_id (str): Parent session identifier.
            default_model (Optional[str]): Inherited model for tasks without an override.
            relay (AgentEventSubscriber): Orchestrator relay callable.
            child_system_prompt (str): Assembled system prompt shared by all child
                processes. Written to ``spawn_context.json`` via each
                ``SubAgentProcess``. Defaults to empty string for backwards compat.
        """
        self._orchestrator_session_id: str = orchestrator_session_id
        self._default_model: Optional[str] = default_model
        self._relay: AgentEventSubscriber = relay
        self._child_system_prompt: str = child_system_prompt
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        fleet_store: FleetStore = FleetStore(
            history_root=default_history_root(),
            orchestrator_session_id=orchestrator_session_id,
            workflow_id=os.environ.get("SLO_WORKFLOW_ID"),
        )
        self._registry: ProcessRegistry = ProcessRegistry(fleet_store=fleet_store)
        self._active: list[SubAgentProcess] = []
        self._sealed: bool = False
        self._abort_and_drain_task: Optional[asyncio.Task[None]] = None
        self._cancel_outcomes: dict[str, ReapOutcome] = {}

    @property
    def registry(self) -> ProcessRegistry:
        """Return the pool-owned process registry for external observers.

        Returns:
            ProcessRegistry: The live process registry for this pool.
        """
        return self._registry

    async def dispatch(
        self,
        *,
        mode: SubAgentMode,
        tasks: list[SubAgentTaskDAO],
    ) -> OrchestratorResultDAO:
        """Run a batch of tasks under the requested dispatch mode.

        Rejects batches larger than ``MAX_PARALLEL_TASKS`` before spawning
        any child so the orchestrator gets immediate feedback on oversized
        requests.

        Args:
            mode (SubAgentMode): ``"parallel"``, ``"chain"``, or ``"single"``.
            tasks (list[SubAgentTaskDAO]): Ordered task list.

        Returns:
            OrchestratorResultDAO: Aggregated batch result.
        """
        if self._sealed:
            return OrchestratorResultDAO(
                mode=mode,
                results=[],
                all_completed=False,
                failed_task_ids=[task.task_id for task in tasks],
                error="pool sealed by abort; no new sub-agents will be spawned",
            )
        if len(tasks) > MAX_PARALLEL_TASKS:
            return OrchestratorResultDAO(
                mode=mode,
                all_completed=False,
                failed_task_ids=[t.task_id for t in tasks],
            )
        if mode == "chain":
            results: list[SubAgentResultDAO] = await self._run_chain(tasks=tasks)
        else:
            results = list(await asyncio.gather(*[self._run_one(task=t) for t in tasks]))
        return self._aggregate(mode=mode, results=results)

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

    async def _run_one(self, *, task: SubAgentTaskDAO) -> SubAgentResultDAO:
        """Spawn and await one task under the concurrency semaphore.

        Lifecycle: register → emit spawned → acquire semaphore → mark running
        → run process → mark terminal → emit completed/failed → return result.

        Args:
            task (SubAgentTaskDAO): The task to run.

        Returns:
            SubAgentResultDAO: Terminal result for this task.
        """
        session_id: str = await self._resolve_child_session_id(task=task)
        if self._sealed:
            return self._sealed_task_result(task=task, session_id=session_id)
        self._registry.register(
            task_id=task.task_id,
            session_id=session_id,
            task=task,
        )
        await self._emit_lifecycle(
            kind="sub_agent_spawned",
            task_id=task.task_id,
            session_id=session_id,
            prompt_preview=task.prompt[:80],
        )
        process: SubAgentProcess = SubAgentProcess(
            task=task,
            session_id=session_id,
            model=task.model or self._default_model,
            relay=self._relay,
            registry=self._registry,
            system_prompt=self._child_system_prompt,
            parent_session_id=self._orchestrator_session_id,
            slo_home=SLO_HOME,
        )
        self._active.append(process)
        try:
            async with self._semaphore:
                if self._sealed:
                    return self._sealed_task_result(task=task, session_id=session_id)
                result: SubAgentResultDAO = await process.run()
            recorded: Optional[SubAgentStatusDAO] = self._registry.get(session_id=session_id)
            if recorded is not None and recorded.status in {"completed", "failed", "aborted"}:
                await self._emit_lifecycle(
                    kind=lifecycle_kind_for_status(status=recorded.status),
                    task_id=task.task_id,
                    session_id=session_id,
                )
                return result.model_copy(
                    update={
                        "status": recorded.status,
                        "answer": recorded.last_text or result.answer,
                        "exit_code": (
                            recorded.exit_code if recorded.exit_code is not None else result.exit_code
                        ),
                    }
                )
            terminal_kind: str = lifecycle_kind_for_status(status=result.status)
            self._registry.mark_terminal(
                session_id=session_id,
                status=result.status,
                answer=result.answer,
                exit_code=result.exit_code,
                terminal_reason=terminal_reason_for_status(status=result.status),  # type: ignore[arg-type]
                terminated_by="natural",
            )
            await self._emit_lifecycle(
                kind=terminal_kind,
                task_id=task.task_id,
                session_id=session_id,
            )
            return result
        finally:
            self._active.remove(process)

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

    async def _run_chain(
        self,
        *,
        tasks: list[SubAgentTaskDAO],
    ) -> list[SubAgentResultDAO]:
        """Run tasks sequentially, substituting ``{previous}`` and stopping on failure.

        Each step's prompt may contain ``{previous}``, which is replaced with
        the prior step's final answer before the child is spawned. A failed step
        stops the chain; remaining tasks are not run.

        Args:
            tasks (list[SubAgentTaskDAO]): Ordered chain steps.

        Returns:
            list[SubAgentResultDAO]: Results for the steps that were run.
        """
        results: list[SubAgentResultDAO] = []
        previous_answer: str = ""
        for task in tasks:
            stepped: SubAgentTaskDAO = task.model_copy(
                update={"prompt": task.prompt.replace("{previous}", previous_answer)}
            )
            result: SubAgentResultDAO = await self._run_one(task=stepped)
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

        WHAT: Seals new dispatches, cancels active children, then records abort facts.
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
        processes: list[SubAgentProcess] = list(self._active)
        outcomes: list[object] = await asyncio.gather(
            *[process.cancel() for process in processes],
            return_exceptions=True,
        )
        for process, outcome in zip(processes, outcomes):
            if isinstance(outcome, BaseException):
                self._cancel_outcomes[process._session_id] = "unresolved"
                continue
            if outcome in {"graceful", "killed", "already_dead", "recycled_pid", "unresolved"}:
                self._cancel_outcomes[process._session_id] = outcome  # type: ignore[assignment]

    async def _record_abort_outcomes(self) -> None:
        """Mark running fleet entries aborted and report hard reaps.

        WHAT: Persists operator-abort ownership only for still-running entries.
        WHO: Called by abort_and_drain after child cancellation returns.
        WHEN: Once after a pool has completed its ordered shutdown.
        """
        for entry in self._registry.snapshot():
            if entry.status not in {"pending", "running"}:
                continue
            if self._cancel_outcomes.get(entry.session_id) == "unresolved":
                continue
            self._registry.mark_terminal(
                session_id=entry.session_id,
                status="aborted",
                answer="aborted by operator",
                exit_code=2,
                terminal_reason="operator_abort",
                terminated_by="abort",
            )
            if self._cancel_outcomes.get(entry.session_id) != "killed":
                continue
            await self._emit_lifecycle(
                kind="sub_agent_reaped",
                task_id=entry.task_id,
                session_id=entry.session_id,
            )

    async def _emit_lifecycle(
        self,
        *,
        kind: str,
        task_id: str,
        session_id: str,
        prompt_preview: str = "",
    ) -> None:
        """Emit one orchestrator-level lifecycle event to the relay.

        Called at the start and end of each sub-agent run so the TUI (and
        history) can track spawned / completed / failed events.

        Args:
            kind (str): One of ``sub_agent_spawned``, ``sub_agent_completed``,
                ``sub_agent_failed``.
            task_id (str): The task the event concerns.
            session_id (str): The child session identifier.
            prompt_preview (str): First 80 characters of the task prompt;
                carried on ``sub_agent_spawned`` events so the TUI can show
                meaningful fleet-row text before the first ``text_delta``
                arrives. Empty string for terminal lifecycle events.
        """
        await self._relay(
            AgentStreamEventDAO(
                kind=kind,  # type: ignore[arg-type]
                sub_agent_id=session_id,
                task_id=task_id,
                content=prompt_preview if prompt_preview else None,
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
