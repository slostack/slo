"""Filesystem-backed JSONL session history store (sub-spec 05.a §7).

One process owns one session writer. The store optimises for strict
append order, private file permissions, and atomic metadata rewrites
rather than cross-process coordination.

Layout::

    ~/.slo/sessions/history/<session_id>/
    ├── session.json      # SessionHistoryMetadataDAO, atomic temp+rename
    ├── events.jsonl      # SessionHistoryEventDAO per line, append-only
    └── transcript.md     # derived from events; not authoritative
"""

from __future__ import annotations

import asyncio
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.cfg import SLO_HOME as _CFG_SLO_HOME

from src.agents.slo_agent.compaction.compacter import CompactionResult
from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
    SessionHistoryMetadataDAO,
)

# ``history`` owns persistence and accepts ``CompactionResult`` as a command
# value.  The reverse dependency does not exist: compaction only consumes
# history DAOs, so importing the result type here preserves a one-way graph.
# ``TokenEstimator`` remains lazy in ``_append_event_sync`` because it belongs
# to the compaction package and is only required when appending an unstamped event.

__all__ = [
    "FilesystemSessionHistoryStore",
    "HistoryCompactionRecoveryError",
    "normalize_session_name_key",
]


_DIR_MODE: int = 0o700
_FILE_MODE: int = 0o600
_COMPACTION_ARCHIVE_PREFIX: str = "events.pre-"


class HistoryCompactionRecoveryError(RuntimeError):
    """Report a failed compaction restore with deterministic recovery paths.

    Reader-side recovery can restore ``archive_path`` to ``active_path`` before
    parsing history, so callers must surface this error rather than treating a
    partial activation as successful.
    """

    def __init__(self, *, active_path: Path, archive_path: Path) -> None:
        """Capture the paths required for deterministic reader recovery.

        Args:
            active_path (Path): Missing or partially activated live event log.
            archive_path (Path): Preserved pre-transaction event log.
        """
        self.active_path: Path = active_path
        self.archive_path: Path = archive_path
        super().__init__("compaction restoration failed; " f"active={active_path}; archive={archive_path}")


def normalize_session_name_key(*, session_name: str) -> str:
    """Return the canonical lookup key for a session name.

    Args:
        session_name (str): User-facing session name.

    Returns:
        str: Lowercased, whitespace-normalized lookup key.

    Raises:
        ValueError: When the normalized name would be blank.
    """
    normalized: str = " ".join(session_name.strip().lower().split())
    if not normalized:
        raise ValueError("session name must not be blank")
    return normalized


def default_history_root() -> Path:
    """Return the default on-disk history root.

    Honours ``SLO_HOME`` for parity with the credential store and the
    distribution root resolved by the CLI.

    Returns:
        Path: Resolved absolute path of ``~/.slo/sessions/history``.
    """
    return (_CFG_SLO_HOME / "sessions" / "history").resolve()


class FilesystemSessionHistoryStore:
    """Append-only JSONL history store rooted at ``~/.slo/sessions/history``.

    The public surface stays async-friendly because the TUI and agent
    streaming path run on the main event loop. The actual filesystem IO
    is offloaded via ``asyncio.to_thread`` so fsync-heavy history writes
    cannot stall Textual rendering while a prompt is in flight.
    """

    def __init__(self, *, root: Optional[Path] = None) -> None:
        """Default to ``~/.slo/sessions/history``; override for tests.

        Args:
            root (Optional[Path]): Override root directory.
        """
        self._root: Path = (root or default_history_root()).expanduser().resolve()
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def root(self) -> Path:
        """Resolved absolute history root. Read-only."""
        return self._root

    # ---- Public surface ---------------------------------------------------

    async def ensure_session(
        self,
        *,
        session_id: str,
        workdir: Path,
        model_name: Optional[str],
        workspace_file: Optional[Path] = None,
    ) -> SessionHistoryMetadataDAO:
        """Create the per-session directory and metadata file if needed.

        Idempotent: when the session already exists the persisted
        metadata is returned unchanged.

        Args:
            session_id (str): The session identifier.
            workdir (Path): Workdir captured at session creation.
            model_name (Optional[str]): Active model name.
            workspace_file (Optional[Path]): Optional workspace file to persist
                for resume-time context reconstruction.

        Returns:
            SessionHistoryMetadataDAO: The persisted (or newly created)
                metadata record.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._ensure_session_sync,
                session_id=session_id,
                workdir=workdir,
                model_name=model_name,
                workspace_file=workspace_file,
            )

    async def read_metadata(self, *, session_id: str) -> SessionHistoryMetadataDAO:
        """Return the persisted metadata for ``session_id``.

        Args:
            session_id (str): The session identifier.

        Returns:
            SessionHistoryMetadataDAO: Parsed metadata.

        Raises:
            FileNotFoundError: When the session has not been ensured.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._read_metadata_sync,
                session_id=session_id,
            )

    async def write_metadata(self, *, metadata: SessionHistoryMetadataDAO) -> None:
        """Overwrite the metadata file atomically.

        Args:
            metadata (SessionHistoryMetadataDAO): The metadata to persist.
        """
        async with self._lock:
            await asyncio.to_thread(
                self._write_metadata_sync,
                metadata=metadata,
            )

    async def update_metadata_model_name(
        self,
        *,
        session_id: str,
        model_name: str,
    ) -> None:
        """Update ``session.json``'s ``model_name`` and bump ``updated_at``.

        Reads the current metadata, sets the (routed) model name, bumps the
        update timestamp, and atomically rewrites the file. Used by the session
        to keep persisted identity truthful as the pool routes between members.

        Args:
            session_id (str): The session whose metadata to update.
            model_name (str): The routed model name to persist.
        """
        async with self._lock:
            await asyncio.to_thread(
                self._update_metadata_model_name_sync,
                session_id=session_id,
                model_name=model_name,
            )

    async def append_event(
        self,
        *,
        event: SessionHistoryEventDAO,
    ) -> SessionHistoryEventDAO:
        """Append one canonical event and bump metadata sequence.

        The store assigns the event's ``sequence`` based on the current
        ``latest_sequence`` in metadata. Callers do not need to set it.

        Args:
            event (SessionHistoryEventDAO): The canonical event. Its
                ``session_id`` must already match an ensured session.

        Returns:
            SessionHistoryEventDAO: The event as persisted, with the
                store-assigned ``sequence``.

        Raises:
            FileNotFoundError: When the session was never ensured.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._append_event_sync,
                event=event,
            )

    async def load_events(
        self,
        *,
        session_id: str,
    ) -> list[SessionHistoryEventDAO]:
        """Load and validate every event for ``session_id``.

        Args:
            session_id (str): The session identifier.

        Returns:
            list[SessionHistoryEventDAO]: Events in append order
                (sorted by ``sequence`` defensively).
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._load_events_sync,
                session_id=session_id,
            )

    async def session_exists(self, *, session_id: str) -> bool:
        """Return ``True`` iff the session directory and metadata exist.

        Args:
            session_id (str): The session identifier.

        Returns:
            bool: ``True`` when the session has been ensured before.
        """
        return await asyncio.to_thread(
            self._metadata_path(session_id=session_id).exists,
        )

    async def rebuild_transcript(
        self,
        *,
        session_id: str,
        markdown: str,
    ) -> Path:
        """Write a derived ``transcript.md`` for ``session_id``.

        The transcript is a presentation artifact. It is rewritten on
        demand from canonical events by the caller (a transcript
        projector); the store only persists the bytes.

        Args:
            session_id (str): The session identifier.
            markdown (str): Pre-rendered markdown body.

        Returns:
            Path: The transcript file path.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._rebuild_transcript_sync,
                session_id=session_id,
                markdown=markdown,
            )

    async def resolve_session_reference(self, *, reference: str) -> str:
        """Resolve a session id or unique session name to ``session_id``.

        Resolution order is intentional:

        1. exact ``session_id`` match,
        2. normalized ``session_name_key`` match.

        Args:
            reference (str): Operator-provided resume reference.

        Returns:
            str: Resolved canonical ``session_id``.

        Raises:
            ValueError: When the reference cannot be resolved.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._resolve_session_reference_sync,
                reference=reference,
            )

    async def rename_session(
        self,
        *,
        session_id: str,
        session_name: str,
    ) -> SessionHistoryMetadataDAO:
        """Persist a human-readable session name for an existing session.

        Args:
            session_id (str): Session whose metadata should be updated.
            session_name (str): User-facing human-readable session name.

        Returns:
            SessionHistoryMetadataDAO: Persisted updated metadata.

        Raises:
            ValueError: When the normalized name is blank or conflicts with
                another session's normalized name.
            FileNotFoundError: When the session metadata does not exist.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._rename_session_sync,
                session_id=session_id,
                session_name=session_name,
            )

    async def compact_to_boundary(
        self,
        *,
        session_id: str,
        events: list[SessionHistoryEventDAO],
        result: CompactionResult,
        turn_id: str,
    ) -> SessionHistoryEventDAO:
        """Atomically replace active history with a retained tail and summary.

        The command writes the candidate active log before moving the old log to
        its archive and only advances metadata after the new active file is in
        place. A normal write failure leaves the active log and metadata intact.

        Args:
            session_id (str): Session whose history is compacted.
            events (list[SessionHistoryEventDAO]): Validated pre-compaction events.
            result (CompactionResult): Summary and retain-boundary result.
            turn_id (str): Fresh or active turn id recorded on the summary.

        Returns:
            SessionHistoryEventDAO: The activated summary with its assigned sequence.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._compact_to_boundary_sync,
                session_id=session_id,
                events=events,
                result=result,
                turn_id=turn_id,
            )

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

        Constructs a ``SessionHistoryEventDAO`` with ``kind='compaction_summary'``,
        places the LLM-generated summary in ``payload.content``, pre-stamps
        ``payload.token_usage``, and records compaction bookkeeping in
        ``payload.metadata``. Delegates to ``append_event`` for sequencing,
        locking, and fsync — no separate lock acquisition needed here.

        Args:
            session_id (str): The session to append to.
            summary (str): LLM-generated summary of the compacted portion.
            first_kept_entry_id (str): ``event_id`` of the first event in
                the retained tail (the oldest event that is NOT compacted).
            cut_point_entry_id (str): ``event_id`` of the last event that
                was included in the compacted portion.
            tokens_before (int): Estimated token count of the compacted events.
            tokens_after (int): Estimated token count of the summary text.

        Returns:
            SessionHistoryEventDAO: The persisted compaction_summary event,
                carrying its store-assigned ``sequence``.
        """
        event: SessionHistoryEventDAO = SessionHistoryEventDAO(
            session_id=session_id,
            kind="compaction_summary",
            payload=SessionHistoryEventPayloadDAO(
                content=summary,
                token_usage=math.ceil(len(summary) / 4),
                metadata={
                    "first_kept_entry_id": first_kept_entry_id,
                    "cut_point_entry_id": cut_point_entry_id,
                    "tokens_before": tokens_before,
                    "tokens_after": tokens_after,
                },
            ),
        )
        return await self.append_event(event=event)

    async def truncate_to_compaction_boundary(
        self,
        *,
        session_id: str,
        events: list[SessionHistoryEventDAO],
        first_kept_entry_id: str,
        summary_event: SessionHistoryEventDAO,
    ) -> None:
        """Rewrite events.jsonl to the retained tail plus the compaction summary.

        After compaction, ``CompactionChecker.should_compact`` sums only the
        active events because the accumulated pre-compaction history is no
        longer in the file.  The pre-compaction file is preserved as an audit
        archive under ``events.pre-<YYYYMMDDTHHMMSSZ>.jsonl`` in the same
        session directory.

        Atomic protocol (POSIX rename semantics):

        1. Write the new event list to ``events.jsonl.tmp`` and fsync.
        2. Rename ``events.jsonl`` → ``events.pre-<ts>.jsonl`` (archive).
        3. Rename ``events.jsonl.tmp`` → ``events.jsonl`` (activate).

        The entire operation runs under ``self._lock`` via
        ``asyncio.to_thread``, keeping it consistent with all other store
        mutations.

        Args:
            session_id (str): Session whose ``events.jsonl`` will be rewritten.
            events (list[SessionHistoryEventDAO]): The pre-compaction event list
                in sequence order, as passed to ``Compacter.compact()``.
            first_kept_entry_id (str): ``event_id`` of the first retained event
                from ``CompactionResult.first_kept_entry_id``.
            summary_event (SessionHistoryEventDAO): The ``compaction_summary``
                event returned by ``CompactedSessionUpdater.update()``, with its
                store-assigned sequence number.

        Raises:
            FileNotFoundError: When ``events.jsonl`` does not exist for the session.
            ValueError: When ``first_kept_entry_id`` does not resolve to any event
                in ``events``.
        """
        async with self._lock:
            await asyncio.to_thread(
                self._truncate_to_compaction_boundary_sync,
                session_id=session_id,
                events=events,
                first_kept_entry_id=first_kept_entry_id,
                summary_event=summary_event,
            )

    # ---- Path helpers -----------------------------------------------------

    def _session_dir(self, *, session_id: str) -> Path:
        """Return the per-session directory path."""
        return self._root / session_id

    def _events_path(self, *, session_id: str) -> Path:
        """Return the per-session ``events.jsonl`` path."""
        return self._session_dir(session_id=session_id) / "events.jsonl"

    def _metadata_path(self, *, session_id: str) -> Path:
        """Return the per-session ``session.json`` path."""
        return self._session_dir(session_id=session_id) / "session.json"

    def _transcript_path(self, *, session_id: str) -> Path:
        """Return the per-session ``transcript.md`` path."""
        return self._session_dir(session_id=session_id) / "transcript.md"

    # ---- Private IO -------------------------------------------------------

    def _ensure_session_sync(
        self,
        *,
        session_id: str,
        workdir: Path,
        model_name: Optional[str],
        workspace_file: Optional[Path],
    ) -> SessionHistoryMetadataDAO:
        """Synchronously ensure the per-session directory + metadata."""
        self._ensure_root()
        session_dir: Path = self._session_dir(session_id=session_id)
        self._ensure_session_dir(path=session_dir)
        metadata_path: Path = self._metadata_path(session_id=session_id)
        if metadata_path.exists():
            return self._read_metadata_sync(session_id=session_id)
        metadata: SessionHistoryMetadataDAO = SessionHistoryMetadataDAO(
            session_id=session_id,
            workdir=workdir,
            model_name=model_name,
            workspace_file=workspace_file,
        )
        self._write_metadata_sync(metadata=metadata)
        events_path: Path = self._events_path(session_id=session_id)
        if not events_path.exists():
            events_path.touch()
            events_path.chmod(_FILE_MODE)
        return metadata

    def _append_event_sync(
        self,
        *,
        event: SessionHistoryEventDAO,
    ) -> SessionHistoryEventDAO:
        """Synchronously append one event, stamp token_usage, and rewrite metadata.

        Reads the current metadata to derive the next sequence number, stamps
        token_usage via TokenEstimator when the caller has not pre-set it,
        fsyncs the new JSONL line, then atomically rewrites session.json.

        Args:
            event (SessionHistoryEventDAO): The event to persist. Its
                ``session_id`` must match an already-ensured session.

        Returns:
            SessionHistoryEventDAO: The event as persisted, carrying the
                store-assigned ``sequence`` and a non-None ``token_usage``.

        Raises:
            FileNotFoundError: When the session was never ensured.
        """
        metadata: SessionHistoryMetadataDAO = self._read_metadata_sync(
            session_id=event.session_id,
        )
        next_sequence: int = metadata.latest_sequence + 1
        stamped: SessionHistoryEventDAO = event.model_copy(
            update={"sequence": next_sequence},
        )

        if stamped.payload.token_usage is None:
            from src.agents.slo_agent.compaction.token_estimator import TokenEstimator

            estimated: int = TokenEstimator.estimate(event=stamped)
            stamped = stamped.model_copy(
                update={
                    "payload": stamped.payload.model_copy(
                        update={"token_usage": estimated},
                    )
                }
            )

        self._append_event_line(event=stamped)
        metadata.latest_sequence = next_sequence
        metadata.updated_at = datetime.now(timezone.utc)
        if stamped.kind == "run_completed" and stamped.turn_id is not None:
            metadata.last_completed_turn_id = stamped.turn_id
        self._write_metadata_sync(metadata=metadata)
        return stamped

    def _load_events_sync(
        self,
        *,
        session_id: str,
    ) -> list[SessionHistoryEventDAO]:
        """Synchronously recover an interrupted archive then validate events.

        Args:
            session_id (str): Session whose active history is read.

        Returns:
            list[SessionHistoryEventDAO]: Validated active events in sequence order.
        """
        events_path: Path = self._events_path(session_id=session_id)
        self._recover_compaction_archive_if_needed(active_path=events_path)
        if not events_path.exists():
            return []
        raw_text: str = events_path.read_text(encoding="utf-8")
        events: list[SessionHistoryEventDAO] = []
        for raw_line in raw_text.split("\n"):
            # JSONL is newline-delimited on literal LF bytes only. Do not use
            # ``splitlines()`` here: tool output can legitimately contain
            # Unicode line-separator characters like U+0085 inside a JSON
            # string value (for example when the ``read`` tool is pointed at a
            # binary file). ``splitlines()`` would split a valid JSON record in
            # the middle of that string and make the session unreadable.
            stripped: str = raw_line.rstrip("\r")
            if not stripped.strip():
                continue
            events.append(SessionHistoryEventDAO.model_validate(json.loads(stripped)))
        events.sort(key=lambda e: e.sequence)
        return events

    def _rebuild_transcript_sync(
        self,
        *,
        session_id: str,
        markdown: str,
    ) -> Path:
        """Synchronously rewrite the derived transcript markdown."""
        path: Path = self._transcript_path(session_id=session_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
        tmp: Path = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(markdown, encoding="utf-8")
        tmp.chmod(_FILE_MODE)
        tmp.replace(path)
        return path

    def _iter_metadata_paths(self) -> list[Path]:
        """Return every persisted ``session.json`` path under the root.

        Returns:
            list[Path]: Sorted metadata paths for all known sessions.
        """
        if not self._root.exists():
            return []
        return sorted(
            path / "session.json"
            for path in self._root.iterdir()
            if path.is_dir() and (path / "session.json").is_file()
        )

    def _load_all_metadata_sync(self) -> list[SessionHistoryMetadataDAO]:
        """Load every persisted metadata record under the history root.

        Returns:
            list[SessionHistoryMetadataDAO]: Parsed metadata records.
        """
        metadata_items: list[SessionHistoryMetadataDAO] = []
        for path in self._iter_metadata_paths():
            payload: dict = json.loads(path.read_text(encoding="utf-8"))
            metadata_items.append(SessionHistoryMetadataDAO.model_validate(payload))
        return metadata_items

    def _resolve_session_reference_sync(self, *, reference: str) -> str:
        """Synchronously resolve a session id or normalized name.

        Args:
            reference (str): Operator-provided resume reference.

        Returns:
            str: Resolved canonical session id.

        Raises:
            ValueError: When the reference cannot be resolved or resolves ambiguously.
        """
        exact_session_id: str = reference.strip()
        if exact_session_id and self._metadata_path(session_id=exact_session_id).exists():
            return exact_session_id
        normalized_key: str = normalize_session_name_key(session_name=reference)
        matches: list[SessionHistoryMetadataDAO] = [
            metadata
            for metadata in self._load_all_metadata_sync()
            if metadata.session_name_key == normalized_key
        ]
        if len(matches) == 1:
            return matches[0].session_id
        if len(matches) > 1:
            raise ValueError(f"ambiguous session reference: {reference}; use the raw session id instead")
        raise ValueError(f"unknown session reference: {reference}")

    def _rename_session_sync(
        self,
        *,
        session_id: str,
        session_name: str,
    ) -> SessionHistoryMetadataDAO:
        """Synchronously rewrite session metadata with a human-readable name.

        Args:
            session_id (str): Session whose metadata should be updated.
            session_name (str): User-facing human-readable session name.

        Returns:
            SessionHistoryMetadataDAO: Persisted updated metadata.

        Raises:
            ValueError: When the normalized name is blank or already owned by another session.
        """
        metadata: SessionHistoryMetadataDAO = self._read_metadata_sync(session_id=session_id)
        normalized_key: str = normalize_session_name_key(session_name=session_name)
        self._assert_session_name_key_available(
            session_name_key=normalized_key,
            owning_session_id=session_id,
        )
        metadata.session_name = session_name.strip()
        metadata.session_name_key = normalized_key
        metadata.updated_at = datetime.now(timezone.utc)
        self._write_metadata_sync(metadata=metadata)
        return metadata

    def _assert_session_name_key_available(
        self,
        *,
        session_name_key: str,
        owning_session_id: str,
    ) -> None:
        """Raise when another session already owns ``session_name_key``.

        Args:
            session_name_key (str): Normalized key being claimed.
            owning_session_id (str): Session currently being updated.

        Raises:
            ValueError: When another session already owns the key.
        """
        for metadata in self._load_all_metadata_sync():
            if metadata.session_id == owning_session_id:
                continue
            if metadata.session_name_key != session_name_key:
                continue
            raise ValueError(f"session name already in use: {metadata.session_name or session_name_key}")

    def _ensure_root(self) -> None:
        """Create the history root directory tree with private permissions."""
        self._root.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
        # Re-chmod the leaf so a hand-edited mode is corrected.
        try:
            self._root.chmod(_DIR_MODE)
        except FileNotFoundError:
            pass

    def _ensure_session_dir(self, *, path: Path) -> None:
        """Create one session directory with private permissions."""
        path.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
        path.chmod(_DIR_MODE)

    def _read_metadata_sync(
        self,
        *,
        session_id: str,
    ) -> SessionHistoryMetadataDAO:
        """Synchronously parse ``session.json`` for ``session_id``."""
        path: Path = self._metadata_path(session_id=session_id)
        if not path.exists():
            raise FileNotFoundError(f"No persisted session metadata at {path}; call ensure_session first.")
        payload: dict = json.loads(path.read_text(encoding="utf-8"))
        return SessionHistoryMetadataDAO.model_validate(payload)

    def _update_metadata_model_name_sync(
        self,
        *,
        session_id: str,
        model_name: str,
    ) -> None:
        """Synchronously set ``model_name`` on persisted metadata and rewrite."""
        metadata: SessionHistoryMetadataDAO = self._read_metadata_sync(session_id=session_id)
        metadata.model_name = model_name
        metadata.updated_at = datetime.now(timezone.utc)
        self._write_metadata_sync(metadata=metadata)

    def _write_metadata_sync(
        self,
        *,
        metadata: SessionHistoryMetadataDAO,
    ) -> None:
        """Atomically rewrite ``session.json`` via temp file + rename."""
        path: Path = self._metadata_path(session_id=metadata.session_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
        path.parent.chmod(_DIR_MODE)
        tmp: Path = path.with_suffix(path.suffix + ".tmp")
        payload: str = metadata.model_dump_json(indent=2)
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.chmod(_FILE_MODE)
        tmp.replace(path)

    def _append_event_line(self, *, event: SessionHistoryEventDAO) -> None:
        """Append one JSONL line to ``events.jsonl`` and fsync."""
        path: Path = self._events_path(session_id=event.session_id)
        is_new: bool = not path.exists()
        line: str = event.model_dump_json()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if is_new:
            path.chmod(_FILE_MODE)

    def _compact_to_boundary_sync(
        self,
        *,
        session_id: str,
        events: list[SessionHistoryEventDAO],
        result: CompactionResult,
        turn_id: str,
    ) -> SessionHistoryEventDAO:
        """Synchronously commit one all-or-nothing compaction candidate.

        Args:
            session_id (str): Session owner.
            events (list[SessionHistoryEventDAO]): Pre-compaction events.
            result (CompactionResult): LLM-produced summary metadata.
            turn_id (str): Compaction-originating turn id.

        Returns:
            SessionHistoryEventDAO: Summary assigned the transaction sequence.
        """
        metadata: SessionHistoryMetadataDAO = self._read_metadata_sync(session_id=session_id)
        sequence: int = metadata.latest_sequence + 1
        summary_event: SessionHistoryEventDAO = SessionHistoryEventDAO(
            session_id=session_id,
            turn_id=turn_id,
            kind="compaction_summary",
            sequence=sequence,
            payload=SessionHistoryEventPayloadDAO(
                content=result.summary_text,
                token_usage=math.ceil(len(result.summary_text) / 4),
                metadata={
                    "first_kept_entry_id": result.first_kept_entry_id,
                    "cut_point_entry_id": result.cut_point_entry_id,
                    "tokens_before": result.tokens_before,
                    "tokens_after": result.tokens_after,
                },
            ),
        )
        retain_from_sequence: int = self._resolve_retain_boundary_sequence(
            events=events,
            first_kept_entry_id=result.first_kept_entry_id,
        )
        candidate_events: list[SessionHistoryEventDAO] = self._build_post_compaction_events(
            events=events,
            retain_from_sequence=retain_from_sequence,
            summary_event=summary_event,
        )
        self._commit_compaction_transaction(
            session_id=session_id,
            candidate_events=candidate_events,
            metadata=metadata,
            sequence=sequence,
        )
        return summary_event

    def _truncate_to_compaction_boundary_sync(
        self,
        *,
        session_id: str,
        events: list[SessionHistoryEventDAO],
        first_kept_entry_id: str,
        summary_event: SessionHistoryEventDAO,
    ) -> None:
        """Synchronously rewrite events.jsonl to the post-compaction boundary.

        Args:
            session_id (str): Session owner.
            events (list[SessionHistoryEventDAO]): Pre-compaction event list.
            first_kept_entry_id (str): ``event_id`` of the first retained event.
            summary_event (SessionHistoryEventDAO): The compaction summary event
                to include at the end of the new file.

        Raises:
            FileNotFoundError: When ``events.jsonl`` does not exist.
            ValueError: When ``first_kept_entry_id`` cannot be resolved.
        """
        retain_from_sequence: int = self._resolve_retain_boundary_sequence(
            events=events,
            first_kept_entry_id=first_kept_entry_id,
        )
        new_events: list[SessionHistoryEventDAO] = self._build_post_compaction_events(
            events=events,
            retain_from_sequence=retain_from_sequence,
            summary_event=summary_event,
        )
        self._atomic_replace_events_file(
            session_id=session_id,
            new_events=new_events,
        )

    @staticmethod
    def _resolve_retain_boundary_sequence(
        *,
        events: list[SessionHistoryEventDAO],
        first_kept_entry_id: str,
    ) -> int:
        """Return the sequence of the first retained event.

        Args:
            events (list[SessionHistoryEventDAO]): Pre-compaction event list.
            first_kept_entry_id (str): ``event_id`` to resolve.

        Returns:
            int: Sequence number of the matching event.

        Raises:
            ValueError: When no event in ``events`` carries ``first_kept_entry_id``.
        """
        for event in events:
            if event.event_id == first_kept_entry_id:
                return event.sequence
        raise ValueError(f"first_kept_entry_id {first_kept_entry_id!r} not found in events")

    @staticmethod
    def _build_post_compaction_events(
        *,
        events: list[SessionHistoryEventDAO],
        retain_from_sequence: int,
        summary_event: SessionHistoryEventDAO,
    ) -> list[SessionHistoryEventDAO]:
        """Build the retained-tail + summary list for the new events.jsonl.

        Args:
            events (list[SessionHistoryEventDAO]): Pre-compaction event list.
            retain_from_sequence (int): Sequence of the first event to retain.
            summary_event (SessionHistoryEventDAO): Compaction summary to append.

        Returns:
            list[SessionHistoryEventDAO]: Retained tail events followed by the
                compaction summary.
        """
        retained_tail: list[SessionHistoryEventDAO] = [
            e for e in events if e.sequence >= retain_from_sequence
        ]
        return retained_tail + [summary_event]

    def _atomic_replace_events_file(
        self,
        *,
        session_id: str,
        new_events: list[SessionHistoryEventDAO],
    ) -> None:
        """Replace active events using the recoverable compaction transaction.

        Compatibility callers do not update metadata, but still receive the
        candidate/archive/activation recovery guarantees of the store command.

        Args:
            session_id (str): Session owner.
            new_events (list[SessionHistoryEventDAO]): Events for the candidate log.
        """
        metadata: SessionHistoryMetadataDAO = self._read_metadata_sync(session_id=session_id)
        self._commit_compaction_transaction(
            session_id=session_id,
            candidate_events=new_events,
            metadata=metadata,
            sequence=None,
        )

    def _commit_compaction_transaction(
        self,
        *,
        session_id: str,
        candidate_events: list[SessionHistoryEventDAO],
        metadata: SessionHistoryMetadataDAO,
        sequence: Optional[int],
    ) -> None:
        """Durably activate candidate events and optionally advance metadata.

        The pre-transaction active and metadata files are left byte-identical on
        every ordinary failure. If restoration fails after archival, the typed
        error names the deterministic archive for reader-side recovery.

        Args:
            session_id (str): Session owner.
            candidate_events (list[SessionHistoryEventDAO]): Candidate log contents.
            metadata (SessionHistoryMetadataDAO): Pre-transaction metadata object.
            sequence (Optional[int]): New high-water sequence, or ``None`` for
                legacy truncation callers that do not advance metadata.

        Raises:
            HistoryCompactionRecoveryError: When restoring an archived active log fails.
        """
        active_path: Path = self._events_path(session_id=session_id)
        if not active_path.exists():
            raise FileNotFoundError(
                f"events.jsonl not found for session {session_id!r}; call ensure_session first"
            )
        candidate_path: Path = active_path.with_suffix(active_path.suffix + ".compaction-candidate")
        archive_path: Path = self._next_compaction_archive_path(active_path=active_path)
        self._write_events_to_path(path=candidate_path, events=candidate_events)
        archive_created: bool = False
        try:
            active_path.replace(archive_path)
            archive_created = True
            candidate_path.replace(active_path)
            self._write_compaction_metadata(
                metadata=metadata,
                sequence=sequence,
            )
        except Exception:
            self._recover_failed_compaction_activation(
                archive_created=archive_created,
                active_path=active_path,
                archive_path=archive_path,
                candidate_path=candidate_path,
            )
            raise

    def _recover_failed_compaction_activation(
        self,
        *,
        archive_created: bool,
        active_path: Path,
        archive_path: Path,
        candidate_path: Path,
    ) -> None:
        """Restore pre-transaction state after a failed activation step.

        Args:
            archive_created (bool): Whether the live file was moved to archive.
            active_path (Path): Live event-log destination.
            archive_path (Path): Preserved pre-transaction archive.
            candidate_path (Path): Unactivated candidate file.
        """
        self._remove_path_if_exists(path=candidate_path)
        if not archive_created:
            return
        self._restore_archived_active_or_raise(
            active_path=active_path,
            archive_path=archive_path,
        )

    def _write_compaction_metadata(
        self,
        *,
        metadata: SessionHistoryMetadataDAO,
        sequence: Optional[int],
    ) -> None:
        """Advance metadata only after the candidate has become active.

        Args:
            metadata (SessionHistoryMetadataDAO): Metadata copied from durable state.
            sequence (Optional[int]): New sequence, or ``None`` when unchanged.
        """
        if sequence is None:
            return
        metadata.latest_sequence = sequence
        metadata.updated_at = datetime.now(timezone.utc)
        self._write_metadata_sync(metadata=metadata)

    def _next_compaction_archive_path(self, *, active_path: Path) -> Path:
        """Return a collision-free deterministic archive path for one transaction.

        Args:
            active_path (Path): Current active event-log path.

        Returns:
            Path: Unused archive path in the active log directory.
        """
        index: int = 1
        while True:
            candidate: Path = active_path.parent / f"{_COMPACTION_ARCHIVE_PREFIX}compaction-{index}.jsonl"
            if not candidate.exists():
                return candidate
            index += 1

    def _restore_archived_active_or_raise(
        self,
        *,
        active_path: Path,
        archive_path: Path,
    ) -> None:
        """Restore the archived active log after a post-archive transaction failure.

        Args:
            active_path (Path): Destination live log path.
            archive_path (Path): Pre-transaction archive path.

        Raises:
            HistoryCompactionRecoveryError: When archive restoration itself fails.
        """
        try:
            self._remove_path_if_exists(path=active_path)
            archive_path.replace(active_path)
        except OSError as exc:
            raise HistoryCompactionRecoveryError(
                active_path=active_path,
                archive_path=archive_path,
            ) from exc

    def _recover_compaction_archive_if_needed(self, *, active_path: Path) -> None:
        """Restore the oldest deterministic archive when no active log exists.

        Args:
            active_path (Path): Expected active events file.

        Raises:
            HistoryCompactionRecoveryError: When an archive exists but cannot be restored.
        """
        if active_path.exists():
            return
        archives: list[Path] = sorted(active_path.parent.glob(f"{_COMPACTION_ARCHIVE_PREFIX}*.jsonl"))
        if not archives:
            return
        archive_path: Path = archives[0]
        try:
            archive_path.replace(active_path)
        except OSError as exc:
            raise HistoryCompactionRecoveryError(
                active_path=active_path,
                archive_path=archive_path,
            ) from exc

    @staticmethod
    def _remove_path_if_exists(*, path: Path) -> None:
        """Remove a file when present.

        Args:
            path (Path): Candidate file to remove.
        """
        try:
            path.unlink()
        except FileNotFoundError:
            return

    @staticmethod
    def _write_events_to_path(
        *,
        path: Path,
        events: list[SessionHistoryEventDAO],
    ) -> None:
        """Serialize ``events`` as JSONL to ``path`` and fsync.

        Args:
            path (Path): Destination file path (will be created or overwritten).
            events (list[SessionHistoryEventDAO]): Events to write, one per line.
        """
        lines: str = "\n".join(e.model_dump_json() for e in events) + "\n"
        with path.open("w", encoding="utf-8") as handle:
            handle.write(lines)
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(_FILE_MODE)
