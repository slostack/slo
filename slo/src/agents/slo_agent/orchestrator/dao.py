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
    "SubAgentTaskDAO",
    "SubAgentTaskResolutionDAO",
    "SubAgentStatusDAO",
    "SubAgentResultDAO",
    "OrchestratorResultDAO",
]


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
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    session_id: str
    status: SubAgentStatus = "pending"
    last_text: Optional[str] = None
    prompt_preview: str = ""


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
