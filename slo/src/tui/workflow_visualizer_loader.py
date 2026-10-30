"""WorkflowVisualizerLoader — data-discovery service for workflow progress views.

Loads the parent orchestrator session and its children from persisted
canonical history and child capture files. Keeps all filesystem IO out of
the Textual widget tree so apps await results while blocking reads run off
the event loop.

Sub-spec 53.a.5. Extended in 54.a.4 to surface orchestrator and spawn
context files, enrich child summaries with prompt previews, and reconstruct
thinking/tool transcript entries from stdout.jsonl captures. Feature 94 a.3
adds bounded observation (``load_observation_group``,
``load_session_progress``) for the five-second session list and progress
modal: every read is contained below the history root, refuses symlinks and is
byte-bounded before decode, and old-shaped child files are trusted only through
matching versioned execution evidence (94 a.4).
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import os
import stat
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config.cfg import VISUALIZER_REFRESH_SECONDS as _CFG_VISUALIZER_REFRESH_SECONDS
from config.logger import log_warning
from config.timeout_resolver import positive_float_env
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.dao import (
    HistoryObservationWindowDAO,
    SessionHistoryEventDAO,
    SessionHistoryMetadataDAO,
)
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol
from src.agents.slo_agent.history.transcript import (
    ReplayEntryProjector,
    TranscriptEntryDAO,
)
from src.agents.slo_agent.orchestrator.context_reader import OrchestratorContextReader
from src.agents.slo_agent.orchestrator.context_dao import (
    OrchestratorContextDAO,
    SpawnContextDAO,
)
from src.agents.slo_agent.orchestrator.dao import (
    ChildExecutionEvidenceDAO,
    ExecutionIndexDAO,
    FleetSnapshotDAO,
    OrchestratorStatusDAO,
    SubAgentResultDAO,
    SubAgentStatusDAO,
    safe_identifier,
    status_for_lifecycle_kind,
)
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout
from src.agents.slo_agent.orchestrator.process import CHILD_INACTIVITY_TIMEOUT_SECONDS
from src.agents.slo_agent.orchestrator.task_preview import TaskPreview, TASK_SUMMARY_FALLBACK
from src.tui.jsonl_tail import JsonlTail
from src.tui.tree_export_format import TreeExportFormat
from src.tui.workflows.dao import (
    SessionProgressAvailability,
    SessionProgressSnapshotDAO,
    WorkflowSessionRowDAO,
)

__all__ = [
    "HeadlessWorkflowVisualizerConfigDAO",
    "ChildSessionSummaryDAO",
    "OrchestratorNodeDAO",
    "WorkflowDataDAO",
    "WorkflowVisualizerLoader",
]

_DEFAULT_REFRESH_SECONDS: float = _CFG_VISUALIZER_REFRESH_SECONDS
_HEARTBEAT_SECONDS: float = positive_float_env(
    primary_name="SLO_HEADLESS_HEARTBEAT_SECONDS",
    default=15.0,
)

_TERMINAL_EVENT_KINDS: frozenset[str] = frozenset({"run_completed", "run_aborted", "run_failed"})
_RUN_BOUNDARY_EVENT_KINDS: frozenset[str] = _TERMINAL_EVENT_KINDS | {"run_started"}
"""Canonical kinds that open or close a run; the newest one decides completion."""

OBSERVATION_MAX_JSON_BYTES: int = 2_097_152
"""Byte budget for each fleet/index/status/context/spawn JSON read before decode."""

OBSERVATION_MAX_CHILDREN: int = 2_000
"""Most child capture directories one observation lists; one more is unavailable."""

GROUP_UNAVAILABLE_NOTICE: str = "Workflow group unavailable; retrying on the next refresh."
GROUP_LIMIT_NOTICE: str = "Too many child sessions to observe."

PROGRESS_WAITING_NOTICE: str = "Waiting for this session's progress."
PROGRESS_UNAVAILABLE_NOTICE: str = "Progress unavailable; retrying."
PROGRESS_CHANGED_NOTICE: str = "Session execution changed; refreshing."
PROGRESS_OMITTED_NOTICE: str = "Earlier output omitted from this view."
PROGRESS_RESET_NOTICE: str = "Progress source restarted; showing new output."
LIVE_CAPTURE_UNAVAILABLE_NOTICE: str = "Live capture unavailable; showing session history."
SESSION_HISTORY_NOTICE: str = "Showing session history; it may include earlier runs."

_TERMINAL_ROW_STATUSES: frozenset[str] = frozenset({"completed", "failed", "aborted"})
"""Row statuses whose progress comes from terminal sources."""

_CAPTURE_VIEW_CACHE_LIMIT: int = 64
"""Most live capture views one loader retains (least recently observed evicted)."""

_ModelT = TypeVar("_ModelT", bound=BaseModel)


class HeadlessWorkflowVisualizerConfigDAO(BaseModel):
    """Configuration DAO for ``HeadlessWorkflowVisualizer``.

    Attributes:
        session_reference (str): Session id or unique name to inspect. Bounded
            observation treats it as the exact, already validated parent id.
        follow (bool): When ``True``, poll for live updates.
        refresh_seconds (float): Polling cadence in seconds.
        detail_format (TreeExportFormat): Initial right-pane transcript rendering
            mode. ``TEXTUAL`` (default) uses Rich colour styles; ``MARKDOWN`` uses
            markdown sigils; ``HTML`` uses HTML-comment role tags.
    """

    session_reference: str
    follow: bool = True
    refresh_seconds: float = _DEFAULT_REFRESH_SECONDS
    detail_format: TreeExportFormat = TreeExportFormat.TEXTUAL


class ChildSessionSummaryDAO(BaseModel):
    """Summary of one discovered child (sub-agent) session.

    Attributes:
        session_id (str): Child session identifier.
        task_id (Optional[str]): Pool task id from the spawning event.
        status (str): Latest known lifecycle status — ``"pending"``, ``"running"``,
            ``"completed"``, ``"failed"``, or ``"aborted"``.
        has_stdout_capture (bool): Whether a trusted stdout.jsonl capture exists.
        has_stderr_capture (bool): Whether a stderr.jsonl capture file exists.
        has_spawn_context (bool): Whether a trusted spawn_context.json was read.
        prompt_preview (str): ``TaskPreview`` label of ``task_text``; empty when no
            task text is available.
        task_text (str): Full task from trusted spawn context, else the registry
            preview, else empty. Transient; rendered literally.
        task_text_complete (bool): True only when ``task_text`` is the full task of
            the current (or legacy, identity-less) incarnation.
        execution_id (str): Current incarnation from the execution index; empty for
            legacy children.
        dispatch_id (str): Admitting dispatch from verified evidence; empty when
            unknown or legacy.
        execution_verified (bool): True when matching execution evidence supplied
            ``status`` for the current incarnation.
        status_sha256 (Optional[str]): Digest of the exact status.json bytes named
            by verified terminal evidence; None for legacy or non-terminal
            children. Transient and excluded from serialization.
    """

    session_id: str
    task_id: Optional[str] = None
    status: str = "running"
    has_stdout_capture: bool = False
    has_stderr_capture: bool = False
    has_spawn_context: bool = False
    prompt_preview: str = ""
    task_summary: str = Field(
        default="", description="Prepared literal work label; never original task text."
    )
    task_text: str = ""
    task_text_complete: bool = False
    execution_id: str = ""
    dispatch_id: str = ""
    execution_verified: bool = False
    status_sha256: Optional[str] = Field(default=None, exclude=True)
    pid: Optional[int] = None
    heartbeat_phase: Optional[str] = None
    last_stdout_at: Optional[float] = None
    liveness_state: Optional[str] = None
    exit_code: Optional[int] = None
    terminal_reason: Optional[str] = None
    terminated_by: Optional[str] = None

    @property
    def trusts_status_file(self) -> bool:
        """Whether status.json at this child's path belongs to its current incarnation."""
        return not self.execution_id or (self.execution_verified and self.status in _TERMINAL_ROW_STATUSES)

    def overlay_status(self, *, entry: SubAgentStatusDAO, result: Optional[SubAgentResultDAO]) -> str:
        """Choose the displayed status from verified evidence, a trusted result or the fleet.

        Args:
            entry (SubAgentStatusDAO): Matching fleet entry.
            result (Optional[SubAgentResultDAO]): Terminal result read only when trusted.

        Returns:
            str: Display status.
        """
        if self.execution_verified:
            return self.status
        return result.status if result is not None else entry.status


class OrchestratorNodeDAO(BaseModel):
    """First-class visualizer entry for the headless orchestrator.

    Attributes:
        session_id (str): Orchestrator session identifier.
        state (str): Self-reported workflow state, or ``unknown`` before 71.
        phase (str): Latest self-reported heartbeat phase.
        pid (Optional[int]): Self-reported operating-system process id.
        updated_at (Optional[str]): Self-report timestamp.
        has_stdout_capture (bool): Whether the session stdout capture exists.
        has_stderr_capture (bool): Whether the session stderr capture exists.
    """

    session_id: str
    state: str = "unknown"
    phase: str = "awaiting_provider_stream"
    pid: Optional[int] = None
    updated_at: Optional[str] = None
    has_stdout_capture: bool = False
    has_stderr_capture: bool = False


class WorkflowDataDAO(BaseModel):
    """Snapshot returned by ``load()`` and ``load_observation_group()``.

    Attributes:
        parent_session_id (str): Resolved canonical parent session id.
        parent_metadata (Optional[SessionHistoryMetadataDAO]): Persisted
            metadata; ``None`` when absent or not read (observation).
        parent_events (list[SessionHistoryEventDAO]): Canonical parent events in
            sequence order; a bounded suffix for observation.
        children (list[ChildSessionSummaryDAO]): Fleet entries in registration
            order, then event-discovered and sorted directory-only extras.
        is_complete (bool): ``True`` when a terminal event is present.
        orchestrator_context (Optional[OrchestratorContextDAO]): Loaded
            orchestrator invocation context; ``None`` when the capture file
            does not exist or cannot be parsed.
        orchestrator (Optional[OrchestratorNodeDAO]): Parent self-report node.
        fleet_snapshot (Optional[FleetSnapshotDAO]): Durable fleet evidence.
        availability (Literal["available", "unavailable"]): ``unavailable`` when
            membership could not be read without truncation; children are empty
            while parent events, completion and the orchestrator node remain.
        notice (Optional[str]): Fixed safe notice for an unavailable group.
        run_id (str): Pool composition run from the execution index; empty when
            unknown. Never inferred from timestamps.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    parent_session_id: str
    parent_metadata: Optional[SessionHistoryMetadataDAO] = None
    parent_events: list[SessionHistoryEventDAO] = Field(default_factory=list)
    children: list[ChildSessionSummaryDAO] = Field(default_factory=list)
    is_complete: bool = False
    orchestrator_context: Optional[OrchestratorContextDAO] = None
    orchestrator: Optional[OrchestratorNodeDAO] = None
    fleet_snapshot: Optional[FleetSnapshotDAO] = None
    availability: Literal["available", "unavailable"] = "available"
    notice: Optional[str] = None
    run_id: str = ""


class _ChildIncarnationDAO(BaseModel):
    """Which incarnation a child's old-shaped files may be trusted for.

    Attributes:
        execution_id (str): Current incarnation named by the execution index; empty
            for a legacy child without identity.
        evidence (Optional[ChildExecutionEvidenceDAO]): Verified sibling for exactly
            that incarnation; None when unverified or legacy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str = ""
    evidence: Optional[ChildExecutionEvidenceDAO] = None
    modern_identity_missing: bool = Field(
        default=False, description="Versioned child evidence survives without an exact index mapping."
    )

    @property
    def is_legacy(self) -> bool:
        """Whether the child predates execution identity."""
        return self.execution_id == "" and not self.modern_identity_missing

    @property
    def trusts_capture(self) -> bool:
        """Whether the stdout capture at the child path belongs to this incarnation."""
        return self.is_legacy or (self.evidence is not None and self.evidence.stdout_identity is not None)

    @property
    def confirms_pending_abort(self) -> bool:
        """Whether verified evidence shows an abort before the incarnation ever ran.

        Only terminal ``aborted`` evidence that never recorded a spawn context or a
        capture qualifies; a child that ran without opening its capture does not.
        """
        evidence: Optional[ChildExecutionEvidenceDAO] = self.evidence
        return (
            evidence is not None
            and evidence.phase == "terminal"
            and evidence.status == "aborted"
            and evidence.spawn_context_sha256 is None
            and evidence.stdout_identity is None
        )


_LEGACY_INCARNATION: _ChildIncarnationDAO = _ChildIncarnationDAO()


class _GroupSourcesDAO(BaseModel):
    """Bounded membership evidence read once per observation group.

    Attributes:
        fleet (Optional[FleetSnapshotDAO]): Fleet membership authority, if present.
        index (Optional[ExecutionIndexDAO]): Run execution index, if present.
        child_dir_names (tuple[str, ...]): Sorted safe child directory names.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fleet: Optional[FleetSnapshotDAO] = None
    index: Optional[ExecutionIndexDAO] = None
    child_dir_names: tuple[str, ...] = ()


class _ProgressSourceDAO(BaseModel):
    """The single source one progress read may use, decided before reading.

    Attributes:
        session_id (str): Observed session.
        identity (str): Execution id, else dispatch/run id; empty for legacy rows.
        dispatch_id (str): Dispatch or run identity for the snapshot.
        status (str): Display status from verified evidence or the row.
        mode (Literal["waiting", "unavailable", "live", "terminal"]): Which read applies.
        capture_path (Optional[Path]): Trusted capture path; None when untrusted.
        evidence (Optional[ChildExecutionEvidenceDAO]): Evidence re-checked after reads.
        task_text (str): Full task from matching context, else the row text.
        task_text_complete (bool): Whether ``task_text`` is the full task.
        pending_abort (bool): Verified abort before the incarnation ever ran.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    identity: str
    dispatch_id: str
    status: str
    mode: Literal["waiting", "unavailable", "live", "terminal"]
    capture_path: Optional[Path] = None
    evidence: Optional[ChildExecutionEvidenceDAO] = None
    task_text: str
    task_text_complete: bool
    pending_abort: bool = False


class _ProgressContentDAO(BaseModel):
    """Bounded content one source read produced, before snapshot assembly.

    Attributes:
        entries (tuple[TranscriptEntryDAO, ...]): Bounded public entries.
        revision (str): Content revision.
        source_generation (str): Source identity independent of appends.
        availability (SessionProgressAvailability): Readability of the read.
        notices (tuple[str, ...]): Fixed notices joined into the snapshot notice.
        final (bool): Whether this read completes a terminal source.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[TranscriptEntryDAO, ...] = ()
    revision: str = ""
    source_generation: str = ""
    availability: SessionProgressAvailability
    notices: tuple[str, ...] = ()
    final: bool = False


class WorkflowVisualizerLoader:
    """Data-discovery service for the workflow visualizer and progress modal.

    Resolves the parent session reference, loads its canonical events, and
    discovers child sessions from fleet membership, the parent history event
    log and the ``children/<session_id>/`` capture directories. One instance
    serves one parent; it caches live capture views between observations.
    """

    def __init__(
        self,
        *,
        config: HeadlessWorkflowVisualizerConfigDAO,
        store: Optional[SessionHistoryStoreProtocol] = None,
    ) -> None:
        """Bind the loader to its config and an optional history-store adapter.

        Args:
            config (HeadlessWorkflowVisualizerConfigDAO): Visualizer config.
            store (Optional[SessionHistoryStoreProtocol]): History adapter; the TUI
                always supplies its session adapter. ``None`` keeps the legacy CLI
                default store rooted at ``~/.slo``.
        """
        self._config: HeadlessWorkflowVisualizerConfigDAO = config
        self._store: SessionHistoryStoreProtocol = store or FilesystemSessionHistoryStore()
        self._reader: _ObservationReader = _ObservationReader(root=self._store.root)
        self._capture_views: OrderedDict[tuple[Path, str], _CaptureView] = OrderedDict()
        self._parent_session_id: Optional[str] = None

    async def load(self) -> WorkflowDataDAO:
        """Resolve the parent session and discover all child sessions.

        WHAT: Legacy full load for the external ``slo visualize`` list: resolves a
            name reference and reads the complete parent history; child discovery
            and file reads share the bounded observation path.
        WHO: Called by HeadlessWorkflowVisualizer for its first refresh only;
            later follow ticks use ``load_observation_group``.
        WHEN: Never from live polling (the TUI's five-second poll or the
            external viewer's follow ticks).

        Returns:
            WorkflowDataDAO: Full workflow snapshot with parent and children.

        Raises:
            ValueError: When the session reference cannot be resolved.
        """
        parent_session_id: str = await self._resolve_parent_session_id()
        self._parent_session_id = parent_session_id
        parent_metadata: Optional[SessionHistoryMetadataDAO] = await self._load_parent_metadata(
            session_id=parent_session_id
        )
        parent_events: list[SessionHistoryEventDAO] = await self._load_parent_events(
            session_id=parent_session_id,
        )
        group: WorkflowDataDAO = await asyncio.to_thread(
            self._assemble_group,
            parent_session_id=parent_session_id,
            parent_events=parent_events,
        )
        return group.model_copy(update={"parent_metadata": parent_metadata})

    async def load_observation_group(self) -> WorkflowDataDAO:
        """Discover the group for one bounded poll without full history or repair.

        WHAT: Reads the parent's canonical events only through the bounded
            observation window, then fleet/index/status/context JSON (2 MiB each)
            and at most 2,001 child directory names. Oversized or malformed
            membership evidence, or more than 2,000 children, returns an
            unavailable group with a fixed notice instead of truncated membership.
        WHO: Called by DetachedWorkflowAppService for each owned detached group.
        WHEN: On every coordinator refresh (immediate and five-second ticks).

        Returns:
            WorkflowDataDAO: Bounded group; ``availability`` reports trust.

        Raises:
            ValueError: When the configured parent id is not a safe identifier.
        """
        parent_session_id: str = self._observation_parent_id()
        window: HistoryObservationWindowDAO = await self._observe_history(session_id=parent_session_id)
        return await asyncio.to_thread(
            self._assemble_group,
            parent_session_id=parent_session_id,
            parent_events=list(window.events),
        )

    async def enrich_task_row(self, *, row: WorkflowSessionRowDAO) -> WorkflowSessionRowDAO:
        """Return ``row`` with the full task when its incarnation's context matches.

        WHAT: Reads only the child's verified execution evidence and bounded spawn
            context; never loads history or discovers children. Missing, invalid,
            pending or mismatched evidence returns the original row unchanged.
        WHO: Called by DetachedWorkflowAppService for attached registry rows.
        WHEN: During each session snapshot assembly.

        Args:
            row (WorkflowSessionRowDAO): Registry-authorized row of this parent.

        Returns:
            WorkflowSessionRowDAO: Enriched copy or the original row.

        Raises:
            ValueError: When the row belongs to another parent.
        """
        self._validate_member(row=row)
        if row.key.is_parent or not row.execution_id:
            return row
        context: Optional[SpawnContextDAO] = await asyncio.to_thread(self._row_context, row=row)
        if context is None:
            return row
        return row.model_copy(
            update={
                "task_text": context.prompt,
                "task_text_complete": True,
                "task_summary": (
                    row.task_summary
                    if row.task_summary and row.task_summary != TASK_SUMMARY_FALLBACK
                    else TaskPreview.project_summary(prompt_preview="", task_text=context.prompt)
                ),
            }
        )

    async def load_session_progress(self, *, row: WorkflowSessionRowDAO) -> SessionProgressSnapshotDAO:
        """Read bounded public progress for one member row from exactly one source.

        WHAT: Validates membership, then reads the live capture while running or
            canonical replay when terminal (matching terminal capture when history
            is absent); canonical history substitutes for a missing live capture
            with an explicit notice. Sources are alternatives, never concatenated.
            Modern child evidence is re-verified after the read; a changed
            incarnation discards the content as stale. Pending children return
            empty with their task preview. Read failures become an unavailable
            snapshot with a fixed notice. ``abort_target`` is always None here.
        WHO: Called by DetachedWorkflowAppService.load_session_progress and the
            external viewer's detail pane.
        WHEN: On progress modal open/refresh ticks and external viewer refreshes.

        Args:
            row (WorkflowSessionRowDAO): Authoritative row of this parent group.

        Returns:
            SessionProgressSnapshotDAO: At most 2,000 entries / 2 MiB public text.

        Raises:
            ValueError: When the row belongs to another parent.
        """
        self._validate_member(row=row)
        try:
            source: _ProgressSourceDAO = await asyncio.to_thread(self._progress_source, row=row)
            content: _ProgressContentDAO = await self._read_progress(source=source)
        except (OSError, ValueError, RecursionError):
            log_warning(msg="progress_read_unavailable", session_id=row.key.session_id)
            return self._snapshot(
                row=row, source=self._row_source(row=row, mode="live"), content=_UNAVAILABLE
            )
        return self._snapshot(row=row, source=source, content=content)

    def load_orchestrator_context(
        self,
        *,
        parent_session_id: str,
    ) -> Optional[OrchestratorContextDAO]:
        """Load the orchestrator invocation context from disk.

        Reads ``orchestrator_context.json`` from the parent session directory
        through the bounded no-follow reader. Degrades gracefully on missing,
        oversized or unparseable files.

        Args:
            parent_session_id (str): Orchestrator (parent) session id.

        Returns:
            Optional[OrchestratorContextDAO]: Parsed DAO, or ``None`` when the
                file does not exist or cannot be read safely.
        """
        return OrchestratorContextReader.load(
            history_root=self._store.root, parent_session_id=parent_session_id
        )

    def load_spawn_context(
        self,
        *,
        parent_session_id: str,
        child_session_id: str,
    ) -> Optional[SpawnContextDAO]:
        """Load the spawn invocation context for one child session.

        Reads ``spawn_context.json`` from the child capture directory through the
        bounded no-follow reader. Degrades gracefully on missing, oversized or
        unparseable files. Does not check incarnation; progress and summaries
        use ``_matching_context`` for modern children.

        Args:
            parent_session_id (str): Orchestrator session id.
            child_session_id (str): Child session id.

        Returns:
            Optional[SpawnContextDAO]: Parsed DAO, or ``None`` when the
                file does not exist or cannot be read safely.
        """
        path: Path = self._child_capture_path(
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
            filename="spawn_context.json",
        )
        return self._read_optional_model(path=path, model=SpawnContextDAO)

    def load_child_stderr_lines(
        self,
        *,
        parent_session_id: str,
        child_session_id: str,
    ) -> list[str]:
        """Return captured stderr lines for one child session.

        Args:
            parent_session_id (str): Parent session id.
            child_session_id (str): Child session id.

        Returns:
            list[str]: Decoded stderr lines; empty when no capture exists.
        """
        stderr_path: Path = self._child_capture_path(
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
            filename="stderr.jsonl",
        )
        if not stderr_path.exists():
            return []
        try:
            return stderr_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []

    def load_node_stderr_lines(
        self,
        *,
        parent_session_id: str,
        session_id: str,
    ) -> list[str]:
        """Return stderr capture lines for a child or its orchestrator.

        Args:
            parent_session_id (str): Orchestrator session that owns child captures.
            session_id (str): Selected child or orchestrator session id.

        Returns:
            list[str]: Decoded stderr lines, or an empty list when absent or unreadable.
        """
        path: Path = self._stderr_capture_path(
            parent_session_id=parent_session_id,
            session_id=session_id,
        )
        if not path.exists():
            return []
        try:
            return path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []

    def _stderr_capture_path(self, *, parent_session_id: str, session_id: str) -> Path:
        """Resolve the selected node's stderr capture path.

        Args:
            parent_session_id (str): Orchestrator parent session id.
            session_id (str): Selected child or orchestrator session id.

        Returns:
            Path: Child stderr JSONL path or orchestrator stderr log path.
        """
        if session_id == parent_session_id:
            return OrchestrationLayout.capture_path(
                history_root=self._store.root,
                session_id=session_id,
                name="stderr.log",
            )
        return self._child_capture_path(
            parent_session_id=parent_session_id,
            child_session_id=session_id,
            filename="stderr.jsonl",
        )

    # ── membership and incarnation ───────────────────────────────────────────

    def _observation_parent_id(self) -> str:
        """Return the exact parent id observation reads; never resolves a name.

        Returns:
            str: The id resolved by a prior legacy load, else the configured id.

        Raises:
            ValueError: When the id is not a safe single path component.
        """
        return safe_identifier(value=self._parent_session_id or self._config.session_reference)

    def _validate_member(self, *, row: WorkflowSessionRowDAO) -> None:
        """Refuse rows that do not belong to this loader's parent group.

        Args:
            row (WorkflowSessionRowDAO): Row supplied by the owner-scoped service.

        Raises:
            ValueError: When the row names another parent or an unsafe session id.
        """
        if row.key.orchestrator_session_id != self._observation_parent_id():
            raise ValueError("row is not a member of this workflow group")
        safe_identifier(value=row.key.session_id)

    def _resolve_incarnation(
        self,
        *,
        parent_session_id: str,
        child_session_id: str,
        execution_id: str,
        index: Optional[ExecutionIndexDAO],
    ) -> _ChildIncarnationDAO:
        """Bind a child's old-shaped files to the given current incarnation.

        Verification uses the run index the caller already decoded within the
        2 MiB observation budget, so a group decodes its index once, not per child.

        Args:
            parent_session_id (str): Parent owning the child.
            child_session_id (str): Child whose evidence is verified.
            execution_id (str): Current incarnation; empty for a legacy child.
            index (Optional[ExecutionIndexDAO]): Decoded run index; None leaves a
                modern child unverified.

        Returns:
            _ChildIncarnationDAO: Legacy, unverified or verified incarnation.
        """
        if not execution_id:
            return _ChildIncarnationDAO(
                modern_identity_missing=self._has_modern_sibling(
                    parent_session_id=parent_session_id, child_session_id=child_session_id
                )
            )
        if index is None or child_session_id not in index.executions:
            return _ChildIncarnationDAO(execution_id=execution_id, modern_identity_missing=True)
        evidence: Optional[ChildExecutionEvidenceDAO] = FleetStore.verify_execution(
            history_root=self._store.root,
            orchestrator_session_id=parent_session_id,
            child_session_id=child_session_id,
            index=index,
        )
        matching: bool = evidence is not None and evidence.execution_id == execution_id
        return _ChildIncarnationDAO(execution_id=execution_id, evidence=evidence if matching else None)

    def _has_modern_sibling(self, *, parent_session_id: str, child_session_id: str) -> bool:
        """Classify surviving versioned evidence without granting it execution authority.

        Args:
            parent_session_id: Parent owning the capture directory.
            child_session_id: Child whose legacy eligibility is being checked.

        Returns:
            bool: Whether the versioned sibling exists, including a dangling link.
        """
        path = self._child_capture_path(
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
            filename="execution.v1.json",
        )
        return path.exists() or path.is_symlink()

    def _resolve_row_incarnation(self, *, row: WorkflowSessionRowDAO) -> _ChildIncarnationDAO:
        """Resolve one child row's incarnation against a fresh bounded index read.

        Args:
            row (WorkflowSessionRowDAO): Validated child row carrying its execution id.

        Returns:
            _ChildIncarnationDAO: Legacy, unverified or verified incarnation.
        """
        return self._resolve_current_incarnation(
            parent_session_id=row.key.orchestrator_session_id,
            child_session_id=row.key.session_id,
            execution_id=row.execution_id,
        )

    def _resolve_current_incarnation(
        self, *, parent_session_id: str, child_session_id: str, execution_id: str
    ) -> _ChildIncarnationDAO:
        """Resolve one child's incarnation, reading the run index once for it.

        Args:
            parent_session_id (str): Parent owning the child.
            child_session_id (str): Child whose evidence is verified.
            execution_id (str): Expected incarnation; empty for a legacy child.

        Returns:
            _ChildIncarnationDAO: Legacy, unverified or verified incarnation.
        """
        return self._resolve_incarnation(
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
            execution_id=execution_id,
            index=self._read_index(parent_session_id=parent_session_id) if execution_id else None,
        )

    def _read_index(self, *, parent_session_id: str) -> Optional[ExecutionIndexDAO]:
        """Read the run execution index within the 2 MiB budget; None when unusable.

        Args:
            parent_session_id (str): Parent owning the index.

        Returns:
            Optional[ExecutionIndexDAO]: Decoded index, or None when absent,
                refused, oversized or malformed.
        """
        return self._read_optional_model(
            path=OrchestrationLayout.execution_index_path(
                history_root=self._store.root, orchestrator_session_id=parent_session_id
            ),
            model=ExecutionIndexDAO,
        )

    def _matching_context(
        self, *, parent_session_id: str, child_session_id: str, incarnation: _ChildIncarnationDAO
    ) -> Optional[SpawnContextDAO]:
        """Return spawn context only when its exact bytes belong to the incarnation.

        Legacy children read the context as-is. Modern children require verified
        non-pending evidence and a SHA-256 match of the bounded bytes actually
        decoded, so a context rewritten after verification is never trusted.

        Args:
            parent_session_id (str): Parent owning the child.
            child_session_id (str): Child whose context is read.
            incarnation (_ChildIncarnationDAO): Trust decision for the child.

        Returns:
            Optional[SpawnContextDAO]: Trusted context, or None.
        """
        if incarnation.is_legacy:
            return self.load_spawn_context(
                parent_session_id=parent_session_id, child_session_id=child_session_id
            )
        evidence: Optional[ChildExecutionEvidenceDAO] = incarnation.evidence
        if evidence is None or evidence.phase == "pending" or evidence.spawn_context_sha256 is None:
            return None
        data: Optional[bytes] = self._read_optional_bytes(
            path=self._child_capture_path(
                parent_session_id=parent_session_id,
                child_session_id=child_session_id,
                filename="spawn_context.json",
            )
        )
        if data is None or hashlib.sha256(data).hexdigest() != evidence.spawn_context_sha256:
            return None
        return self._decode_optional(data=data, model=SpawnContextDAO)

    def _row_context(self, *, row: WorkflowSessionRowDAO) -> Optional[SpawnContextDAO]:
        """Return trusted spawn context for one modern child row.

        Args:
            row (WorkflowSessionRowDAO): Child row carrying its execution id.

        Returns:
            Optional[SpawnContextDAO]: Matching context, or None.
        """
        incarnation: _ChildIncarnationDAO = self._resolve_row_incarnation(row=row)
        if incarnation.evidence is None:
            return None
        return self._matching_context(
            parent_session_id=row.key.orchestrator_session_id,
            child_session_id=row.key.session_id,
            incarnation=incarnation,
        )

    # ── progress sources ─────────────────────────────────────────────────────

    def _progress_source(self, *, row: WorkflowSessionRowDAO) -> _ProgressSourceDAO:
        """Decide which single source this row's progress may come from.

        Args:
            row (WorkflowSessionRowDAO): Validated member row.

        Returns:
            _ProgressSourceDAO: Waiting, live or terminal source.
        """
        if row.key.is_parent:
            return self._row_source(row=row, mode=self._mode_for(status=row.status)).model_copy(
                update={"capture_path": self._parent_capture_path(session_id=row.key.session_id)}
            )
        incarnation: _ChildIncarnationDAO = self._resolve_row_incarnation(row=row)
        if incarnation.modern_identity_missing:
            return self._row_source(row=row, mode="unavailable")
        if self._awaits_incarnation(incarnation=incarnation):
            return self._row_source(row=row, mode="waiting")
        return self._child_source(row=row, incarnation=incarnation)

    @staticmethod
    def _awaits_incarnation(*, incarnation: _ChildIncarnationDAO) -> bool:
        """Return whether a modern child has no trusted running/terminal evidence yet.

        Args:
            incarnation (_ChildIncarnationDAO): Trust decision for the child.

        Returns:
            bool: True when progress must wait for the current incarnation.
        """
        if incarnation.is_legacy:
            return False
        return incarnation.evidence is None or incarnation.evidence.phase == "pending"

    def _child_source(
        self, *, row: WorkflowSessionRowDAO, incarnation: _ChildIncarnationDAO
    ) -> _ProgressSourceDAO:
        """Build a live or terminal child source from trusted evidence and context.

        Args:
            row (WorkflowSessionRowDAO): Validated child row.
            incarnation (_ChildIncarnationDAO): Legacy or verified incarnation.

        Returns:
            _ProgressSourceDAO: Source whose capture path is set only when trusted.
        """
        evidence: Optional[ChildExecutionEvidenceDAO] = incarnation.evidence
        context: Optional[SpawnContextDAO] = self._matching_context(
            parent_session_id=row.key.orchestrator_session_id,
            child_session_id=row.key.session_id,
            incarnation=incarnation,
        )
        status: str = evidence.status if evidence is not None else row.status
        capture_path: Optional[Path] = (
            self._child_capture_path(
                parent_session_id=row.key.orchestrator_session_id,
                child_session_id=row.key.session_id,
                filename="stdout.jsonl",
            )
            if incarnation.trusts_capture
            else None
        )
        return _ProgressSourceDAO(
            session_id=row.key.session_id,
            identity=row.execution_id or row.dispatch_id,
            dispatch_id=(
                (evidence.dispatch_id or row.dispatch_id) if evidence is not None else row.dispatch_id
            ),
            status=status,
            mode=self._mode_for(status=status),
            capture_path=capture_path,
            evidence=evidence,
            task_text=context.prompt if context is not None else row.task_text,
            task_text_complete=context is not None or row.task_text_complete,
            pending_abort=incarnation.confirms_pending_abort,
        )

    @staticmethod
    def _row_source(
        *, row: WorkflowSessionRowDAO, mode: Literal["waiting", "unavailable", "live", "terminal"]
    ) -> _ProgressSourceDAO:
        """Build a source that carries only the row's own identity and task text.

        Args:
            row (WorkflowSessionRowDAO): Validated member row.
            mode (Literal["waiting", "unavailable", "live", "terminal"]): Read to apply.

        Returns:
            _ProgressSourceDAO: Source without capture or evidence.
        """
        return _ProgressSourceDAO(
            session_id=row.key.session_id,
            identity=row.execution_id or row.dispatch_id,
            dispatch_id=row.dispatch_id,
            status=row.status,
            mode=mode,
            task_text=row.task_text,
            task_text_complete=row.task_text_complete,
        )

    @staticmethod
    def _mode_for(*, status: str) -> Literal["live", "terminal"]:
        """Map a display status to its progress read.

        Args:
            status (str): Display status.

        Returns:
            Literal["live", "terminal"]: Terminal for completed/failed/aborted.
        """
        return "terminal" if status in _TERMINAL_ROW_STATUSES else "live"

    def _parent_capture_path(self, *, session_id: str) -> Path:
        """Return the orchestrator's own stdout capture path.

        Args:
            session_id (str): Parent session id.

        Returns:
            Path: ``<root>/<session>/stdout.jsonl``.
        """
        return OrchestrationLayout.capture_path(
            history_root=self._store.root, session_id=session_id, name="stdout.jsonl"
        )

    async def _read_progress(self, *, source: _ProgressSourceDAO) -> _ProgressContentDAO:
        """Dispatch to the waiting, live or terminal read.

        Args:
            source (_ProgressSourceDAO): Decided source.

        Returns:
            _ProgressContentDAO: Bounded content, possibly stale or unavailable.
        """
        if source.mode == "unavailable":
            return _ProgressContentDAO(availability="unavailable", notices=(PROGRESS_WAITING_NOTICE,))
        if source.mode == "waiting":
            return _ProgressContentDAO(availability="empty", notices=(PROGRESS_WAITING_NOTICE,))
        if source.mode == "live":
            return await self._load_live_progress(source=source)
        return await self._load_terminal_progress(source=source)

    async def _load_live_progress(self, *, source: _ProgressSourceDAO) -> _ProgressContentDAO:
        """Read the live capture, falling back to labelled canonical history.

        Args:
            source (_ProgressSourceDAO): Live source.

        Returns:
            _ProgressContentDAO: Capture content, labelled canonical fallback,
                stale on incarnation change, or unavailable.
        """
        observation: Optional[_CaptureObservationDAO] = await self._observe_capture(source=source)
        if observation is None:
            return await self._live_fallback(source=source)
        content: _ProgressContentDAO = self._capture_content(
            source=source, observation=observation, final=False
        )
        return await self._accept_if_current(source=source, content=content)

    async def _live_fallback(self, *, source: _ProgressSourceDAO) -> _ProgressContentDAO:
        """Substitute labelled canonical history when no live capture can be read.

        Args:
            source (_ProgressSourceDAO): Live source without a readable capture.

        Returns:
            _ProgressContentDAO: Non-final canonical content, or unavailable.
        """
        fallback: _ProgressContentDAO = await self._canonical_content(source=source)
        if not fallback.entries:
            return _UNAVAILABLE
        notices: tuple[str, ...] = (LIVE_CAPTURE_UNAVAILABLE_NOTICE, *fallback.notices[1:])
        return await self._accept_if_current(
            source=source, content=fallback.model_copy(update={"final": False, "notices": notices})
        )

    async def _load_terminal_progress(self, *, source: _ProgressSourceDAO) -> _ProgressContentDAO:
        """Prefer canonical replay; else a confirmed pending abort or the matching capture.

        Args:
            source (_ProgressSourceDAO): Terminal source.

        Returns:
            _ProgressContentDAO: Final only with a stable terminal record.
        """
        canonical: _ProgressContentDAO = await self._canonical_content(source=source)
        if canonical.entries:
            return await self._accept_if_current(source=source, content=canonical)
        if source.pending_abort:
            return await self._accept_if_current(
                source=source, content=_ProgressContentDAO(availability="empty", final=True)
            )
        observation: Optional[_CaptureObservationDAO] = await self._observe_capture(source=source)
        if observation is None:
            return _UNAVAILABLE
        content: _ProgressContentDAO = self._capture_content(
            source=source, observation=observation, final=observation.terminal_seen
        )
        return await self._accept_if_current(source=source, content=content)

    async def _observe_capture(self, *, source: _ProgressSourceDAO) -> Optional[_CaptureObservationDAO]:
        """Read the source's trusted capture through its cached view.

        Args:
            source (_ProgressSourceDAO): Source with an optional trusted capture.

        Returns:
            Optional[_CaptureObservationDAO]: Observation, or None when no trusted
                regular capture could be read.
        """
        if source.capture_path is None:
            return None
        view: _CaptureView = self._capture_view(path=source.capture_path, identity=source.identity)
        observation: _CaptureObservationDAO = await asyncio.to_thread(view.observe)
        return observation if observation.available else None

    def _capture_view(self, *, path: Path, identity: str) -> _CaptureView:
        """Return the cached view for one capture incarnation, bounding the cache.

        Args:
            path (Path): Contained capture path.
            identity (str): Execution or run identity owning the capture.

        Returns:
            _CaptureView: Existing or new view; least recently used views beyond 64
                are released.
        """
        self._reader.require_contained(path=path)
        key: tuple[Path, str] = (path, identity)
        view: _CaptureView = self._capture_views.get(key) or _CaptureView(path=path)
        self._capture_views[key] = view
        self._capture_views.move_to_end(key)
        while len(self._capture_views) > _CAPTURE_VIEW_CACHE_LIMIT:
            self._capture_views.popitem(last=False)
        return view

    @staticmethod
    def _capture_content(
        *, source: _ProgressSourceDAO, observation: _CaptureObservationDAO, final: bool
    ) -> _ProgressContentDAO:
        """Translate a capture observation into progress content.

        Args:
            source (_ProgressSourceDAO): Source that was read.
            observation (_CaptureObservationDAO): Available capture observation.
            final (bool): Whether this read completes a terminal source.

        Returns:
            _ProgressContentDAO: Capture-kind content with omission/reset notices.
        """
        notices: tuple[str, ...] = tuple(
            notice
            for notice, applies in (
                (PROGRESS_RESET_NOTICE, observation.reset),
                (PROGRESS_OMITTED_NOTICE, observation.omitted),
            )
            if applies
        )
        return _ProgressContentDAO(
            entries=observation.entries,
            revision=f"capture:{source.identity}:{observation.revision}",
            source_generation=f"capture:{source.identity}:{observation.generation}",
            availability="available" if observation.entries else "empty",
            notices=notices,
            final=final,
        )

    async def _canonical_content(self, *, source: _ProgressSourceDAO) -> _ProgressContentDAO:
        """Project one bounded canonical window of the source session.

        Args:
            source (_ProgressSourceDAO): Source whose session history is read.

        Returns:
            _ProgressContentDAO: Canonical content (empty entries when the window
                is empty or unavailable); final only when the newest run boundary
                is a run terminal record, so an earlier run's terminal in a reused
                or resumed session never completes the read.
        """
        window: HistoryObservationWindowDAO = await self._observe_history(session_id=source.session_id)
        projected: list[TranscriptEntryDAO] = ReplayEntryProjector.build_entries(events=list(window.events))
        entries, dropped = _bounded_entries(entries=projected)
        notices: list[str] = [SESSION_HISTORY_NOTICE]
        if window.truncated or dropped:
            notices.append(PROGRESS_OMITTED_NOTICE)
        device_inode: str = ":".join(window.revision.split(":")[:2])
        return _ProgressContentDAO(
            entries=entries,
            revision=f"canonical:{source.identity}:{window.revision}",
            source_generation=f"canonical:{source.identity}:{device_inode}",
            availability="available" if entries else "empty",
            notices=tuple(notices),
            final=_latest_run_closed(events=window.events),
        )

    async def _accept_if_current(
        self, *, source: _ProgressSourceDAO, content: _ProgressContentDAO
    ) -> _ProgressContentDAO:
        """Discard content read across an incarnation change of a modern child.

        Args:
            source (_ProgressSourceDAO): Source decided before the read.
            content (_ProgressContentDAO): Content read from it.

        Returns:
            _ProgressContentDAO: The content, or stale with no entries.
        """
        if source.evidence is None:
            return content
        current: _ChildIncarnationDAO = await asyncio.to_thread(
            self._resolve_current_incarnation,
            parent_session_id=self._observation_parent_id(),
            child_session_id=source.session_id,
            execution_id=source.evidence.execution_id,
        )
        if current.evidence == source.evidence:
            return content
        return _ProgressContentDAO(availability="stale", notices=(PROGRESS_CHANGED_NOTICE,))

    @staticmethod
    def _snapshot(
        *, row: WorkflowSessionRowDAO, source: _ProgressSourceDAO, content: _ProgressContentDAO
    ) -> SessionProgressSnapshotDAO:
        """Assemble the public snapshot; read-only consumers get no abort target.

        Args:
            row (WorkflowSessionRowDAO): Requested row.
            source (_ProgressSourceDAO): Decided source.
            content (_ProgressContentDAO): Bounded content read.

        Returns:
            SessionProgressSnapshotDAO: Snapshot for the coordinator and viewers.
        """
        return SessionProgressSnapshotDAO(
            key=row.key,
            execution_id=row.execution_id,
            dispatch_id=source.dispatch_id,
            entries=content.entries,
            revision=content.revision,
            source_generation=content.source_generation,
            availability=content.availability,
            observed_at=datetime.now(tz=timezone.utc).isoformat(),
            notice=" ".join(content.notices) or None,
            task_text=source.task_text,
            task_text_complete=source.task_text_complete,
            status=source.status,
            final_read_complete=content.final and content.availability in {"available", "empty"},
        )

    # ── bounded group assembly ───────────────────────────────────────────────

    async def _observe_history(self, *, session_id: str) -> HistoryObservationWindowDAO:
        """Read one bounded canonical window, translating read failures to unavailable.

        Args:
            session_id (str): Session whose active history is observed.

        Returns:
            HistoryObservationWindowDAO: Bounded window, or unavailable on failure.
        """
        try:
            return await self._store.load_observation_window(session_id=session_id)
        except (OSError, ValueError, RecursionError):
            log_warning(msg="progress_history_unavailable", session_id=session_id)
            return HistoryObservationWindowDAO.unavailable()

    def _assemble_group(
        self, *, parent_session_id: str, parent_events: list[SessionHistoryEventDAO]
    ) -> WorkflowDataDAO:
        """Build the group from bounded sources; refuse truncated membership.

        Args:
            parent_session_id (str): Exact parent id.
            parent_events (list[SessionHistoryEventDAO]): Parent events already read.

        Returns:
            WorkflowDataDAO: Available group, or an unavailable group with notice
                that still carries the parent's events, completion and node.
        """
        parent: WorkflowDataDAO = WorkflowDataDAO(
            parent_session_id=parent_session_id,
            parent_events=parent_events,
            is_complete=self._detect_workflow_complete(events=parent_events),
            orchestrator_context=self.load_orchestrator_context(parent_session_id=parent_session_id),
            orchestrator=self._build_orchestrator_node(parent_session_id=parent_session_id),
        )
        try:
            sources: _GroupSourcesDAO = self._read_group_sources(parent_session_id=parent_session_id)
        except _ObservationLimitError:
            return parent.model_copy(update={"availability": "unavailable", "notice": GROUP_LIMIT_NOTICE})
        except (OSError, ValueError):
            return parent.model_copy(
                update={"availability": "unavailable", "notice": GROUP_UNAVAILABLE_NOTICE}
            )
        return parent.model_copy(
            update={
                "children": self._observed_children(
                    parent_session_id=parent_session_id, parent_events=parent_events, sources=sources
                ),
                "fleet_snapshot": sources.fleet,
                "run_id": sources.index.run_id if sources.index is not None else "",
            }
        )

    def _read_group_sources(self, *, parent_session_id: str) -> _GroupSourcesDAO:
        """Read fleet, execution index and child names within their budgets.

        Args:
            parent_session_id (str): Exact parent id.

        Returns:
            _GroupSourcesDAO: Decoded membership evidence.

        Raises:
            _ObservationLimitError: More than 2,000 child directory entries.
            OSError: Refused or unreadable evidence.
            ValueError: Escaped, oversized or malformed evidence.
        """
        root: Path = self._store.root
        return _GroupSourcesDAO(
            fleet=self._reader.read_model(
                path=OrchestrationLayout.fleet_path(
                    history_root=root, orchestrator_session_id=parent_session_id
                ),
                model=FleetSnapshotDAO,
            ),
            index=self._reader.read_model(
                path=OrchestrationLayout.execution_index_path(
                    history_root=root, orchestrator_session_id=parent_session_id
                ),
                model=ExecutionIndexDAO,
            ),
            child_dir_names=self._reader.child_names(
                directory=OrchestrationLayout.children_dir(
                    history_root=root, parent_session_id=parent_session_id
                )
            ),
        )

    def _observed_children(
        self,
        *,
        parent_session_id: str,
        parent_events: list[SessionHistoryEventDAO],
        sources: _GroupSourcesDAO,
    ) -> list[ChildSessionSummaryDAO]:
        """Order children by fleet registration, then event and directory extras.

        Args:
            parent_session_id (str): Exact parent id.
            parent_events (list[SessionHistoryEventDAO]): Parent events read.
            sources (_GroupSourcesDAO): Bounded membership evidence.

        Returns:
            list[ChildSessionSummaryDAO]: Identity-checked summaries.
        """
        from_events: list[ChildSessionSummaryDAO] = self._discover_children_from_events(
            parent_session_id=parent_session_id, parent_events=parent_events, index=sources.index
        )
        event_ids: set[str] = {child.session_id for child in from_events}
        discovered: list[ChildSessionSummaryDAO] = self._merge_child_discoveries(
            from_events=from_events,
            from_dirs=[
                self._build_child_summary(
                    child_session_id=name,
                    task_id=None,
                    parent_session_id=parent_session_id,
                    status="running",
                    index=sources.index,
                )
                for name in sources.child_dir_names
                if name not in event_ids
            ],
        )
        fleet_entries: dict[str, SubAgentStatusDAO] = (
            {
                entry.session_id: entry.model_copy(
                    update={
                        "execution_id": (
                            sources.index.executions.get(entry.session_id, "") if sources.index else ""
                        )
                    }
                )
                for entry in sources.fleet.entries
            }
            if sources.fleet
            else {}
        )
        by_id: dict[str, ChildSessionSummaryDAO] = {child.session_id: child for child in discovered}
        ordered: list[ChildSessionSummaryDAO] = [
            by_id.get(session_id)
            or self._build_child_summary(
                child_session_id=session_id,
                task_id=None,
                parent_session_id=parent_session_id,
                status="running",
                index=sources.index,
            )
            for session_id in fleet_entries
        ]
        ordered.extend(child for child in discovered if child.session_id not in fleet_entries)
        return [
            self._overlay_fleet(
                child=child,
                entry=fleet_entries.get(child.session_id),
                parent_session_id=parent_session_id,
                admit_summary=self._summary_fleet_is_current(
                    sources=sources, parent_session_id=parent_session_id, child_session_id=child.session_id
                ),
            )
            for child in ordered
        ]

    def _summary_fleet_is_current(
        self, *, sources: _GroupSourcesDAO, parent_session_id: str, child_session_id: str
    ) -> bool:
        """Refuse old labels during index-first publication or loss of modern identity.

        Args:
            sources: Bounded fleet and index from this observation.
            parent_session_id: Owning parent.
            child_session_id: Child whose label would be admitted.

        Returns:
            bool: Whether the fleet can supply this child's label.
        """
        if sources.index is None or child_session_id not in sources.index.executions:
            return not self._has_modern_sibling(
                parent_session_id=parent_session_id, child_session_id=child_session_id
            )
        if sources.fleet is None:
            return False
        return sources.fleet.updated_at >= sources.index.updated_at

    def _overlay_fleet(
        self,
        *,
        child: ChildSessionSummaryDAO,
        entry: Optional[SubAgentStatusDAO],
        parent_session_id: str,
        admit_summary: bool = True,
    ) -> ChildSessionSummaryDAO:
        """Merge matching fleet and terminal status evidence into one child summary.

        Modern children keep the status their verified evidence supplied and read
        status.json only when that evidence is terminal; unverified modern children
        use the fleet status. A missing full task falls back to the registry preview.

        Args:
            child (ChildSessionSummaryDAO): Summary produced by child discovery.
            entry (Optional[SubAgentStatusDAO]): This child's fleet entry, if any.
            parent_session_id (str): Parent owning the child's status file.
            admit_summary (bool): Whether this observation binds the fleet label to its index.

        Returns:
            ChildSessionSummaryDAO: Original summary without a matching entry, or
                a summary enriched with fleet and terminal fields.
        """
        if entry is None:
            return child
        result: Optional[SubAgentResultDAO] = (
            self._load_child_terminal_result(
                parent_session_id=parent_session_id,
                child_session_id=child.session_id,
                expected_sha256=child.status_sha256,
            )
            if child.trusts_status_file
            else None
        )
        return child.model_copy(
            update={
                "status": child.overlay_status(entry=entry, result=result),
                "pid": entry.pid,
                "heartbeat_phase": entry.heartbeat_phase,
                "last_stdout_at": entry.last_stdout_at,
                "liveness_state": entry.liveness(
                    now_seconds=time.monotonic(),
                    heartbeat_seconds=_HEARTBEAT_SECONDS,
                    inactivity_seconds=CHILD_INACTIVITY_TIMEOUT_SECONDS,
                ),
                "exit_code": result.exit_code if result is not None else entry.exit_code,
                "terminal_reason": entry.terminal_reason,
                "terminated_by": entry.terminated_by,
                **(self._registry_preview(child=child, entry=entry) if admit_summary else {}),
            }
        )

    @staticmethod
    def _registry_preview(*, child: ChildSessionSummaryDAO, entry: SubAgentStatusDAO) -> dict[str, object]:
        """Supply the registry preview only when no full task text is known.

        Args:
            child (ChildSessionSummaryDAO): Discovered summary.
            entry (SubAgentStatusDAO): Matching fleet entry.

        Returns:
            dict[str, object]: Task-text update fields, empty when not needed.
        """
        if child.execution_id != entry.execution_id:
            return {}
        summary = TaskPreview.project_summary(
            prompt_preview=entry.prompt_preview,
            task_text=child.task_text if child.task_text_complete else None,
        )
        if child.task_text or not entry.prompt_preview:
            return {"task_summary": summary}
        return {
            "task_summary": summary,
            "task_text": entry.prompt_preview,
            "task_text_complete": False,
            "prompt_preview": TaskPreview.build(task_text=entry.prompt_preview),
        }

    def _load_child_terminal_result(
        self,
        *,
        parent_session_id: str,
        child_session_id: str,
        expected_sha256: Optional[str],
    ) -> Optional[SubAgentResultDAO]:
        """Load the parent-written terminal result for one child when available.

        Legacy children read status.json as-is. Verified terminal children decode
        only bytes whose SHA-256 matches their evidence, so a file rewritten after
        verification is never trusted.

        Args:
            parent_session_id (str): Orchestrator session that owns the child.
            child_session_id (str): Terminal child session identifier.
            expected_sha256 (Optional[str]): Evidence digest of status.json; None
                for a legacy child.

        Returns:
            Optional[SubAgentResultDAO]: Parsed status result, or ``None`` when
                absent, malformed or not the bytes the evidence names.
        """
        data: Optional[bytes] = self._read_optional_bytes(
            path=OrchestrationLayout.child_status_path(
                history_root=self._store.root,
                parent_session_id=parent_session_id,
                child_session_id=child_session_id,
            )
        )
        if data is None or (
            expected_sha256 is not None and hashlib.sha256(data).hexdigest() != expected_sha256
        ):
            return None
        return self._decode_optional(data=data, model=SubAgentResultDAO)

    def _build_orchestrator_node(self, *, parent_session_id: str) -> OrchestratorNodeDAO:
        """Build an orchestrator list node from bounded status evidence and captures.

        Args:
            parent_session_id (str): Orchestrator session to render.

        Returns:
            OrchestratorNodeDAO: Self-reported node, or an unknown node when the
                status is absent, oversized or unreadable.
        """
        session_dir: Path = OrchestrationLayout.session_dir(
            history_root=self._store.root,
            session_id=parent_session_id,
        )
        captures: dict[str, object] = {
            "session_id": parent_session_id,
            "has_stdout_capture": (session_dir / "stdout.jsonl").exists(),
            "has_stderr_capture": (session_dir / "stderr.log").exists(),
        }
        status: Optional[OrchestratorStatusDAO] = self._read_optional_model(
            path=OrchestrationLayout.orchestrator_status_path(
                history_root=self._store.root,
                orchestrator_session_id=parent_session_id,
            ),
            model=OrchestratorStatusDAO,
        )
        if status is None:
            return OrchestratorNodeDAO.model_validate(captures)
        return OrchestratorNodeDAO.model_validate(
            {
                **captures,
                "state": status.state,
                "phase": status.phase,
                "pid": status.pid,
                "updated_at": status.updated_at,
            }
        )

    def _read_optional_bytes(self, *, path: Path) -> Optional[bytes]:
        """Read one bounded optional file; None when absent, refused or oversized.

        Args:
            path (Path): Contained file path.

        Returns:
            Optional[bytes]: File bytes, or None.
        """
        try:
            return self._reader.read_bytes(path=path)
        except (OSError, ValueError):
            return None

    def _read_optional_model(self, *, path: Path, model: type[_ModelT]) -> Optional[_ModelT]:
        """Read and decode one optional bounded JSON file; None on any failure.

        Args:
            path (Path): Contained file path.
            model (type[_ModelT]): Closed DAO to decode.

        Returns:
            Optional[_ModelT]: Decoded model, or None.
        """
        data: Optional[bytes] = self._read_optional_bytes(path=path)
        return None if data is None else self._decode_optional(data=data, model=model)

    @staticmethod
    def _decode_optional(*, data: bytes, model: type[_ModelT]) -> Optional[_ModelT]:
        """Decode bounded bytes into ``model``; None when malformed.

        Args:
            data (bytes): Bounded file bytes.
            model (type[_ModelT]): Closed DAO to decode.

        Returns:
            Optional[_ModelT]: Decoded model, or None.
        """
        try:
            return model.model_validate_json(data)
        except (ValidationError, ValueError, RecursionError):
            return None

    # ── private helpers ──────────────────────────────────────────────────────

    async def _resolve_parent_session_id(self) -> str:
        """Resolve the config session reference to a canonical session id.

        Returns:
            str: Resolved canonical session id.

        Raises:
            ValueError: When the reference cannot be resolved.
        """
        return await self._store.resolve_session_reference(
            reference=self._config.session_reference,
        )

    async def _load_parent_metadata(
        self,
        *,
        session_id: str,
    ) -> Optional[SessionHistoryMetadataDAO]:
        """Load parent metadata, returning ``None`` when absent.

        Args:
            session_id (str): Parent session id.

        Returns:
            Optional[SessionHistoryMetadataDAO]: Metadata or ``None``.
        """
        try:
            return await self._store.read_metadata(session_id=session_id)
        except FileNotFoundError:
            return None

    async def _load_parent_events(
        self,
        *,
        session_id: str,
    ) -> list[SessionHistoryEventDAO]:
        """Load all canonical events for the parent session (legacy load only).

        Args:
            session_id (str): Parent session id.

        Returns:
            list[SessionHistoryEventDAO]: Events in sequence order.
        """
        try:
            return await self._store.load_events(session_id=session_id)
        except FileNotFoundError:
            return []

    def _discover_children_from_events(
        self,
        *,
        parent_session_id: str,
        parent_events: list[SessionHistoryEventDAO],
        index: Optional[ExecutionIndexDAO] = None,
    ) -> list[ChildSessionSummaryDAO]:
        """Build child summaries from ``sub_agent_spawned``/``sub_agent_completed`` events.

        Args:
            parent_session_id (str): Orchestrator session id for capture probing.
            parent_events (list[SessionHistoryEventDAO]): Parent event log.
            index (Optional[ExecutionIndexDAO]): Run execution index, when present.

        Returns:
            list[ChildSessionSummaryDAO]: Ordered child summaries.
        """
        summaries: dict[str, ChildSessionSummaryDAO] = {}
        for event in parent_events:
            if event.kind == "sub_agent_spawned":
                child_id: str = event.payload.metadata.get("sub_agent_id", "")
                task_id: Optional[str] = event.payload.metadata.get("task_id")
                if not child_id or child_id in summaries:
                    continue
                summaries[child_id] = self._build_child_summary(
                    child_session_id=child_id,
                    task_id=task_id,
                    parent_session_id=parent_session_id,
                    status="running",
                    index=index,
                )
            elif event.kind == "sub_agent_completed":
                child_id = event.payload.metadata.get("sub_agent_id", "")
                terminal_kind: str = event.payload.metadata.get("terminal_kind", "sub_agent_failed")
                if not child_id or child_id not in summaries:
                    continue
                status: str = status_for_lifecycle_kind(kind=terminal_kind)
                summaries[child_id] = self._event_status(summary=summaries[child_id], status=status)
        return list(summaries.values())

    @staticmethod
    def _event_status(*, summary: ChildSessionSummaryDAO, status: str) -> ChildSessionSummaryDAO:
        """Apply an event-derived terminal status to legacy children only.

        Args:
            summary (ChildSessionSummaryDAO): Summary built at spawn.
            status (str): Status from the completion event.

        Returns:
            ChildSessionSummaryDAO: Updated legacy summary; modern summaries keep
                their evidence-derived status because events carry no incarnation.
        """
        if summary.execution_id:
            return summary
        return summary.model_copy(update={"status": status})

    def _build_child_summary(
        self,
        *,
        child_session_id: str,
        task_id: Optional[str],
        parent_session_id: str,
        status: str,
        index: Optional[ExecutionIndexDAO] = None,
    ) -> ChildSessionSummaryDAO:
        """Build one child summary trusting only files of its current incarnation.

        Args:
            child_session_id (str): Child session id.
            task_id (Optional[str]): Pool task id, or ``None``.
            parent_session_id (str): Parent session id.
            status (str): Initial lifecycle status for legacy children.
            index (Optional[ExecutionIndexDAO]): Run execution index; a child it
                maps is modern and needs matching evidence.

        Returns:
            ChildSessionSummaryDAO: Summary with trusted capture flags and task text.
        """
        incarnation: _ChildIncarnationDAO = self._resolve_incarnation(
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
            execution_id=index.executions.get(child_session_id, "") if index is not None else "",
            index=index,
        )
        spawn: Optional[SpawnContextDAO] = self._matching_context(
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
            incarnation=incarnation,
        )
        task_text: str = spawn.prompt if spawn is not None else ""
        evidence: Optional[ChildExecutionEvidenceDAO] = incarnation.evidence
        return ChildSessionSummaryDAO(
            session_id=child_session_id,
            task_id=task_id,
            status=evidence.status if evidence is not None else status,
            has_stdout_capture=incarnation.trusts_capture
            and self._child_capture_path(
                parent_session_id=parent_session_id,
                child_session_id=child_session_id,
                filename="stdout.jsonl",
            ).exists(),
            has_stderr_capture=self._child_capture_path(
                parent_session_id=parent_session_id,
                child_session_id=child_session_id,
                filename="stderr.jsonl",
            ).exists(),
            has_spawn_context=spawn is not None,
            prompt_preview=TaskPreview.build(task_text=task_text) if task_text else "",
            task_text=task_text,
            task_summary=TaskPreview.project_summary(
                prompt_preview="", task_text=spawn.prompt if spawn else None
            ),
            task_text_complete=spawn is not None,
            execution_id=incarnation.execution_id,
            dispatch_id=(evidence.dispatch_id or "") if evidence is not None else "",
            execution_verified=evidence is not None,
            status_sha256=evidence.status_sha256 if evidence is not None else None,
        )

    @staticmethod
    def _merge_child_discoveries(
        *,
        from_events: list[ChildSessionSummaryDAO],
        from_dirs: list[ChildSessionSummaryDAO],
    ) -> list[ChildSessionSummaryDAO]:
        """Merge event-derived and directory-derived child summaries.

        Events-derived entries take precedence; directory-only entries are
        appended at the end for resilience when history events lag behind
        capture file creation.

        Args:
            from_events (list[ChildSessionSummaryDAO]): Summaries from events.
            from_dirs (list[ChildSessionSummaryDAO]): Summaries from dirs.

        Returns:
            list[ChildSessionSummaryDAO]: Merged deduplicated list.
        """
        seen: set[str] = {s.session_id for s in from_events}
        extras: list[ChildSessionSummaryDAO] = [s for s in from_dirs if s.session_id not in seen]
        return from_events + extras

    @staticmethod
    def _detect_workflow_complete(
        *,
        events: list[SessionHistoryEventDAO],
    ) -> bool:
        """Return ``True`` when the parent session has a terminal event.

        Args:
            events (list[SessionHistoryEventDAO]): Parent event log.

        Returns:
            bool: ``True`` when the newest run boundary is a terminal record.
        """
        return _latest_run_closed(events=events)

    def _child_capture_path(
        self,
        *,
        parent_session_id: str,
        child_session_id: str,
        filename: str,
    ) -> Path:
        """Build the path to a child capture file.

        Args:
            parent_session_id (str): Parent session id.
            child_session_id (str): Child session id.
            filename (str): Capture file name (e.g. ``stdout.jsonl``).

        Returns:
            Path: Absolute path to the capture file.
        """
        child_capture_dir: Path = OrchestrationLayout.child_capture_dir(
            history_root=self._store.root,
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
        )
        return child_capture_dir / filename


_UNAVAILABLE: _ProgressContentDAO = _ProgressContentDAO(
    availability="unavailable", notices=(PROGRESS_UNAVAILABLE_NOTICE,)
)
"""Content of a read that found no safe source; keeps the last-good paint."""


def _latest_run_closed(*, events: Iterable[SessionHistoryEventDAO]) -> bool:
    """Return whether the newest run boundary in ``events`` is a run terminal record.

    A terminal record counts only when no ``run_started`` follows it, so a reused
    child session or a resumed parent whose window still holds an earlier run's
    terminal record is not complete.

    Args:
        events (Iterable[SessionHistoryEventDAO]): Canonical events in sequence order.

    Returns:
        bool: True when the last run boundary closes the run.
    """
    boundaries: list[str] = [event.kind for event in events if event.kind in _RUN_BOUNDARY_EVENT_KINDS]
    return bool(boundaries) and boundaries[-1] in _TERMINAL_EVENT_KINDS


def _bounded_entries(*, entries: list[TranscriptEntryDAO]) -> tuple[tuple[TranscriptEntryDAO, ...], bool]:
    """Keep the newest entries within 2,000 entries and 2 MiB public text.

    Args:
        entries (list[TranscriptEntryDAO]): Projected entries in order.

    Returns:
        tuple[tuple[TranscriptEntryDAO, ...], bool]: Retained suffix and whether
            any entry was dropped.
    """
    kept: list[TranscriptEntryDAO] = []
    total: int = 0
    for entry in reversed(entries[-PROGRESS_MAX_ENTRIES:]):
        total += _public_text_bytes(entry=entry)
        if total > PROGRESS_MAX_TEXT_BYTES:
            break
        kept.append(entry)
    return tuple(reversed(kept)), len(kept) < len(entries)


# ---------------------------------------------------------------------------
# Bounded, contained, no-follow observation reads (feature 94 a.3)
# ---------------------------------------------------------------------------


class _ObservationLimitError(ValueError):
    """Raised when listing children would have to truncate membership."""


class _ObservationReader:
    """Contained, symlink-refusing, byte-bounded reads below one history root.

    Every path must resolve to itself below the root (no symlinked component);
    files open with ``O_NOFOLLOW | O_NONBLOCK`` and must be regular. Reads stop
    one byte past the budget, so oversized input is refused before decode.
    """

    def __init__(self, *, root: Path) -> None:
        """Bind the reader to the store's history root.

        Args:
            root (Path): History root; paths outside it are refused.
        """
        self._lexical_root: Path = Path(os.path.abspath(root))
        self._real_root: Path = Path(os.path.realpath(root))

    def read_bytes(self, *, path: Path, max_bytes: int = OBSERVATION_MAX_JSON_BYTES) -> Optional[bytes]:
        """Return a contained regular file's bytes within ``max_bytes``.

        Args:
            path (Path): File below the root.
            max_bytes (int, optional): Byte budget. Defaults to 2,097,152.

        Returns:
            Optional[bytes]: File bytes, or None when the file or a parent is absent.

        Raises:
            ValueError: When the path escapes the root or the file exceeds the budget.
            OSError: When the file is a symlink, not regular, or unreadable.
        """
        self.require_contained(path=path)
        try:
            descriptor: int = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except (FileNotFoundError, NotADirectoryError):
            return None
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise OSError("observation input is not a regular file")
            data: bytes = handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("observation input exceeds its byte budget")
        return data

    def read_model(self, *, path: Path, model: type[_ModelT]) -> Optional[_ModelT]:
        """Decode a contained bounded JSON file into ``model``.

        Args:
            path (Path): File below the root.
            model (type[_ModelT]): Closed DAO to decode.

        Returns:
            Optional[_ModelT]: Decoded model, or None when the file is absent.

        Raises:
            ValueError: Escaped, oversized or malformed input.
            OSError: Refused or unreadable input.
        """
        data: Optional[bytes] = self.read_bytes(path=path)
        return None if data is None else model.model_validate_json(data)

    def child_names(self, *, directory: Path) -> tuple[str, ...]:
        """List safe child directory names, scanning at most 2,001 entries.

        Args:
            directory (Path): Parent's ``children`` directory below the root.

        Returns:
            tuple[str, ...]: Sorted names of real (non-symlink) subdirectories;
                empty when the directory is absent.

        Raises:
            _ObservationLimitError: When more than 2,000 entries exist.
            ValueError: When the directory escapes the root.
        """
        self.require_contained(path=directory)
        try:
            scanner = os.scandir(directory)
        except (FileNotFoundError, NotADirectoryError):
            return ()
        with scanner:
            entries: list[os.DirEntry[str]] = list(itertools.islice(scanner, OBSERVATION_MAX_CHILDREN + 1))
        if len(entries) > OBSERVATION_MAX_CHILDREN:
            raise _ObservationLimitError("child directory limit exceeded")
        return tuple(sorted(entry.name for entry in entries if self._is_child_dir(entry=entry)))

    @staticmethod
    def _is_child_dir(*, entry: os.DirEntry[str]) -> bool:
        """Return whether a scanned entry is a real directory with a safe name.

        Args:
            entry (os.DirEntry[str]): Scanned entry.

        Returns:
            bool: True for a non-symlink directory named by a safe identifier.
        """
        try:
            safe_identifier(value=entry.name)
        except ValueError:
            return False
        return entry.is_dir(follow_symlinks=False)

    def require_contained(self, *, path: Path) -> None:
        """Refuse paths outside the root or reached through a symlinked component.

        Args:
            path (Path): Candidate path.

        Raises:
            ValueError: When the path is outside the root or not its own real path.
        """
        relative: Path = Path(os.path.abspath(path)).relative_to(self._lexical_root)
        if Path(os.path.realpath(path)) != self._real_root / relative:
            raise ValueError("observation path escapes the history root")


# ---------------------------------------------------------------------------
# Live capture projection (feature 94 a.3: moved from HeadlessWorkflowVisualizer)
# ---------------------------------------------------------------------------

PROGRESS_MAX_ENTRIES: int = 2_000
"""Most public entries one progress view retains."""

PROGRESS_MAX_TEXT_BYTES: int = 2_097_152
"""Most UTF-8 bytes of public entry text one progress view retains."""

PROGRESS_MAX_PENDING_TOOLS: int = 256
"""Most streamed tool calls one progress view buffers while awaiting their result."""

PROGRESS_TEXT_CLIPPED_MARKER: str = "… [clipped to fit this view]"
"""Fixed suffix on a single entry whose public text alone exceeded the budget.

Truncated tool arguments always reach the budget, so their entry is clipped and
carries this marker too.
"""

_RUN_TERMINAL_STREAM_KINDS: frozenset[str] = frozenset({"run_completed", "run_failed", "run_aborted"})
"""Captured stream kinds that end a run and close every open block."""

_OpenBlockKind = Literal["thinking", "assistant"]


class _LiveToolBuffers:
    """Accumulate one live tool invocation until its result arrives."""

    def __init__(self, *, tool_name: str) -> None:
        """Create an empty buffer for one streamed tool call.

        Args:
            tool_name (str): Name reported by the tool-call start event.
        """
        self.tool_name: str = tool_name
        self.arguments_chunks: list[str] = []
        self.buffered_bytes: int = 0
        self.truncated: bool = False

    def append_arguments(self, *, delta: str, allowance: int) -> int:
        """Record one tool-arguments fragment, keeping at most ``allowance`` bytes of it.

        Args:
            delta (str): JSON/text fragment from a tool-call delta event.
            allowance (int): UTF-8 bytes this buffer may still add.

        Returns:
            int: UTF-8 bytes actually buffered from ``delta``.
        """
        encoded: bytes = delta.encode("utf-8")
        kept: str = (
            delta if len(encoded) <= allowance else encoded[: max(allowance, 0)].decode("utf-8", "ignore")
        )
        self.truncated = self.truncated or len(kept) < len(delta)
        added: int = len(kept.encode("utf-8"))
        self.arguments_chunks.append(kept)
        self.buffered_bytes += added
        return added

    def release_arguments(self) -> int:
        """Drop the buffered arguments once the call entry was emitted.

        Returns:
            int: UTF-8 bytes released from the pending budget.
        """
        released: int = self.buffered_bytes
        self.arguments_chunks = []
        self.buffered_bytes = 0
        return released

    def build_call_entry(self) -> TranscriptEntryDAO:
        """Build the visible tool-call entry from buffered arguments.

        Returns:
            TranscriptEntryDAO: Tool-call entry; truncated, unparseable or non-object
                arguments are kept verbatim under ``raw``.
        """
        raw_arguments: str = "".join(self.arguments_chunks)
        if self.truncated:
            return TranscriptEntryDAO(
                kind="tool", tool_name=self.tool_name, tool_input={"raw": raw_arguments}
            )
        try:
            parsed_arguments: object = json.loads(raw_arguments)
        except (json.JSONDecodeError, ValueError):
            parsed_arguments = {"raw": raw_arguments}
        tool_input: dict[str, object] = (
            parsed_arguments if isinstance(parsed_arguments, dict) else {"raw": raw_arguments}
        )
        return TranscriptEntryDAO(kind="tool", tool_name=self.tool_name, tool_input=tool_input)


class _PendingToolCalls:
    """Bounded set of streamed tool calls awaiting their call end or result.

    Owns the pending-buffer bounds: at most PROGRESS_MAX_PENDING_TOOLS calls and
    PROGRESS_MAX_TEXT_BYTES of buffered arguments across them. The oldest calls
    are evicted first; any eviction or truncation is recorded in ``omitted``.
    """

    def __init__(self) -> None:
        """Start with no pending tool calls."""
        self._calls: OrderedDict[str, _LiveToolBuffers] = OrderedDict()
        self._buffered_bytes: int = 0
        self.omitted: bool = False

    @property
    def buffered_bytes(self) -> int:
        """UTF-8 bytes of arguments buffered across pending calls. Read-only."""
        return self._buffered_bytes

    @property
    def pending_calls(self) -> int:
        """Number of calls awaiting their end or result. Read-only."""
        return len(self._calls)

    def start(self, *, block_id: str, tool_name: str) -> None:
        """Begin buffering one tool call, evicting the oldest beyond the count bound.

        Args:
            block_id (str): Stream block id of the call.
            tool_name (str): Name reported by the tool-call start event.
        """
        self._evict(block_id=block_id)
        self._calls[block_id] = _LiveToolBuffers(tool_name=tool_name)
        while len(self._calls) > PROGRESS_MAX_PENDING_TOOLS:
            self._evict(block_id=next(iter(self._calls)))
            self.omitted = True

    def append(self, *, block_id: str, delta: str) -> None:
        """Buffer one arguments fragment, evicting older calls before truncating it.

        Args:
            block_id (str): Stream block id of the call.
            delta (str): Arguments fragment.
        """
        buffers: Optional[_LiveToolBuffers] = self._calls.get(block_id)
        if buffers is None:
            return
        needed: int = len(delta.encode("utf-8"))
        oldest: Optional[str] = self._oldest_other(block_id=block_id)
        while oldest is not None and self._buffered_bytes + needed > PROGRESS_MAX_TEXT_BYTES:
            self._evict(block_id=oldest)
            self.omitted = True
            oldest = self._oldest_other(block_id=block_id)
        self._buffered_bytes += buffers.append_arguments(
            delta=delta, allowance=PROGRESS_MAX_TEXT_BYTES - self._buffered_bytes
        )
        self.omitted = self.omitted or buffers.truncated

    def end(self, *, block_id: str) -> Optional[TranscriptEntryDAO]:
        """Emit a call's entry and release its arguments; the name awaits the result.

        Args:
            block_id (str): Stream block id of the call.

        Returns:
            Optional[TranscriptEntryDAO]: Call entry, or None for an unknown call.
        """
        buffers: Optional[_LiveToolBuffers] = self._calls.get(block_id)
        if buffers is None:
            return None
        entry: TranscriptEntryDAO = buffers.build_call_entry()
        self._buffered_bytes -= buffers.release_arguments()
        return entry

    def finish(self, *, call_id: str) -> Optional[str]:
        """Remove a call whose result arrived and return its tool name.

        Args:
            call_id (str): Tool call id carried by the result event.

        Returns:
            Optional[str]: Tool name, or None for an unknown or evicted call.
        """
        buffers: Optional[_LiveToolBuffers] = self._calls.get(call_id)
        self._evict(block_id=call_id)
        return buffers.tool_name if buffers is not None else None

    def _oldest_other(self, *, block_id: str) -> Optional[str]:
        """Return the oldest pending call id other than ``block_id``.

        Args:
            block_id (str): Call id to skip.

        Returns:
            Optional[str]: Oldest other call id, or None when there is none.
        """
        return next((key for key in self._calls if key != block_id), None)

    def _evict(self, *, block_id: str) -> None:
        """Forget one pending call and release its buffered bytes.

        Args:
            block_id (str): Call id to remove; unknown ids are ignored.
        """
        buffers: Optional[_LiveToolBuffers] = self._calls.pop(block_id, None)
        if buffers is not None:
            self._buffered_bytes -= buffers.buffered_bytes


def _public_text_bytes(*, entry: TranscriptEntryDAO) -> int:
    """Return the UTF-8 size of an entry's public text fields.

    Args:
        entry (TranscriptEntryDAO): Public transcript entry.

    Returns:
        int: Bytes counted against the progress text budget.
    """
    fields: tuple[Optional[str], ...] = (
        entry.content,
        entry.reasoning,
        entry.answer,
        entry.output,
        entry.terminal_note,
        entry.tool_name,
    )
    text_bytes: int = sum(len(value.encode("utf-8")) for value in fields if value)
    return text_bytes + (len(json.dumps(entry.tool_input)) if entry.tool_input else 0)


_CLIPPABLE_TEXT_FIELDS: tuple[str, ...] = (
    "content",
    "reasoning",
    "answer",
    "output",
    "terminal_note",
    "tool_name",
)
"""Public string fields a lone over-budget entry may be clipped in."""


def _clipped_to_budget(*, entry: TranscriptEntryDAO) -> TranscriptEntryDAO:
    """Clip an entry's largest public fields until it fits the text budget.

    Each pass removes at least the measured excess (plus marker) from the largest
    field, so escape-expanding tool input converges in a few passes. A field
    already reduced to the marker cannot shrink further and ends the loop.

    Args:
        entry (TranscriptEntryDAO): Entry whose public text exceeds the budget.

    Returns:
        TranscriptEntryDAO: Entry within PROGRESS_MAX_TEXT_BYTES whose clipped
            fields end with PROGRESS_TEXT_CLIPPED_MARKER.
    """
    clipped: TranscriptEntryDAO = entry
    excess: int = _public_text_bytes(entry=clipped) - PROGRESS_MAX_TEXT_BYTES
    while excess > 0:
        shorter: TranscriptEntryDAO = _clip_largest_field(entry=clipped, excess=excess)
        if shorter == clipped:
            return clipped
        clipped = shorter
        excess = _public_text_bytes(entry=clipped) - PROGRESS_MAX_TEXT_BYTES
    return clipped


def _clip_largest_field(*, entry: TranscriptEntryDAO, excess: int) -> TranscriptEntryDAO:
    """Shorten the entry's largest public field by at least ``excess`` bytes.

    Tool input is clipped as its rendered JSON text under ``raw``.

    Args:
        entry (TranscriptEntryDAO): Over-budget entry.
        excess (int): UTF-8 bytes above the budget.

    Returns:
        TranscriptEntryDAO: Copy with one field shortened, or ``entry`` unchanged
            when no field can shrink.
    """
    texts: dict[str, str] = {
        name: getattr(entry, name) for name in _CLIPPABLE_TEXT_FIELDS if getattr(entry, name)
    }
    if entry.tool_input:
        raw: object = entry.tool_input.get("raw")
        texts["tool_input"] = (
            raw if set(entry.tool_input) == {"raw"} and isinstance(raw, str) else json.dumps(entry.tool_input)
        )
    name: str = max(texts, key=lambda field: len(texts[field].encode("utf-8")), default="")
    if not name:
        return entry
    value: str = texts[name]
    keep: int = max(len(value) - excess - len(PROGRESS_TEXT_CLIPPED_MARKER), 0)
    shortened: str = value[:keep] + PROGRESS_TEXT_CLIPPED_MARKER
    update: dict[str, object] = {name: {"raw": shortened} if name == "tool_input" else shortened}
    return entry.model_copy(update=update)


class _LiveTranscript:
    """Bounded public transcript accumulated from one capture generation.

    Owns the open thinking/assistant block, buffered tool calls and the retained
    entries. Retains at most PROGRESS_MAX_ENTRIES entries and
    PROGRESS_MAX_TEXT_BYTES of public text, dropping the oldest entries first and
    recording that omission. Only public delta/tool fields are projected; stream
    metadata never enters an entry.
    """

    def __init__(self) -> None:
        """Start an empty transcript for a new capture generation."""
        self._entries: deque[TranscriptEntryDAO] = deque()
        self._open_kind: Optional[_OpenBlockKind] = None
        self._tools: _PendingToolCalls = _PendingToolCalls()
        self._omitted: bool = False
        self.terminal_seen: bool = False

    @property
    def omitted(self) -> bool:
        """Whether entries, text, tool arguments or pending calls were dropped. Read-only."""
        return self._omitted or self._tools.omitted

    @property
    def entries(self) -> tuple[TranscriptEntryDAO, ...]:
        """Retained public entries in event order. Read-only."""
        return tuple(self._entries)

    def absorb(self, *, events: list[AgentStreamEventDAO]) -> None:
        """Apply parsed capture events in order, then enforce the retention bounds.

        WHAT: Extends open blocks, closes them on block/run ends, emits tool call and
            result entries, then drops the oldest entries beyond the bounds.
        WHO: Called by _CaptureView after each bounded capture read.
        WHEN: Once per observation that returned new complete lines.

        Args:
            events (list[AgentStreamEventDAO]): Newly captured events in order.
        """
        for event in events:
            self._absorb_event(event=event)
        self._enforce_bounds()

    def _absorb_event(self, *, event: AgentStreamEventDAO) -> None:
        """Dispatch one stream event to its block, tool or terminal handler.

        Args:
            event (AgentStreamEventDAO): Parsed capture event.
        """
        if event.kind == "thinking_delta" and event.delta:
            self._extend_open(kind="thinking", delta=event.delta)
            return
        if event.kind == "text_delta" and event.delta:
            self._extend_open(kind="assistant", delta=event.delta)
            return
        if event.kind == "thinking_end":
            self._close_open(kind="thinking")
            return
        if event.kind == "text_end" or event.kind in _RUN_TERMINAL_STREAM_KINDS:
            self._open_kind = None
            self.terminal_seen = self.terminal_seen or event.kind in _RUN_TERMINAL_STREAM_KINDS
            return
        self._absorb_tool_event(event=event)

    def _absorb_tool_event(self, *, event: AgentStreamEventDAO) -> None:
        """Track streamed tool calls and emit their call and result entries.

        Args:
            event (AgentStreamEventDAO): Parsed capture event of a tool kind.
        """
        if event.kind == "tool_call_start" and event.block_id and event.tool_name:
            self._tools.start(block_id=event.block_id, tool_name=event.tool_name)
            return
        if event.kind == "tool_call_delta" and event.block_id and event.tool_arguments_delta:
            self._tools.append(block_id=event.block_id, delta=event.tool_arguments_delta)
            return
        call: Optional[TranscriptEntryDAO] = (
            self._tools.end(block_id=event.block_id)
            if event.kind == "tool_call_end" and event.block_id
            else None
        )
        if call is not None:
            self._append(entry=call)
            return
        tool_name: Optional[str] = (
            self._tools.finish(call_id=event.tool_call_id)
            if event.kind == "tool_result" and event.tool_call_id
            else None
        )
        if tool_name is not None:
            self._append(entry=TranscriptEntryDAO(kind="tool", tool_name=tool_name, output=event.content))

    def _extend_open(self, *, kind: _OpenBlockKind, delta: str) -> None:
        """Extend the open block of ``kind`` or start a new entry for it.

        A block that would exceed the text budget continues in a new entry of the
        same kind, so retention can drop its oldest part.

        Args:
            kind (_OpenBlockKind): Block kind the delta belongs to.
            delta (str): New visible text.
        """
        field: str = "content" if kind == "thinking" else "answer"
        current: Optional[TranscriptEntryDAO] = self._entries[-1] if self._open_kind == kind else None
        fits: bool = current is not None and (
            _public_text_bytes(entry=current) + len(delta.encode("utf-8")) <= PROGRESS_MAX_TEXT_BYTES
        )
        if current is None or not fits:
            self._append(entry=TranscriptEntryDAO.model_validate({"kind": kind, field: delta}))
            self._open_kind = kind
            return
        self._entries[-1] = current.model_copy(update={field: (getattr(current, field) or "") + delta})

    def _close_open(self, *, kind: _OpenBlockKind) -> None:
        """Close the open block only when it is of ``kind``.

        Args:
            kind (_OpenBlockKind): Block kind whose end event arrived.
        """
        if self._open_kind == kind:
            self._open_kind = None

    def _append(self, *, entry: TranscriptEntryDAO) -> None:
        """Append a completed or newly opened entry, closing any other open block.

        Args:
            entry (TranscriptEntryDAO): Entry to retain.
        """
        self._open_kind = None
        self._entries.append(entry)

    def _enforce_bounds(self) -> None:
        """Drop the oldest entries beyond the budgets, then clip a lone over-budget entry."""
        total: int = sum(_public_text_bytes(entry=entry) for entry in self._entries)
        while len(self._entries) > 1 and (
            len(self._entries) > PROGRESS_MAX_ENTRIES or total > PROGRESS_MAX_TEXT_BYTES
        ):
            total -= _public_text_bytes(entry=self._entries.popleft())
            self._omitted = True
        if total > PROGRESS_MAX_TEXT_BYTES:
            self._entries[-1] = _clipped_to_budget(entry=self._entries[-1])
            self._omitted = True


class _CaptureObservationDAO(BaseModel):
    """One bounded read of a live capture, as seen by the progress loader.

    Attributes:
        available (bool): Whether a regular capture file was read this time.
        entries (tuple[TranscriptEntryDAO, ...]): Retained public entries.
        generation (str): ``device:inode:tail-revision``; fixed across appends.
        revision (str): Generation plus content version; changes on new lines.
        omitted (bool): Whether bytes, lines or entries were dropped.
        reset (bool): Whether the capture was replaced or truncated since last read.
        terminal_seen (bool): Whether a run terminal event was captured.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    available: bool
    entries: tuple[TranscriptEntryDAO, ...] = ()
    generation: str = ""
    revision: str = ""
    omitted: bool = False
    reset: bool = False
    terminal_seen: bool = False


class _CaptureView:
    """Incremental public transcript of one capture file (the loader's live seam).

    Owns one bounded JsonlTail and the transcript it feeds. A replaced or
    truncated capture starts a fresh transcript, so old entries are never
    replayed into the new generation. Malformed complete lines are skipped and
    logged with a fixed code and count only. Observations are serialised by the
    view itself: overlapping worker-thread reads (follow timer and key handlers)
    each absorb every new line exactly once.
    """

    def __init__(self, *, path: Path) -> None:
        """Bind the view to one capture path without reading it.

        Args:
            path (Path): Contained capture path; it may not exist yet.
        """
        self._path: Path = path
        self._tail: JsonlTail = JsonlTail(path=path)
        self._transcript: _LiveTranscript = _LiveTranscript()
        self._tail_revision: int = 0
        self._version: int = 0
        self._lock: threading.Lock = threading.Lock()

    def observe(self) -> _CaptureObservationDAO:
        """Read newly completed lines and return the bounded transcript.

        WHAT: Performs one bounded tail read, resets on a new file generation,
            absorbs valid events and reports omission/reset/terminal evidence.
        WHO: Called by WorkflowVisualizerLoader's live and terminal progress reads.
        WHEN: Off the event loop, once per progress observation; concurrent calls
            wait for each other.

        Returns:
            _CaptureObservationDAO: Unavailable when no regular capture was read.
        """
        with self._lock:
            return self._observe_exclusively()

    def _observe_exclusively(self) -> _CaptureObservationDAO:
        """Read, reset and absorb under the view lock; see ``observe``.

        Returns:
            _CaptureObservationDAO: Unavailable when no regular capture was read.
        """
        lines: list[bytes] = self._tail.read_new()
        identity: Optional[tuple[int, int]] = self._tail.identity
        if identity is None:
            return _CaptureObservationDAO(available=False)
        reset: bool = self._tail.revision != self._tail_revision
        if reset:
            self._transcript = _LiveTranscript()
            self._tail_revision = self._tail.revision
        self._absorb_lines(lines=lines)
        generation: str = f"{identity[0]}:{identity[1]}:{self._tail_revision}"
        return _CaptureObservationDAO(
            available=True,
            entries=self._transcript.entries,
            generation=generation,
            revision=f"{generation}:{self._version}",
            omitted=self._transcript.omitted or self._tail.truncated,
            reset=reset,
            terminal_seen=self._transcript.terminal_seen,
        )

    def _absorb_lines(self, *, lines: list[bytes]) -> None:
        """Parse complete lines, skipping malformed ones, and feed the transcript.

        Args:
            lines (list[bytes]): Complete capture lines from one bounded read.
        """
        if not lines:
            return
        events: list[AgentStreamEventDAO] = []
        for line in lines:
            try:
                events.append(AgentStreamEventDAO.model_validate_json(line))
            except (ValidationError, ValueError, RecursionError):
                continue
        if len(events) < len(lines):
            log_warning(msg="progress_capture_lines_invalid", count=len(lines) - len(events))
        self._transcript.absorb(events=events)
        self._version += 1
