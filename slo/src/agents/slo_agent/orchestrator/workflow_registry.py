"""Workflow handle registry — durable records for detached workflows (spec 57.a.1)."""

from __future__ import annotations

import asyncio
import fcntl
import inspect
import itertools
import json
import os
import signal
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterator, List, Literal, Optional, Protocol, TextIO, TypeAlias

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from config.logger import log_info
from config.timeout_resolver import positive_float_env
from src.agents.slo_agent.history.atomic_io import AtomicFileWriter
from src.agents.slo_agent.orchestrator.dao import (
    FleetSnapshotDAO,
    OrchestratorStatusDAO,
    SubAgentStatusDAO,
    build_cleanup_summary,
    safe_identifier,
)
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout
from src.agents.slo_agent.orchestrator.process_probe import ProcessProbe
from src.agents.slo_agent.orchestrator.reaper import (
    FleetReaper,
    IdentityVerificationOutcome,
    ReapOutcome,
)
from src.agents.slo_agent.orchestrator.status_store import OrchestratorStatusStore

if TYPE_CHECKING:
    from src.agents.slo_agent.orchestrator.relaunch import RelaunchOutcomeDAO

__all__ = [
    "WorkflowCommandResultDAO",
    "WorkflowCommandService",
    "WorkflowHandleDAO",
    "WorkflowHandleStore",
    "WorkflowState",
    "WorkflowStateTransitionError",
    "WorkflowStatusSchemaDAO",
    "WorkflowStatusTool",
]

WorkflowState: TypeAlias = Literal["launching", "running", "completed", "failed", "aborted", "stalled"]
PidAliveProbe = Callable[[int], bool]


class ProcessGroupKiller(Protocol):
    """Kill one process group for a durable workflow abort request."""

    def __call__(self, *, pid: int, signal_number: int) -> None:
        """Deliver one signal to the process group identified by pid."""


class EscalationScheduler(Protocol):
    """Schedule one workflow process-group escalation callback."""

    def __call__(self, *, delay_seconds: float, callback: Callable[[], None]) -> None:
        """Schedule callback after delay_seconds."""


def _default_kill_process_group(*, pid: int, signal_number: int) -> None:
    """Kill the process group identified by pid for WorkflowCommandService."""
    os.killpg(pid, signal_number)


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

_RELAUNCH_TRANSITIONS: dict[str, frozenset[str]] = {
    "stalled": frozenset({"launching"}),
    "failed": frozenset({"launching"}),
}
"""Relaunch-only edges that resume a terminal workflow with a fresh pid."""

_EVIDENCE_TRANSITIONS: dict[str, frozenset[str]] = {
    "launching": frozenset({"completed", "failed"}),
    "running": frozenset({"completed", "failed", "aborted"}),
    "stalled": frozenset({"completed", "failed", "running"}),
    "failed": frozenset({"running"}),
}
"""Correction edges reachable only through verified self-reported evidence."""

_STATUS_STALE_MULTIPLIER: int = 3
"""Heartbeat intervals tolerated before a running self-report becomes stale."""

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

_UNSAFE_WORKFLOW_ID_MARKERS: tuple[str, ...] = ("/", "\\", "..", "\x00")
"""Path-meta sequences rejected in workflow ids before any filesystem join.

Workflow ids reach the store from inbox payloads and user-typed
``/workflows abort <id>`` arguments; they are used as file names and must
never be able to escape the per-session ``workflows/`` directory."""

OBSERVATION_MAX_HANDLES: int = 256
"""Largest owned workflow group set one observation admits (feature 94 a.2)."""

OBSERVATION_MAX_HANDLE_BYTES: int = 65_536
"""Per-handle byte budget enforced before decode during observation."""

OBSERVATION_MAX_DIRECTORY_ENTRIES: int = 4 * (OBSERVATION_MAX_HANDLES + 1)
"""Directory-entry scan budget: each handle may sit beside its lock and transient temp file."""

OBSERVATION_UNAVAILABLE_MESSAGE: str = "workflow observation unavailable"
"""Fixed error for every refused observation; never partial membership or raw adapter text."""

_CAPTURE_WRITER_FAILURE_CODE: Literal["capture_writer_failed"] = "capture_writer_failed"
_CAPTURE_WRITER_FAILURE_MESSAGE: str = "Capture writer failed; workflow output may be incomplete."


class WorkflowStateTransitionError(RuntimeError):
    """Raised when a workflow state transition is illegal."""


class WorkflowCaptureHealthDAO(BaseModel):
    """Fixed-safe capture-health projection stored with one workflow handle."""

    model_config = ConfigDict(frozen=True)

    status: Literal["degraded"] = Field(description="Capture health classification.")
    failure_code: Literal["capture_writer_failed"] = Field(description="Allowlisted capture failure code.")
    safe_message: str = Field(description="Fixed operator-facing capture failure message.")


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
    capture_health: Optional[WorkflowCaptureHealthDAO] = Field(
        default=None,
        description="Fixed-safe capture health for the active orchestrator run.",
    )


class WorkflowStatusSchemaDAO(BaseModel):
    """Validated input schema for the ``workflow_status`` tool."""

    workflow_id: Optional[str] = Field(
        default=None,
        description="Workflow id to inspect. Omit to list all session workflows.",
    )


class WorkflowCommandResultDAO(BaseModel):
    """Typed outcome of one ``/workflows dismiss`` or ``resume`` command (feature 94 a.2).

    The transcript text stays the operator contract; the optional ids are the
    only signal observers use, so no caller parses success text.

    Attributes:
        rendered (str): One-line transcript confirmation or refusal.
        dismissed_workflow_id (Optional[str]): Set only after a durable
            ``stalled → failed`` dismissal succeeded.
        resumed_workflow_id (Optional[str]): Set only after a relaunch was
            durably adopted and confirmed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rendered: str
    dismissed_workflow_id: Optional[str] = None
    resumed_workflow_id: Optional[str] = None

    @model_validator(mode="after")
    def _reject_conflicting_signals(self) -> "WorkflowCommandResultDAO":
        """Refuse a result that claims both dismissal and resume.

        Returns:
            WorkflowCommandResultDAO: Self after validation.

        Raises:
            ValueError: When both workflow ids are set.
        """
        if self.dismissed_workflow_id is not None and self.resumed_workflow_id is not None:
            raise ValueError("a command result signals dismissal or resume, not both")
        return self


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

    async def list_observation(self, *, owner_session_id: str) -> tuple[WorkflowHandleDAO, ...]:
        """Return every owned handle for one bounded, read-only observation poll.

        WHAT: Scans the owner's workflows directory within fixed budgets (at most
            256 handle names, 64 KiB per handle before decode, symlinks refused)
            and returns the complete owned set. Unlike ``list`` it never skips an
            entry: any malformed, oversized, misnamed, foreign or excess handle
            refuses the whole observation, so callers never mistake an unreadable
            file for a removed workflow. It never reconciles, locks files or writes.
        WHO: Called by DetachedWorkflowAppService session snapshot assembly.
        WHEN: On every workflow observation refresh of the owning TUI session.

        Args:
            owner_session_id (str): Owning TUI session id.

        Returns:
            tuple[WorkflowHandleDAO, ...]: Owned handles sorted by ``started_at``
                then ``workflow_id``; empty when the directory does not exist.

        Raises:
            ValueError: ``OBSERVATION_UNAVAILABLE_MESSAGE`` for an unsafe owner,
                escaped directory, exceeded budget or untrusted handle.
            OSError: When the directory or a handle cannot be read.
        """
        async with self._lock:
            return await asyncio.to_thread(self._list_observation_sync, owner_session_id=owner_session_id)

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

    async def record_capture_failure(
        self,
        *,
        owner_session_id: str,
        workflow_id: str,
        expected_pid: int,
    ) -> WorkflowHandleDAO:
        """Record fixed-safe capture degradation for the current workload identity.

        WHAT: Persists only the allowlisted capture-writer failure projection
            without changing workflow state, pid, or stable run identity.
        WHO: A future detached capture owner calls this after observing its
            fixed writer failure signal.
        WHEN: Once a capture failure is known for a specific workload run.

        Args:
            owner_session_id (str): TUI session that owns the workflow handle.
            workflow_id (str): Workflow identifier.
            expected_pid (int): Workload pid that observed the failure.

        Returns:
            WorkflowHandleDAO: The unchanged workload handle with degradation.

        Raises:
            FileNotFoundError: If the handle is missing or unsafe.
            WorkflowStateTransitionError: If the supplied pid belongs to a stale run.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self.record_capture_failure_sync,
                owner_session_id=owner_session_id,
                workflow_id=workflow_id,
                expected_pid=expected_pid,
            )

    async def reserve_relaunch(
        self,
        *,
        owner_session_id: str,
        workflow_id: str,
    ) -> WorkflowHandleDAO:
        """Reserve one dead workflow for relaunch before workload spawning.

        WHAT: Moves a resumable handle to ``launching`` with its existing pid
            while holding its durable flock, making admission visible to every
            command-service instance before the workload can execute.
        WHO: ``WorkflowCommandService.resume`` calls this before
            ``WorkflowRelauncher.invoke``.
        WHEN: Once at the beginning of an operator-requested resume attempt.

        Args:
            owner_session_id (str): TUI session that owns the workflow handle.
            workflow_id (str): Workflow handle identifier.

        Returns:
            WorkflowHandleDAO: Reserved launching handle with its prior pid.

        Raises:
            FileNotFoundError: If the handle is missing or its id is unsafe.
            WorkflowStateTransitionError: If the handle cannot be relaunched.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._reserve_relaunch_sync,
                owner_session_id=owner_session_id,
                workflow_id=workflow_id,
            )

    async def relaunch(
        self,
        *,
        owner_session_id: str,
        workflow_id: str,
        new_pid: int,
    ) -> WorkflowHandleDAO:
        """Patch a reserved relaunch handle with its fresh workload pid.

        WHAT: Atomically patches the actual spawned workload pid while the
            handle remains in its durable ``launching`` reservation state.
        WHO: ``WorkflowCommandService.resume`` calls this after a successful
            ``WorkflowRelauncher`` invocation.
        WHEN: Once a reserved resume workload has spawned successfully.

        Args:
            owner_session_id (str): TUI session that owns the workflow handle.
            workflow_id (str): Workflow handle identifier.
            new_pid (int): Positive pid of the newly spawned orchestrator.

        Returns:
            WorkflowHandleDAO: Relaunched handle in the launching state.

        Raises:
            FileNotFoundError: If the handle is missing or its id is unsafe.
            WorkflowStateTransitionError: If the handle was not reserved.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._relaunch_sync,
                owner_session_id=owner_session_id,
                workflow_id=workflow_id,
                new_pid=new_pid,
            )

    async def rollback_relaunch(
        self,
        *,
        owner_session_id: str,
        workflow_id: str,
        state: WorkflowState,
    ) -> WorkflowHandleDAO:
        """Restore a failed relaunch reservation to its prior recoverable state.

        WHAT: Changes an unpatched launching reservation back to its original
            stalled or failed state under the durable handle flock.
        WHO: ``WorkflowCommandService.resume`` calls this when spawning fails.
        WHEN: Immediately after a reserved workload fails to return a pid.

        Args:
            owner_session_id (str): TUI session that owns the workflow handle.
            workflow_id (str): Workflow handle identifier.
            state (WorkflowState): Original resumable state to restore.

        Returns:
            WorkflowHandleDAO: Recovered resumable workflow handle.

        Raises:
            FileNotFoundError: If the handle is missing or its id is unsafe.
            WorkflowStateTransitionError: If the reservation cannot be rolled back.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._rollback_relaunch_sync,
                owner_session_id=owner_session_id,
                workflow_id=workflow_id,
                state=state,
            )

    async def correct_from_evidence(
        self,
        *,
        owner_session_id: str,
        workflow_id: str,
        state: WorkflowState,
        evidence: OrchestratorStatusDAO,
    ) -> WorkflowHandleDAO:
        """Correct a handle state with matching durable self-reported evidence.

        WHAT: Persists correction-only state transitions after verifying the
            supplied evidence names the requested terminal target.
        WHO: Called by the reconcile ladder and future workflow resume flow.
        WHEN: When a self-reported status corrects a stale handle projection.

        Args:
            owner_session_id (str): TUI session that owns the handle.
            workflow_id (str): Workflow handle identifier.
            state (WorkflowState): Evidence-backed target state.
            evidence (OrchestratorStatusDAO): Verified orchestrator self-report.

        Returns:
            WorkflowHandleDAO: Corrected durable handle.

        Raises:
            FileNotFoundError: If the handle is missing or its id is unsafe.
            WorkflowStateTransitionError: If evidence does not permit the correction.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._correct_from_evidence_sync,
                owner_session_id=owner_session_id,
                workflow_id=workflow_id,
                state=state,
                evidence=evidence,
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
        with self._locked_handle(path=path) as lock_file:
            existing: Optional[WorkflowHandleDAO] = self._read_path(path=path)
            if existing is not None and existing.state != handle.state:
                raise WorkflowStateTransitionError(
                    f"write() may not bypass state transitions for {handle.workflow_id}: "
                    f"{existing.state} -> {handle.state}"
                )
            self._write_handle_locked(path=path, handle=handle, lock_file=lock_file)
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

    def _list_observation_sync(self, *, owner_session_id: str) -> tuple[WorkflowHandleDAO, ...]:
        """Synchronously read the complete bounded owned handle set.

        Args:
            owner_session_id (str): Owning TUI session id.

        Returns:
            tuple[WorkflowHandleDAO, ...]: Sorted owned handles.
        """
        directory: Path = self._observation_dir(owner_session_id=owner_session_id)
        handles: tuple[WorkflowHandleDAO, ...] = tuple(
            self._read_observation_handle(entry=entry, owner_session_id=owner_session_id)
            for entry in self._observation_handle_entries(directory=directory)
        )
        return tuple(sorted(handles, key=lambda handle: (handle.started_at, handle.workflow_id)))

    def _observation_dir(self, *, owner_session_id: str) -> Path:
        """Return the owner's workflows directory after identity and containment checks.

        Args:
            owner_session_id (str): Candidate owner id from the TUI session.

        Returns:
            Path: Contained workflows directory, which may not exist.

        Raises:
            ValueError: When the owner is unsafe or a path component is a symlink.
        """
        try:
            safe_identifier(value=owner_session_id)
        except ValueError:
            raise ValueError(OBSERVATION_UNAVAILABLE_MESSAGE) from None
        directory: Path = self._workflows_dir(owner_session_id=owner_session_id)
        if Path(os.path.realpath(directory)) != directory:
            raise ValueError(OBSERVATION_UNAVAILABLE_MESSAGE)
        return directory

    @staticmethod
    def _observation_handle_entries(*, directory: Path) -> tuple[os.DirEntry[str], ...]:
        """Scan bounded directory entries and keep the handle-named ones.

        Args:
            directory (Path): Contained owner workflows directory.

        Returns:
            tuple[os.DirEntry[str], ...]: At most 256 ``wf-*.json`` entries; empty
                when the directory is absent.

        Raises:
            ValueError: When the entry or handle budget is exceeded.
        """
        try:
            scanner = os.scandir(directory)
        except FileNotFoundError:
            return ()
        with scanner:
            entries: list[os.DirEntry[str]] = list(
                itertools.islice(scanner, OBSERVATION_MAX_DIRECTORY_ENTRIES + 1)
            )
        handle_entries: tuple[os.DirEntry[str], ...] = tuple(
            entry for entry in entries if entry.name.startswith("wf-") and entry.name.endswith(".json")
        )
        if len(entries) > OBSERVATION_MAX_DIRECTORY_ENTRIES or len(handle_entries) > OBSERVATION_MAX_HANDLES:
            raise ValueError(OBSERVATION_UNAVAILABLE_MESSAGE)
        return handle_entries

    @classmethod
    def _read_observation_handle(cls, *, entry: os.DirEntry[str], owner_session_id: str) -> WorkflowHandleDAO:
        """Decode one regular handle file within its byte budget and verify ownership.

        Args:
            entry (os.DirEntry[str]): Scanned handle entry.
            owner_session_id (str): Owner the handle must name.

        Returns:
            WorkflowHandleDAO: Trusted owned handle.

        Raises:
            ValueError: Symlinked, non-regular, oversized, malformed, foreign or
                misnamed handle.
        """
        if not entry.is_file(follow_symlinks=False):
            raise ValueError(OBSERVATION_UNAVAILABLE_MESSAGE)
        try:
            handle: WorkflowHandleDAO = WorkflowHandleDAO.model_validate_json(
                cls._read_bounded(path=entry.path)
            )
        except ValueError:
            raise ValueError(OBSERVATION_UNAVAILABLE_MESSAGE) from None
        if handle.owner_session_id != owner_session_id or entry.name != f"{handle.workflow_id}.json":
            raise ValueError(OBSERVATION_UNAVAILABLE_MESSAGE)
        return handle

    @staticmethod
    def _read_bounded(*, path: str) -> bytes:
        """Read one regular file without following links, stopping past the budget.

        Args:
            path (str): Handle path from the bounded scan.

        Returns:
            bytes: At most 64 KiB of handle bytes.

        Raises:
            ValueError: When the file is not regular or exceeds the budget.
            OSError: When the file cannot be opened or read.
        """
        descriptor: int = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle_file:
            if not stat.S_ISREG(os.fstat(handle_file.fileno()).st_mode):
                raise ValueError(OBSERVATION_UNAVAILABLE_MESSAGE)
            data: bytes = handle_file.read(OBSERVATION_MAX_HANDLE_BYTES + 1)
        if len(data) > OBSERVATION_MAX_HANDLE_BYTES:
            raise ValueError(OBSERVATION_UNAVAILABLE_MESSAGE)
        return data

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
        with self._locked_handle(path=path) as lock_file:
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
            self._write_handle_locked(path=path, handle=updated, lock_file=lock_file)
            return updated

    def _reject_relaunch_status(self, *, status: OrchestratorStatusDAO) -> None:
        """Reject durable evidence that makes a relaunch unsafe.

        WHAT: Refuses a replacement when same-identity status evidence proves
            the prior orchestrator is running, completed, or aborted.
        WHO: _reject_live_relaunch_locked calls this under the handle flock.
        WHEN: Immediately before a dead handle receives a replacement pid.

        Args:
            status (OrchestratorStatusDAO): Same-identity orchestrator evidence.

        Raises:
            WorkflowStateTransitionError: If the evidence proves relaunch is unsafe.
        """
        if status.state in {"completed", "aborted"}:
            raise WorkflowStateTransitionError(f"workflow {status.workflow_id} is {status.state}")
        if status.state == "running" and self._status_is_fresh(status=status):
            raise WorkflowStateTransitionError(f"workflow {status.workflow_id} has fresh running evidence")

    def _reject_live_relaunch_locked(self, *, handle: WorkflowHandleDAO) -> None:
        """Reject a relaunch when locked durable evidence proves the workflow lives.

        WHAT: Checks same-identity status evidence and legacy PID liveness at
            the atomic relaunch boundary.
        WHO: _relaunch_sync calls this while holding the handle flock.
        WHEN: Before it writes a new launching pid for /workflows resume.

        Args:
            handle (WorkflowHandleDAO): Current handle loaded under its flock.

        Raises:
            WorkflowStateTransitionError: If current evidence proves the workflow is live.
        """
        status: Optional[OrchestratorStatusDAO] = OrchestratorStatusStore.load_status(
            path=OrchestrationLayout.orchestrator_status_path(
                history_root=self._history_root,
                orchestrator_session_id=handle.orchestrator_session_id,
            )
        )
        if status is not None and self._status_matches_handle(handle=handle, status=status):
            self._reject_relaunch_status(status=status)
        if handle.state == "launching":
            return
        if handle.pid > 0 and self._pid_alive(handle.pid):
            raise WorkflowStateTransitionError(f"workflow {handle.workflow_id} still has a live pid")

    def record_capture_failure_sync(
        self,
        *,
        owner_session_id: str,
        workflow_id: str,
        expected_pid: int,
    ) -> WorkflowHandleDAO:
        """Persist capture degradation while validating the current workload pid.

        The independent capture reporter uses this synchronous owner boundary
        after its launcher has gone. The async API delegates here too; the
        existing cross-process flock and atomic writer serialize both paths.

        Args:
            owner_session_id (str): TUI session that owns the workflow handle.
            workflow_id (str): Workflow identifier.
            expected_pid (int): Workload pid whose capture failed.

        Returns:
            WorkflowHandleDAO: Updated handle preserving the workload identity.

        Raises:
            FileNotFoundError: If the handle is missing or unsafe.
            WorkflowStateTransitionError: If a newer workload owns the handle.
        """
        if not self._is_path_safe_workflow_id(workflow_id=workflow_id):
            raise FileNotFoundError(workflow_id)
        path: Path = self._handle_path(owner_session_id=owner_session_id, workflow_id=workflow_id)
        with self._locked_handle(path=path) as lock_file:
            existing: Optional[WorkflowHandleDAO] = self._read_path(path=path)
            if existing is None:
                raise FileNotFoundError(path)
            if existing.pid != expected_pid:
                raise WorkflowStateTransitionError(f"workflow {workflow_id} has a newer workload identity")
            health = WorkflowCaptureHealthDAO(
                status="degraded",
                failure_code=_CAPTURE_WRITER_FAILURE_CODE,
                safe_message=_CAPTURE_WRITER_FAILURE_MESSAGE,
            )
            updated: WorkflowHandleDAO = existing.model_copy(update={"capture_health": health})
            self._write_handle_locked(path=path, handle=updated, lock_file=lock_file)
            return updated

    def _reserve_relaunch_sync(
        self,
        *,
        owner_session_id: str,
        workflow_id: str,
    ) -> WorkflowHandleDAO:
        """Persist one relaunch reservation while the handle flock is held.

        WHAT: Checks durable evidence and moves one terminal resumable handle
            to launching before workload spawn admission.
        WHO: ``reserve_relaunch`` reaches this sync filesystem boundary.
        WHEN: Immediately before ``WorkflowRelauncher`` is permitted to spawn.

        Args:
            owner_session_id (str): TUI session that owns the workflow handle.
            workflow_id (str): Workflow handle identifier.

        Returns:
            WorkflowHandleDAO: The reserved launching handle.
        """
        if not self._is_path_safe_workflow_id(workflow_id=workflow_id):
            raise FileNotFoundError(workflow_id)
        path: Path = self._handle_path(owner_session_id=owner_session_id, workflow_id=workflow_id)
        with self._locked_handle(path=path) as lock_file:
            existing: Optional[WorkflowHandleDAO] = self._read_path(path=path)
            if existing is None:
                raise FileNotFoundError(path)
            if "launching" not in _RELAUNCH_TRANSITIONS.get(existing.state, frozenset()):
                raise WorkflowStateTransitionError(
                    f"illegal workflow relaunch for {workflow_id}: {existing.state} -> launching"
                )
            reserved: WorkflowHandleDAO = existing.model_copy(update={"state": "launching", "pid": 0})
            self._write_handle_locked(path=path, handle=reserved, lock_file=lock_file)
            return reserved

    def _relaunch_sync(
        self,
        *,
        owner_session_id: str,
        workflow_id: str,
        new_pid: int,
    ) -> WorkflowHandleDAO:
        """Patch one durable relaunch reservation with the spawned workload pid.

        WHAT: Records the actual replacement pid without reopening admission.
        WHO: ``relaunch`` reaches this sync filesystem boundary after spawn.
        WHEN: Once a reserved relaunch workload returns a positive pid.

        Args:
            owner_session_id (str): TUI session that owns the workflow handle.
            workflow_id (str): Workflow handle identifier.
            new_pid (int): Positive spawned workload pid.

        Returns:
            WorkflowHandleDAO: The patched launching handle.
        """
        if not self._is_path_safe_workflow_id(workflow_id=workflow_id):
            raise FileNotFoundError(workflow_id)
        if new_pid <= 0:
            raise WorkflowStateTransitionError(f"relaunch requires a positive pid for {workflow_id}")
        path: Path = self._handle_path(owner_session_id=owner_session_id, workflow_id=workflow_id)
        with self._locked_handle(path=path) as lock_file:
            existing: Optional[WorkflowHandleDAO] = self._read_path(path=path)
            if existing is None:
                raise FileNotFoundError(path)
            if existing.state in {"stalled", "failed"}:
                self._reject_live_relaunch_locked(handle=existing)
                relaunched: WorkflowHandleDAO = existing.model_copy(
                    update={"state": "launching", "pid": new_pid, "capture_health": None}
                )
                self._write_handle_locked(path=path, handle=relaunched, lock_file=lock_file)
                return relaunched
            if existing.state != "launching":
                raise WorkflowStateTransitionError(
                    f"workflow {workflow_id} is {existing.state} — relaunch reservation is not active"
                )
            updated: WorkflowHandleDAO = existing.model_copy(update={"pid": new_pid, "capture_health": None})
            self._write_handle_locked(path=path, handle=updated, lock_file=lock_file)
            return updated

    def _rollback_relaunch_sync(
        self,
        *,
        owner_session_id: str,
        workflow_id: str,
        state: WorkflowState,
    ) -> WorkflowHandleDAO:
        """Restore one unpatched reservation under the durable handle flock.

        WHAT: Returns a failed spawn reservation to its prior resumable state.
        WHO: ``rollback_relaunch`` reaches this sync filesystem boundary.
        WHEN: ``WorkflowRelauncher`` cannot provide a workload pid.

        Args:
            owner_session_id (str): TUI session that owns the workflow handle.
            workflow_id (str): Workflow handle identifier.
            state (WorkflowState): Original stalled or failed state.

        Returns:
            WorkflowHandleDAO: The restored workflow handle.
        """
        if state not in {"stalled", "failed"}:
            raise WorkflowStateTransitionError(f"invalid relaunch rollback state for {workflow_id}")
        if not self._is_path_safe_workflow_id(workflow_id=workflow_id):
            raise FileNotFoundError(workflow_id)
        path: Path = self._handle_path(owner_session_id=owner_session_id, workflow_id=workflow_id)
        with self._locked_handle(path=path) as lock_file:
            existing: Optional[WorkflowHandleDAO] = self._read_path(path=path)
            if existing is None:
                raise FileNotFoundError(path)
            if existing.state != "launching":
                raise WorkflowStateTransitionError(
                    f"workflow {workflow_id} is {existing.state} — relaunch reservation is not active"
                )
            restored: WorkflowHandleDAO = existing.model_copy(update={"state": state})
            self._write_handle_locked(path=path, handle=restored, lock_file=lock_file)
            return restored

    def _correct_from_evidence_sync(
        self,
        *,
        owner_session_id: str,
        workflow_id: str,
        state: WorkflowState,
        evidence: OrchestratorStatusDAO,
    ) -> WorkflowHandleDAO:
        """Validate and persist one correction while the handle lock is held."""
        if not self._is_path_safe_workflow_id(workflow_id=workflow_id):
            raise FileNotFoundError(workflow_id)
        path: Path = self._handle_path(owner_session_id=owner_session_id, workflow_id=workflow_id)
        with self._locked_handle(path=path) as lock_file:
            existing: Optional[WorkflowHandleDAO] = self._read_path(path=path)
            if existing is None:
                raise FileNotFoundError(path)
            if not self._status_matches_handle(handle=existing, status=evidence):
                raise WorkflowStateTransitionError(
                    f"evidence does not identify workflow {existing.workflow_id}"
                )
            if existing.state == state:
                return existing
            if state not in _EVIDENCE_TRANSITIONS.get(existing.state, frozenset()):
                raise WorkflowStateTransitionError(
                    f"no evidence-backed correction for {workflow_id}: {existing.state} -> {state}"
                )
            self._require_evidence_supports(state=state, evidence=evidence)
            updated: WorkflowHandleDAO = existing.model_copy(update={"state": state})
            self._write_handle_locked(path=path, handle=updated, lock_file=lock_file)
            return updated

    @staticmethod
    def _status_matches_handle(*, handle: WorkflowHandleDAO, status: OrchestratorStatusDAO) -> bool:
        """Return whether durable status evidence identifies one workflow handle.

        WHAT: Compares workflow and orchestrator session identities before the
            reconcile ladder trusts a status payload.
        WHO: Called by evidence correction and reconciliation.
        WHEN: Before durable status can change or keep a handle state.

        Args:
            handle (WorkflowHandleDAO): Handle the evidence proposes to change.
            status (OrchestratorStatusDAO): Self-reported durable status evidence.

        Returns:
            bool: True only when both stable identifiers agree.
        """
        return (
            status.workflow_id == handle.workflow_id
            and status.orchestrator_session_id == handle.orchestrator_session_id
        )

    @staticmethod
    def _require_evidence_supports(*, state: WorkflowState, evidence: OrchestratorStatusDAO) -> None:
        """Reject terminal corrections whose durable evidence names another state."""
        if state == "running":
            return
        if evidence.state != state:
            raise WorkflowStateTransitionError(
                f"evidence state {evidence.state} does not support correction to {state}"
            )

    def _reconcile_sync(self, *, owner_session_id: str) -> List[WorkflowHandleDAO]:
        """Refresh workflow handles from self-reported evidence before PID fallback.

        Args:
            owner_session_id (str): Owning TUI session id.

        Returns:
            list[WorkflowHandleDAO]: Reconciled handles sorted by ``started_at``.
        """
        handles: list[WorkflowHandleDAO] = self._list_sync(owner_session_id=owner_session_id)
        reconciled: list[WorkflowHandleDAO] = [self._reconcile_one(handle=handle) for handle in handles]
        reconciled.sort(key=lambda item: item.started_at)
        return reconciled

    def _reconcile_one(self, *, handle: WorkflowHandleDAO) -> WorkflowHandleDAO:
        """Apply the terminal, fresh, then PID evidence ladder to one handle."""
        if handle.state not in {"launching", "running", "stalled", "failed"}:
            return handle
        status: Optional[OrchestratorStatusDAO] = OrchestratorStatusStore.load_status(
            path=OrchestrationLayout.orchestrator_status_path(
                history_root=self._history_root,
                orchestrator_session_id=handle.orchestrator_session_id,
            )
        )
        if status is None or not self._status_matches_handle(handle=handle, status=status):
            return self._reconcile_launching_without_status(handle=handle)
        if status.state != "running":
            return self._correct_to_terminal(handle=handle, status=status)
        if self._status_is_fresh(status=status):
            return self._keep_live_from_evidence(handle=handle, status=status)
        return self._reconcile_by_pid(handle=handle)

    def _correct_to_terminal(
        self,
        *,
        handle: WorkflowHandleDAO,
        status: OrchestratorStatusDAO,
    ) -> WorkflowHandleDAO:
        """Persist the terminal state proven by an orchestrator self-report.

        WHAT: Applies a legal terminal transition or an evidence-only correction
            after the self-report is verified to name the requested target.
        WHO: Called by ``_reconcile_one`` for a terminal ``orchestrator.json`` record.
        WHEN: Before fresh-heartbeat and legacy PID reconciliation are considered.

        Args:
            handle (WorkflowHandleDAO): Durable workflow projection being reconciled.
            status (OrchestratorStatusDAO): Terminal self-report for the orchestrator.

        Returns:
            WorkflowHandleDAO: Handle whose terminal state agrees with the evidence.
        """
        target_state: WorkflowState = status.state
        if handle.state == target_state:
            return handle
        self._require_evidence_supports(state=target_state, evidence=status)
        if target_state in _LEGAL_TRANSITIONS.get(handle.state, frozenset()):
            return self._update_state_sync(
                owner_session_id=handle.owner_session_id,
                workflow_id=handle.workflow_id,
                state=target_state,
            )
        return self._correct_from_evidence_sync(
            owner_session_id=handle.owner_session_id,
            workflow_id=handle.workflow_id,
            state=target_state,
            evidence=status,
        )

    def _keep_live_from_evidence(
        self,
        *,
        handle: WorkflowHandleDAO,
        status: OrchestratorStatusDAO,
    ) -> WorkflowHandleDAO:
        """Keep a fresh handle live or repair it to running from self-report evidence."""
        if handle.state == "running":
            return handle
        if handle.state == "launching":
            return self._update_state_sync(
                owner_session_id=handle.owner_session_id,
                workflow_id=handle.workflow_id,
                state="running",
            )
        return self._correct_from_evidence_sync(
            owner_session_id=handle.owner_session_id,
            workflow_id=handle.workflow_id,
            state="running",
            evidence=status,
        )

    def _reconcile_launching_without_status(self, *, handle: WorkflowHandleDAO) -> WorkflowHandleDAO:
        """Keep a fresh reservation but reap an aged pid-less launch handle.

        WHAT: Distinguishes a current resume reservation from an abandoned
            pre-spawn launch record when no matching self-report exists.
        WHO: ``_reconcile_one`` calls this for absent or mismatched status.
        WHEN: Before generic PID reconciliation can classify a handle dead.

        Args:
            handle (WorkflowHandleDAO): Launching or non-launching handle.

        Returns:
            WorkflowHandleDAO: Existing handle or a failed stale launch handle.
        """
        if handle.state != "launching":
            return self._reconcile_by_pid(handle=handle)
        if handle.pid == 0 and self._is_within_launch_grace(handle=handle):
            return handle
        return self._reconcile_by_pid(handle=handle)

    def _reconcile_by_pid(self, *, handle: WorkflowHandleDAO) -> WorkflowHandleDAO:
        """Apply legacy PID reconciliation when self-report evidence is absent or stale."""
        if handle.state not in {"launching", "running"}:
            return handle
        if handle.pid > 0 and self._pid_alive(handle.pid):
            return handle
        if self._is_within_launch_grace(handle=handle):
            return handle
        state: WorkflowState = "stalled" if handle.state == "running" else "failed"
        return self._update_state_sync(
            owner_session_id=handle.owner_session_id,
            workflow_id=handle.workflow_id,
            state=state,
        )

    def _status_is_fresh(self, *, status: OrchestratorStatusDAO) -> bool:
        """Return whether a running self-report is inside the tolerated silence bound.

        WHAT: Treats only a timezone-aware, parseable status timestamp inside the
            heartbeat bound as liveness evidence.
        WHO: Called by ``_reconcile_one`` before it chooses PID fallback.
        WHEN: For each running orchestrator self-report during reconciliation.

        Args:
            status (OrchestratorStatusDAO): Self-report carrying the timestamp.

        Returns:
            bool: True only when the self-report timestamp is valid and fresh.
        """
        updated_at: Optional[datetime] = self._parse_status_updated_at(status=status)
        if updated_at is None:
            return False
        age_seconds: float = (datetime.now(timezone.utc) - updated_at).total_seconds()
        return age_seconds < self._heartbeat_seconds() * _STATUS_STALE_MULTIPLIER

    @staticmethod
    def _parse_status_updated_at(*, status: OrchestratorStatusDAO) -> Optional[datetime]:
        """Parse a timezone-aware timestamp from one self-report.

        WHAT: Converts durable status text into a safe UTC-comparable timestamp.
        WHO: Called only by ``_status_is_fresh``.
        WHEN: Before reconcile trusts a running status as liveness evidence.

        Args:
            status (OrchestratorStatusDAO): Self-report carrying the timestamp.

        Returns:
            Optional[datetime]: Parsed aware timestamp, or ``None`` for corrupt evidence.
        """
        try:
            updated_at: datetime = datetime.fromisoformat(status.updated_at)
        except ValueError:
            return None
        if updated_at.tzinfo is None:
            return None
        return updated_at

    @staticmethod
    def _heartbeat_seconds() -> float:
        """Read the shared headless heartbeat interval for evidence staleness."""
        return positive_float_env(primary_name="SLO_HEADLESS_HEARTBEAT_SECONDS", default=15.0)

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
        return OrchestrationLayout.workflows_dir(
            history_root=self._history_root,
            owner_session_id=owner_session_id,
        )

    def _handle_path(self, *, owner_session_id: str, workflow_id: str) -> Path:
        """Return the on-disk path for one workflow handle.

        Args:
            owner_session_id (str): Owning TUI session id.
            workflow_id (str): Workflow identifier.

        Returns:
            Path: Absolute handle path.
        """
        return OrchestrationLayout.workflow_handle_path(
            history_root=self._history_root,
            owner_session_id=owner_session_id,
            workflow_id=workflow_id,
        )

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

    @staticmethod
    @contextmanager
    def _locked_handle(*, path: Path) -> Iterator[TextIO]:
        """Hold a cross-process advisory lock for one handle mutation."""
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path: Path = path.with_suffix(path.suffix + ".lock")
        with lock_path.open("w") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                yield lock_file
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    @classmethod
    def _write_handle_locked(cls, *, path: Path, handle: WorkflowHandleDAO, lock_file: TextIO) -> None:
        """Persist a handle while the caller holds its advisory file lock.

        Args:
            path (Path): Final handle path.
            handle (WorkflowHandleDAO): Handle to serialize.
            lock_file (TextIO): Locked sibling lock file for the mutation.
        """
        del lock_file
        AtomicFileWriter.write_json(path=path, model=handle)

    @staticmethod
    def _default_pid_alive(pid: int) -> bool:
        """Return whether ``pid`` is a currently live process.

        WHAT: Delegates conservative PID liveness to the shared process probe.
        WHO: Called by workflow reconcile and injected into command services.
        WHEN: When durable handles need legacy process evidence.

        Args:
            pid (int): Process id to probe.

        Returns:
            bool: False only when the process is proven missing.
        """
        return ProcessProbe.is_alive(pid=pid)


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
        kill: Optional[ProcessGroupKiller] = None,
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
        self._history_root: Path = store._history_root
        self._owner_session_id: str = owner_session_id
        self._resume_lock: asyncio.Lock = asyncio.Lock()
        self._kill: ProcessGroupKiller = kill or _default_kill_process_group
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
        rows: list[str] = []
        for handle in handles:
            await self._sweep_terminal_handle_if_needed(handle=handle)
            rows.append(self._format_row(handle=handle))
        return "\n".join(rows)

    async def abort(self, *, workflow_id: str) -> str:
        """Request shutdown for a live workflow or surviving fleet children.

        WHAT: Persists a durable abort order before stopping the orchestrator or
            children that outlived a terminal workflow handle.
        WHO: Called by the ``/workflows abort <id>`` slash-command handler.
        WHEN: When an operator cancels a live workflow or cleans up an orphaned
            live child group shown on a terminal workflow row.

        Args:
            workflow_id (str): Workflow whose active processes require shutdown.

        Returns:
            str: One-line confirmation or explanation when no target remains.
        """
        handle: Optional[WorkflowHandleDAO] = await self._store.read(
            owner_session_id=self._owner_session_id,
            workflow_id=workflow_id,
        )
        if handle is None:
            return f"no workflow {workflow_id}"
        if handle.state in ("launching", "running"):
            return await self._abort_live_workflow(handle=handle)
        return await self._abort_terminal_fleet_children(handle=handle)

    async def dismiss(self, *, workflow_id: str) -> str:
        """Acknowledge a stalled workflow and return only its transcript text.

        Compatibility delegate for string callers of ``dismiss_result``.

        Args:
            workflow_id (str): Workflow to dismiss.

        Returns:
            str: One-line confirmation or error text for the transcript.
        """
        return (await self.dismiss_result(workflow_id=workflow_id)).rendered

    async def dismiss_result(self, *, workflow_id: str) -> WorkflowCommandResultDAO:
        """Acknowledge a stalled workflow (``stalled → failed``) with a typed outcome.

        WHAT: Applies the durable dismissal transition; the handle file is kept.
        WHO: Invoked by ``/workflows dismiss <id>`` so a crashed orchestrator's
            row stops appearing as actionable.
        WHEN: Once per operator dismiss command.

        Args:
            workflow_id (str): Workflow to dismiss.

        Returns:
            WorkflowCommandResultDAO: Transcript text, plus the dismissed id only
                after the durable transition succeeded.
        """
        handle: Optional[WorkflowHandleDAO] = await self._store.read(
            owner_session_id=self._owner_session_id,
            workflow_id=workflow_id,
        )
        if handle is None:
            return WorkflowCommandResultDAO(rendered=f"no workflow {workflow_id}")
        if handle.state != "stalled":
            return WorkflowCommandResultDAO(
                rendered=f"workflow {workflow_id} is {handle.state} — only stalled workflows can be dismissed"
            )
        try:
            await self._store.update_state(
                owner_session_id=self._owner_session_id,
                workflow_id=workflow_id,
                state="failed",
            )
        except (FileNotFoundError, WorkflowStateTransitionError) as exc:
            return WorkflowCommandResultDAO(rendered=f"could not dismiss workflow {workflow_id}: {exc}")
        return WorkflowCommandResultDAO(
            rendered=f"workflow {workflow_id} dismissed (stalled → failed)",
            dismissed_workflow_id=workflow_id,
        )

    async def resume(self, *, workflow_id: str) -> str:
        """Relaunch a dead workflow orchestrator and return only its transcript text.

        Compatibility delegate for string callers of ``resume_result``.

        Args:
            workflow_id (str): Identifier of the workflow to resume.

        Returns:
            str: One-line transcript confirmation or safe refusal text.
        """
        return (await self.resume_result(workflow_id=workflow_id)).rendered

    async def resume_result(self, *, workflow_id: str) -> WorkflowCommandResultDAO:
        """Relaunch a dead workflow orchestrator with its persisted history.

        WHAT: Spawns a fresh orchestrator for a stalled or failed handle, then
            applies the dedicated relaunch transition with its new process id.
        WHO: SlashRouter invokes this for /workflows resume <workflow-id>.
        WHEN: When an operator recovers a workflow whose prior orchestrator died.

        Args:
            workflow_id (str): Identifier of the workflow to resume.

        Returns:
            WorkflowCommandResultDAO: Transcript text, plus the resumed id only
                for a confirmed relaunch.
        """
        async with self._resume_lock:
            return await self._resume_locked(workflow_id=workflow_id)

    async def _resume_locked(self, *, workflow_id: str) -> WorkflowCommandResultDAO:
        """Spawn and atomically admit one relaunch while this service owns resume admission.

        WHAT: Serializes resume requests so an old capture drain completes before
        a replacement workload can append its first byte.
        WHO: ``resume`` delegates after taking the per-service admission lock.
        WHEN: Once for each operator-requested resume attempt.

        Args:
            workflow_id (str): Identifier of the terminal workflow to relaunch.

        Returns:
            WorkflowCommandResultDAO: Safe confirmation, warning, or refusal; only a
                confirmed relaunch names the resumed workflow.
        """
        from src.agents.slo_agent.orchestrator.relaunch import RelaunchOutcomeDAO, WorkflowRelauncher

        handles: List[WorkflowHandleDAO] = await self._store.reconcile(
            owner_session_id=self._owner_session_id,
        )
        handle: Optional[WorkflowHandleDAO] = next(
            (candidate for candidate in handles if candidate.workflow_id == workflow_id),
            None,
        )
        if handle is None:
            return WorkflowCommandResultDAO(rendered=f"no workflow {workflow_id}")
        if handle.state not in ("stalled", "failed"):
            return WorkflowCommandResultDAO(
                rendered=self._resume_state_refusal(workflow_id=workflow_id, state=handle.state)
            )
        try:
            reserved_handle: WorkflowHandleDAO = await self._store.reserve_relaunch(
                owner_session_id=self._owner_session_id,
                workflow_id=workflow_id,
            )
        except (FileNotFoundError, WorkflowStateTransitionError) as exc:
            return WorkflowCommandResultDAO(rendered=f"could not relaunch workflow {workflow_id}: {exc}")
        ownership: object | None = None
        adopted_pid: int | None = None
        adoption_committed: bool = False
        try:
            async with WorkflowRelauncher.spawn_for_adoption(
                handle=reserved_handle,
                history_root=self._history_root,
            ) as ownership:
                adopted_pid = ownership.process.pid
                outcome: RelaunchOutcomeDAO = RelaunchOutcomeDAO(pid=adopted_pid)
                await self._store.relaunch(
                    owner_session_id=self._owner_session_id,
                    workflow_id=workflow_id,
                    new_pid=adopted_pid,
                )
                adoption_committed = True
                activation_result = ownership.activate(expected_pid=adopted_pid)
                if inspect.isawaitable(activation_result):
                    await activation_result
        except asyncio.CancelledError:
            if adoption_committed:
                raise
            if ownership is not None:
                self._shutdown_rejected_relaunch(ownership=ownership)
            await self._rollback_failed_relaunch(workflow_id=workflow_id, state=handle.state)
            raise
        except OSError:
            if adoption_committed and adopted_pid is not None:
                await self._record_adopted_capture_failure(workflow_id=workflow_id, expected_pid=adopted_pid)
                return WorkflowCommandResultDAO(rendered=f"workflow {workflow_id} resume failed")
            if ownership is not None:
                self._shutdown_rejected_relaunch(ownership=ownership)
                return WorkflowCommandResultDAO(rendered=f"workflow {workflow_id} resume failed")
            await self._rollback_failed_relaunch(workflow_id=workflow_id, state=handle.state)
            return WorkflowCommandResultDAO(rendered=f"workflow {workflow_id} resume failed")
        except (FileNotFoundError, WorkflowStateTransitionError) as exc:
            if ownership is not None:
                self._shutdown_rejected_relaunch(ownership=ownership)
            return WorkflowCommandResultDAO(rendered=f"could not relaunch workflow {workflow_id}: {exc}")
        return WorkflowCommandResultDAO(
            rendered=self._resume_confirmation(workflow_id=workflow_id, outcome=outcome),
            resumed_workflow_id=workflow_id,
        )

    async def _record_adopted_capture_failure(self, *, workflow_id: str, expected_pid: int) -> None:
        """Persist fixed-safe capture degradation without changing an adopted workload.

        WHAT: Records the existing safe capture-health projection after durable
            relaunch adoption succeeds but activation or capture closing fails.
        WHO: ``_resume_locked`` calls this only for its retained replacement.
        WHEN: After the real workload PID is durable, before the safe failure
            result returns to the slash-command caller.

        Args:
            workflow_id (str): Identifier of the already-adopted workflow.
            expected_pid (int): Durable PID of its retained workload.
        """
        try:
            await self._store.record_capture_failure(
                owner_session_id=self._owner_session_id,
                workflow_id=workflow_id,
                expected_pid=expected_pid,
            )
        except (FileNotFoundError, WorkflowStateTransitionError):
            return

    def _shutdown_rejected_relaunch(self, *, ownership: object) -> None:
        """Stop the owned workload when durable resume adoption rejects its PID.

        WHAT: Sends the existing cooperative group shutdown only to the process
            created by the current command-owned relaunch context.
        WHO: ``_resume_locked`` calls this after ``store.relaunch`` rejects the
            just-spawned workload's durable adoption.
        WHEN: Before the private capture lifetime closes, so rejected workloads
            cannot continue without a durable handle identity.

        Args:
            ownership (object): Private relaunch ownership with the spawned
                process; the concrete type remains private to ``relaunch.py``.
        """
        process = getattr(ownership, "process", None)
        pid = getattr(process, "pid", 0)
        if not isinstance(pid, int):
            return
        self._request_group_shutdowns(pids=[pid])

    @staticmethod
    def _resume_state_refusal(*, workflow_id: str, state: WorkflowState) -> str:
        """Render the existing refusal for a locally observed non-resumable state."""
        return f"workflow {workflow_id} is {state} — only stalled or failed workflows can be resumed"

    async def _rollback_failed_relaunch(self, *, workflow_id: str, state: WorkflowState) -> None:
        """Best-effort restore of a spawn-failed durable relaunch reservation.

        WHAT: Returns the exclusive launching reservation to its prior
            resumable state so a later explicit resume can retry.
        WHO: ``_resume_locked`` calls this after a spawn outcome has no pid.
        WHEN: Before the original safe spawn-failure message is returned.

        Args:
            workflow_id (str): Reserved workflow identifier.
            state (WorkflowState): Original stalled or failed state.
        """
        try:
            await self._store.rollback_relaunch(
                owner_session_id=self._owner_session_id,
                workflow_id=workflow_id,
                state=state,
            )
        except (FileNotFoundError, WorkflowStateTransitionError):
            return

    @staticmethod
    def _resume_confirmation(*, workflow_id: str, outcome: "RelaunchOutcomeDAO") -> str:
        """Render a safe resume result while preserving capture failure evidence.

        Args:
            workflow_id (str): Durable workflow identifier.
            outcome (RelaunchOutcomeDAO): Successfully admitted relaunch outcome.

        Returns:
            str: Operator-facing resume confirmation with an optional safe warning.
        """
        confirmation = (
            f"workflow {workflow_id} resumed (pid {outcome.pid}); "
            "history replaying — state advances to running on the first heartbeat"
        )
        if outcome.warning is None:
            return confirmation
        return f"{confirmation}; warning: {outcome.warning}"

    def _format_row(self, *, handle: WorkflowHandleDAO) -> str:
        """Render one listing row for a workflow handle.

        Args:
            handle (WorkflowHandleDAO): Handle to render.

        Returns:
            str: ``<id>  <state>  orch <sid[:8]>  started <HH:MM>  <hint>``.
        """
        row: str = self._base_row(handle=handle)
        snapshot: Optional[FleetSnapshotDAO] = FleetStore.load_snapshot(
            path=OrchestrationLayout.fleet_path(
                history_root=self._history_root,
                orchestrator_session_id=handle.orchestrator_session_id,
            )
        )
        if snapshot is None:
            return row
        live_count: int = self._count_live_entries(entries=snapshot.entries)
        if handle.state in ("launching", "running"):
            return f"{row}  · {live_count} live{self._degraded_suffix(entries=snapshot.entries)}"
        if live_count > 0:
            return (
                f"{row}  · ⚠ {live_count} live children (reap pending or orphaned; "
                f"abort: /workflows abort {handle.workflow_id})"
            )
        return f"{row}  · {build_cleanup_summary(entries=snapshot.entries, live_count=live_count)}"

    async def _sweep_terminal_handle_if_needed(self, *, handle: WorkflowHandleDAO) -> None:
        """Sweep a terminal handle's live fleet only after its owner is proven dead.

        WHAT: Loads durable fleet evidence and delegates the terminal sweep when needed.
        WHO: Called by list_text before it renders each workflow row.
        WHEN: Only for terminal workflow handles with a fleet snapshot.
        """
        if handle.state not in {"completed", "failed", "aborted", "stalled"}:
            return
        snapshot: Optional[FleetSnapshotDAO] = FleetStore.load_snapshot(
            path=OrchestrationLayout.fleet_path(
                history_root=self._history_root,
                orchestrator_session_id=handle.orchestrator_session_id,
            )
        )
        if snapshot is None:
            return
        if self._count_live_entries(entries=snapshot.entries) == 0:
            return
        await self._sweep_terminal_fleet(handle=handle, snapshot=snapshot)

    async def _sweep_terminal_fleet(self, *, handle: WorkflowHandleDAO, snapshot: FleetSnapshotDAO) -> int:
        """Reap verified live children of a terminal workflow with a dead owner.

        WHAT: Applies the terminal sweep backstop and persists corrected fleet facts.
        WHO: Called by list_text's terminal-handle preparation helper.
        WHEN: Only when a terminal handle has pid-verified live fleet entries.

        Args:
            handle (WorkflowHandleDAO): Terminal workflow being inspected.
            snapshot (FleetSnapshotDAO): Durable fleet snapshot to correct.

        Returns:
            int: Live child count remaining after the sweep.
        """
        if handle.pid > 0 and self._pid_alive(handle.pid):
            return self._count_live_entries(entries=snapshot.entries)
        corrected_entries: list[SubAgentStatusDAO] = []
        changed: bool = False
        for entry in snapshot.entries:
            corrected_entry: SubAgentStatusDAO = await self._sweep_one(entry=entry)
            corrected_entries.append(corrected_entry)
            changed = changed or corrected_entry != entry
        if changed:
            self._persist_sweep_corrections(handle=handle, entries=corrected_entries)
        return self._count_live_entries(entries=corrected_entries)

    async def _sweep_one(self, *, entry: SubAgentStatusDAO) -> SubAgentStatusDAO:
        """Return one terminal-sweep correction without signaling an unverified pid.

        WHAT: Reaps exact children and records dead or recycled entries as terminal.
        WHO: Called by _sweep_terminal_fleet for every durable fleet entry.
        WHEN: After the workflow owner is proven dead.
        """
        if entry.status != "running" or entry.pid is None:
            return entry
        identity: IdentityVerificationOutcome = FleetReaper.child_identity_outcome(
            pid=entry.pid,
            session_id=entry.session_id,
        )
        if identity == "unreadable":
            return entry
        if identity == "recycled_pid":
            return entry.model_copy(
                update={
                    "status": "failed",
                    "last_text": "recorded pid belongs to a different process; not signalled",
                    "exit_code": 1,
                    "terminal_reason": "failed",
                    "terminated_by": "sweep",
                }
            )
        if identity == "already_dead":
            return entry.model_copy(
                update={
                    "status": "failed",
                    "last_text": "child was already absent during terminal sweep",
                    "exit_code": 1,
                    "terminal_reason": "failed",
                    "terminated_by": "sweep",
                }
            )
        outcome: ReapOutcome = await FleetReaper.reap(pid=entry.pid)
        if outcome == "unresolved":
            return entry
        return entry.model_copy(
            update={
                "status": "aborted" if outcome != "already_dead" else "failed",
                "last_text": (
                    "reaped during terminal sweep"
                    if outcome != "already_dead"
                    else "child exited during terminal sweep"
                ),
                "exit_code": -9 if outcome == "killed" else -15,
                "terminal_reason": "reaped_orphan" if outcome != "already_dead" else "failed",
                "terminated_by": "sweep",
            }
        )

    def _persist_sweep_corrections(
        self, *, handle: WorkflowHandleDAO, entries: list[SubAgentStatusDAO]
    ) -> None:
        """Persist terminal-sweep fleet corrections through the durable fleet store.

        WHAT: Writes corrected entries only after the owner-death single-writer guard.
        WHO: Called by _sweep_terminal_fleet after at least one entry changes.
        WHEN: After identity-verified terminal child reaping.
        """
        FleetStore(
            history_root=self._history_root,
            orchestrator_session_id=handle.orchestrator_session_id,
        ).persist(entries=entries)

    def _base_row(self, *, handle: WorkflowHandleDAO) -> str:
        """Render the legacy handle row before fleet evidence is appended."""
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

    @staticmethod
    def _count_live_entries(*, entries: list[SubAgentStatusDAO]) -> int:
        """Count running fleet entries whose pid remains alive at render time."""
        return sum(
            1
            for entry in entries
            if entry.status == "running" and entry.pid is not None and ProcessProbe.is_alive(pid=entry.pid)
        )

    @staticmethod
    def _degraded_suffix(*, entries: list[SubAgentStatusDAO]) -> str:
        """Render the advisory degraded count for running children when present."""
        import time

        degraded_count: int = sum(
            1
            for entry in entries
            if entry.status == "running"
            and entry.liveness(
                now_seconds=time.monotonic(), heartbeat_seconds=15.0, inactivity_seconds=7200.0
            )
            in ("degraded", "silent")
        )
        return f" · {degraded_count} degraded" if degraded_count else ""

    async def _abort_live_workflow(self, *, handle: WorkflowHandleDAO) -> str:
        """Write a durable order, stop a live orchestrator group, and mark it aborted.

        Args:
            handle (WorkflowHandleDAO): Live workflow handle receiving the order.

        Returns:
            str: Transcript-safe confirmation or durable-write failure text.
        """
        if not self._write_abort_request(handle=handle):
            return f"could not record durable abort request for workflow {handle.workflow_id}"
        self._request_group_shutdowns(pids=[handle.pid])
        return await self._mark_aborted(handle=handle)

    async def _abort_terminal_fleet_children(self, *, handle: WorkflowHandleDAO) -> str:
        """Sweep verified children whose terminal workflow owner is dead.

        WHAT: Reuses the identity-verified terminal sweep instead of child killpg calls.
        WHO: Called by abort for terminal workflow handles.
        WHEN: After an operator explicitly requests terminal survivor cleanup.

        Args:
            handle (WorkflowHandleDAO): Terminal workflow whose fleet may contain survivors.

        Returns:
            str: Cleanup result naming whether verified survivors remain.
        """
        snapshot: Optional[FleetSnapshotDAO] = FleetStore.load_snapshot(
            path=OrchestrationLayout.fleet_path(
                history_root=self._history_root,
                orchestrator_session_id=handle.orchestrator_session_id,
            )
        )
        if snapshot is None:
            return f"no live workflow {handle.workflow_id} (state {handle.state})"
        remaining: int = await self._sweep_terminal_fleet(handle=handle, snapshot=snapshot)
        if remaining > 0:
            return f"workflow {handle.workflow_id} has {remaining} unverified live children; not signalled"
        return f"workflow {handle.workflow_id} child cleanup completed"

    def _live_fleet_child_pids(self, *, handle: WorkflowHandleDAO) -> list[int]:
        """Return unique live child process-group leaders from durable fleet truth.

        Args:
            handle (WorkflowHandleDAO): Handle identifying the fleet snapshot.

        Returns:
            list[int]: Sorted positive process-group leaders still reported alive.
        """
        snapshot: Optional[FleetSnapshotDAO] = FleetStore.load_snapshot(
            path=OrchestrationLayout.fleet_path(
                history_root=self._history_root,
                orchestrator_session_id=handle.orchestrator_session_id,
            )
        )
        if snapshot is None:
            return []
        return sorted(
            {
                entry.pid
                for entry in snapshot.entries
                if entry.status == "running"
                and entry.pid is not None
                and entry.pid > 0
                and self._pid_alive(entry.pid)
            }
        )

    def _request_group_shutdowns(self, *, pids: list[int]) -> None:
        """Send SIGTERM and arm SIGKILL escalation for each positive group leader.

        Args:
            pids (list[int]): Process-group leaders targeted by one abort request.
        """
        for pid in pids:
            if pid <= 0:
                continue
            self._signal_process_group(pid=pid, signal_number=signal.SIGTERM)
            self._schedule_group_escalation(pid=pid)

    def _schedule_group_escalation(self, *, pid: int) -> None:
        """Arm SIGKILL escalation for one process group after its SIGTERM grace.

        Args:
            pid (int): Process-group leader captured for this one callback.
        """

        def escalate_group() -> None:
            """Escalate the process group captured by this scheduling call."""
            self._escalate(pid=pid)

        self._schedule(
            delay_seconds=_ABORT_ESCALATION_SECONDS,
            callback=escalate_group,
        )

    def _write_abort_request(self, *, handle: WorkflowHandleDAO) -> bool:
        """Write the watchdog abort order before the immediate signal channel.

        WHAT: Persists the durable half of an operator abort before any signal.
        WHO: Called by abort for each live workflow handle.
        WHEN: Immediately before the SIGTERM and delayed SIGKILL channels.

        Args:
            handle (WorkflowHandleDAO): Live handle receiving the abort order.

        Returns:
            bool: True when the watchdog can observe the durable order.
        """
        path: Path = OrchestrationLayout.abort_request_path(
            history_root=self._history_root,
            orchestrator_session_id=handle.orchestrator_session_id,
        )
        try:
            AtomicFileWriter.write_text(
                path=path,
                text=json.dumps({"requested_at": datetime.now(timezone.utc).isoformat()}),
            )
        except OSError as exc:
            log_info(msg="workflow_abort_request_write_failed", error=str(exc))
            return False
        return True

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
            return f"workflow {handle.workflow_id} aborted " f"(SIGTERM sent to process group {handle.pid})"
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
            self._kill(pid=pid, signal_number=signal_number)
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
    def _default_schedule(*, delay_seconds: float, callback: Callable[[], None]) -> None:
        """Arm one delayed callback on the running event loop.

        Args:
            delay_seconds (float): Delay before the callback fires.
            callback (Callable[[], None]): Zero-argument callback.
        """
        asyncio.get_running_loop().call_later(delay_seconds, callback)
