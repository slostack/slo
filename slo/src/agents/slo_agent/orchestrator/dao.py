"""Domain DAOs for the Slo orchestrator / sub-agent system.

These are the shared vocabulary for all orchestrator modules. Import
from here; do not duplicate these types in other modules.

Sub-spec 01-sub-agents 01.b.
"""

from __future__ import annotations

import re
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.agents.reasoning_capabilities import ReasoningLevel

__all__ = [
    "ReasoningLevel",
    "SubAgentMode",
    "SubAgentStatus",
    "LivenessState",
    "TerminalReason",
    "TerminatedBy",
    "SubAgentTaskDAO",
    "SubAgentTaskResolutionDAO",
    "SubAgentStatusDAO",
    "FleetSnapshotDAO",
    "SubAgentResultDAO",
    "OrchestratorRunState",
    "OrchestratorStatusDAO",
    "OrchestratorResultDAO",
    "ExecutionPhase",
    "StdoutCaptureIdentityDAO",
    "ChildExecutionEvidenceDAO",
    "ExecutionIndexDAO",
    "ChildAbortOutcome",
    "ChildAbortRequestDAO",
    "ChildAbortOutcomeDAO",
    "ChildControlCapabilityDAO",
    "TERMINAL_STATUSES",
    "canonical_uuid",
    "safe_identifier",
    "exit_code_for_terminal_kind",
    "lifecycle_kind_for_status",
    "run_state_for_terminal_kind",
    "status_for_lifecycle_kind",
    "terminal_reason_for_status",
    "project_fleet_entries",
    "build_cleanup_summary",
    "TERMINAL_KIND_TO_HEADLESS_LIFECYCLE",
]


TERMINAL_KIND_TO_EXIT_CODE: dict[str, int] = {"run_completed": 0, "run_aborted": 2}
"""Terminal event kind to POSIX exit code; unrecognized kinds exit with 1."""

TERMINAL_KIND_TO_HEADLESS_LIFECYCLE: dict[str, str] = {
    "run_completed": "headless_run_completed",
    "run_aborted": "headless_run_aborted",
}
"""Terminal event kind to the matching stderr lifecycle event kind."""

TERMINAL_KIND_TO_RUN_STATE: dict[str, str] = {
    "run_completed": "completed",
    "run_aborted": "aborted",
    "run_failed": "failed",
}
"""Terminal event kind to durable orchestrator run state."""

SUB_AGENT_STATUS_TO_LIFECYCLE_KIND: dict[str, str] = {
    "completed": "sub_agent_completed",
    "aborted": "sub_agent_aborted",
    "failed": "sub_agent_failed",
}
"""Child terminal status to pool lifecycle event kind."""

SUB_AGENT_LIFECYCLE_KIND_TO_STATUS: dict[str, str] = {
    "sub_agent_completed": "completed",
    "sub_agent_aborted": "aborted",
    "sub_agent_failed": "failed",
}
"""Pool lifecycle event kind to child terminal status."""

SUB_AGENT_STATUS_TO_TERMINAL_REASON: dict[str, str] = {
    "completed": "completed",
    "aborted": "operator_abort",
    "failed": "failed",
}
"""Child terminal status to its default terminal reason."""

TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "aborted"})
"""Child statuses that end an execution incarnation and can never regress."""

_SAFE_IDENTIFIER_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._-]+$")
"""Safe session-id slug rule shared with ``src.cli.headless_request``.

Duplicated as a pattern (not imported) because importing ``src.cli`` from this
foundational DAO module would load the CLI application and create an import cycle.
"""

_SHA256_HEX_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{64}$")
"""Lower-case hexadecimal SHA-256 digest of exact persisted bytes."""


def canonical_uuid(*, value: str) -> str:
    """Return a strictly parsed canonical UUID string.

    WHAT: Accepts only the lower-case hyphenated form that ``str(UUID)`` emits,
        so one identity never has two spellings on disk or in memory.
    WHO: Called by DAO validators for execution, run and request identities.
    WHEN: Whenever a runtime or durable identity is constructed or decoded.

    Args:
        value (str): Candidate UUID text.

    Returns:
        str: The unchanged canonical UUID text.

    Raises:
        ValueError: If the value is not a canonical UUID string.
    """
    try:
        parsed: UUID = UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("identity must be a canonical UUID") from exc
    if str(parsed) != value:
        raise ValueError("identity must be a canonical UUID")
    return value


def safe_identifier(*, value: str) -> str:
    """Return a session-style identifier that is safe as one path component.

    WHAT: Applies the existing headless session-id rule (``[A-Za-z0-9._-]``
        slug, which also covers canonical UUIDs) and rejects traversal components.
    WHO: Called by DAO validators for session, owner and dispatch identities.
    WHEN: Before an identity can address any durable child-control or evidence file.

    Args:
        value (str): Candidate identifier.

    Returns:
        str: The unchanged identifier.

    Raises:
        ValueError: If the value is empty or unsafe as one path component.
    """
    if ".." in value or value == "." or not _SAFE_IDENTIFIER_RE.fullmatch(value):
        raise ValueError("identifier must be a safe path component")
    return value


def _optional_runtime_uuid(*, value: str) -> str:
    """Accept an empty legacy runtime identity or a canonical UUID.

    Args:
        value (str): Runtime execution identity; empty for legacy rows.

    Returns:
        str: The unchanged value.

    Raises:
        ValueError: If a non-empty value is not a canonical UUID.
    """
    if value == "":
        return value
    return canonical_uuid(value=value)


def exit_code_for_terminal_kind(*, kind: str) -> int:
    """Return the POSIX exit code for a terminal event kind.

    WHAT: Projects an event terminal kind to its process exit code.
    WHO: Called by HeadlessRunner after the session stream ends.
    WHEN: Once per headless process exit.

    Args:
        kind (str): Terminal event kind.

    Returns:
        int: Mapped POSIX exit code, or 1 for an unknown kind.
    """
    return TERMINAL_KIND_TO_EXIT_CODE.get(kind, 1)


def run_state_for_terminal_kind(*, kind: str) -> str:
    """Return the durable run state for a terminal event kind.

    WHAT: Projects terminal stream vocabulary to orchestrator state vocabulary.
    WHO: Called by the status store in a later feature slice.
    WHEN: When terminal evidence is persisted.

    Args:
        kind (str): Terminal event kind.

    Returns:
        str: Mapped run state, or ``failed`` for an unknown kind.
    """
    return TERMINAL_KIND_TO_RUN_STATE.get(kind, "failed")


def lifecycle_kind_for_status(*, status: str) -> str:
    """Return the pool lifecycle event kind for a child terminal status.

    WHAT: Projects a child status to the event sent through the pool relay.
    WHO: Called by SubAgentPool after a child returns a terminal result.
    WHEN: Once for each completed child wrapper.

    Args:
        status (str): Child terminal status.

    Returns:
        str: Mapped lifecycle kind, or the failed kind for an unknown status.
    """
    return SUB_AGENT_STATUS_TO_LIFECYCLE_KIND.get(status, "sub_agent_failed")


def status_for_lifecycle_kind(*, kind: str) -> str:
    """Return the child terminal status for a pool lifecycle event kind.

    WHAT: Projects a pool lifecycle event kind to the visualizer's child status.
    WHO: Called by WorkflowVisualizerLoader after it reads terminal child events.
    WHEN: While building a child summary from durable parent history.

    Args:
        kind (str): Pool lifecycle event kind.

    Returns:
        str: Mapped child terminal status, or ``failed`` for an unknown kind.
    """
    return SUB_AGENT_LIFECYCLE_KIND_TO_STATUS.get(kind, "failed")


def terminal_reason_for_status(*, status: str) -> str:
    """Return the default terminal reason for a child terminal status.

    WHAT: Projects child status to its default operator-visible terminal reason.
    WHO: Called by fleet persistence in a later feature slice.
    WHEN: When a child terminal record is written.

    Args:
        status (str): Child terminal status.

    Returns:
        str: Mapped terminal reason, or ``failed`` for an unknown status.
    """
    return SUB_AGENT_STATUS_TO_TERMINAL_REASON.get(status, "failed")


OrchestratorRunState = Literal["running", "completed", "failed", "aborted"]
"""Self-reported state of one detached orchestrator run."""


class OrchestratorStatusDAO(BaseModel):
    """Self-reported status of one detached orchestrator in ``orchestrator.json``.

    The HeadlessRunner is the single writer. Workflow reconcile, the TUI, and
    the visualizer read this durable evidence to determine workflow state.

    Attributes:
        workflow_id (str): Detached workflow identifier from ``SLO_WORKFLOW_ID``.
        orchestrator_session_id (str): Session identifier of this headless run.
        pid (int): Self-reported operating-system process identifier.
        state (OrchestratorRunState): Running heartbeat or terminal state.
        phase (str): Current safe heartbeat phase label.
        updated_at (str): UTC ISO-8601 timestamp of this write.
        exit_code (Optional[int]): POSIX exit code on terminal writes only.
    """

    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    orchestrator_session_id: str
    pid: int
    state: OrchestratorRunState
    phase: str = "awaiting_provider_stream"
    updated_at: str
    exit_code: Optional[int] = None


SubAgentMode = Literal["parallel", "chain", "single"]
"""Dispatch strategy for a batch of sub-tasks.

``parallel`` — all tasks fan out concurrently (bounded by ``MAX_CONCURRENCY``).
``chain``    — tasks run sequentially; ``{previous}`` in a prompt is substituted with
               the prior task's answer; a failure stops the chain.
``single``   — exactly one task runs (a degenerate parallel batch of size 1).
"""

SubAgentStatus = Literal["pending", "running", "completed", "failed", "aborted"]
"""Lifecycle state of one sub-agent process.

``pending``   — task created; not yet dispatched to a child process.
``running``   — child process started; events are streaming.
``completed`` — child exited with code 0.
``failed``    — child exited non-zero or crashed during spawn or streaming.
``aborted``   — child was cancelled (SIGTERM/SIGKILL) by the orchestrator.
"""

LivenessState = Literal["healthy", "degraded", "silent"]
"""Read-time liveness classification for one fleet entry.

``healthy`` is terminal or has a fresh heartbeat. ``degraded`` has overdue
heartbeat telemetry but recent stdout. ``silent`` has neither; it is
informational and never a cancellation trigger.
"""

TerminalReason = Literal["completed", "failed", "operator_abort", "orchestrator_died", "reaped_orphan"]
"""How a sub-agent ended; None while the child remains live."""

TerminatedBy = Literal["natural", "abort", "watchdog", "sweep"]
"""Which reaper ended a sub-agent; None while the child remains live."""

_HEARTBEAT_STALE_MULTIPLIER: int = 3
"""Internal number of heartbeat intervals considered fresh for display."""

_CLEANUP_REASON_LABELS: dict[str, str] = {
    "completed": "completed",
    "failed": "failed",
    "operator_abort": "aborted (operator)",
    "orchestrator_died": "died with orchestrator",
    "reaped_orphan": "reaped orphan",
}
"""Terminal reason to operator-facing cleanup summary label."""


class SubAgentTaskDAO(BaseModel):
    """One decomposed sub-task dispatched to a child agent process.

    Attributes:
        task_id (str): Caller-assigned stable identifier, unique within the
            batch. Used to correlate events and results across processes.
        prompt (str): Natural-language task for the child agent. In chain mode
            it may contain a ``{previous}`` placeholder, substituted with the
            prior step's answer before the child is spawned.
        cwd (Optional[str]): Working directory for the child process; defaults
            to the orchestrator's cwd when ``None``.
        model (Optional[str]): Per-task model override; inherits the
            orchestrator's active model when ``None``.
        reasoning_level (Optional[ReasoningLevel]): Per-task reasoning budget
            override. ``None`` lets the child inherit its session default.
        resume_session_reference (Optional[str]): Resume a previously persisted
            child session by id or unique name. Implies ``--enable-history``.
            Cannot be combined with ``session_id``.
        session_id (Optional[str]): Run the child under an exact validated
            session id. Cannot be combined with ``resume_session_reference``.
        enable_history (Optional[bool]): ``True`` persists the child's history
            for later resumption. ``False`` (default) keeps the child ephemeral.
            ``None`` inherits the orchestrator's history policy.
        system_prompt (Optional[str]): Optional system prompt override for this child
            ``slo run`` process. When ``None``, the child uses the standard solo coding
            agent system prompt. When set, the child is invoked with
            ``--system-prompt-b64 <encoded>``.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    prompt: str
    cwd: Optional[str] = None
    model: Optional[str] = None
    reasoning_level: Optional[ReasoningLevel] = None
    resume_session_reference: Optional[str] = None
    session_id: Optional[str] = None
    enable_history: Optional[bool] = None
    system_prompt: Optional[str] = None

    @model_validator(mode="after")
    def _validate_session_reference_exclusivity(self) -> "SubAgentTaskDAO":
        """Ensure ``resume_session_reference`` and ``session_id`` are not both set.

        Returns:
            SubAgentTaskDAO: Self after validation.

        Raises:
            ValueError: When both ``resume_session_reference`` and ``session_id``
                are supplied, as they are mutually exclusive continuation strategies.
        """
        if self.resume_session_reference is not None and self.session_id is not None:
            raise ValueError(
                "SubAgentTaskDAO: 'resume_session_reference' and 'session_id' "
                "are mutually exclusive — provide at most one."
            )
        return self

    @model_validator(mode="after")
    def _coerce_history_for_resume(self) -> "SubAgentTaskDAO":
        """Force ``enable_history=True`` when ``resume_session_reference`` is set.

        A resume requires history to be enabled — without it the child process
        cannot load its previous context. Silently upgrading ``None`` / ``False``
        to ``True`` avoids surprising failures when the caller omits the flag.

        Returns:
            SubAgentTaskDAO: Self after coercion.
        """
        if self.resume_session_reference is not None and not self.enable_history:
            self.enable_history = True
        return self


class SubAgentTaskResolutionDAO(BaseModel):
    """Result of resolving ``spawn_sub_agents`` input into validated tasks.

    Attributes:
        tasks (list[SubAgentTaskDAO]): Validated tasks ready for dispatch. Empty
            when ``error`` is set.
        recovery_notes (list[str]): Tolerances applied while parsing a legacy
            ``tasks_json`` string. Empty for the native ``tasks`` path.
        error (Optional[str]): Set when the input could not be resolved into
            tasks; ``None`` on success.
    """

    model_config = ConfigDict(extra="forbid")

    tasks: list[SubAgentTaskDAO] = Field(default_factory=list)
    recovery_notes: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class SubAgentStatusDAO(BaseModel):
    """Live status snapshot for one sub-agent, produced by ``ProcessRegistry``.

    Consumed by the TUI's ``/agents`` listing and orchestrator progress lines.

    Attributes:
        task_id (str): Matches the originating ``SubAgentTaskDAO.task_id``.
        session_id (str): The child process's session identifier, assigned
            by the pool before spawning.
        status (SubAgentStatus): Current lifecycle state.
        last_text (Optional[str]): Latest visible answer text from the child.
            Updated on each ``text_delta`` event relayed from the child.
        prompt_preview (str): First 120 characters of the task prompt.
            Used as a human-readable label in the TUI fleet status.
        last_heartbeat_at (Optional[float]): Monotonic timestamp of the most
            recent recognized child heartbeat.
        last_stdout_at (Optional[float]): Monotonic timestamp of the most
            recent child stdout line.
        pid (Optional[int]): Child process id recorded after spawn.
        started_at (Optional[float]): Wall-clock spawn time.
        heartbeat_phase (Optional[str]): Most recent heartbeat phase label.
        exit_code (Optional[int]): Child exit code at terminal time.
        terminal_reason (Optional[TerminalReason]): How the child ended.
        terminated_by (Optional[TerminatedBy]): Which reaper ended the child.
        execution_id (str): Runtime incarnation identity allocated at registration.
            Excluded from serialization so released closed readers keep decoding
            fleet.json; ``execution.v1.json`` is the persisted identity owner.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    session_id: str
    status: SubAgentStatus = "pending"
    last_text: Optional[str] = None
    prompt_preview: str = ""
    last_heartbeat_at: Optional[float] = None
    last_stdout_at: Optional[float] = None
    pid: Optional[int] = None
    started_at: Optional[float] = None
    heartbeat_phase: Optional[str] = None
    exit_code: Optional[int] = None
    terminal_reason: Optional[TerminalReason] = None
    terminated_by: Optional[TerminatedBy] = None
    execution_id: str = Field(
        default="",
        exclude=True,
        description="Runtime incarnation identity; never serialized into released fleet files.",
    )

    @field_validator("execution_id")
    @classmethod
    def _validate_execution_id(cls, value: str) -> str:
        """Reject a non-empty runtime identity that is not a canonical UUID."""
        return _optional_runtime_uuid(value=value)

    def liveness(
        self,
        *,
        now_seconds: float,
        heartbeat_seconds: float,
        inactivity_seconds: float,
    ) -> LivenessState:
        """Classify this entry's liveness at ``now_seconds``.

        WHAT: Answers healthy, degraded, or silent from activity ages.
        WHO: Called by registry snapshot consumers such as the TUI and visualizer.
        WHEN: At read time while a fleet snapshot is rendered; never stored.

        Args:
            now_seconds (float): Current monotonic time.
            heartbeat_seconds (float): Configured heartbeat interval.
            inactivity_seconds (float): Child stdout inactivity budget.

        Returns:
            LivenessState: Classification for rendering.
        """
        if self.status != "running":
            return "healthy"
        if self._heartbeat_is_fresh(now_seconds=now_seconds, heartbeat_seconds=heartbeat_seconds):
            return "healthy"
        if self._stdout_is_fresh(now_seconds=now_seconds, inactivity_seconds=inactivity_seconds):
            return "degraded"
        return "silent"

    def _heartbeat_is_fresh(self, *, now_seconds: float, heartbeat_seconds: float) -> bool:
        """Return whether heartbeat telemetry is within the display bound."""
        if self.last_heartbeat_at is None:
            return False
        return now_seconds - self.last_heartbeat_at < heartbeat_seconds * _HEARTBEAT_STALE_MULTIPLIER

    def _stdout_is_fresh(self, *, now_seconds: float, inactivity_seconds: float) -> bool:
        """Return whether child stdout is within the inactivity budget."""
        if self.last_stdout_at is None:
            return False
        return now_seconds - self.last_stdout_at < inactivity_seconds


def project_fleet_entries(*, entries: list[SubAgentStatusDAO]) -> tuple[list[dict[str, object]], int]:
    """Project registry entries into the compact fleet-note payload.

    WHAT: Retains only child identity, status, and heartbeat phase for inbox notes.
    WHO: Called by HeadlessRunner's pool lifecycle tap.
    WHEN: Once for every relayed child lifecycle event.

    Args:
        entries (list[SubAgentStatusDAO]): Registry snapshot in registration order.

    Returns:
        tuple[list[dict[str, object]], int]: Compact entries and running-child count.
    """
    projected: list[dict[str, object]] = [
        {
            "task_id": entry.task_id,
            "status": entry.status,
            "heartbeat_phase": entry.heartbeat_phase or "",
        }
        for entry in entries
    ]
    live_count: int = sum(1 for entry in entries if entry.status == "running")
    return projected, live_count


def build_cleanup_summary(*, entries: list[SubAgentStatusDAO], live_count: int) -> str:
    """Compose the terminal fleet accounting line.

    WHAT: Counts terminal reasons and appends the pid-verified live count.
    WHO: Called by HeadlessRunner terminal notifications and workflow rows.
    WHEN: After a workflow reaches a terminal state or its row is rendered.

    Args:
        entries (list[SubAgentStatusDAO]): Final durable fleet entries.
        live_count (int): Pid-verified count of still-running children.

    Returns:
        str: One-line operator-facing cleanup summary.
    """
    parts: list[str] = [
        f"{sum(1 for entry in entries if entry.terminal_reason == reason)} {label}"
        for reason, label in _CLEANUP_REASON_LABELS.items()
        if any(entry.terminal_reason == reason for entry in entries)
    ]
    parts.append(f"{live_count} live")
    return "fleet: " + " · ".join(parts)


class FleetSnapshotDAO(BaseModel):
    """Durable snapshot of one orchestrator's fleet, persisted as ``fleet.json``.

    Attributes:
        orchestrator_session_id (str): Session owning the fleet.
        workflow_id (Optional[str]): Detached workflow identifier when known.
        entries (list[SubAgentStatusDAO]): Fleet entries in registration order.
        updated_at (str): UTC ISO-8601 durable write time.
    """

    model_config = ConfigDict(extra="forbid")

    orchestrator_session_id: str
    workflow_id: Optional[str] = None
    entries: list[SubAgentStatusDAO] = Field(default_factory=list)
    updated_at: str


class SubAgentResultDAO(BaseModel):
    """Terminal result from one child agent process.

    Produced by ``SubAgentProcess._terminal_result()`` and collected by the
    pool into ``OrchestratorResultDAO``.

    Attributes:
        task_id (str): Matches the originating ``SubAgentTaskDAO.task_id``.
        session_id (str): The child session that produced this result.
        status (SubAgentStatus): Terminal state: ``completed``, ``failed``,
            or ``aborted``.
        answer (str): Final assistant answer, or the error message when
            not completed.
        exit_code (int): Child process exit code. ``0`` on success; ``2``
            on abort; ``1`` on failure; ``-1`` while the child is still
            running (interim value; never returned to callers).
        usage (dict[str, int]): Token-usage totals when available. Reserved
            for per-child billing attribution; empty dict in v1.
        execution_id (str): Runtime incarnation that produced this result; excluded
            from serialization so released readers keep decoding status.json.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    session_id: str
    status: SubAgentStatus
    answer: str = ""
    exit_code: int = -1
    usage: dict[str, int] = Field(default_factory=dict)
    failure_code: Optional[str] = Field(
        default=None,
        description="Machine-readable redacted terminal failure cause.",
    )
    partial_output_committed: Optional[bool] = Field(
        default=None,
        description="Whether the child crossed its commit boundary before failing.",
    )
    attempts: Optional[int] = Field(
        default=None,
        description="Provider attempts consumed by the child run.",
    )
    safe_message: Optional[str] = Field(
        default=None,
        description="Redacted operator-facing failure summary.",
    )
    execution_id: str = Field(
        default="",
        exclude=True,
        description="Runtime incarnation identity; never serialized into released status files.",
    )

    @field_validator("execution_id")
    @classmethod
    def _validate_execution_id(cls, value: str) -> str:
        """Reject a non-empty runtime identity that is not a canonical UUID."""
        return _optional_runtime_uuid(value=value)


class OrchestratorResultDAO(BaseModel):
    """Aggregated result returned to the orchestrator LLM after a batch finishes.

    Serialised via ``model_dump_json()`` and returned as the
    ``spawn_sub_agents`` tool's string result so the LLM can synthesise a
    combined final answer.

    Attributes:
        mode (SubAgentMode): The dispatch mode the batch ran under.
        results (list[SubAgentResultDAO]): One entry per task, in spawn order.
        all_completed (bool): ``True`` when every task reached ``completed``.
        failed_task_ids (list[str]): ``task_id`` values whose children did not
            reach ``completed``. Empty when ``all_completed`` is ``True``.
    """

    model_config = ConfigDict(extra="forbid")

    mode: SubAgentMode
    results: list[SubAgentResultDAO] = Field(default_factory=list)
    all_completed: bool = True
    failed_task_ids: list[str] = Field(default_factory=list)
    error: Optional[str] = None


ExecutionPhase = Literal["pending", "running", "terminal"]
"""Persisted phase of one execution incarnation in ``execution.v1.json``.

``pending``  — registered; no trusted capture, context or status evidence.
``running``  — fresh spawn context and stdout capture belong to this incarnation.
``terminal`` — old-shaped status.json holds this incarnation's registry winner.
"""

_PHASE_STATUSES: dict[str, frozenset[str]] = {
    "pending": frozenset({"pending"}),
    "running": frozenset({"running"}),
    "terminal": TERMINAL_STATUSES,
}
"""Public statuses each persisted phase may carry; the registry winner supplies them."""


class StdoutCaptureIdentityDAO(BaseModel):
    """Exact filesystem identity of one freshly opened stdout capture.

    Attributes:
        device (int): ``st_dev`` of the opened capture file.
        inode (int): ``st_ino`` of the opened capture file.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    device: int = Field(ge=0)
    inode: int = Field(ge=0)


class ChildExecutionEvidenceDAO(BaseModel):
    """Versioned sibling that binds old-shaped child files to one incarnation.

    Written to ``children/<session_id>/execution.v1.json`` beside the released
    spawn_context.json/status.json files, which keep their closed schemas. New
    readers trust capture, context or status bytes only when this sibling, the
    run's execution index and the file identities/digests all agree. Old readers
    ignore it. It is a regenerated projection of the registry winner, never a
    second execution authority and never backfilled into older records.

    Attributes:
        schema_version (Literal[1]): Closed sibling schema version.
        session_id (str): Safe child session identifier.
        execution_id (str): Canonical UUID of this incarnation.
        dispatch_id (Optional[str]): Dispatch batch identity once dispatch metadata exists.
        phase (ExecutionPhase): Pending, running or terminal publication phase.
        status (SubAgentStatus): Registry status published with the phase.
        stdout_identity (Optional[StdoutCaptureIdentityDAO]): Fresh capture identity;
            None before spawn, for a pending abort, or when capture could not open.
        spawn_context_sha256 (Optional[str]): Digest of this incarnation's exact
            spawn_context.json bytes; None when the context was not written.
        status_sha256 (Optional[str]): Digest of the exact status.json bytes; set
            only in the terminal phase.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    session_id: str
    execution_id: str
    dispatch_id: Optional[str] = None
    phase: ExecutionPhase
    status: SubAgentStatus
    stdout_identity: Optional[StdoutCaptureIdentityDAO] = None
    spawn_context_sha256: Optional[str] = None
    status_sha256: Optional[str] = None

    @field_validator("session_id")
    @classmethod
    def _validate_session_id(cls, value: str) -> str:
        """Require a safe child session path component."""
        return safe_identifier(value=value)

    @field_validator("execution_id")
    @classmethod
    def _validate_execution_id(cls, value: str) -> str:
        """Require a canonical incarnation UUID."""
        return canonical_uuid(value=value)

    @field_validator("dispatch_id")
    @classmethod
    def _validate_dispatch_id(cls, value: Optional[str]) -> Optional[str]:
        """Require a safe dispatch identity when one is present."""
        return value if value is None else safe_identifier(value=value)

    @field_validator("spawn_context_sha256", "status_sha256")
    @classmethod
    def _validate_digest(cls, value: Optional[str]) -> Optional[str]:
        """Require lower-case SHA-256 hex digests when present."""
        if value is not None and not _SHA256_HEX_RE.fullmatch(value):
            raise ValueError("digest must be lower-case SHA-256 hex")
        return value

    @model_validator(mode="after")
    def _validate_phase_evidence(self) -> "ChildExecutionEvidenceDAO":
        """Reject evidence whose phase, status and digests disagree.

        Returns:
            ChildExecutionEvidenceDAO: Self after validation.

        Raises:
            ValueError: If the status does not belong to the phase, a pending phase
                carries capture/context evidence, or the status digest is present
                exactly when the phase is not terminal.
        """
        if self.status not in _PHASE_STATUSES[self.phase]:
            raise ValueError("status does not belong to the execution phase")
        if (self.phase == "terminal") != (self.status_sha256 is not None):
            raise ValueError("status digest is required exactly in the terminal phase")
        if self.phase == "pending" and (self.stdout_identity or self.spawn_context_sha256):
            raise ValueError("pending evidence carries no capture or context identity")
        return self

    @classmethod
    def pending(
        cls,
        *,
        session_id: str,
        execution_id: str,
        dispatch_id: Optional[str] = None,
    ) -> "ChildExecutionEvidenceDAO":
        """Build the initial evidence published at registration.

        WHAT: Declares a new incarnation with no trusted capture, context or status.
        WHO: Called by ProcessRegistry.register.
        WHEN: Before the pending fleet projection is persisted.

        Args:
            session_id (str): Safe child session identifier.
            execution_id (str): Freshly allocated incarnation UUID.
            dispatch_id (Optional[str]): Dispatch identity when known. Defaults to None.

        Returns:
            ChildExecutionEvidenceDAO: Pending-phase evidence.
        """
        return cls(
            session_id=session_id,
            execution_id=execution_id,
            dispatch_id=dispatch_id,
            phase="pending",
            status="pending",
        )

    def running(
        self,
        *,
        stdout_identity: Optional[StdoutCaptureIdentityDAO],
        spawn_context_sha256: Optional[str],
    ) -> "ChildExecutionEvidenceDAO":
        """Return running evidence for this incarnation's fresh capture and context.

        Args:
            stdout_identity (Optional[StdoutCaptureIdentityDAO]): Identity of the
                freshly opened stdout capture, or None when capture is unavailable.
            spawn_context_sha256 (Optional[str]): Digest of the fresh context bytes.

        Returns:
            ChildExecutionEvidenceDAO: Running-phase evidence.
        """
        return self.model_validate(
            {
                **self.model_dump(),
                "phase": "running",
                "status": "running",
                "stdout_identity": stdout_identity,
                "spawn_context_sha256": spawn_context_sha256,
            }
        )

    def terminal(self, *, status: SubAgentStatus, status_sha256: str) -> "ChildExecutionEvidenceDAO":
        """Return terminal evidence bound to the exact status.json bytes.

        Args:
            status (SubAgentStatus): Terminal status of the registry winner.
            status_sha256 (str): Digest of the exact status.json bytes just written.

        Returns:
            ChildExecutionEvidenceDAO: Terminal-phase evidence retaining capture identity.
        """
        return self.model_validate(
            {**self.model_dump(), "phase": "terminal", "status": status, "status_sha256": status_sha256}
        )


class ExecutionIndexDAO(BaseModel):
    """Run-scoped projection of current fleet sessions to incarnations.

    Written as ``execution-index.v1.json`` beside fleet.json. A new reader accepts
    a child's sibling only when this index maps the session to the same
    execution_id, so a previous incarnation's sibling cannot authorize a newly
    pending fleet row. It is a regenerated projection, not an authority.

    Attributes:
        schema_version (Literal[1]): Closed index schema version.
        orchestrator_session_id (str): Parent session owning the fleet.
        run_id (str): Canonical UUID of the pool composition that wrote the index.
        executions (dict[str, str]): Child session id to current execution UUID.
        updated_at (str): UTC ISO-8601 write time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    orchestrator_session_id: str
    run_id: str
    executions: dict[str, str] = Field(default_factory=dict)
    updated_at: str

    @field_validator("orchestrator_session_id")
    @classmethod
    def _validate_orchestrator_session_id(cls, value: str) -> str:
        """Require a safe parent session path component."""
        return safe_identifier(value=value)

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, value: str) -> str:
        """Require a canonical run UUID."""
        return canonical_uuid(value=value)

    @field_validator("executions")
    @classmethod
    def _validate_executions(cls, value: dict[str, str]) -> dict[str, str]:
        """Require safe session keys and canonical execution UUID values."""
        for session_id, execution_id in value.items():
            safe_identifier(value=session_id)
            canonical_uuid(value=execution_id)
        return value


ChildAbortOutcome = Literal[
    "requested", "aborted", "already_terminal", "not_owned", "unavailable", "unresolved"
]
"""Closed child-abort outcomes; ``requested`` is admission only, all others settle."""


class _ChildControlIdentity(BaseModel):
    """Shared validators for child-control DAOs (structure only in T02)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("owner_session_id", "orchestrator_session_id", "session_id", check_fields=False)
    @classmethod
    def _validate_safe_identity(cls, value: str) -> str:
        """Require safe session path components."""
        return safe_identifier(value=value)

    @field_validator("request_id", "run_id", "execution_id", check_fields=False)
    @classmethod
    def _validate_uuid_identity(cls, value: str) -> str:
        """Require canonical UUID identities."""
        return canonical_uuid(value=value)


class ChildAbortRequestDAO(_ChildControlIdentity):
    """Typed request to abort one exact child incarnation.

    No PID, prompt or path is accepted. Admission, storage and execution belong
    to later tickets; this ticket defines the closed structure only.

    Attributes:
        schema_version (Literal[1]): Closed request schema version.
        request_id (str): Immutable request UUID.
        owner_session_id (str): TUI owner session that submits the request.
        orchestrator_session_id (str): Parent orchestrator owning the child.
        session_id (str): Target child session.
        run_id (str): Runner invocation that must still own the child.
        execution_id (str): Exact target incarnation.
    """

    schema_version: Literal[1] = 1
    request_id: str
    owner_session_id: str
    orchestrator_session_id: str
    session_id: str
    run_id: str
    execution_id: str


class ChildAbortOutcomeDAO(_ChildControlIdentity):
    """Fixed-message outcome (receipt) for one child-abort request.

    Attributes:
        request_id (str): Request this outcome settles or admits.
        session_id (str): Target child session.
        execution_id (str): Target incarnation.
        outcome (ChildAbortOutcome): Closed outcome literal.
        terminal_status (Optional[SubAgentStatus]): Canonical terminal status when known.
        safe_message (str): Fixed operator-facing message; never exception text.
    """

    request_id: str
    session_id: str
    execution_id: str
    outcome: ChildAbortOutcome
    terminal_status: Optional[SubAgentStatus] = None
    safe_message: str


class ChildControlCapabilityDAO(_ChildControlIdentity):
    """Runner-published evidence that one run accepts child-control requests.

    Attributes:
        schema_version (Literal[1]): Closed capability schema version.
        run_id (str): Runner invocation UUID; regenerated on every invocation.
        owner_session_id (str): Launch owner bound from workflow context.
        orchestrator_session_id (str): Parent orchestrator session.
        accepting (bool): True only while the runner's controller admits requests.
    """

    schema_version: Literal[1] = 1
    run_id: str
    owner_session_id: str
    orchestrator_session_id: str
    accepting: bool
