"""LaunchWorkflowTool — detach a dynamic workflow as a headless orchestrator (spec 57.a.2).

The tool mirrors the ``SpawnSubAgentsTool`` factory shape: a ``*SchemaDAO``
args model, a ``build(...)`` classmethod returning a bound ``BaseTool``, and
operational and tool-validation errors returned as JSON strings. Direct schema
construction and invalid factory defaults still raise validation errors. Unlike
``spawn_sub_agents`` it does not await the child: the orchestrator process is
spawned with ``start_new_session=True`` (its own process group) and the tool
returns the workflow handle JSON within seconds.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
from pathlib import Path
from typing import IO, Awaitable, Callable, Optional, Protocol
from uuid import uuid4

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from src.agents.reasoning_capabilities import ReasoningLevel

import config.cfg as cfg_module
from config.logger import log_info
from src.agents.slo_agent.history.filesystem_store import default_history_root
from src.agents.slo_agent.orchestrator.capture_writer import WorkflowCaptureCompletionContext
from src.agents.slo_agent.orchestrator.spawn_env import build_headless_child_env, open_capture_file_append
from src.agents.slo_agent.orchestrator.workflow_registry import (
    WorkflowHandleDAO,
    WorkflowHandleStore,
    WorkflowStateTransitionError,
)

__all__ = ["LaunchWorkflowSchemaDAO", "LaunchWorkflowTool", "SpawnCallable"]


class _ProcessLike(Protocol):
    """Minimal spawned-process surface the tool depends on."""

    pid: int


SpawnCallable = Callable[..., Awaitable[_ProcessLike]]


class LaunchWorkflowSchemaDAO(BaseModel):
    """Validated input schema for the ``launch_workflow`` LangChain tool."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    brief: str = Field(
        description=(
            "Self-contained workflow brief for the detached orchestrator: the workflow "
            "name and file path, the feature context, repository paths, and output "
            "locations. The orchestrator receives ONLY this text as its prompt."
        ),
    )
    reasoning_level: Optional[ReasoningLevel] = Field(
        default=None,
        description=(
            "Canonical orchestrator reasoning override. Omitted/null uses the tool's "
            "bootstrap-time default; child model policy may clamp. Does not configure "
            "phase agents or persist across managed resume."
        ),
    )
    cwd: Optional[str] = Field(default=None, description="Working directory override.")
    model: Optional[str] = Field(default=None, description="Orchestrator model override.")


def _build_argv(
    *,
    brief: str,
    orchestrator_session_id: str,
    owner_session_id: str,
    model: Optional[str],
    cwd: str,
    reasoning_level: Optional[ReasoningLevel] = None,
) -> list[str]:
    """Build the detached headless orchestrator command line.

    Mirrors ``SubAgentProcess._build_argv``: ``sys.executable -m src.cli``
    keeps the child on the same interpreter and virtualenv as the parent in
    both dev and installed layouts.

    Args:
        brief (str): Workflow brief passed as the headless ``-p`` prompt.
        orchestrator_session_id (str): Fresh session id for the orchestrator.
        owner_session_id (str): TUI session whose inbox receives lifecycle notes.
        model (Optional[str]): Orchestrator model override; ``None`` omits the flag.
        cwd (str): Working directory the workflow operates in.
        reasoning_level (Optional[ReasoningLevel]): Canonical request passed unchanged;
            None omits the flag, preserving child preference/seed resolution.

    Returns:
        list[str]: Argv for ``create_subprocess_exec``.
    """
    argv: list[str] = [
        sys.executable,
        "-m",
        "src.cli",
        "run",
        "--orchestrator",
        "--json",
        "--enable-history",
        "-p",
        brief,
        "--session-id",
        orchestrator_session_id,
        "--notify-session",
        owner_session_id,
        "--cwd",
        cwd,
    ]
    if model is not None:
        argv += ["--model", model]
    if reasoning_level is not None:
        argv += ["--reasoning", reasoning_level]
    return argv


class LaunchWorkflowTool:
    """Factory for the ``launch_workflow`` LangChain tool.

    Built once per TUI session by ``OrchestratorSessionBootstrap.attach`` and
    injected into the session tool bundle next to ``spawn_sub_agents``. Model and
    reasoning defaults are immutable construction snapshots, not live settings.
    Child policy owns clamping; managed resume does not retain the request.
    """

    @classmethod
    def build(
        cls,
        *,
        owner_session_id: str,
        default_model: Optional[str],
        default_reasoning_level: Optional[ReasoningLevel] = None,
        handle_store: Optional[WorkflowHandleStore] = None,
        spawn: Optional[SpawnCallable] = None,
        history_root: Optional[Path] = None,
    ) -> BaseTool:
        """Build a ``launch_workflow`` tool bound to one owning session.

        Args:
            owner_session_id (str): The TUI session that owns launched workflows.
            default_model (Optional[str]): Construction-time model snapshot.
            default_reasoning_level (Optional[ReasoningLevel]): Immutable reasoning fallback;
                None preserves child preferences and model defaults.
            handle_store (Optional[WorkflowHandleStore]): Injectable store for tests.
            spawn (Optional[SpawnCallable]): Injectable process creator for tests.
                ``None`` uses ``asyncio.create_subprocess_exec``.
            history_root (Optional[Path]): Root for handle files and orchestrator
                capture files. ``None`` uses ``default_history_root()``.

        Returns:
            BaseTool: A bound LangChain tool the LLM can call.

        Raises:
            ValidationError: Invalid reasoning default, before dependencies are resolved.
        """
        bound_reasoning_level: Optional[ReasoningLevel] = TypeAdapter(
            Optional[ReasoningLevel]
        ).validate_python(default_reasoning_level)
        _history_root: Path = history_root or default_history_root()
        _store: WorkflowHandleStore = handle_store or WorkflowHandleStore(history_root=_history_root)
        _spawn: SpawnCallable = spawn or asyncio.create_subprocess_exec  # type: ignore[assignment]
        _default_model: Optional[str] = default_model

        @tool(args_schema=LaunchWorkflowSchemaDAO)
        async def launch_workflow(
            brief: str,
            cwd: Optional[str] = None,
            model: Optional[str] = None,
            reasoning_level: Optional[ReasoningLevel] = None,
        ) -> str:
            """Launch a dynamic workflow as a DETACHED headless orchestrator process.

            Use this ONLY when the user gave an explicit detach qualifier — the
            word "headless", "detached", or "independent" applied to a
            dynamic-workflows request or a named workflow ("headless dynamic
            workflows", "detached dynamic workflows", "independent dynamic
            workflows", "run the code-test-review workflow detached") — or
            equivalent detach wording such as "in the background" or "without
            blocking". An unqualified "dynamic workflows" request runs in-session
            via spawn_sub_agents — do not call this tool for it. Returns immediately with a workflow handle JSON; progress
            arrives later as workflow notes. The detached orchestrator decomposes
            phases and spawns its own sub-agents; do NOT also call
            spawn_sub_agents for the same request.

            Args:
                brief (str): Self-contained workflow brief handed to the
                    detached orchestrator as its headless prompt.
                cwd (Optional[str]): Working directory override; defaults to
                    the current directory.
                model (Optional[str]): Orchestrator model override; defaults to
                    the owning tool's construction-time model snapshot.
                reasoning_level (Optional[ReasoningLevel]): Canonical override;
                    omitted/null inherits the bootstrap snapshot. Child policy may
                    clamp; this neither configures phases nor persists on resume.

            Returns:
                str: Workflow handle JSON (``workflow_id``,
                    ``orchestrator_session_id``, ``pid``, ``state``, …), or an
                    operational or validation error JSON. A handle acknowledges
                    spawn, not child admission or effective reasoning.
            """
            return await cls._launch(
                store=_store,
                spawn=_spawn,
                history_root=_history_root,
                owner_session_id=owner_session_id,
                brief=brief,
                cwd=cwd,
                model=model or _default_model,
                reasoning_level=cls._resolve_reasoning_level(
                    reasoning_level=reasoning_level,
                    default_reasoning_level=bound_reasoning_level,
                ),
            )

        launch_workflow.handle_validation_error = '{"error": "invalid launch_workflow arguments; use brief, cwd, model and canonical reasoning_level"}'
        return launch_workflow

    @classmethod
    async def _launch(
        cls,
        *,
        store: WorkflowHandleStore,
        spawn: SpawnCallable,
        history_root: Path,
        owner_session_id: str,
        brief: str,
        cwd: Optional[str],
        model: Optional[str],
        reasoning_level: Optional[ReasoningLevel],
    ) -> str:
        """Register an initial launch after the bound bridge validates and resolves inputs.

        Existing depth/brief/cap guards precede handle reservation and capture/spawn.
        Resource helpers retain partial-spawn cleanup; cancellation propagates.

        Args:
            store (WorkflowHandleStore): Shared owning-session registry.
            spawn (SpawnCallable): Process creator.
            history_root (Path): Handle and capture root.
            owner_session_id (str): Notification destination.
            brief (str): Workflow prompt, not configuration.
            cwd (Optional[str]): Directory override or current directory.
            model (Optional[str]): Already resolved model snapshot or override.
            reasoning_level (Optional[ReasoningLevel]): Resolved canonical request.

        Returns:
            str: Handle JSON or existing guard/operational-error JSON; a handle
                acknowledges spawn, not child admission or effective reasoning.
        """
        enclosing_workflow_id: Optional[str] = os.environ.get("SLO_WORKFLOW_ID")
        if enclosing_workflow_id:
            return json.dumps(
                {
                    "error": (
                        f"refusing to launch: this session already runs inside "
                        f"detached workflow {enclosing_workflow_id}; detached "
                        f"orchestrators execute phases with spawn_sub_agents"
                    )
                }
            )
        if not brief.strip():
            return json.dumps({"error": "brief must not be blank"})
        cap_refusal: Optional[str] = await cls._cap_refusal(
            store=store,
            owner_session_id=owner_session_id,
        )
        if cap_refusal is not None:
            return cap_refusal
        history_warning: Optional[str] = cls._history_backing_warning(
            history_root=history_root,
            owner_session_id=owner_session_id,
        )
        workflow_id: str = f"wf-{uuid4().hex[:4]}"
        orchestrator_session_id: str = str(uuid4())
        resolved_cwd: str = cwd or os.getcwd()
        handle: WorkflowHandleDAO = WorkflowHandleDAO(
            workflow_id=workflow_id,
            owner_session_id=owner_session_id,
            orchestrator_session_id=orchestrator_session_id,
            pid=0,  # patched after spawn via model_copy + store rewrite
            brief=brief,
            cwd=resolved_cwd,
        )
        try:
            await store.write(handle=handle)
        except (OSError, WorkflowStateTransitionError) as exc:
            return json.dumps({"error": f"workflow launch failed: {exc}"})
        return await cls._spawn_and_patch(
            store=store,
            spawn=spawn,
            history_root=history_root,
            handle=handle,
            model=model,
            reasoning_level=reasoning_level,
            history_warning=history_warning,
        )

    @classmethod
    def _resolve_reasoning_level(
        cls,
        *,
        reasoning_level: Optional[ReasoningLevel],
        default_reasoning_level: Optional[ReasoningLevel],
    ) -> Optional[ReasoningLevel]:
        """Select request data without parsing, model policy or shared-state mutation.

        The validated bridge calls this once per invocation before launch I/O.

        Args:
            reasoning_level (Optional[ReasoningLevel]): Explicit override or None.
            default_reasoning_level (Optional[ReasoningLevel]): Validated bound snapshot.

        Returns:
            Optional[ReasoningLevel]: Non-null override, otherwise the bound fallback.
        """
        if reasoning_level is not None:
            return reasoning_level
        return default_reasoning_level

    @classmethod
    async def _cap_refusal(
        cls,
        *,
        store: WorkflowHandleStore,
        owner_session_id: str,
    ) -> Optional[str]:
        """Return a refusal JSON string when the live-workflow cap is reached.

        Args:
            store (WorkflowHandleStore): Handle store for the owning session.
            owner_session_id (str): Owning TUI session id.

        Returns:
            Optional[str]: Refusal JSON at the cap, ``None`` when under it.
        """
        handles: list[WorkflowHandleDAO] = await store.reconcile(owner_session_id=owner_session_id)
        live: list[WorkflowHandleDAO] = [
            handle for handle in handles if handle.state in ("launching", "running")
        ]
        if len(live) < cfg_module.MAX_DETACHED_WORKFLOWS:
            return None
        return json.dumps(
            {
                "error": (
                    f"workflow cap reached ({len(live)} live, max "
                    f"{cfg_module.MAX_DETACHED_WORKFLOWS}); abort one with /workflows"
                )
            }
        )

    @classmethod
    async def _spawn_and_patch(
        cls,
        *,
        store: WorkflowHandleStore,
        spawn: SpawnCallable,
        history_root: Path,
        handle: WorkflowHandleDAO,
        model: Optional[str],
        history_warning: Optional[str],
        reasoning_level: Optional[ReasoningLevel] = None,
    ) -> str:
        """Spawn the detached orchestrator and patch the handle with its pid.

        The handle is already on disk with state ``launching`` (crash-safe: a
        handle with no live process reconciles to ``failed``). A spawn failure
        marks the handle ``failed`` and returns an error JSON string.

        Args:
            store (WorkflowHandleStore): Handle store for the owning session.
            spawn (SpawnCallable): Process creator.
            history_root (Path): Root for orchestrator capture files.
            handle (WorkflowHandleDAO): Pre-spawn handle (state ``launching``).
            model (Optional[str]): Resolved orchestrator model, when any.
            history_warning (Optional[str]): Existing owner-history warning.
            reasoning_level (Optional[ReasoningLevel]): Unchanged canonical request;
                None preserves the legacy no-flag path.

        Returns:
            str: Patched handle JSON, or an error JSON string on any failure —
                this method never raises into the agent graph.
        """
        child_env: dict[str, str] = build_headless_child_env(workflow_id=handle.workflow_id)
        proc: Optional[_ProcessLike] = None
        capture_warning: Optional[str] = None
        capture_files = contextlib.ExitStack()
        capture_endpoints: list[IO[bytes]] = []
        try:
            stdout_file: IO[bytes] = capture_files.enter_context(
                open_capture_file_append(
                    history_root=history_root,
                    session_id=handle.orchestrator_session_id,
                    name="stdout.jsonl",
                    credential=child_env.get("SLO_OPENROUTER_API_KEY", ""),
                    completion_context=WorkflowCaptureCompletionContext(
                        history_root=history_root,
                        owner_session_id=handle.owner_session_id,
                        workflow_id=handle.workflow_id,
                        expected_pid=0,
                    ),
                )
            )
            stderr_file: IO[bytes] = capture_files.enter_context(
                open_capture_file_append(
                    history_root=history_root,
                    session_id=handle.orchestrator_session_id,
                    name="stderr.log",
                    credential=child_env.get("SLO_OPENROUTER_API_KEY", ""),
                    completion_context=WorkflowCaptureCompletionContext(
                        history_root=history_root,
                        owner_session_id=handle.owner_session_id,
                        workflow_id=handle.workflow_id,
                        expected_pid=0,
                    ),
                )
            )
            capture_endpoints.extend([stdout_file, stderr_file])
            proc = await spawn(
                *_build_argv(
                    brief=handle.brief,
                    orchestrator_session_id=handle.orchestrator_session_id,
                    owner_session_id=handle.owner_session_id,
                    model=model,
                    cwd=handle.cwd,
                    reasoning_level=reasoning_level,
                ),
                start_new_session=True,
                stdout=stdout_file,
                stderr=stderr_file,
                env=child_env,
            )
        except OSError:
            if proc is None:
                with contextlib.suppress(OSError):
                    await asyncio.to_thread(capture_files.close)
                await cls._mark_failed_best_effort(store=store, handle=handle)
                return json.dumps({"error": "workflow launch failed"})
            capture_warning = "capture writer failed"
        patched: WorkflowHandleDAO = handle.model_copy(update={"pid": proc.pid})
        try:
            await store.write(handle=patched)
            cls._activate_capture_files(capture_endpoints=capture_endpoints, handle=patched)
        except (OSError, WorkflowStateTransitionError) as exc:
            # The orchestrator process IS running; only the handle bookkeeping
            # failed (e.g. /workflows abort or a reconcile pass flipped the
            # state underneath us). An operator abort must not leave an
            # orphaned orchestrator invisible to /workflows.
            await cls._reap_if_aborted(store=store, handle=handle, pid=proc.pid)
            return json.dumps(
                {
                    "error": (
                        f"workflow {handle.workflow_id} spawned "
                        f"(pid {proc.pid}) but its handle update failed: {exc}"
                    )
                }
            )
        finally:
            # Writer drain waits must not stall the parent event loop.
            try:
                await asyncio.to_thread(capture_files.close)
            except OSError:
                capture_warning = "capture writer failed"
        payload: dict[str, object] = patched.model_dump(mode="json")
        if capture_warning is not None:
            payload["warning"] = capture_warning
        elif history_warning is not None:
            payload["warning"] = history_warning
        return json.dumps(payload)

    @staticmethod
    def _activate_capture_files(
        *,
        capture_endpoints: list[IO[bytes]],
        handle: WorkflowHandleDAO,
    ) -> None:
        """Activate capture writers only after their workload PID is durable.

        Args:
            capture_endpoints (list[IO[bytes]]): Capture endpoints that own writers.
            handle (WorkflowHandleDAO): Persisted workload identity.
        """
        for capture in capture_endpoints:
            activate = getattr(capture, "activate", None)
            if activate is not None:
                activate(expected_pid=handle.pid)

    @staticmethod
    def _history_backing_warning(*, history_root: Path, owner_session_id: str) -> Optional[str]:
        """Return a monitoring warning when the owner session has no history directory.

        WHAT: Detects whether inbox delivery and later monitoring have durable backing.
        WHO: Called by launch_workflow after it patches a successful handle.
        WHEN: Once per detached workflow launch result.

        Args:
            history_root (Path): Root containing session history directories.
            owner_session_id (str): Session expected to receive workflow notes.

        Returns:
            Optional[str]: Warning text without history backing, otherwise None.
        """
        if (history_root / owner_session_id).exists():
            return None
        return (
            "owner session has no history backing — workflow notes, fleet monitoring, "
            "and resume will not be available for this workflow"
        )

    @classmethod
    async def _reap_if_aborted(
        cls,
        *,
        store: WorkflowHandleStore,
        handle: WorkflowHandleDAO,
        pid: int,
    ) -> None:
        """SIGTERM a freshly spawned process group whose handle was aborted mid-spawn.

        Covers the abort-during-spawn-window race: the operator ran
        ``/workflows abort`` on the pid-0 ``launching`` handle while the spawn
        await was in flight. The handle is terminal ``aborted`` (so
        ``/workflows`` will never reconcile it again) but the just-spawned
        process group is alive — honour the recorded abort by terminating it.
        Best-effort: every failure is logged, never raised.

        Args:
            store (WorkflowHandleStore): Handle store for the owning session.
            handle (WorkflowHandleDAO): Pre-patch handle identity.
            pid (int): Process-group leader pid of the fresh spawn.
        """
        if pid <= 0:
            return
        try:
            current: Optional[WorkflowHandleDAO] = await store.read(
                owner_session_id=handle.owner_session_id,
                workflow_id=handle.workflow_id,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort on an error path
            log_info(
                msg="workflow_reap_check_failed",
                workflow_id=handle.workflow_id,
                error=str(exc),
            )
            return
        if current is None or current.state != "aborted":
            return
        with contextlib.suppress(OSError):
            os.killpg(pid, signal.SIGTERM)
        log_info(
            msg="workflow_aborted_mid_spawn_reaped",
            workflow_id=handle.workflow_id,
            pid=pid,
        )

    @classmethod
    async def _mark_failed_best_effort(
        cls,
        *,
        store: WorkflowHandleStore,
        handle: WorkflowHandleDAO,
    ) -> None:
        """Mark a handle ``failed`` after a launch error, swallowing store errors.

        The caller is already on an error path returning error JSON to the
        LLM; a second failure while recording the first (missing handle,
        state changed by a concurrent reconcile) must not raise into the
        graph.

        Args:
            store (WorkflowHandleStore): Handle store for the owning session.
            handle (WorkflowHandleDAO): Handle whose launch failed.
        """
        try:
            await store.update_state(
                owner_session_id=handle.owner_session_id,
                workflow_id=handle.workflow_id,
                state="failed",
            )
        except Exception as exc:  # noqa: BLE001 — best-effort on an error path
            log_info(
                msg="workflow_mark_failed_skipped",
                workflow_id=handle.workflow_id,
                error=str(exc),
            )
