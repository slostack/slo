"""Structural protocol that both session-history store implementations satisfy.

``FilesystemSessionHistoryStore`` (flat JSONL) and
``TreeBasedFileSystemSessionHistoryStore`` (turn-grouped tree) expose the
same async public surface. Code that only needs to read/write history
should type against ``SessionHistoryStoreProtocol`` rather than a
concrete class.

Both stores are runtime-compatible without registering as virtual
subclasses — duck-typing is enough because the TUI/session code only
calls the methods listed here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryMetadataDAO,
)

__all__ = ["SessionHistoryStoreProtocol"]


@runtime_checkable
class SessionHistoryStoreProtocol(Protocol):
    """Async read/write interface shared by both history-store implementations."""

    @property
    def root(self) -> Path:
        """Resolved absolute history root directory."""
        ...

    async def ensure_session(
        self,
        *,
        session_id: str,
        workdir: Path,
        model_name: Optional[str],
        workspace_file: Optional[Path] = None,
    ) -> SessionHistoryMetadataDAO:
        """Create the per-session directory and metadata file if needed.

        Args:
            session_id (str): The session identifier.
            workdir (Path): Workdir captured at session creation.
            model_name (Optional[str]): Active model name.
            workspace_file (Optional[Path]): Optional workspace file.

        Returns:
            SessionHistoryMetadataDAO: Persisted (or existing) metadata.
        """
        ...

    async def read_metadata(self, *, session_id: str) -> SessionHistoryMetadataDAO:
        """Return the persisted metadata for ``session_id``.

        Args:
            session_id (str): The session identifier.

        Returns:
            SessionHistoryMetadataDAO: Parsed metadata.
        """
        ...

    async def write_metadata(self, *, metadata: SessionHistoryMetadataDAO) -> None:
        """Overwrite the metadata file atomically.

        Args:
            metadata (SessionHistoryMetadataDAO): Metadata to persist.
        """
        ...

    async def update_metadata_model_name(
        self,
        *,
        session_id: str,
        model_name: str,
    ) -> None:
        """Update ``session.json``'s ``model_name`` and bump ``updated_at``.

        Args:
            session_id (str): The session to update.
            model_name (str): The routed model name to persist.
        """
        ...

    async def append_event(
        self,
        *,
        event: SessionHistoryEventDAO,
    ) -> SessionHistoryEventDAO:
        """Append one canonical event, stamp its sequence, and persist.

        Args:
            event (SessionHistoryEventDAO): The event to persist.

        Returns:
            SessionHistoryEventDAO: The event with assigned ``sequence``
                and computed ``token_usage``.
        """
        ...

    async def load_events(
        self,
        *,
        session_id: str,
    ) -> list[SessionHistoryEventDAO]:
        """Load every event for ``session_id`` in append order.

        Args:
            session_id (str): The session identifier.

        Returns:
            list[SessionHistoryEventDAO]: Events sorted by ``sequence``.
        """
        ...

    async def session_exists(self, *, session_id: str) -> bool:
        """Return ``True`` iff the session directory and metadata exist.

        Args:
            session_id (str): The session identifier.

        Returns:
            bool: Whether the session has been ensured before.
        """
        ...

    async def rebuild_transcript(
        self,
        *,
        session_id: str,
        markdown: str,
    ) -> Path:
        """Write a derived ``transcript.md`` for ``session_id``.

        Args:
            session_id (str): The session identifier.
            markdown (str): Pre-rendered markdown body.

        Returns:
            Path: The transcript file path.
        """
        ...

    async def resolve_session_reference(self, *, reference: str) -> str:
        """Resolve a session id or unique session name to ``session_id``.

        Args:
            reference (str): Operator-provided resume reference.

        Returns:
            str: Resolved canonical ``session_id``.
        """
        ...

    async def rename_session(
        self,
        *,
        session_id: str,
        session_name: str,
    ) -> SessionHistoryMetadataDAO:
        """Persist a human-readable session name for an existing session.

        Args:
            session_id (str): Session to update.
            session_name (str): User-facing name.

        Returns:
            SessionHistoryMetadataDAO: Updated metadata.
        """
        ...

    async def append_compaction_summary(
        self,
        *,
        session_id: str,
        summary: str,
        first_kept_entry_id: str,
        cut_point_entry_id: str,
        tokens_before: int,
        tokens_after: int,
    ) -> SessionHistoryEventDAO:
        """Append a compaction_summary event to the session's event log.

        Args:
            session_id (str): The session to append to.
            summary (str): LLM-generated summary of the compacted portion.
            first_kept_entry_id (str): ``event_id`` of the first event in
                the retained tail.
            cut_point_entry_id (str): ``event_id`` of the last compacted event.
            tokens_before (int): Estimated token count of the compacted events.
            tokens_after (int): Estimated token count of the summary text.

        Returns:
            SessionHistoryEventDAO: The persisted compaction_summary event.
        """
        ...

    async def truncate_to_compaction_boundary(
        self,
        *,
        session_id: str,
        events: list[SessionHistoryEventDAO],
        first_kept_entry_id: str,
        summary_event: SessionHistoryEventDAO,
    ) -> None:
        """Rewrite events.jsonl to the retained tail plus the compaction summary.

        After compaction the JSONL is atomically replaced so that
        ``CompactionChecker.should_compact`` sums only the active events.
        The pre-compaction file is archived in the same session directory.

        Args:
            session_id (str): Session whose ``events.jsonl`` will be rewritten.
            events (list[SessionHistoryEventDAO]): Pre-compaction event list in
                sequence order, as passed to ``Compacter.compact()``.
            first_kept_entry_id (str): ``event_id`` of the first retained event
                from ``CompactionResult.first_kept_entry_id``.
            summary_event (SessionHistoryEventDAO): The ``compaction_summary``
                event returned by ``CompactedSessionUpdater.update()``.

        Raises:
            FileNotFoundError: When ``events.jsonl`` does not exist.
            ValueError: When ``first_kept_entry_id`` cannot be resolved.
        """
        ...
