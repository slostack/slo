"""Tree-based session history store (sub-spec 01.a.4).

Wraps FilesystemSessionHistoryStore and threads entry_id / parent_entry_id
into every event's payload.metadata so compaction cut-point logic can
navigate tool_call / tool_result relationships without string scanning.

The on-disk format is identical to FilesystemSessionHistoryStore: plain
``events.jsonl`` under ``~/.slo/sessions/history/<session_id>/``. Tree
metadata is stored in the existing ``payload.metadata`` dict so old readers
parse events written by this store without error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryMetadataDAO,
)
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore

__all__ = ["TreeBasedFilesystemSessionHistoryStore"]


class TreeBasedFilesystemSessionHistoryStore:
    """Session history store that threads parent_entry_id through every event.

    Wraps FilesystemSessionHistoryStore and adds tree-node metadata
    (entry_id, parent_entry_id) to every appended event so compaction
    cut-point logic can navigate tool_call / tool_result relationships
    without string scanning.

    Implements SessionHistoryStoreProtocol. All read methods delegate
    unchanged to the underlying flat store.

    The invariant enforced: a ``tool_result`` event's ``parent_entry_id``
    always points to its opening ``tool_call``, not to whatever event
    happened to be appended immediately before it.
    """

    def __init__(self, *, root: Optional[Path] = None) -> None:
        """Initialise the tree store backed by a flat FilesystemSessionHistoryStore.

        Args:
            root (Optional[Path]): Override history root directory.
                Defaults to ~/.slo/sessions/history when None.
        """
        self._flat: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=root)
        self._last_entry_id: Optional[str] = None
        self._pending_tool_calls: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Read-only delegation
    # ------------------------------------------------------------------

    @property
    def root(self) -> Path:
        """Resolved absolute history root directory."""
        return self._flat.root

    async def ensure_session(
        self,
        *,
        session_id: str,
        workdir: Path,
        model_name: Optional[str],
        workspace_file: Optional[Path] = None,
    ) -> SessionHistoryMetadataDAO:
        """Create or verify a session directory and write initial metadata.

        Args:
            session_id (str): Session identifier.
            workdir (Path): Workdir captured at session creation.
            model_name (Optional[str]): Active model name.
            workspace_file (Optional[Path]): Optional workspace file.

        Returns:
            SessionHistoryMetadataDAO: The persisted metadata.
        """
        return await self._flat.ensure_session(
            session_id=session_id,
            workdir=workdir,
            model_name=model_name,
            workspace_file=workspace_file,
        )

    async def read_metadata(
        self,
        *,
        session_id: str,
    ) -> SessionHistoryMetadataDAO:
        """Return the persisted metadata for ``session_id``.

        Args:
            session_id (str): Session identifier.

        Returns:
            SessionHistoryMetadataDAO: Parsed metadata.
        """
        return await self._flat.read_metadata(session_id=session_id)

    async def write_metadata(self, *, metadata: SessionHistoryMetadataDAO) -> None:
        """Overwrite the metadata file atomically.

        Args:
            metadata (SessionHistoryMetadataDAO): Metadata to persist.
        """
        await self._flat.write_metadata(metadata=metadata)

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
        await self._flat.update_metadata_model_name(
            session_id=session_id,
            model_name=model_name,
        )

    async def load_events(
        self,
        *,
        session_id: str,
    ) -> list[SessionHistoryEventDAO]:
        """Load and parse all events from events.jsonl in append order.

        Args:
            session_id (str): Session identifier.

        Returns:
            list[SessionHistoryEventDAO]: All events in sequence order.
        """
        return await self._flat.load_events(session_id=session_id)

    async def session_exists(self, *, session_id: str) -> bool:
        """Return ``True`` iff the session directory and metadata exist.

        Args:
            session_id (str): Session identifier.

        Returns:
            bool: Whether the session has been ensured before.
        """
        return await self._flat.session_exists(session_id=session_id)

    async def rebuild_transcript(
        self,
        *,
        session_id: str,
        markdown: str,
    ) -> Path:
        """Write a derived ``transcript.md`` for ``session_id``.

        Args:
            session_id (str): Session identifier.
            markdown (str): Pre-rendered markdown body.

        Returns:
            Path: The transcript file path.
        """
        return await self._flat.rebuild_transcript(
            session_id=session_id,
            markdown=markdown,
        )

    async def resolve_session_reference(self, *, reference: str) -> str:
        """Resolve a session id or unique session name to ``session_id``.

        Args:
            reference (str): Operator-provided resume reference.

        Returns:
            str: Resolved canonical ``session_id``.

        Raises:
            ValueError: When the reference cannot be resolved.
        """
        return await self._flat.resolve_session_reference(reference=reference)

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
        return await self._flat.rename_session(
            session_id=session_id,
            session_name=session_name,
        )

    # ------------------------------------------------------------------
    # Write — tree-metadata injection
    # ------------------------------------------------------------------

    async def append_event(
        self,
        *,
        event: SessionHistoryEventDAO,
    ) -> SessionHistoryEventDAO:
        """Append one event, threading entry_id and parent_entry_id into metadata.

        For tool_result events, parent_entry_id points to the opening tool_call.
        For all other events, parent_entry_id points to the immediately preceding
        event. The root event (first append in a session) gets parent_entry_id=None.

        Args:
            event (SessionHistoryEventDAO): The canonical event to persist.

        Returns:
            SessionHistoryEventDAO: The persisted event with tree metadata stamped.
        """
        parent_id = self._resolve_parent_id(event=event)

        metadata = dict(event.payload.metadata)
        metadata["entry_id"] = event.event_id
        metadata["parent_entry_id"] = parent_id

        enriched_payload = event.payload.model_copy(update={"metadata": metadata})
        enriched_event = event.model_copy(update={"payload": enriched_payload})

        persisted = await self._flat.append_event(event=enriched_event)

        if event.kind == "tool_call":
            tool_call_id: str = event.payload.tool_call_id or ""
            if tool_call_id:
                self._pending_tool_calls[tool_call_id] = event.event_id

        self._last_entry_id = event.event_id
        return persisted

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
        """Append a compaction_summary event, threading parent_entry_id into metadata.

        The compaction summary's parent_entry_id is the last event appended before
        the compaction summary — i.e. the last event in the pre-cut portion of history.

        Args:
            session_id (str): Session identifier.
            summary (str): LLM-generated summary of the compacted history segment.
            first_kept_entry_id (str): ``event_id`` of the first retained event.
            cut_point_entry_id (str): ``event_id`` of the last compacted event.
            tokens_before (int): Estimated token count of the compacted events.
            tokens_after (int): Estimated token count of the summary text.

        Returns:
            SessionHistoryEventDAO: The persisted compaction_summary event.
        """
        parent_id = self._last_entry_id

        compaction_event = await self._flat.append_compaction_summary(
            session_id=session_id,
            summary=summary,
            first_kept_entry_id=first_kept_entry_id,
            cut_point_entry_id=cut_point_entry_id,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
        )

        enriched_metadata = dict(compaction_event.payload.metadata)
        enriched_metadata["entry_id"] = compaction_event.event_id
        enriched_metadata["parent_entry_id"] = parent_id

        enriched_payload = compaction_event.payload.model_copy(
            update={"metadata": enriched_metadata}
        )
        enriched_event = compaction_event.model_copy(update={"payload": enriched_payload})

        self._last_entry_id = compaction_event.event_id
        return enriched_event

    async def truncate_to_compaction_boundary(
        self,
        *,
        session_id: str,
        events: list[SessionHistoryEventDAO],
        first_kept_entry_id: str,
        summary_event: SessionHistoryEventDAO,
    ) -> None:
        """Rewrite events.jsonl to the retained tail plus the compaction summary.

        Delegates directly to the underlying flat store. The tree-metadata
        (entry_id, parent_entry_id) already lives inside each event's
        payload.metadata and is preserved verbatim in the rewritten file.

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
        await self._flat.truncate_to_compaction_boundary(
            session_id=session_id,
            events=events,
            first_kept_entry_id=first_kept_entry_id,
            summary_event=summary_event,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_parent_id(self, *, event: SessionHistoryEventDAO) -> Optional[str]:
        """Return the correct parent_entry_id for the event about to be appended.

        For tool_result events, the parent is the opening tool_call (popped from
        _pending_tool_calls). For all other events, the parent is the last appended
        event.

        Args:
            event (SessionHistoryEventDAO): Event about to be appended.

        Returns:
            Optional[str]: parent_entry_id, or None for the root event.
        """
        if event.kind == "tool_result":
            tool_call_id: str = event.payload.tool_call_id or ""
            return self._pending_tool_calls.pop(tool_call_id, self._last_entry_id)
        return self._last_entry_id

    def seed_last_entry_id(self, *, entry_id: str) -> None:
        """Seed _last_entry_id from a previously loaded event list.

        Call this after load_events() when resuming a session so the first
        new append gets the correct parent_entry_id instead of None.

        Args:
            entry_id (str): event_id of the last persisted event.
        """
        self._last_entry_id = entry_id
