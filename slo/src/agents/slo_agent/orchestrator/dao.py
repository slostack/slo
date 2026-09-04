"""Domain DAOs for the Slo orchestrator / sub-agent system.

These are the shared vocabulary for all orchestrator modules. Import
from here; do not duplicate these types in other modules.

Sub-spec 01-sub-agents 01.b.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
