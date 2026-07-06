"""WorkflowVisualizerLoader — data-discovery service for ``slo visualize``.

Loads the parent orchestrator session and its children from persisted
canonical history and child capture files. Keeps all filesystem IO out of
the Textual widget tree so the app can await results from worker threads.

Sub-spec 53.a.5. Extended in 54.a.4 to surface orchestrator and spawn
context files, enrich child summaries with prompt previews, and reconstruct
thinking/tool transcript entries from stdout.jsonl captures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config.cfg import VISUALIZER_REFRESH_SECONDS as _CFG_VISUALIZER_REFRESH_SECONDS
from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryMetadataDAO,
)
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.transcript import (
    ReplayEntryProjector,
    TranscriptEntryDAO,
)
from src.agents.slo_agent.orchestrator.context_dao import (
    OrchestratorContextDAO,
    SpawnContextDAO,
)
from src.tui.tree_export_format import TreeExportFormat

__all__ = [
    "HeadlessWorkflowVisualizerConfigDAO",
    "ChildSessionSummaryDAO",
    "WorkflowDataDAO",
    "WorkflowVisualizerLoader",
]

_DEFAULT_REFRESH_SECONDS: float = _CFG_VISUALIZER_REFRESH_SECONDS

_TERMINAL_EVENT_KINDS: frozenset[str] = frozenset(
    {"run_completed", "run_aborted", "run_failed"}
)

_TERMINAL_KIND_TO_STATUS: dict[str, str] = {
    "sub_agent_completed": "completed",
    "sub_agent_failed": "failed",
    "sub_agent_aborted": "aborted",
}


class HeadlessWorkflowVisualizerConfigDAO(BaseModel):
    """Configuration DAO for ``HeadlessWorkflowVisualizer``.

    Attributes:
        session_reference (str): Session id or unique name to inspect.
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
        status (str): Latest known lifecycle status — ``"running"``,
            ``"completed"``, ``"failed"``, or ``"aborted"``.
        has_stdout_capture (bool): Whether a stdout.jsonl capture file exists.
        has_stderr_capture (bool): Whether a stderr.jsonl capture file exists.
        has_spawn_context (bool): Whether a spawn_context.json capture file exists.
        prompt_preview (str): First 60 characters of the task prompt, truncated
            with ``…`` when longer. Empty string when no spawn context is available.
    """

    session_id: str
    task_id: Optional[str] = None
    status: str = "running"
    has_stdout_capture: bool = False
    has_stderr_capture: bool = False
    has_spawn_context: bool = False
    prompt_preview: str = ""


class WorkflowDataDAO(BaseModel):
    """Snapshot returned by ``WorkflowVisualizerLoader.load()``.

    Attributes:
        parent_session_id (str): Resolved canonical parent session id.
        parent_metadata (Optional[SessionHistoryMetadataDAO]): Persisted
            metadata; ``None`` when the session directory does not exist yet.
        parent_events (list[SessionHistoryEventDAO]): All canonical events
            for the parent session in sequence order.
        children (list[ChildSessionSummaryDAO]): Discovered child sessions;
            events-derived entries first, capture-dir-only extras appended.
        is_complete (bool): ``True`` when a terminal event is present.
        orchestrator_context (Optional[OrchestratorContextDAO]): Loaded
            orchestrator invocation context; ``None`` when the capture file
            does not exist or cannot be parsed.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    parent_session_id: str
    parent_metadata: Optional[SessionHistoryMetadataDAO] = None
    parent_events: list[SessionHistoryEventDAO] = Field(default_factory=list)
    children: list[ChildSessionSummaryDAO] = Field(default_factory=list)
    is_complete: bool = False
    orchestrator_context: Optional[OrchestratorContextDAO] = None


class WorkflowVisualizerLoader:
    """Data-discovery service for the headless workflow visualizer.

    Resolves the parent session reference, loads its canonical events, and
    discovers child sessions from both the parent history event log and
    the ``children/<session_id>/`` capture directories.
    """

    def __init__(
        self,
        *,
        config: HeadlessWorkflowVisualizerConfigDAO,
        store: Optional[FilesystemSessionHistoryStore] = None,
    ) -> None:
        """Bind the loader to its config and an optional history-store override.

        Args:
            config (HeadlessWorkflowVisualizerConfigDAO): Visualizer config.
            store (Optional[FilesystemSessionHistoryStore]): Override for tests;
                ``None`` constructs a default store rooted at ``~/.slo``.
        """
        self._config: HeadlessWorkflowVisualizerConfigDAO = config
        self._store: FilesystemSessionHistoryStore = (
            store or FilesystemSessionHistoryStore()
        )

    async def load(self) -> WorkflowDataDAO:
        """Resolve the parent session and discover all child sessions.

        Returns:
            WorkflowDataDAO: Full workflow snapshot with parent and children.

        Raises:
            ValueError: When the session reference cannot be resolved.
        """
        parent_session_id: str = await self._resolve_parent_session_id()
        parent_metadata: Optional[SessionHistoryMetadataDAO] = (
            await self._load_parent_metadata(session_id=parent_session_id)
        )
        parent_events: list[SessionHistoryEventDAO] = await self._load_parent_events(
            session_id=parent_session_id,
        )
        children: list[ChildSessionSummaryDAO] = self._discover_children(
            parent_session_id=parent_session_id,
            parent_events=parent_events,
        )
        is_complete: bool = self._detect_workflow_complete(events=parent_events)
        orchestrator_context: Optional[OrchestratorContextDAO] = (
            self.load_orchestrator_context(parent_session_id=parent_session_id)
        )
        return WorkflowDataDAO(
            parent_session_id=parent_session_id,
            parent_metadata=parent_metadata,
            parent_events=parent_events,
            children=children,
            is_complete=is_complete,
            orchestrator_context=orchestrator_context,
        )

    def load_orchestrator_context(
        self,
        *,
        parent_session_id: str,
    ) -> Optional[OrchestratorContextDAO]:
        """Load the orchestrator invocation context from disk.

        Reads ``orchestrator_context.json`` from the parent session directory.
        Degrades gracefully on missing file or parse errors.

        Args:
            parent_session_id (str): Orchestrator (parent) session id.

        Returns:
            Optional[OrchestratorContextDAO]: Parsed DAO, or ``None`` when the
                file does not exist or cannot be parsed.
        """
        path: Path = (
            self._store.root / parent_session_id / "orchestrator_context.json"
        )
        if not path.exists():
            return None
        try:
            return OrchestratorContextDAO.model_validate_json(
                path.read_bytes()
            )
        except (OSError, ValidationError, ValueError):
            return None

    def load_spawn_context(
        self,
        *,
        parent_session_id: str,
        child_session_id: str,
    ) -> Optional[SpawnContextDAO]:
        """Load the spawn invocation context for one child session.

        Reads ``spawn_context.json`` from the child capture directory.
        Degrades gracefully on missing file or parse errors.

        Args:
            parent_session_id (str): Orchestrator session id.
            child_session_id (str): Child session id.

        Returns:
            Optional[SpawnContextDAO]: Parsed DAO, or ``None`` when the
                file does not exist or cannot be parsed.
        """
        path: Path = self._child_capture_path(
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
            filename="spawn_context.json",
        )
        if not path.exists():
            return None
        try:
            return SpawnContextDAO.model_validate_json(path.read_bytes())
        except (OSError, ValidationError, ValueError):
            return None

    async def load_child_transcript_entries(
        self,
        *,
        parent_session_id: str,
        child_session_id: str,
    ) -> list[TranscriptEntryDAO]:
        """Load transcript entries for one child session.

        Prefers canonical history when it exists; falls back to captured
        ``stdout.jsonl`` lines so ephemeral (non-history) children can still
        be inspected.

        Args:
            parent_session_id (str): Orchestrator session id.
            child_session_id (str): Child session id to load.

        Returns:
            list[TranscriptEntryDAO]: Transcript entries in order.
        """
        if await self._store.session_exists(session_id=child_session_id):
            return await self._load_transcript_from_canonical_history(
                session_id=child_session_id,
            )
        return self._load_transcript_from_stdout_capture(
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
        )

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
            return stderr_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError:
            return []

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
        """Load all canonical events for the parent session.

        Args:
            session_id (str): Parent session id.

        Returns:
            list[SessionHistoryEventDAO]: Events in sequence order.
        """
        try:
            return await self._store.load_events(session_id=session_id)
        except FileNotFoundError:
            return []

    def _discover_children(
        self,
        *,
        parent_session_id: str,
        parent_events: list[SessionHistoryEventDAO],
    ) -> list[ChildSessionSummaryDAO]:
        """Discover child sessions from history events and capture directories.

        Args:
            parent_session_id (str): Orchestrator session id.
            parent_events (list[SessionHistoryEventDAO]): Parent event log.

        Returns:
            list[ChildSessionSummaryDAO]: Deduplicated summaries.
        """
        from_events: list[ChildSessionSummaryDAO] = (
            self._discover_children_from_events(
                parent_session_id=parent_session_id,
                parent_events=parent_events,
            )
        )
        from_dirs: list[ChildSessionSummaryDAO] = (
            self._discover_children_from_capture_dirs(
                parent_session_id=parent_session_id,
            )
        )
        return self._merge_child_discoveries(
            from_events=from_events,
            from_dirs=from_dirs,
        )

    def _discover_children_from_events(
        self,
        *,
        parent_session_id: str,
        parent_events: list[SessionHistoryEventDAO],
    ) -> list[ChildSessionSummaryDAO]:
        """Build child summaries from ``sub_agent_spawned``/``sub_agent_completed`` events.

        Args:
            parent_session_id (str): Orchestrator session id for capture probing.
            parent_events (list[SessionHistoryEventDAO]): Parent event log.

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
                )
            elif event.kind == "sub_agent_completed":
                child_id = event.payload.metadata.get("sub_agent_id", "")
                terminal_kind: str = event.payload.metadata.get(
                    "terminal_kind", "sub_agent_failed"
                )
                if not child_id or child_id not in summaries:
                    continue
                status: str = _TERMINAL_KIND_TO_STATUS.get(terminal_kind, "failed")
                summaries[child_id] = summaries[child_id].model_copy(
                    update={"status": status}
                )
        return list(summaries.values())

    def _discover_children_from_capture_dirs(
        self,
        *,
        parent_session_id: str,
    ) -> list[ChildSessionSummaryDAO]:
        """Build child summaries by scanning ``children/`` capture directories.

        Args:
            parent_session_id (str): Orchestrator session id.

        Returns:
            list[ChildSessionSummaryDAO]: Summaries for each capture directory.
        """
        children_root: Path = self._store.root / parent_session_id / "children"
        if not children_root.is_dir():
            return []
        result: list[ChildSessionSummaryDAO] = []
        for child_dir in sorted(children_root.iterdir()):
            if not child_dir.is_dir():
                continue
            result.append(
                self._build_child_summary(
                    child_session_id=child_dir.name,
                    task_id=None,
                    parent_session_id=parent_session_id,
                    status="running",
                )
            )
        return result

    def _build_child_summary(
        self,
        *,
        child_session_id: str,
        task_id: Optional[str],
        parent_session_id: str,
        status: str,
    ) -> ChildSessionSummaryDAO:
        """Build one child summary with capture-file presence flags and prompt preview.

        Args:
            child_session_id (str): Child session id.
            task_id (Optional[str]): Pool task id, or ``None``.
            parent_session_id (str): Parent session id.
            status (str): Initial lifecycle status.

        Returns:
            ChildSessionSummaryDAO: Summary with capture presence flags and prompt preview.
        """
        spawn: Optional[SpawnContextDAO] = self.load_spawn_context(
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
        )
        prompt_preview: str = ""
        if spawn is not None:
            raw: str = spawn.prompt[:60]
            prompt_preview = (raw + "…") if len(spawn.prompt) > 60 else raw
        return ChildSessionSummaryDAO(
            session_id=child_session_id,
            task_id=task_id,
            status=status,
            has_stdout_capture=self._child_capture_path(
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
            prompt_preview=prompt_preview,
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
        extras: list[ChildSessionSummaryDAO] = [
            s for s in from_dirs if s.session_id not in seen
        ]
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
            bool: ``True`` when any terminal event kind is present.
        """
        return any(event.kind in _TERMINAL_EVENT_KINDS for event in events)

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
        return (
            self._store.root
            / parent_session_id
            / "children"
            / child_session_id
            / filename
        )

    async def _load_transcript_from_canonical_history(
        self,
        *,
        session_id: str,
    ) -> list[TranscriptEntryDAO]:
        """Load transcript from a child session's canonical history store.

        Args:
            session_id (str): Child session id.

        Returns:
            list[TranscriptEntryDAO]: Projected transcript entries.
        """
        events: list[SessionHistoryEventDAO] = await self._store.load_events(
            session_id=session_id,
        )
        return ReplayEntryProjector.build_entries(events=events)

    def _load_transcript_from_stdout_capture(
        self,
        *,
        parent_session_id: str,
        child_session_id: str,
    ) -> list[TranscriptEntryDAO]:
        """Reconstruct transcript from captured stdout.jsonl lines.

        Args:
            parent_session_id (str): Parent session id.
            child_session_id (str): Child session id.

        Returns:
            list[TranscriptEntryDAO]: Reconstructed transcript entries.
        """
        stdout_path: Path = self._child_capture_path(
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
            filename="stdout.jsonl",
        )
        if not stdout_path.exists():
            return []
        return _project_stdout_capture(path=stdout_path)


# ---------------------------------------------------------------------------
# Module-level projection helpers (no instance state needed)
# ---------------------------------------------------------------------------


class _ToolBuffers:
    """Accumulator for one in-progress tool call reconstructed from stdout.

    Collects streamed argument fragments and an optional result so the
    projector can emit a matched tool-call + tool-result pair.

    Attributes:
        tool_name (str): Tool name from the ``tool_call_start`` event.
        arguments_chunks (list[str]): Partial argument JSON fragments.
        result (Optional[str]): Tool output from the matching ``tool_result``.
    """

    def __init__(self, *, tool_name: str) -> None:
        """Seed an empty accumulator for one tool call.

        Args:
            tool_name (str): Tool name from the ``tool_call_start`` event.
        """
        self.tool_name: str = tool_name
        self.arguments_chunks: list[str] = []
        self.result: Optional[str] = None

    def commit_call(self, *, entries: list[TranscriptEntryDAO]) -> None:
        """Emit a tool-call entry from the accumulated argument fragments.

        Tries to parse the concatenated fragment as JSON; falls back to a
        ``{"raw": ...}`` dict when parsing fails.

        Args:
            entries (list[TranscriptEntryDAO]): Receiver for the new entry.
        """
        tool_input_raw: str = "".join(self.arguments_chunks)
        try:
            tool_input: dict = json.loads(tool_input_raw)
        except (json.JSONDecodeError, ValueError):
            tool_input = {"raw": tool_input_raw}
        entries.append(
            TranscriptEntryDAO(
                kind="tool",
                tool_name=self.tool_name,
                tool_input=tool_input,
            )
        )

    def commit_result(self, *, entries: list[TranscriptEntryDAO]) -> None:
        """Emit a tool-result entry carrying the stored result text.

        Args:
            entries (list[TranscriptEntryDAO]): Receiver for the new entry.
        """
        entries.append(
            TranscriptEntryDAO(
                kind="tool",
                tool_name=self.tool_name,
                output=self.result,
            )
        )


def _project_stdout_capture(*, path: Path) -> list[TranscriptEntryDAO]:
    """Project captured stdout.jsonl lines into TranscriptEntryDAO objects.

    Handles thinking blocks (delta + end), tool call/result pairs, and
    assistant text blocks. Non-JSON lines and unknown kinds are silently
    ignored. Flushes open buffers at EOF so partial captures still yield
    visible content.

    Args:
        path (Path): Path to the stdout.jsonl capture file.

    Returns:
        list[TranscriptEntryDAO]: Projected transcript entries in event order.
    """
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO  # noqa: PLC0415

    try:
        raw_lines: list[str] = path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return []

    entries: list[TranscriptEntryDAO] = []
    assistant_text: str = ""
    thinking_text: str = ""
    pending_tools: dict[str, _ToolBuffers] = {}

    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            event: AgentStreamEventDAO = AgentStreamEventDAO.model_validate_json(line)
        except Exception:
            continue

        kind = event.kind

        if kind == "thinking_delta" and event.delta:
            thinking_text += event.delta
        elif kind == "thinking_end":
            if thinking_text:
                entries.append(
                    TranscriptEntryDAO(kind="thinking", content=thinking_text)
                )
                thinking_text = ""
        elif kind == "tool_call_start" and event.block_id and event.tool_name:
            pending_tools[event.block_id] = _ToolBuffers(tool_name=event.tool_name)
        elif kind == "tool_call_delta" and event.block_id and event.tool_arguments_delta:
            buffers: Optional[_ToolBuffers] = pending_tools.get(event.block_id)
            if buffers is not None:
                buffers.arguments_chunks.append(event.tool_arguments_delta)
        elif kind == "tool_call_end" and event.block_id:
            buffers = pending_tools.get(event.block_id)
            if buffers is not None:
                buffers.commit_call(entries=entries)
        elif kind == "tool_result" and event.tool_call_id:
            buffers = pending_tools.get(event.tool_call_id)
            if buffers is not None:
                buffers.result = event.content
                buffers.commit_result(entries=entries)
        elif kind == "text_delta" and event.delta:
            assistant_text += event.delta
        elif kind in ("text_end", "run_completed"):
            if assistant_text:
                entries.append(
                    TranscriptEntryDAO(kind="assistant", answer=assistant_text)
                )
                assistant_text = ""

    if thinking_text:
        entries.append(TranscriptEntryDAO(kind="thinking", content=thinking_text))
    if assistant_text:
        entries.append(TranscriptEntryDAO(kind="assistant", answer=assistant_text))
    return entries
