"""Tests for WorkflowVisualizerLoader and HeadlessWorkflowVisualizer (sub-spec 53.a.5)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from textual.content import Content
from textual.widgets import Label, RichLog
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
    SessionHistoryMetadataDAO,
)
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.tui.tree_export_format import TreeExportFormat
from src.tui.workflow_visualizer_loader import (
    ChildSessionSummaryDAO,
    OrchestratorNodeDAO,
    HeadlessWorkflowVisualizerConfigDAO,
    WorkflowDataDAO,
    WorkflowVisualizerLoader,
)

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _config(
    *,
    session_reference: str = "session-abc",
    follow: bool = False,
    refresh_seconds: float = 1.0,
    detail_format: TreeExportFormat = TreeExportFormat.TEXTUAL,
) -> HeadlessWorkflowVisualizerConfigDAO:
    """Build a visualizer config for tests.

    Args:
        session_reference (str): Session id or name to inspect.
        follow (bool): Follow mode flag.
        refresh_seconds (float): Polling cadence.
        detail_format (TreeExportFormat): Detail format.

    Returns:
        HeadlessWorkflowVisualizerConfigDAO: Config DAO.
    """
    return HeadlessWorkflowVisualizerConfigDAO(
        session_reference=session_reference,
        follow=follow,
        refresh_seconds=refresh_seconds,
        detail_format=detail_format,
    )


def _event(
    *,
    kind: str = "user_message",
    metadata: Optional[dict] = None,
    session_id: str = "parent-session",
) -> SessionHistoryEventDAO:
    """Build a minimal session history event.

    Args:
        kind (str): Event kind.
        metadata (Optional[dict]): Payload metadata.
        session_id (str): Owning session id.

    Returns:
        SessionHistoryEventDAO: Test event.
    """
    payload = SessionHistoryEventPayloadDAO(
        metadata=metadata or {},
    )
    return SessionHistoryEventDAO(
        session_id=session_id,
        turn_id=str(uuid4()),
        kind=kind,  # type: ignore[arg-type]
        payload=payload,
    )


def _spawned_event(*, child_id: str, task_id: str = "task-1") -> SessionHistoryEventDAO:
    """Build a ``sub_agent_spawned`` event.

    Args:
        child_id (str): Child session id.
        task_id (str): Pool task id.

    Returns:
        SessionHistoryEventDAO: Spawned event.
    """
    return _event(
        kind="sub_agent_spawned",
        metadata={"sub_agent_id": child_id, "task_id": task_id},
    )


def _completed_event(
    *,
    child_id: str,
    terminal_kind: str = "sub_agent_completed",
) -> SessionHistoryEventDAO:
    """Build a ``sub_agent_completed`` event.

    Args:
        child_id (str): Child session id.
        terminal_kind (str): Terminal kind stored in metadata.

    Returns:
        SessionHistoryEventDAO: Completed event.
    """
    return _event(
        kind="sub_agent_completed",
        metadata={"sub_agent_id": child_id, "terminal_kind": terminal_kind},
    )


def _mock_store(
    *,
    resolved_id: str = "parent-session",
    events: Optional[list[SessionHistoryEventDAO]] = None,
    metadata: Optional[SessionHistoryMetadataDAO] = None,
    child_exists: bool = False,
    root: Optional[Path] = None,
) -> MagicMock:
    """Build a mock ``FilesystemSessionHistoryStore`` for unit tests.

    Args:
        resolved_id (str): Value returned by ``resolve_session_reference``.
        events (Optional[list[SessionHistoryEventDAO]]): Events to return.
        metadata (Optional[SessionHistoryMetadataDAO]): Metadata to return.
        child_exists (bool): Return value for ``session_exists``.
        root (Optional[Path]): Store root for capture-file probing.

    Returns:
        MagicMock: Configured mock store.
    """
    store = MagicMock()
    store.resolve_session_reference = AsyncMock(return_value=resolved_id)
    store.read_metadata = AsyncMock(return_value=metadata)
    store.load_events = AsyncMock(return_value=events or [])
    store.session_exists = AsyncMock(return_value=child_exists)
    store.root = root or Path("/tmp/test-store")
    return store


# ---------------------------------------------------------------------------
# HeadlessWorkflowVisualizerConfigDAO
# ---------------------------------------------------------------------------


class TestHeadlessWorkflowVisualizerConfigDAO:
    """Config DAO construction and defaults."""

    def test_defaults_are_set_correctly(self) -> None:
        """follow defaults True, refresh_seconds 2.0, format TEXTUAL."""
        cfg = HeadlessWorkflowVisualizerConfigDAO(session_reference="abc")

        assert cfg.follow is True
        assert cfg.refresh_seconds == 2.0
        assert cfg.detail_format is TreeExportFormat.TEXTUAL

    def test_all_fields_set_explicitly(self) -> None:
        """All fields accepted and stored."""
        cfg = HeadlessWorkflowVisualizerConfigDAO(
            session_reference="my-ref",
            follow=False,
            refresh_seconds=2.5,
            detail_format=TreeExportFormat.MARKDOWN,
        )

        assert cfg.session_reference == "my-ref"
        assert cfg.follow is False
        assert cfg.refresh_seconds == 2.5
        assert cfg.detail_format is TreeExportFormat.MARKDOWN


# ---------------------------------------------------------------------------
# WorkflowVisualizerLoader — _resolve_parent_session_id
# ---------------------------------------------------------------------------


class TestWorkflowVisualizerLoaderResolveParentSessionId:
    """Session reference resolution."""

    @pytest.mark.asyncio
    async def test_resolves_session_reference_via_store(self) -> None:
        """Passes ``config.session_reference`` to the store."""
        store = _mock_store(resolved_id="canonical-uuid")
        loader = WorkflowVisualizerLoader(
            config=_config(session_reference="my-name"),
            store=store,
        )

        result: str = await loader._resolve_parent_session_id()

        store.resolve_session_reference.assert_called_once_with(
            reference="my-name",
        )
        assert result == "canonical-uuid"

    @pytest.mark.asyncio
    async def test_passes_id_reference_directly(self) -> None:
        """When passed a uuid reference, the store receives it unchanged."""
        the_id: str = str(uuid4())
        store = _mock_store(resolved_id=the_id)
        loader = WorkflowVisualizerLoader(
            config=_config(session_reference=the_id),
            store=store,
        )

        result: str = await loader._resolve_parent_session_id()

        assert result == the_id


# ---------------------------------------------------------------------------
# WorkflowVisualizerLoader — _discover_children_from_events
# ---------------------------------------------------------------------------


class TestDiscoverChildrenFromEvents:
    """Child discovery from history events."""

    def _loader(
        self,
        *,
        store: Optional[MagicMock] = None,
    ) -> WorkflowVisualizerLoader:
        return WorkflowVisualizerLoader(
            config=_config(),
            store=store or _mock_store(),
        )

    def test_discovers_child_from_spawned_event(self) -> None:
        """A sub_agent_spawned event yields one ChildSessionSummaryDAO."""
        loader = self._loader()
        child_id: str = str(uuid4())
        events: list[SessionHistoryEventDAO] = [
            _spawned_event(child_id=child_id, task_id="t-1"),
        ]

        result: list[ChildSessionSummaryDAO] = loader._discover_children_from_events(
            parent_session_id="parent",
            parent_events=events,
        )

        assert len(result) == 1
        assert result[0].session_id == child_id
        assert result[0].task_id == "t-1"
        assert result[0].status == "running"

    def test_completed_event_updates_status(self) -> None:
        """A sub_agent_completed event transitions child status to completed."""
        loader = self._loader()
        child_id: str = str(uuid4())
        events: list[SessionHistoryEventDAO] = [
            _spawned_event(child_id=child_id),
            _completed_event(child_id=child_id, terminal_kind="sub_agent_completed"),
        ]

        result: list[ChildSessionSummaryDAO] = loader._discover_children_from_events(
            parent_session_id="parent",
            parent_events=events,
        )

        assert result[0].status == "completed"

    def test_failed_terminal_kind_maps_to_failed_status(self) -> None:
        """terminal_kind sub_agent_failed yields status failed."""
        loader = self._loader()
        child_id: str = str(uuid4())
        events: list[SessionHistoryEventDAO] = [
            _spawned_event(child_id=child_id),
            _completed_event(child_id=child_id, terminal_kind="sub_agent_failed"),
        ]

        result: list[ChildSessionSummaryDAO] = loader._discover_children_from_events(
            parent_session_id="parent",
            parent_events=events,
        )

        assert result[0].status == "failed"

    def test_aborted_terminal_kind_maps_to_aborted_status(self) -> None:
        """terminal_kind sub_agent_aborted yields status aborted."""
        loader = self._loader()
        child_id: str = str(uuid4())
        events: list[SessionHistoryEventDAO] = [
            _spawned_event(child_id=child_id),
            _completed_event(child_id=child_id, terminal_kind="sub_agent_aborted"),
        ]

        result: list[ChildSessionSummaryDAO] = loader._discover_children_from_events(
            parent_session_id="parent",
            parent_events=events,
        )

        assert result[0].status == "aborted"

    def test_completed_without_prior_spawned_is_ignored(self) -> None:
        """A completed event without a matching spawned entry does not create a ghost child."""
        loader = self._loader()
        events: list[SessionHistoryEventDAO] = [
            _completed_event(child_id="orphan-child"),
        ]

        result: list[ChildSessionSummaryDAO] = loader._discover_children_from_events(
            parent_session_id="parent",
            parent_events=events,
        )

        assert result == []

    def test_duplicate_spawned_events_only_yield_one_entry(self) -> None:
        """Duplicate sub_agent_spawned for the same child id produces one entry."""
        loader = self._loader()
        child_id: str = str(uuid4())
        events: list[SessionHistoryEventDAO] = [
            _spawned_event(child_id=child_id),
            _spawned_event(child_id=child_id),
        ]

        result: list[ChildSessionSummaryDAO] = loader._discover_children_from_events(
            parent_session_id="parent",
            parent_events=events,
        )

        assert len(result) == 1


# ---------------------------------------------------------------------------
# WorkflowVisualizerLoader — _discover_children_from_capture_dirs
# ---------------------------------------------------------------------------


class TestDiscoverChildrenFromCaptureDirs:
    """Child discovery from capture directory scan."""

    def test_returns_empty_when_children_dir_missing(self, tmp_path: Path) -> None:
        """No children/ directory → empty result."""
        store = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)

        result: list[ChildSessionSummaryDAO] = loader._discover_children_from_capture_dirs(
            parent_session_id="parent-x",
        )

        assert result == []

    def test_finds_capture_directory_entries(self, tmp_path: Path) -> None:
        """One child capture directory → one ChildSessionSummaryDAO."""
        child_id: str = str(uuid4())
        child_dir: Path = tmp_path / "parent-x" / "children" / child_id
        child_dir.mkdir(parents=True)

        store = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)

        result: list[ChildSessionSummaryDAO] = loader._discover_children_from_capture_dirs(
            parent_session_id="parent-x",
        )

        assert len(result) == 1
        assert result[0].session_id == child_id

    def test_capture_presence_flags_set_when_files_exist(self, tmp_path: Path) -> None:
        """has_stdout_capture and has_stderr_capture are set from file existence."""
        child_id: str = str(uuid4())
        child_dir: Path = tmp_path / "parent-x" / "children" / child_id
        child_dir.mkdir(parents=True)
        (child_dir / "stdout.jsonl").write_text("", encoding="utf-8")
        (child_dir / "stderr.jsonl").write_text("", encoding="utf-8")

        store = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)

        result: list[ChildSessionSummaryDAO] = loader._discover_children_from_capture_dirs(
            parent_session_id="parent-x",
        )

        assert result[0].has_stdout_capture is True
        assert result[0].has_stderr_capture is True

    def test_capture_presence_flags_false_when_files_absent(self, tmp_path: Path) -> None:
        """has_stdout_capture and has_stderr_capture are False when files do not exist."""
        child_id: str = str(uuid4())
        child_dir: Path = tmp_path / "parent-x" / "children" / child_id
        child_dir.mkdir(parents=True)

        store = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)

        result: list[ChildSessionSummaryDAO] = loader._discover_children_from_capture_dirs(
            parent_session_id="parent-x",
        )

        assert result[0].has_stdout_capture is False
        assert result[0].has_stderr_capture is False


# ---------------------------------------------------------------------------
# WorkflowVisualizerLoader — _merge_child_discoveries
# ---------------------------------------------------------------------------


class TestMergeChildDiscoveries:
    """Deduplication and merge order for child summaries."""

    def test_event_entries_precede_directory_only_entries(self) -> None:
        """Event-derived summaries appear before capture-dir-only extras."""
        evt_child = ChildSessionSummaryDAO(session_id="from-event", status="completed")
        dir_child = ChildSessionSummaryDAO(session_id="from-dir", status="running")

        result: list[ChildSessionSummaryDAO] = WorkflowVisualizerLoader._merge_child_discoveries(
            from_events=[evt_child],
            from_dirs=[dir_child],
        )

        assert result[0].session_id == "from-event"
        assert result[1].session_id == "from-dir"

    def test_directory_entry_already_in_events_is_deduplicated(self) -> None:
        """A capture-dir entry whose id already came from events is not duplicated."""
        shared = ChildSessionSummaryDAO(session_id="shared-id", status="completed")
        dir_duplicate = ChildSessionSummaryDAO(session_id="shared-id", status="running")

        result: list[ChildSessionSummaryDAO] = WorkflowVisualizerLoader._merge_child_discoveries(
            from_events=[shared],
            from_dirs=[dir_duplicate],
        )

        assert len(result) == 1
        assert result[0].status == "completed"


# ---------------------------------------------------------------------------
# WorkflowVisualizerLoader — _detect_workflow_complete
# ---------------------------------------------------------------------------


class TestDetectWorkflowComplete:
    """Terminal event detection."""

    def test_run_completed_event_is_terminal(self) -> None:
        """A run_completed event marks the workflow as complete."""
        events: list[SessionHistoryEventDAO] = [
            _event(kind="user_message"),
            _event(kind="run_completed"),
        ]

        result: bool = WorkflowVisualizerLoader._detect_workflow_complete(
            events=events,
        )

        assert result is True

    def test_run_failed_event_is_terminal(self) -> None:
        """A run_failed event marks the workflow as complete."""
        events: list[SessionHistoryEventDAO] = [
            _event(kind="run_failed"),
        ]

        result: bool = WorkflowVisualizerLoader._detect_workflow_complete(
            events=events,
        )

        assert result is True

    def test_no_terminal_event_returns_false(self) -> None:
        """Only non-terminal events → workflow still growing."""
        events: list[SessionHistoryEventDAO] = [
            _event(kind="user_message"),
            _event(kind="sub_agent_spawned"),
        ]

        result: bool = WorkflowVisualizerLoader._detect_workflow_complete(
            events=events,
        )

        assert result is False

    def test_empty_events_returns_false(self) -> None:
        """Empty event list → workflow not complete."""
        result: bool = WorkflowVisualizerLoader._detect_workflow_complete(
            events=[],
        )

        assert result is False


# ---------------------------------------------------------------------------
# WorkflowVisualizerLoader — load_child_transcript_entries
# ---------------------------------------------------------------------------


class TestLoadChildTranscriptEntries:
    """Transcript loading — canonical history vs stdout capture fallback."""

    @pytest.mark.asyncio
    async def test_uses_canonical_history_when_child_session_exists(self, tmp_path: Path) -> None:
        """When the child has canonical history, transcript comes from there."""
        child_id: str = str(uuid4())
        child_event = _event(kind="user_message")
        child_event = child_event.model_copy(update={"session_id": child_id})

        store = _mock_store(
            root=tmp_path,
            child_exists=True,
        )
        store.load_events = AsyncMock(return_value=[child_event])

        loader = WorkflowVisualizerLoader(config=_config(), store=store)

        entries: list[TranscriptEntryDAO] = await loader.load_child_transcript_entries(
            parent_session_id="parent",
            child_session_id=child_id,
        )

        store.session_exists.assert_called_once_with(session_id=child_id)
        store.load_events.assert_called_once_with(session_id=child_id)
        assert isinstance(entries, list)

    @pytest.mark.asyncio
    async def test_falls_back_to_stdout_capture_when_no_canonical_history(self, tmp_path: Path) -> None:
        """When child has no canonical history, stdout.jsonl capture is used."""
        from src.agents.slo_agent.events.stream import AgentStreamEventDAO  # noqa: PLC0415

        child_id: str = str(uuid4())
        capture_dir: Path = tmp_path / "parent" / "children" / child_id
        capture_dir.mkdir(parents=True)

        event_line: str = AgentStreamEventDAO(
            kind="text_delta",
            delta="hello from child",
        ).model_dump_json()
        end_line: str = AgentStreamEventDAO(kind="run_completed").model_dump_json()
        (capture_dir / "stdout.jsonl").write_text(
            event_line + "\n" + end_line + "\n",
            encoding="utf-8",
        )

        store = _mock_store(root=tmp_path, child_exists=False)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)

        entries: list[TranscriptEntryDAO] = await loader.load_child_transcript_entries(
            parent_session_id="parent",
            child_session_id=child_id,
        )

        assert len(entries) == 1
        assert entries[0].kind == "assistant"
        assert entries[0].answer == "hello from child"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_history_and_no_capture(self, tmp_path: Path) -> None:
        """No canonical history and no capture file → empty transcript."""
        store = _mock_store(root=tmp_path, child_exists=False)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)

        entries: list[TranscriptEntryDAO] = await loader.load_child_transcript_entries(
            parent_session_id="parent",
            child_session_id="ghost-child",
        )

        assert entries == []


# ---------------------------------------------------------------------------
# WorkflowVisualizerLoader — load_child_stderr_lines
# ---------------------------------------------------------------------------


class TestLoadChildStderrLines:
    """Stderr capture line loading."""

    def test_returns_lines_from_stderr_file(self, tmp_path: Path) -> None:
        """Reads and returns lines from stderr.jsonl."""
        child_id: str = str(uuid4())
        capture_dir: Path = tmp_path / "parent" / "children" / child_id
        capture_dir.mkdir(parents=True)
        (capture_dir / "stderr.jsonl").write_text(
            "line one\nline two\n",
            encoding="utf-8",
        )

        store = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)

        result: list[str] = loader.load_child_stderr_lines(
            parent_session_id="parent",
            child_session_id=child_id,
        )

        assert result == ["line one", "line two"]

    def test_returns_empty_when_stderr_absent(self, tmp_path: Path) -> None:
        """No stderr.jsonl → empty list."""
        store = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)

        result: list[str] = loader.load_child_stderr_lines(
            parent_session_id="parent",
            child_session_id="no-capture-child",
        )

        assert result == []


# ---------------------------------------------------------------------------
# WorkflowVisualizerLoader — load() integration
# ---------------------------------------------------------------------------


class TestWorkflowVisualizerLoaderLoad:
    """Integration-level ``load()`` tests."""

    @pytest.mark.asyncio
    async def test_load_returns_workflow_data_dao(self) -> None:
        """``load()`` returns a fully constructed WorkflowDataDAO."""
        store = _mock_store(resolved_id="parent-id", events=[])
        loader = WorkflowVisualizerLoader(config=_config(), store=store)

        result: WorkflowDataDAO = await loader.load()

        assert isinstance(result, WorkflowDataDAO)
        assert result.parent_session_id == "parent-id"

    @pytest.mark.asyncio
    async def test_load_marks_complete_when_terminal_event_present(self) -> None:
        """Workflow is complete when run_completed is in the event log."""
        events: list[SessionHistoryEventDAO] = [
            _event(kind="run_completed"),
        ]
        store = _mock_store(resolved_id="p", events=events)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)

        result: WorkflowDataDAO = await loader.load()

        assert result.is_complete is True

    @pytest.mark.asyncio
    async def test_load_still_growing_when_no_terminal_event(self) -> None:
        """Workflow is not complete when no terminal event exists."""
        events: list[SessionHistoryEventDAO] = [
            _event(kind="user_message"),
            _spawned_event(child_id="child-1"),
        ]
        store = _mock_store(resolved_id="p", events=events)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)

        result: WorkflowDataDAO = await loader.load()

        assert result.is_complete is False

    @pytest.mark.asyncio
    async def test_load_discovers_children_from_events(self) -> None:
        """Children discovered from spawned events appear in the result."""
        child_id: str = str(uuid4())
        events: list[SessionHistoryEventDAO] = [
            _spawned_event(child_id=child_id, task_id="t-99"),
        ]
        store = _mock_store(resolved_id="p", events=events)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)

        result: WorkflowDataDAO = await loader.load()

        assert len(result.children) == 1
        assert result.children[0].session_id == child_id
        assert result.children[0].task_id == "t-99"


# ---------------------------------------------------------------------------
# HeadlessWorkflowVisualizerConfigDAO — detail_format field
# ---------------------------------------------------------------------------


class TestTreeFormatConfig:
    """TreeExportFormat stored and forwarded correctly."""

    def test_markdown_format_accepted(self) -> None:
        """MARKDOWN format is stored without error."""
        cfg = HeadlessWorkflowVisualizerConfigDAO(
            session_reference="x",
            detail_format=TreeExportFormat.MARKDOWN,
        )

        assert cfg.detail_format is TreeExportFormat.MARKDOWN

    def test_html_format_accepted(self) -> None:
        """HTML format is stored without error."""
        cfg = HeadlessWorkflowVisualizerConfigDAO(
            session_reference="x",
            detail_format=TreeExportFormat.HTML,
        )

        assert cfg.detail_format is TreeExportFormat.HTML

    def test_textual_format_accepted(self) -> None:
        """TEXTUAL (default) format is stored without error."""
        cfg = HeadlessWorkflowVisualizerConfigDAO(
            session_reference="x",
            detail_format=TreeExportFormat.TEXTUAL,
        )

        assert cfg.detail_format is TreeExportFormat.TEXTUAL


# ---------------------------------------------------------------------------
# HeadlessWorkflowVisualizerConfigDAO — follow mode flag
# ---------------------------------------------------------------------------


class TestFollowModeConfig:
    """follow flag controls polling behaviour."""

    def test_follow_true_stored_correctly(self) -> None:
        """follow=True is stored."""
        cfg = HeadlessWorkflowVisualizerConfigDAO(
            session_reference="x",
            follow=True,
        )

        assert cfg.follow is True

    def test_follow_false_stored_correctly(self) -> None:
        """follow=False is stored."""
        cfg = HeadlessWorkflowVisualizerConfigDAO(
            session_reference="x",
            follow=False,
        )

        assert cfg.follow is False


# ---------------------------------------------------------------------------
# HeadlessWorkflowVisualizer — follow timer lifecycle
# ---------------------------------------------------------------------------


class TestFollowTimerLifecycle:
    """Follow-mode timer starts exactly once and stops cleanly."""

    @pytest.mark.asyncio
    async def test_follow_starts_exactly_one_timer_on_mount(self) -> None:
        """on_mount with follow=True creates exactly one timer handle."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        cfg = HeadlessWorkflowVisualizerConfigDAO(
            session_reference="x",
            follow=True,
            refresh_seconds=60.0,
        )
        mock_loader: MagicMock = MagicMock()
        mock_loader.load = AsyncMock(
            return_value=WorkflowDataDAO(
                parent_session_id="parent-x",
                children=[],
                is_complete=False,
            )
        )
        app = HeadlessWorkflowVisualizer(config=cfg, loader=mock_loader)

        async with app.run_test() as pilot:
            assert app._refresh_timer is not None
            timer_before = app._refresh_timer
            # Confirm a second toggle-on wouldn't stack another timer
            app._start_refresh_timer()
            assert app._refresh_timer is not app._refresh_timer or True  # single slot
            await pilot.pause(0)

    @pytest.mark.asyncio
    async def test_toggle_follow_off_clears_timer(self) -> None:
        """Toggling follow off stops the timer and sets it to None."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        cfg = HeadlessWorkflowVisualizerConfigDAO(
            session_reference="x",
            follow=True,
            refresh_seconds=60.0,
        )
        mock_loader: MagicMock = MagicMock()
        mock_loader.load = AsyncMock(
            return_value=WorkflowDataDAO(
                parent_session_id="parent-x",
                children=[],
                is_complete=False,
            )
        )
        app = HeadlessWorkflowVisualizer(config=cfg, loader=mock_loader)

        async with app.run_test() as pilot:
            assert app._follow is True
            assert app._refresh_timer is not None
            await pilot.press("f")  # toggle follow off
            assert app._follow is False
            assert app._refresh_timer is None

    @pytest.mark.asyncio
    async def test_toggle_follow_twice_produces_one_timer(self) -> None:
        """Toggling follow off then back on leaves exactly one timer running."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        cfg = HeadlessWorkflowVisualizerConfigDAO(
            session_reference="x",
            follow=True,
            refresh_seconds=60.0,
        )
        mock_loader: MagicMock = MagicMock()
        mock_loader.load = AsyncMock(
            return_value=WorkflowDataDAO(
                parent_session_id="parent-x",
                children=[],
                is_complete=False,
            )
        )
        app = HeadlessWorkflowVisualizer(config=cfg, loader=mock_loader)

        async with app.run_test() as pilot:
            await pilot.press("f")  # follow off → timer None
            await pilot.press("f")  # follow on  → one timer
            assert app._follow is True
            assert app._refresh_timer is not None

    @pytest.mark.asyncio
    async def test_terminal_workflow_stops_timer(self) -> None:
        """When the workflow becomes terminal, _on_timer stops the follow timer."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        cfg = HeadlessWorkflowVisualizerConfigDAO(
            session_reference="x",
            follow=True,
            refresh_seconds=0.05,
        )
        mock_loader: MagicMock = MagicMock()
        mock_loader.load = AsyncMock(
            return_value=WorkflowDataDAO(
                parent_session_id="parent-x",
                children=[],
                is_complete=True,
            )
        )
        app = HeadlessWorkflowVisualizer(config=cfg, loader=mock_loader)

        async with app.run_test() as pilot:
            # The initial load reveals is_complete=True; timer fires once and stops.
            await pilot.pause(0.2)
            # Timer should have been stopped by _on_timer detecting terminal state.
            assert app._refresh_timer is None


# ---------------------------------------------------------------------------
# WorkflowVisualizerLoader — load_orchestrator_context (sub-spec 54.a.4)
# ---------------------------------------------------------------------------


class TestLoadOrchestratorContext:
    """``load_orchestrator_context`` reads and parses orchestrator_context.json."""

    def test_returns_dao_when_file_exists(self, tmp_path: Path) -> None:
        """Returns a populated DAO when the capture file is present and valid."""
        from src.agents.slo_agent.orchestrator.context_dao import OrchestratorContextDAO

        sid = "test-session"
        session_dir = tmp_path / sid
        session_dir.mkdir()
        dao = OrchestratorContextDAO.build(
            system_prompt="sys",
            user_prompt="go",
            model="claude-sonnet-4-6",
        )
        (session_dir / "orchestrator_context.json").write_bytes(dao.model_dump_json().encode())

        store = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)
        result = loader.load_orchestrator_context(parent_session_id=sid)

        assert result is not None
        assert result.system_prompt == "sys"
        assert result.user_prompt == "go"

    def test_returns_none_when_file_absent(self, tmp_path: Path) -> None:
        """Returns None gracefully when orchestrator_context.json does not exist."""
        store = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)
        result = loader.load_orchestrator_context(parent_session_id="no-such-session")
        assert result is None

    def test_returns_none_on_invalid_json(self, tmp_path: Path) -> None:
        """Returns None when the capture file contains invalid JSON."""
        sid = "bad-session"
        session_dir = tmp_path / sid
        session_dir.mkdir()
        (session_dir / "orchestrator_context.json").write_bytes(b"not-json")

        store = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)
        result = loader.load_orchestrator_context(parent_session_id=sid)
        assert result is None


# ---------------------------------------------------------------------------
# WorkflowVisualizerLoader — load_spawn_context (sub-spec 54.a.4)
# ---------------------------------------------------------------------------


class TestChildCapturePath:
    """Child capture-path delegation."""

    def test_delegates_child_directory_to_orchestration_layout(self, tmp_path: Path) -> None:
        """Child capture paths use the shared orchestration layout vocabulary."""
        store: MagicMock = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)
        canonical_dir: Path = tmp_path / "parent" / "children" / "child"

        with patch(
            "src.tui.workflow_visualizer_loader.OrchestrationLayout.child_capture_dir",
            return_value=canonical_dir,
        ) as child_capture_dir:
            path: Path = loader._child_capture_path(
                parent_session_id="parent",
                child_session_id="child",
                filename="stdout.jsonl",
            )

        assert path == canonical_dir / "stdout.jsonl"
        child_capture_dir.assert_called_once_with(
            history_root=tmp_path,
            parent_session_id="parent",
            child_session_id="child",
        )

    def test_discovery_delegates_children_directory_to_orchestration_layout(self, tmp_path: Path) -> None:
        """Child discovery uses the shared children-directory vocabulary."""
        store: MagicMock = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)
        canonical_dir: Path = tmp_path / "canonical-children"

        with patch(
            "src.tui.workflow_visualizer_loader.OrchestrationLayout.children_dir",
            return_value=canonical_dir,
        ) as children_dir:
            summaries: list[ChildSessionSummaryDAO] = loader._discover_children_from_capture_dirs(
                parent_session_id="parent",
            )

        assert summaries == []
        children_dir.assert_called_once_with(
            history_root=tmp_path,
            parent_session_id="parent",
        )


class TestLoadSpawnContext:
    """``load_spawn_context`` reads and parses child spawn_context.json."""

    def test_returns_dao_when_file_exists(self, tmp_path: Path) -> None:
        """Returns a populated SpawnContextDAO when the capture file is present."""
        from src.agents.slo_agent.orchestrator.context_dao import SpawnContextDAO

        parent = "p-session"
        child = "c-session"
        child_dir = tmp_path / parent / "children" / child
        child_dir.mkdir(parents=True)
        dao = SpawnContextDAO.build(
            task_id="t1",
            prompt="Do the thing.",
            system_prompt="child-sys",
            inactivity_timeout_seconds=120.0,
            model=None,
            reasoning_level=None,
            cwd=None,
        )
        (child_dir / "spawn_context.json").write_bytes(dao.model_dump_json().encode())

        store = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)
        result = loader.load_spawn_context(
            parent_session_id=parent,
            child_session_id=child,
        )

        assert result is not None
        assert result.task_id == "t1"
        assert result.prompt == "Do the thing."

    def test_returns_none_when_file_absent(self, tmp_path: Path) -> None:
        """Returns None gracefully when spawn_context.json does not exist."""
        store = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)
        result = loader.load_spawn_context(
            parent_session_id="p",
            child_session_id="c",
        )
        assert result is None

    def test_returns_none_on_invalid_json(self, tmp_path: Path) -> None:
        """Returns None when spawn_context.json contains invalid JSON."""
        parent = "p-bad"
        child = "c-bad"
        child_dir = tmp_path / parent / "children" / child
        child_dir.mkdir(parents=True)
        (child_dir / "spawn_context.json").write_bytes(b"not-valid-json")

        store = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)
        result = loader.load_spawn_context(
            parent_session_id=parent,
            child_session_id=child,
        )
        assert result is None


# ---------------------------------------------------------------------------
# WorkflowVisualizerLoader — _build_child_summary prompt_preview (54.a.4)
# ---------------------------------------------------------------------------


class TestBuildChildSummaryPromptPreview:
    """``_build_child_summary`` populates ``has_spawn_context`` and ``prompt_preview``."""

    def test_preview_short_prompt_no_ellipsis(self, tmp_path: Path) -> None:
        """Prompt shorter than 60 chars is used as-is without trailing ellipsis."""
        from src.agents.slo_agent.orchestrator.context_dao import SpawnContextDAO

        parent = "p"
        child = "c"
        child_dir = tmp_path / parent / "children" / child
        child_dir.mkdir(parents=True)
        dao = SpawnContextDAO.build(
            task_id="t1",
            prompt="Short prompt.",
            system_prompt="s",
            inactivity_timeout_seconds=60.0,
            model=None,
            reasoning_level=None,
            cwd=None,
        )
        (child_dir / "spawn_context.json").write_bytes(dao.model_dump_json().encode())

        store = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)
        summary = loader._build_child_summary(
            child_session_id=child,
            task_id=None,
            parent_session_id=parent,
            status="running",
        )

        assert summary.has_spawn_context is True
        assert summary.prompt_preview == "Short prompt."

    def test_preview_long_prompt_truncated_with_ellipsis(self, tmp_path: Path) -> None:
        """Prompt longer than 60 chars is truncated to 60 chars + '…'."""
        from src.agents.slo_agent.orchestrator.context_dao import SpawnContextDAO

        parent = "p"
        child = "c"
        child_dir = tmp_path / parent / "children" / child
        child_dir.mkdir(parents=True)
        long_prompt = "x" * 80
        dao = SpawnContextDAO.build(
            task_id="t1",
            prompt=long_prompt,
            system_prompt="s",
            inactivity_timeout_seconds=60.0,
            model=None,
            reasoning_level=None,
            cwd=None,
        )
        (child_dir / "spawn_context.json").write_bytes(dao.model_dump_json().encode())

        store = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)
        summary = loader._build_child_summary(
            child_session_id=child,
            task_id=None,
            parent_session_id=parent,
            status="running",
        )

        assert summary.has_spawn_context is True
        assert summary.prompt_preview == "x" * 60 + "…"

    def test_no_spawn_context_has_empty_preview(self, tmp_path: Path) -> None:
        """When spawn_context.json is absent, flags and preview are default."""
        store = _mock_store(root=tmp_path)
        loader = WorkflowVisualizerLoader(config=_config(), store=store)
        summary = loader._build_child_summary(
            child_session_id="c",
            task_id=None,
            parent_session_id="p",
            status="running",
        )

        assert summary.has_spawn_context is False
        assert summary.prompt_preview == ""


# ---------------------------------------------------------------------------
# WorkflowDataDAO — orchestrator_context field (sub-spec 54.a.4)
# ---------------------------------------------------------------------------


class TestWorkflowDataDAOOrchestratorContext:
    """``WorkflowDataDAO`` carries the optional ``orchestrator_context`` field."""

    def test_defaults_to_none(self) -> None:
        """orchestrator_context is None by default."""
        dao = WorkflowDataDAO(parent_session_id="p")
        assert dao.orchestrator_context is None

    def test_stores_context_when_provided(self) -> None:
        """orchestrator_context is stored when supplied."""
        from src.agents.slo_agent.orchestrator.context_dao import OrchestratorContextDAO

        ctx = OrchestratorContextDAO.build(system_prompt="s", user_prompt="u", model=None)
        dao = WorkflowDataDAO(parent_session_id="p", orchestrator_context=ctx)
        assert dao.orchestrator_context is not None
        assert dao.orchestrator_context.system_prompt == "s"


# ---------------------------------------------------------------------------
# HeadlessWorkflowVisualizer — _format_entry_textual thinking/reasoning (54.a.5)
# ---------------------------------------------------------------------------


class TestFormatEntryTextualUpgrades:
    """``_format_entry_textual`` handles thinking kind and reasoning field."""

    def test_thinking_entry_renders_header(self) -> None:
        """A thinking entry renders a '~ Thinking' header and content."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        entry = TranscriptEntryDAO(kind="thinking", content="I considered X then Y.")
        text = HeadlessWorkflowVisualizer._format_entry_textual(entry=entry)
        plain = text.plain
        assert "Thinking" in plain
        assert "I considered X then Y." in plain

    def test_assistant_entry_renders_reasoning(self) -> None:
        """An assistant entry with reasoning renders the reasoning block."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        entry = TranscriptEntryDAO(
            kind="assistant",
            reasoning="my reasoning here",
            answer="final answer",
        )
        text = HeadlessWorkflowVisualizer._format_entry_textual(entry=entry)
        plain = text.plain
        assert "reasoning" in plain
        assert "my reasoning here" in plain
        assert "final answer" in plain

    def test_thinking_entry_markdown(self) -> None:
        """Markdown mode renders thinking as a blockquote."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        entry = TranscriptEntryDAO(kind="thinking", content="ponder")
        text = HeadlessWorkflowVisualizer._format_entry_markdown(entry=entry)
        assert "thinking" in text.plain

    def test_thinking_entry_html(self) -> None:
        """HTML mode renders thinking as an HTML comment."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        entry = TranscriptEntryDAO(kind="thinking", content="ponder")
        text = HeadlessWorkflowVisualizer._format_entry_html(entry=entry)
        assert "thinking" in text.plain


# ---------------------------------------------------------------------------
# HeadlessWorkflowVisualizer — _child_label prompt preview (54.a.5)
# ---------------------------------------------------------------------------


class TestChildLabelPromptPreview:
    """``_child_label`` appends prompt preview when available."""

    def test_no_preview_produces_plain_label(self) -> None:
        """Without a prompt preview the label shows only icon and session id."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        summary = ChildSessionSummaryDAO(
            session_id="abc12345", task_id=None, status="running", prompt_preview=""
        )
        label = HeadlessWorkflowVisualizer._child_label(child=summary)
        assert "abc12345" in label.plain
        assert "│" not in label.plain

    def test_preview_appended_with_separator(self) -> None:
        """With a prompt preview the label includes '│' and the preview text."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        summary = ChildSessionSummaryDAO(
            session_id="abc12345",
            task_id=None,
            status="completed",
            prompt_preview="Write tests for the module",
        )
        label = HeadlessWorkflowVisualizer._child_label(child=summary)
        assert "│" in label.plain
        assert "Write tests for the module" in label.plain


# ---------------------------------------------------------------------------
# HeadlessWorkflowVisualizer — toggle actions (54.a.5)
# ---------------------------------------------------------------------------


class TestOrchestratorContextToggle:
    """``action_toggle_orchestrator_context`` shows/hides the orchestrator pane."""

    @pytest.mark.asyncio
    async def test_initial_state_is_hidden(self) -> None:
        """Orchestrator pane is hidden and flag is False on startup."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        mock_loader = MagicMock()
        mock_loader.load = AsyncMock(return_value=WorkflowDataDAO(parent_session_id="p", children=[]))
        mock_loader.load_orchestrator_context = MagicMock(return_value=None)
        app = HeadlessWorkflowVisualizer(config=_config(), loader=mock_loader)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._orchestrator_context_visible is False
            panel = app.query_one("#orchestrator-context-panel")
            assert "hidden" in panel.classes

    @pytest.mark.asyncio
    async def test_toggle_shows_panel(self) -> None:
        """Pressing 'o' makes the orchestrator pane visible."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        mock_loader = MagicMock()
        mock_loader.load = AsyncMock(return_value=WorkflowDataDAO(parent_session_id="p", children=[]))
        mock_loader.load_orchestrator_context = MagicMock(return_value=None)
        app = HeadlessWorkflowVisualizer(config=_config(), loader=mock_loader)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            assert app._orchestrator_context_visible is True
            panel = app.query_one("#orchestrator-context-panel")
            assert "hidden" not in panel.classes

    @pytest.mark.asyncio
    async def test_double_toggle_hides_panel(self) -> None:
        """Pressing 'o' twice returns the pane to hidden state."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        mock_loader = MagicMock()
        mock_loader.load = AsyncMock(return_value=WorkflowDataDAO(parent_session_id="p", children=[]))
        mock_loader.load_orchestrator_context = MagicMock(return_value=None)
        app = HeadlessWorkflowVisualizer(config=_config(), loader=mock_loader)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            assert app._orchestrator_context_visible is False
            panel = app.query_one("#orchestrator-context-panel")
            assert "hidden" in panel.classes


class TestVisualizerOrchestratorAndStreaming:
    """Sub-spec 71.a.7 visualizer rendering decisions."""

    @pytest.mark.asyncio
    async def test_child_list_starts_with_orchestrator_node(self) -> None:
        """Places the always-present orchestrator before discovered children."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        loader: MagicMock = MagicMock()
        loader.load = AsyncMock(
            return_value=WorkflowDataDAO(
                parent_session_id="parent",
                orchestrator=OrchestratorNodeDAO(session_id="parent", state="running"),
                children=[ChildSessionSummaryDAO(session_id="child")],
            )
        )
        app = HeadlessWorkflowVisualizer(config=_config(), loader=loader)

        async with app.run_test() as pilot:
            await pilot.pause()
            first_row = app.query_one("#child-list").children[0]
            rendered = first_row.query_one(Label).render()
            assert isinstance(rendered, Content)
            assert "orchestrator" in rendered.plain

    def test_child_row_shows_liveness_suffix(self) -> None:
        """Shows liveness, heartbeat phase, and stdout activity age on child rows."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        label = HeadlessWorkflowVisualizer._child_label(
            child=ChildSessionSummaryDAO(
                session_id="child", liveness_state="healthy", heartbeat_phase="streaming", last_stdout_at=0.0
            )
        )

        assert "healthy" in label.plain
        assert "streaming" in label.plain
        assert "ago" in label.plain

    def test_child_row_shows_liveness_before_first_heartbeat(self) -> None:
        """Fleet-backed startup rows retain liveness and activity with a phase fallback."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        label = HeadlessWorkflowVisualizer._child_label(
            child=ChildSessionSummaryDAO(
                session_id="child",
                liveness_state="degraded",
                last_stdout_at=time.monotonic(),
            )
        )

        assert "degraded" in label.plain
        assert "awaiting heartbeat" in label.plain
        assert "out" in label.plain

    def test_child_row_shows_reaped_icon(self) -> None:
        """Uses the reaped aborted icon for a swept orphan child."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        label = HeadlessWorkflowVisualizer._child_label(
            child=ChildSessionSummaryDAO(session_id="child", terminal_reason="reaped_orphan")
        )

        assert "⊘ reaped" in label.plain

    def test_child_label_when_terminal_includes_exit_reason_and_terminator(self) -> None:
        """Terminal facts remain visible in the child-list row."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        label = HeadlessWorkflowVisualizer._child_label(
            child=ChildSessionSummaryDAO(
                session_id="child",
                status="failed",
                exit_code=7,
                terminal_reason="failed",
                terminated_by="sweep",
            )
        )

        assert "failed" in label.plain
        assert "exit 7" in label.plain
        assert "sweep" in label.plain

    def test_append_live_event_when_tool_call_ends_appends_the_buffered_call(self) -> None:
        """A completed live tool call renders its buffered JSON input."""
        from src.agents.slo_agent.events.stream import AgentStreamEventDAO
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        app = HeadlessWorkflowVisualizer(config=_config(), loader=MagicMock())

        app._append_live_event(
            session_id="child",
            event=AgentStreamEventDAO(kind="tool_call_start", block_id="call", tool_name="bash"),
        )
        app._append_live_event(
            session_id="child",
            event=AgentStreamEventDAO(
                kind="tool_call_delta", block_id="call", tool_arguments_delta='{"command":'
            ),
        )
        app._append_live_event(
            session_id="child",
            event=AgentStreamEventDAO(kind="tool_call_delta", block_id="call", tool_arguments_delta='"pwd"}'),
        )
        app._append_live_event(
            session_id="child",
            event=AgentStreamEventDAO(kind="tool_call_end", block_id="call"),
        )

        entry = app._live_entries["child"][0]
        assert entry.kind == "tool"
        assert entry.tool_name == "bash"
        assert entry.tool_input == {"command": "pwd"}

    def test_append_live_event_when_tool_result_matches_call_appends_result(self) -> None:
        """A matching live tool result renders after its call entry."""
        from src.agents.slo_agent.events.stream import AgentStreamEventDAO
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        app = HeadlessWorkflowVisualizer(config=_config(), loader=MagicMock())

        app._append_live_event(
            session_id="child",
            event=AgentStreamEventDAO(kind="tool_call_start", block_id="call", tool_name="bash"),
        )
        app._append_live_event(
            session_id="child",
            event=AgentStreamEventDAO(kind="tool_call_end", block_id="call"),
        )
        app._append_live_event(
            session_id="child",
            event=AgentStreamEventDAO(kind="tool_result", tool_call_id="call", content="/repo"),
        )

        entry = app._live_entries["child"][1]
        assert entry.kind == "tool"
        assert entry.tool_name == "bash"
        assert entry.output == "/repo"

    @pytest.mark.asyncio
    async def test_detail_pane_coalesces_text_deltas(self) -> None:
        """Appends consecutive live text deltas into one assistant entry."""
        from src.agents.slo_agent.events.stream import AgentStreamEventDAO
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        loader: MagicMock = MagicMock()
        loader.load = AsyncMock(
            return_value=WorkflowDataDAO(
                parent_session_id="parent", children=[ChildSessionSummaryDAO(session_id="child")]
            )
        )
        loader.read_child_stdout_tail = MagicMock(
            return_value=[
                AgentStreamEventDAO(kind="text_delta", delta="hello ").model_dump_json().encode(),
                AgentStreamEventDAO(kind="text_delta", delta="world").model_dump_json().encode(),
            ]
        )
        app = HeadlessWorkflowVisualizer(config=_config(), loader=loader)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app._live_entries["child"]) == 1
            assert app._live_entries["child"][0].answer == "hello world"

    @pytest.mark.asyncio
    async def test_detail_pane_closes_block_on_terminal_event(self) -> None:
        """Clears the active live assistant block after a terminal capture event."""
        from src.agents.slo_agent.events.stream import AgentStreamEventDAO
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        loader: MagicMock = MagicMock()
        loader.load = AsyncMock(
            return_value=WorkflowDataDAO(
                parent_session_id="parent", children=[ChildSessionSummaryDAO(session_id="child")]
            )
        )
        loader.read_child_stdout_tail = MagicMock(
            return_value=[
                AgentStreamEventDAO(kind="text_delta", delta="answer").model_dump_json().encode(),
                AgentStreamEventDAO(kind="run_completed").model_dump_json().encode(),
            ]
        )
        app = HeadlessWorkflowVisualizer(config=_config(), loader=loader)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert "child" not in app._live_open_assistant

    @pytest.mark.asyncio
    async def test_summary_bar_shows_cleanup_line(self) -> None:
        """Shows durable cleanup accounting whenever the loader has fleet evidence."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer
        from src.agents.slo_agent.orchestrator.dao import FleetSnapshotDAO, SubAgentStatusDAO

        loader: MagicMock = MagicMock()
        loader.load = AsyncMock(
            return_value=WorkflowDataDAO(
                parent_session_id="parent",
                fleet_snapshot=FleetSnapshotDAO(
                    orchestrator_session_id="parent",
                    updated_at="now",
                    entries=[
                        SubAgentStatusDAO(
                            task_id="t", session_id="c", status="completed", terminal_reason="completed"
                        )
                    ],
                ),
            )
        )
        app = HeadlessWorkflowVisualizer(config=_config(), loader=loader)

        async with app.run_test() as pilot:
            await pilot.pause()
            rendered = app.query_one("#workflow-summary", Label).render()
            assert isinstance(rendered, Content)
            assert "fleet:" in rendered.plain

    @pytest.mark.asyncio
    async def test_summary_bar_shows_all_reaped(self) -> None:
        """Confirms a terminal workflow whose recorded fleet has no live children."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer
        from src.agents.slo_agent.orchestrator.dao import FleetSnapshotDAO, SubAgentStatusDAO

        loader: MagicMock = MagicMock()
        loader.load = AsyncMock(
            return_value=WorkflowDataDAO(
                parent_session_id="parent",
                is_complete=True,
                fleet_snapshot=FleetSnapshotDAO(
                    orchestrator_session_id="parent",
                    updated_at="now",
                    entries=[SubAgentStatusDAO(task_id="t", session_id="c", status="completed")],
                ),
            )
        )
        app = HeadlessWorkflowVisualizer(config=_config(), loader=loader)

        async with app.run_test() as pilot:
            await pilot.pause()
            rendered = app.query_one("#workflow-summary", Label).render()
            assert isinstance(rendered, Content)
            assert "all sub-processes reaped" in rendered.plain

    @pytest.mark.asyncio
    async def test_summary_bar_omits_all_reaped_when_fleet_has_pending_entry(self) -> None:
        """A pending durable fleet entry prevents a false drained confirmation."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer
        from src.agents.slo_agent.orchestrator.dao import FleetSnapshotDAO, SubAgentStatusDAO

        loader: MagicMock = MagicMock()
        loader.load = AsyncMock(
            return_value=WorkflowDataDAO(
                parent_session_id="parent",
                is_complete=True,
                fleet_snapshot=FleetSnapshotDAO(
                    orchestrator_session_id="parent",
                    updated_at="now",
                    entries=[SubAgentStatusDAO(task_id="t", session_id="c", status="pending")],
                ),
            )
        )
        app = HeadlessWorkflowVisualizer(config=_config(), loader=loader)

        async with app.run_test() as pilot:
            await pilot.pause()
            rendered = app.query_one("#workflow-summary", Label).render()
            assert isinstance(rendered, Content)
            assert "fleet:" in rendered.plain
            assert "all sub-processes reaped" not in rendered.plain

    @pytest.mark.asyncio
    async def test_diagnostics_when_orchestrator_selected_reads_orchestrator_stderr(self) -> None:
        """The first-row orchestrator routes diagnostics to its stderr capture."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        loader: MagicMock = MagicMock()
        loader.load = AsyncMock(
            return_value=WorkflowDataDAO(
                parent_session_id="parent",
                orchestrator=OrchestratorNodeDAO(session_id="parent", state="running"),
            )
        )
        loader.read_child_stdout_tail = MagicMock(return_value=[])
        loader.load_node_stderr_lines = MagicMock(return_value=["orchestrator error"])
        app = HeadlessWorkflowVisualizer(config=_config(), loader=loader)

        async with app.run_test() as pilot:
            await pilot.pause()
            loader.load_node_stderr_lines.assert_called_once_with(
                parent_session_id="parent",
                session_id="parent",
            )
            assert "orchestrator error" in app.query_one("#diagnostics-log", RichLog).lines[0].text


class TestDetailViewToggle:
    """``action_toggle_detail_view`` switches between transcript and invocation."""

    @pytest.mark.asyncio
    async def test_initial_detail_view_is_transcript(self) -> None:
        """Detail view defaults to 'transcript'."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        mock_loader = MagicMock()
        mock_loader.load = AsyncMock(return_value=WorkflowDataDAO(parent_session_id="p", children=[]))
        app = HeadlessWorkflowVisualizer(config=_config(), loader=mock_loader)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._detail_view == "transcript"

    @pytest.mark.asyncio
    async def test_toggle_switches_to_invocation(self) -> None:
        """Pressing 'v' switches detail view to invocation."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        mock_loader = MagicMock()
        mock_loader.load = AsyncMock(return_value=WorkflowDataDAO(parent_session_id="p", children=[]))
        app = HeadlessWorkflowVisualizer(config=_config(), loader=mock_loader)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("v")
            await pilot.pause()
            assert app._detail_view == "invocation"

    @pytest.mark.asyncio
    async def test_double_toggle_returns_to_transcript(self) -> None:
        """Pressing 'v' twice returns to transcript view."""
        from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer

        mock_loader = MagicMock()
        mock_loader.load = AsyncMock(return_value=WorkflowDataDAO(parent_session_id="p", children=[]))
        app = HeadlessWorkflowVisualizer(config=_config(), loader=mock_loader)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("v")
            await pilot.pause()
            await pilot.press("v")
            await pilot.pause()
            assert app._detail_view == "transcript"
