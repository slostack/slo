"""Workflow handle registry — durable records for detached workflows (spec 57.a.1)."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Literal, Optional, TypeAlias

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_info

__all__ = [
    "WorkflowCommandService",
    "WorkflowHandleDAO",
    "WorkflowHandleStore",
    "WorkflowState",
    "WorkflowStateTransitionError",
    "WorkflowStatusSchemaDAO",
    "WorkflowStatusTool",
]

WorkflowState: TypeAlias = Literal[
    "launching", "running", "completed", "failed", "aborted", "stalled"
]
PidAliveProbe = Callable[[int], bool]
KillCallable = Callable[[int, int], None]
EscalationScheduler = Callable[[float, Callable[[], None]], None]

_ABORT_ESCALATION_SECONDS: float = 5.0
"""Grace after SIGTERM before a surviving workflow process group is SIGKILLed.

``/workflows abort`` first sends SIGTERM to the detached orchestrator's
process group (cooperative shutdown). A process group that is still alive
after this grace is hard-killed — mirroring the TUI's cooperative-then-hard
abort philosophy (``_ABORT_HARD_CANCEL_GRACE_SECONDS``, ``src/tui/app.py``)."""

_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    # launching → aborted: the operator may abort a workflow whose started
    # note has not been claimed yet (/workflows abort during the spawn window).
    "launching": frozenset({"running", "failed", "aborted"}),
    "running": frozenset({"completed", "failed", "aborted", "stalled"}),
    "stalled": frozenset({"failed"}),
}

_LAUNCH_GRACE_SECONDS: float = 30.0
"""Age below which a pid-0 ``launching`` handle is exempt from reconcile.

``LaunchWorkflowTool`` writes the handle with ``pid=0`` *before* the spawn and
patches the real pid afterwards. A reconcile pass that runs inside that window
(slash commands deliberately dispatch mid-turn, and ``/workflows``,
``workflow_status``, and the launch tool's cap check all reconcile) must not
reap the brand-new handle as ``failed`` — doing so would also turn the tool's
post-spawn pid-patch write into an illegal transition. A pid-0 ``launching``
handle older than this grace is genuinely dead (the spawn never completed) and
reconciles to ``failed``."""

_DIR_MODE: int = 0o700
_FILE_MODE: int = 0o600

_UNSAFE_WORKFLOW_ID_MARKERS: tuple[str, ...] = ("/", "\\", "..", "\x00")
"""Path-meta sequences rejected in workflow ids before any filesystem join.

Workflow ids reach the store from inbox payloads and user-typed
``/workflows abort <id>`` arguments; they are used as file names and must
never be able to escape the per-session ``workflows/`` directory."""


class WorkflowStateTransitionError(RuntimeError):
    """Raised when a workflow state transition is illegal."""


class WorkflowHandleDAO(BaseModel):
    """Durable record of one detached workflow owned by a TUI session."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str = Field(description="Stable id, e.g. 'wf-3f2a'.")
    owner_session_id: str = Field(description="TUI session that launched the workflow.")
    orchestrator_session_id: str = Field(description="Detached orchestrator session id.")
    pid: int = Field(description="Orchestrator process id or process-group leader.")
    brief: str = Field(description="Workflow brief passed to the orchestrator.")
    cwd: str = Field(description="Working directory the workflow operates in.")
    state: WorkflowState = Field(default="launching", description="Last known workflow state.")
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC launch timestamp.",
    )


class WorkflowStatusSchemaDAO(BaseModel):
    """Validated input schema for the ``workflow_status`` tool."""

    workflow_id: Optional[str] = Field(
        default=None,
        description="Workflow id to inspect. Omit to list all session workflows.",
    )


class WorkflowHandleStore:
    """Filesystem owner of detached workflow handle files."""

    def __init__(
        self,
        *,
        history_root: Path,
        pid_alive: Optional[PidAliveProbe] = None,
    ) -> None:
        """Bind the store to the shared history root.

        Args:
            history_root (Path): Root directory containing per-session folders.
            pid_alive (Optional[PidAliveProbe]): Optional liveness probe for tests.
        """
        self._history_root: Path = history_root.expanduser().resolve()
        self._pid_alive: PidAliveProbe = pid_alive or self._default_pid_alive
        self._lock: asyncio.Lock = asyncio.Lock()

    async def write(self, *, handle: WorkflowHandleDAO) -> Path:
        """Persist a workflow handle atomically.

        Args:
            handle (WorkflowHandleDAO): Handle to persist.

        Returns:
            Path: Final handle path.

        Raises:
            WorkflowStateTransitionError: When an existing handle's state
                differs — ``write`` may not bypass ``update_state``'s
                transition table.
        """
        async with self._lock:
            return await asyncio.to_thread(self._write_sync, handle=handle)

    async def read(self, *, owner_session_id: str, workflow_id: str) -> Optional[WorkflowHandleDAO]:
        """Read one workflow handle when it exists.

        Args:
            owner_session_id (str): Owning TUI session id.
            workflow_id (str): Workflow identifier.

        Returns:
            Optional[WorkflowHandleDAO]: Parsed handle, or ``None`` when absent.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._read_sync,
                owner_session_id=owner_session_id,
                workflow_id=workflow_id,
            )

    # ``List`` (not ``list``) in signatures below this point: the ``list``
    # method shadows the builtin in class scope.
    async def list(self, *, owner_session_id: str) -> List[WorkflowHandleDAO]:
        """List every parseable workflow handle for one owning session.

        Args:
            owner_session_id (str): Owning TUI session id.

        Returns:
            list[WorkflowHandleDAO]: Handles sorted by ``started_at`` ascending.
        """
        async with self._lock:
            return await asyncio.to_thread(self._list_sync, owner_session_id=owner_session_id)

    async def update_state(
        self,
        *,
        owner_session_id: str,
        workflow_id: str,
        state: WorkflowState,
    ) -> WorkflowHandleDAO:
        """Advance a workflow handle to ``state`` when the transition is legal.

        Args:
            owner_session_id (str): Owning TUI session id.
            workflow_id (str): Workflow identifier.
            state (WorkflowState): Requested new state.

        Returns:
            WorkflowHandleDAO: Updated handle.

        Raises:
            FileNotFoundError: When the handle is missing.
            WorkflowStateTransitionError: When the transition is illegal.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._update_state_sync,
                owner_session_id=owner_session_id,
                workflow_id=workflow_id,
                state=state,
            )

    async def reconcile(self, *, owner_session_id: str) -> List[WorkflowHandleDAO]:
        """Refresh liveness-backed workflow state for one owning session.

        Args:
            owner_session_id (str): Owning TUI session id.

        Returns:
            list[WorkflowHandleDAO]: Reconciled handles sorted by ``started_at``.
        """
        async with self._lock:
            return await asyncio.to_thread(self._reconcile_sync, owner_session_id=owner_session_id)

    def _write_sync(self, *, handle: WorkflowHandleDAO) -> Path:
        """Synchronously persist one handle.

        Args:
            handle (WorkflowHandleDAO): Handle to persist.

        Returns:
            Path: Final handle path.
        """
        path: Path = self._handle_path(
            owner_session_id=handle.owner_session_id,
            workflow_id=handle.workflow_id,
        )
        existing: Optional[WorkflowHandleDAO] = self._read_path(path=path)
        if existing is not None and existing.state != handle.state:
            raise WorkflowStateTransitionError(
                f"write() may not bypass state transitions for {handle.workflow_id}: "
                f"{existing.state} -> {handle.state}"
            )
        self._write_handle(path=path, handle=handle)
        return path

    def _read_sync(self, *, owner_session_id: str, workflow_id: str) -> Optional[WorkflowHandleDAO]:
        """Synchronously read one handle.

        Args:
            owner_session_id (str): Owning TUI session id.
            workflow_id (str): Workflow identifier.

        Returns:
            Optional[WorkflowHandleDAO]: Parsed handle, or ``None`` when the
                handle is absent or the id is not path-safe.
        """
        if not self._is_path_safe_workflow_id(workflow_id=workflow_id):
            return None
        return self._read_path(
            path=self._handle_path(owner_session_id=owner_session_id, workflow_id=workflow_id),
        )

    def _list_sync(self, *, owner_session_id: str) -> List[WorkflowHandleDAO]:
        """Synchronously list parseable handles for one session.

        Args:
            owner_session_id (str): Owning TUI session id.

        Returns:
            list[WorkflowHandleDAO]: Parsed handles sorted by ``started_at``.
        """
        workflows_dir: Path = self._workflows_dir(owner_session_id=owner_session_id)
        if not workflows_dir.exists():
            return []
        handles: list[WorkflowHandleDAO] = []
        for path in sorted(workflows_dir.glob("wf-*.json")):
            handle: Optional[WorkflowHandleDAO] = self._read_path(path=path)
            if handle is not None:
                handles.append(handle)
        handles.sort(key=lambda item: item.started_at)
        return handles

    def _update_state_sync(
        self,
        *,
        owner_session_id: str,
        workflow_id: str,
        state: WorkflowState,
    ) -> WorkflowHandleDAO:
        """Synchronously enforce and persist one state transition.

        Args:
            owner_session_id (str): Owning TUI session id.
            workflow_id (str): Workflow identifier.
            state (WorkflowState): Requested new state.

        Returns:
            WorkflowHandleDAO: Updated handle.
        """
        if not self._is_path_safe_workflow_id(workflow_id=workflow_id):
            raise FileNotFoundError(workflow_id)
        path: Path = self._handle_path(owner_session_id=owner_session_id, workflow_id=workflow_id)
        existing: Optional[WorkflowHandleDAO] = self._read_path(path=path)
        if existing is None:
            raise FileNotFoundError(path)
        if existing.state == state:
            return existing
        if state not in _LEGAL_TRANSITIONS.get(existing.state, frozenset()):
            raise WorkflowStateTransitionError(
                f"illegal workflow transition for {workflow_id}: {existing.state} -> {state}"
            )
        updated: WorkflowHandleDAO = existing.model_copy(update={"state": state})
        self._write_handle(path=path, handle=updated)
        return updated

    def _reconcile_sync(self, *, owner_session_id: str) -> List[WorkflowHandleDAO]:
        """Synchronously flip dead-pid live workflows to their reconciled state.

        A dead ``running`` workflow becomes ``stalled`` (it made progress but
        its process vanished); a dead ``launching`` workflow becomes ``failed``
        (the spawn never produced a live process — the crash-safe path for a
        handle written before a spawn that never happened). A pid-0
        ``launching`` handle younger than ``_LAUNCH_GRACE_SECONDS`` is left
        untouched: its spawn is still in flight and the pid patch has not
        landed yet.

        Args:
            owner_session_id (str): Owning TUI session id.

        Returns:
            list[WorkflowHandleDAO]: Reconciled handles sorted by ``started_at``.
        """
        handles: list[WorkflowHandleDAO] = self._list_sync(owner_session_id=owner_session_id)
        reconciled: list[WorkflowHandleDAO] = []
        for handle in handles:
            if handle.state not in {"launching", "running"}:
                reconciled.append(handle)
                continue
            if handle.pid > 0 and self._pid_alive(handle.pid):
                reconciled.append(handle)
                continue
            if self._is_within_launch_grace(handle=handle):
                reconciled.append(handle)
                continue
            dead_state: WorkflowState = "stalled" if handle.state == "running" else "failed"
            updated: WorkflowHandleDAO = self._update_state_sync(
                owner_session_id=owner_session_id,
                workflow_id=handle.workflow_id,
                state=dead_state,
            )
            reconciled.append(updated)
        reconciled.sort(key=lambda item: item.started_at)
        return reconciled

    @staticmethod
    def _is_within_launch_grace(*, handle: WorkflowHandleDAO) -> bool:
        """Return whether a handle is a pid-0 launch whose spawn is still in flight.

        Args:
            handle (WorkflowHandleDAO): Handle under reconcile.

        Returns:
            bool: ``True`` for a ``launching`` handle without a patched pid
                that is younger than ``_LAUNCH_GRACE_SECONDS``.
        """
        if handle.state != "launching" or handle.pid > 0:
            return False
        age_seconds: float = (datetime.now(timezone.utc) - handle.started_at).total_seconds()
        return age_seconds < _LAUNCH_GRACE_SECONDS

    @staticmethod
    def _is_path_safe_workflow_id(*, workflow_id: str) -> bool:
        """Return whether a workflow id is safe to use as a file name.

        Ids arrive from inbox payloads and user-typed ``/workflows`` arguments;
        anything carrying path-meta sequences must never reach a filesystem
        join. An unsafe id behaves exactly like an unknown workflow.

        Args:
            workflow_id (str): Candidate workflow id.

        Returns:
            bool: ``True`` when the id is non-empty and free of path metas.
        """
        if not workflow_id:
            return False
        return not any(marker in workflow_id for marker in _UNSAFE_WORKFLOW_ID_MARKERS)

    def _workflows_dir(self, *, owner_session_id: str) -> Path:
        """Return the per-session workflows directory.

        Args:
            owner_session_id (str): Owning TUI session id.

        Returns:
            Path: ``<history_root>/<owner_session_id>/workflows``.
        """
        return self._history_root / owner_session_id / "workflows"

    def _handle_path(self, *, owner_session_id: str, workflow_id: str) -> Path:
        """Return the on-disk path for one workflow handle.

        Args:
            owner_session_id (str): Owning TUI session id.
            workflow_id (str): Workflow identifier.

        Returns:
            Path: Absolute handle path.
        """
        return self._workflows_dir(owner_session_id=owner_session_id) / f"{workflow_id}.json"

    @classmethod
    def _ensure_dir(cls, *, path: Path) -> None:
        """Create or chmod a private directory.

        Args:
            path (Path): Directory to create or normalize.
        """
        if not path.exists():
            path.mkdir(parents=True, mode=_DIR_MODE)
            return
        path.chmod(_DIR_MODE)

    @classmethod
    def _read_path(cls, *, path: Path) -> Optional[WorkflowHandleDAO]:
        """Parse one workflow handle file when it is valid.

        Args:
            path (Path): Handle path.

        Returns:
            Optional[WorkflowHandleDAO]: Parsed handle or ``None`` on absence/corruption.
        """
        if not path.exists() or path.suffix != ".json" or path.name.endswith(".tmp"):
            return None
        try:
            return WorkflowHandleDAO.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log_info(msg="workflow_handle_skipped", path=str(path))
            return None

    @classmethod
    def _write_handle(cls, *, path: Path, handle: WorkflowHandleDAO) -> None:
        """Atomically persist one handle file.

        Args:
            path (Path): Final handle path.
            handle (WorkflowHandleDAO): Handle to serialize.
        """
        cls._ensure_dir(path=path.parent)
        tmp_path: Path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(handle.model_dump_json(indent=2), encoding="utf-8")
        tmp_path.chmod(_FILE_MODE)
        os.replace(tmp_path, path)
        path.chmod(_FILE_MODE)

    @staticmethod
    def _default_pid_alive(pid: int) -> bool:
        """Return whether ``pid`` is a currently live process.

        Args:
            pid (int): Process id to probe.

        Returns:
            bool: True when ``os.kill(pid, 0)`` succeeds.
        """
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True


class WorkflowStatusTool:
    """Factory for the read-only ``workflow_status`` tool."""

    @classmethod
    def build(cls, *, owner_session_id: str, store: WorkflowHandleStore) -> BaseTool:
        """Build a ``workflow_status`` tool bound to one owner session.

        Args:
            owner_session_id (str): Owning TUI session id.
            store (WorkflowHandleStore): Shared workflow handle store.

        Returns:
            BaseTool: Bound tool instance.
        """
        _owner_session_id: str = owner_session_id
        _store: WorkflowHandleStore = store

        @tool(args_schema=WorkflowStatusSchemaDAO)
        async def workflow_status(workflow_id: Optional[str] = None) -> str:
            """Report the live state of detached workflows launched from this session.

            Reads durable handle files from disk (no IPC) after a pid-liveness
            reconcile pass. With ``workflow_id``, returns that handle's JSON;
            without it, returns a JSON array of all handles. Unknown ids return
            an error JSON string, never raise.

            Args:
                workflow_id (Optional[str]): Specific workflow id to inspect.

            Returns:
                str: Handle JSON for one workflow, or a JSON array of all handles.
            """
            reconciled: list[WorkflowHandleDAO] = await _store.reconcile(
                owner_session_id=_owner_session_id,
            )
            if workflow_id is None:
                return json.dumps([handle.model_dump(mode="json") for handle in reconciled])
            match: Optional[WorkflowHandleDAO] = next(
                (handle for handle in reconciled if handle.workflow_id == workflow_id),
                None,
            )
            if match is None:
                return json.dumps({"error": f"unknown workflow_id: {workflow_id}"})
            return match.model_dump_json()

        return workflow_status


class WorkflowCommandService:
    """Slash-command façade for detached workflow supervision (spec 57.a.6).

    Owns list/abort/dismiss so ``SlashRouter`` stays a thin dispatcher and the
    logic is testable without Textual. One instance per dispatch call — the
    service is stateless beyond its store binding. Every public method returns
    transcript text and never raises to the router.
    """

    _STATE_HINTS: dict[str, str] = {
        "running": "(abort: /workflows abort {workflow_id})",
        "launching": "(abort: /workflows abort {workflow_id})",
        "stalled": "(dismiss: /workflows dismiss {workflow_id})",
    }
    """Per-state actionable hint templates for list rows."""

    def __init__(
        self,
        *,
        store: WorkflowHandleStore,
        owner_session_id: str,
        kill: Optional[KillCallable] = None,
        pid_alive: Optional[PidAliveProbe] = None,
        schedule: Optional[EscalationScheduler] = None,
    ) -> None:
        """Bind the service to a session's handles.

        Args:
            store (WorkflowHandleStore): Handle store for the owning session.
            owner_session_id (str): The TUI session whose workflows are managed.
            kill (Optional[KillCallable]): Injectable signal sender for tests.
                ``None`` uses ``os.killpg``.
            pid_alive (Optional[PidAliveProbe]): Injectable liveness probe for
                the SIGKILL escalation check. ``None`` uses ``os.kill(pid, 0)``.
            schedule (Optional[EscalationScheduler]): Injectable delayed-call
                scheduler for tests. ``None`` uses the running event loop's
                ``call_later``.
        """
        self._store: WorkflowHandleStore = store
        self._owner_session_id: str = owner_session_id
        self._kill: KillCallable = kill or os.killpg
        self._pid_alive: PidAliveProbe = pid_alive or WorkflowHandleStore._default_pid_alive
        self._schedule: EscalationScheduler = schedule or self._default_schedule

    async def list_text(self) -> str:
        """Return the reconciled one-row-per-workflow listing.

        Runs a pid-liveness reconcile pass first so the output is always
        truthful — a dead orchestrator shows as ``stalled``, never as a stale
        ``running`` row.

        Returns:
            str: One row per workflow, or a no-workflows line.
        """
        handles: List[WorkflowHandleDAO] = await self._store.reconcile(
            owner_session_id=self._owner_session_id,
        )
        if not handles:
            return "no detached workflows for this session"
        return "\n".join(self._format_row(handle=handle) for handle in handles)

    async def abort(self, *, workflow_id: str) -> str:
        """SIGTERM the workflow's process group and mark it aborted.

        Invoked by ``/workflows abort <id>``. Escalates to SIGKILL after
        ``_ABORT_ESCALATION_SECONDS`` when the pid survives. A pid that is
        already dead (``ProcessLookupError``) still marks ``aborted`` — the
        operator's intent is honoured either way. A handle whose pid was never
        patched (``pid=0``, spawn still in flight or never happened) is marked
        ``aborted`` with **no signal sent**: signalling pid 0 would target the
        caller's own process group.

        Known gap: the escalation timer rides this process's event loop, so
        quitting the TUI inside the grace window skips the SIGKILL for a
        process group that survived SIGTERM. The handle already reads
        ``aborted``; a surviving group remains visible via ``ps`` only.

        Args:
            workflow_id (str): Workflow to abort.

        Returns:
            str: One-line confirmation or error text for the transcript.
        """
        handle: Optional[WorkflowHandleDAO] = await self._store.read(
            owner_session_id=self._owner_session_id,
            workflow_id=workflow_id,
        )
        if handle is None:
            return f"no workflow {workflow_id}"
        if handle.state not in ("launching", "running"):
            return f"no live workflow {workflow_id} (state {handle.state})"
        if handle.pid > 0:
            self._signal_process_group(pid=handle.pid, signal_number=signal.SIGTERM)
            self._schedule(
                _ABORT_ESCALATION_SECONDS,
                lambda: self._escalate(pid=handle.pid),
            )
        return await self._mark_aborted(handle=handle)

    async def dismiss(self, *, workflow_id: str) -> str:
        """Acknowledge a stalled workflow (``stalled → failed``).

        Invoked by ``/workflows dismiss <id>`` so a crashed orchestrator's row
        stops appearing as actionable.

        Args:
            workflow_id (str): Workflow to dismiss.

        Returns:
            str: One-line confirmation or error text for the transcript.
        """
        handle: Optional[WorkflowHandleDAO] = await self._store.read(
            owner_session_id=self._owner_session_id,
            workflow_id=workflow_id,
        )
        if handle is None:
            return f"no workflow {workflow_id}"
        if handle.state != "stalled":
            return f"workflow {workflow_id} is {handle.state} — only stalled workflows can be dismissed"
        try:
            await self._store.update_state(
                owner_session_id=self._owner_session_id,
                workflow_id=workflow_id,
                state="failed",
            )
        except (FileNotFoundError, WorkflowStateTransitionError) as exc:
            return f"could not dismiss workflow {workflow_id}: {exc}"
        return f"workflow {workflow_id} dismissed (stalled → failed)"

    def _format_row(self, *, handle: WorkflowHandleDAO) -> str:
        """Render one listing row for a workflow handle.

        Args:
            handle (WorkflowHandleDAO): Handle to render.

        Returns:
            str: ``<id>  <state>  orch <sid[:8]>  started <HH:MM>  <hint>``.
        """
        started: str = handle.started_at.strftime("%H:%M")
        hint_template: str = self._STATE_HINTS.get(handle.state, "")
        hint: str = hint_template.format(workflow_id=handle.workflow_id)
        row: str = (
            f"{handle.workflow_id}  {handle.state}  "
            f"orch {handle.orchestrator_session_id[:8]}  started {started}"
        )
        if hint:
            row += f"  {hint}"
        return row

    async def _mark_aborted(self, *, handle: WorkflowHandleDAO) -> str:
        """Persist the ``aborted`` state and build the confirmation line.

        Both live states transition directly (``launching → aborted`` and
        ``running → aborted`` are legal table edges) — one write, no transient
        intermediate state on disk.

        Args:
            handle (WorkflowHandleDAO): Live handle being aborted.

        Returns:
            str: Confirmation or error text.
        """
        try:
            await self._store.update_state(
                owner_session_id=self._owner_session_id,
                workflow_id=handle.workflow_id,
                state="aborted",
            )
        except (FileNotFoundError, WorkflowStateTransitionError) as exc:
            return f"could not mark workflow {handle.workflow_id} aborted: {exc}"
        if handle.pid > 0:
            return (
                f"workflow {handle.workflow_id} aborted "
                f"(SIGTERM sent to process group {handle.pid})"
            )
        return f"workflow {handle.workflow_id} aborted (no live process to signal)"

    def _signal_process_group(self, *, pid: int, signal_number: int) -> None:
        """Send one signal to the workflow's process group, tolerating dead pids.

        Non-positive pids are refused outright: ``os.killpg(0, sig)`` signals
        the **calling process's own group** — i.e. the TUI and everything in
        its terminal — and negative values target arbitrary groups.

        Args:
            pid (int): Process-group leader pid from the handle.
            signal_number (int): Signal to deliver.
        """
        if pid <= 0:
            log_info(msg="workflow_signal_skipped", pid=pid, error="non-positive pid")
            return
        try:
            self._kill(pid, signal_number)
        except (ProcessLookupError, PermissionError) as exc:
            log_info(msg="workflow_signal_skipped", pid=pid, error=str(exc))

    def _escalate(self, *, pid: int) -> None:
        """SIGKILL the process group when it survived the SIGTERM grace.

        Fired by the escalation timer armed in ``abort``. A no-op when the
        process group already exited. Non-positive pids never escalate —
        ``os.kill(0, 0)`` probes the caller's own group and would report
        "alive" for a process that does not exist.

        Args:
            pid (int): Process-group leader pid captured at abort time.
        """
        if pid <= 0:
            return
        if not self._pid_alive(pid):
            return
        self._signal_process_group(pid=pid, signal_number=signal.SIGKILL)

    @staticmethod
    def _default_schedule(delay_seconds: float, callback: Callable[[], None]) -> None:
        """Arm one delayed callback on the running event loop.

        Args:
            delay_seconds (float): Delay before the callback fires.
            callback (Callable[[], None]): Zero-argument callback.
        """
        asyncio.get_running_loop().call_later(delay_seconds, callback)
