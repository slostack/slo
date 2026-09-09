"""TreeMigrator — convert flat JSONL sessions to tree-format sessions.

Reads events from a ``FilesystemSessionHistoryStore`` flat layout and writes
an equivalent ``events.jsonl`` into a ``TreeBasedFilesystemSessionHistoryStore``
directory, threading ``entry_id`` and ``parent_entry_id`` into every event's
``payload.metadata``.

Parent-link inference rules (applied in priority order):

1. Root event (first by sequence): ``parent_entry_id = None``.
2. ``tool_result`` event with a matching open ``tool_call_id``:
   ``parent_entry_id`` = the ``event_id`` of the opening ``tool_call``.
3. ``tool_result`` event with no matching ``tool_call_id``:
   ``parent_entry_id`` = ``event_id`` of the previous event (linear fallback).
4. ``tool_call`` event: ``parent_entry_id`` = ``event_id`` of the preceding
   ``assistant_message`` in the same ``turn_id``, if one exists; otherwise
   the previous event's ``event_id``.
5. All other event kinds: ``parent_entry_id`` = ``event_id`` of the previous
   event in sequence order.

The migration is non-destructive when ``flat_root != tree_root``: the flat
source ``events.jsonl`` is never modified. When the roots are the same, the
file is replaced atomically via a ``.tmp`` sibling.

Usage::

    migrator = TreeMigrator()
    result = migrator.migrate_session(session_id="s-abc")
    print(result.events_migrated, result.tool_links_resolved)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from config.cfg import SLO_HOME as _CFG_SLO_HOME

from pydantic import BaseModel, ConfigDict, Field

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
)

__all__ = ["MigrationResult", "TreeMigrator"]

_logger = logging.getLogger(__name__)

_DIR_MODE: int = 0o700
_FILE_MODE: int = 0o600


def _default_history_root() -> Path:
    """Return the default on-disk history root.

    Honours ``SLO_HOME`` for parity with ``FilesystemSessionHistoryStore``.

    Returns:
        Path: Resolved absolute path of ``~/.slo/sessions/history``.
    """
    return (_CFG_SLO_HOME / "sessions" / "history").resolve()


class MigrationResult(BaseModel):
    """Outcome of one ``TreeMigrator.migrate_session()`` call.

    Attributes:
        session_id (str): The session that was migrated.
        events_migrated (int): Total number of event lines written to the
            output ``events.jsonl``.
        tool_links_resolved (int): Number of ``tool_result`` events whose
            ``parent_entry_id`` was resolved to an explicit ``tool_call``
            event via ``payload.tool_call_id`` matching.
        unresolved_tool_results (int): Number of ``tool_result`` events that
            fell back to linear chaining because their ``tool_call_id`` was
            not found in the open-calls map. Non-zero when a ``tool_call``
            event was malformed, absent, or had a blank ``tool_call_id``.
    """

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(description="The session that was migrated.")
    events_migrated: int = Field(
        description="Total number of event lines written to the output events.jsonl."
    )
    tool_links_resolved: int = Field(
        description="Number of tool_result events whose parent_entry_id was resolved to an explicit tool_call event via tool_call_id matching."
    )
    unresolved_tool_results: int = Field(
        description="Number of tool_result events that fell back to linear chaining because their tool_call_id was not found in the open-calls map."
    )


class TreeMigrator:
    """Convert flat JSONL sessions to the tree format used by TreeBasedFilesystemSessionHistoryStore.

    Reads ``events.jsonl`` from the flat store directory, infers
    ``entry_id`` and ``parent_entry_id`` for every event, and writes
    an enriched ``events.jsonl`` to the tree store directory. The flat
    source is never modified when ``flat_root != tree_root``.

    When ``flat_root`` and ``tree_root`` are the same path (the default),
    the migrator overwrites the existing ``events.jsonl`` in-place via the
    atomic ``.tmp`` pattern. This is the recommended production usage.
    Supplying a separate ``tree_root`` is useful for testing or for a
    dry-run workflow where the operator inspects the output before swapping.

    Example::

        migrator = TreeMigrator()
        result = migrator.migrate_session(session_id="s-xyz")
        print(f"Migrated {result.events_migrated} events, "
              f"{result.tool_links_resolved} tool links resolved.")
    """

    def __init__(
        self,
        *,
        flat_root: Optional[Path] = None,
        tree_root: Optional[Path] = None,
    ) -> None:
        """Initialise the migrator with source and output history roots.

        Args:
            flat_root (Optional[Path]): Root of the flat (source) session store.
                Defaults to ``~/.slo/sessions/history`` when ``None``.
            tree_root (Optional[Path]): Root of the tree (output) session store.
                Defaults to the same path as ``flat_root`` when ``None``,
                which causes the migrator to overwrite the existing JSONL in-place.
        """
        resolved_flat: Path = (flat_root or _default_history_root()).expanduser().resolve()
        self._flat_root: Path = resolved_flat
        self._tree_root: Path = (tree_root or flat_root or _default_history_root()).expanduser().resolve()

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def migrate_session(self, *, session_id: str) -> MigrationResult:
        """Convert one flat session's ``events.jsonl`` to tree format.

        Reads events from ``_flat_root/<session_id>/events.jsonl``, infers
        parent links, and writes enriched events to
        ``_tree_root/<session_id>/events.jsonl`` atomically. If
        ``_tree_root != _flat_root``, the session directory and ``session.json``
        are also created / copied in the tree root.

        Malformed JSON lines in the source file are skipped with a warning.
        Events with no ``event_id`` are skipped with a warning.

        Args:
            session_id (str): The session to migrate.

        Returns:
            MigrationResult: Statistics about the migration.

        Raises:
            FileNotFoundError: When the source ``events.jsonl`` does not exist.
        """
        source_events_path: Path = self._flat_root / session_id / "events.jsonl"
        if not source_events_path.exists():
            raise FileNotFoundError(
                f"Source events.jsonl not found for session {session_id!r} " f"at {source_events_path}"
            )

        sorted_events: list[SessionHistoryEventDAO] = self._load_events_sorted(
            path=source_events_path,
            session_id=session_id,
        )

        output_dir: Path = self._tree_root / session_id
        self._ensure_dir(path=output_dir)

        if self._tree_root != self._flat_root:
            self._copy_session_json(
                session_id=session_id,
                output_dir=output_dir,
            )

        enriched_lines, tool_links_resolved, unresolved_tool_results = self._enrich_events(
            events=sorted_events
        )

        output_events_path: Path = output_dir / "events.jsonl"
        self._atomic_rewrite(path=output_events_path, lines=enriched_lines)

        result = MigrationResult(
            session_id=session_id,
            events_migrated=len(enriched_lines),
            tool_links_resolved=tool_links_resolved,
            unresolved_tool_results=unresolved_tool_results,
        )
        _logger.info(
            "TreeMigrator: session %r — %d events migrated, "
            "%d tool links resolved, %d unresolved tool_results",
            session_id,
            result.events_migrated,
            result.tool_links_resolved,
            result.unresolved_tool_results,
        )
        return result

    # ------------------------------------------------------------------
    # Private — event loading
    # ------------------------------------------------------------------

    def _load_events_sorted(
        self,
        *,
        path: Path,
        session_id: str,
    ) -> list[SessionHistoryEventDAO]:
        """Load and sort all events from a raw ``events.jsonl`` file.

        Lines that fail JSON parsing or DAO validation are logged and skipped.
        The returned list is sorted by ``event.sequence`` ascending.

        Args:
            path (Path): Absolute path to ``events.jsonl``.
            session_id (str): Session identifier (used in log messages only).

        Returns:
            list[SessionHistoryEventDAO]: All valid events in sequence order.
        """
        raw_text: str = path.read_text(encoding="utf-8")
        events: list[SessionHistoryEventDAO] = []

        for line_number, raw_line in enumerate(raw_text.split("\n"), start=1):
            # JSONL framing is physical LF-delimited; ``splitlines()`` is too
            # broad because it also splits on Unicode separators that may live
            # inside a JSON string payload.
            stripped: str = raw_line.rstrip("\r").strip()
            if not stripped:
                continue

            try:
                raw_dict: dict = json.loads(stripped)
            except json.JSONDecodeError:
                _logger.warning(
                    "TreeMigrator: skipping malformed JSON on line %d of session %r",
                    line_number,
                    session_id,
                )
                continue

            try:
                event: SessionHistoryEventDAO = SessionHistoryEventDAO.model_validate(raw_dict)
            except Exception:
                _logger.warning(
                    "TreeMigrator: skipping line %d of session %r — DAO validation failed",
                    line_number,
                    session_id,
                    exc_info=True,
                )
                continue

            if not event.event_id:
                _logger.warning(
                    "TreeMigrator: skipping line %d of session %r — event has no event_id",
                    line_number,
                    session_id,
                )
                continue

            events.append(event)

        events.sort(key=lambda e: e.sequence)
        return events

    # ------------------------------------------------------------------
    # Private — parent-link inference
    # ------------------------------------------------------------------

    def _enrich_events(
        self,
        *,
        events: list[SessionHistoryEventDAO],
    ) -> tuple[list[str], int, int]:
        """Thread ``entry_id`` and ``parent_entry_id`` into every event.

        Walks ``events`` in the order provided (must be sorted by sequence).
        Applies the parent-link inference rules and serialises each enriched
        event to a compact JSON string.

        Args:
            events (list[SessionHistoryEventDAO]): Events in sequence order.

        Returns:
            tuple[list[str], int, int]: A 3-tuple of:
                - enriched_lines: compact JSON strings ready to write, one per event.
                - tool_links_resolved: count of tool_result events resolved
                  to an explicit tool_call parent.
                - unresolved_tool_results: count of tool_result events that
                  fell back to linear chaining.
        """
        enriched_lines: list[str] = []
        tool_links_resolved: int = 0
        unresolved_tool_results: int = 0

        last_event_id: Optional[str] = None
        open_tool_calls: dict[str, str] = {}
        last_assistant_message_per_turn: dict[str, str] = {}

        for index, event in enumerate(events):
            is_root: bool = index == 0

            parent_id: Optional[str]
            if is_root:
                parent_id = None
            elif event.kind == "tool_result":
                tool_call_id: str = event.payload.tool_call_id or ""
                if tool_call_id and tool_call_id in open_tool_calls:
                    parent_id = open_tool_calls.pop(tool_call_id)
                    tool_links_resolved += 1
                else:
                    parent_id = last_event_id
                    unresolved_tool_results += 1
                    if tool_call_id:
                        _logger.warning(
                            "TreeMigrator: tool_result with tool_call_id=%r has no "
                            "matching open tool_call — using linear parent",
                            tool_call_id,
                        )
            elif event.kind == "tool_call":
                turn_id: Optional[str] = event.turn_id
                if turn_id and turn_id in last_assistant_message_per_turn:
                    parent_id = last_assistant_message_per_turn[turn_id]
                else:
                    parent_id = last_event_id
            else:
                parent_id = last_event_id

            metadata: dict = dict(event.payload.metadata)
            metadata["entry_id"] = event.event_id
            metadata["parent_entry_id"] = parent_id

            enriched_payload = event.payload.model_copy(update={"metadata": metadata})
            enriched_event = event.model_copy(update={"payload": enriched_payload})
            enriched_lines.append(enriched_event.model_dump_json())

            # Update state for the next iteration.
            if event.kind == "tool_call":
                tc_id: str = event.payload.tool_call_id or ""
                if tc_id:
                    open_tool_calls[tc_id] = event.event_id

            if event.kind == "assistant_message" and event.turn_id:
                last_assistant_message_per_turn[event.turn_id] = event.event_id

            last_event_id = event.event_id

        return enriched_lines, tool_links_resolved, unresolved_tool_results

    # ------------------------------------------------------------------
    # Private — filesystem helpers
    # ------------------------------------------------------------------

    def _ensure_dir(self, *, path: Path) -> None:
        """Create a directory with private permissions if it does not exist.

        Args:
            path (Path): Directory to create.
        """
        path.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
        path.chmod(_DIR_MODE)

    def _copy_session_json(
        self,
        *,
        session_id: str,
        output_dir: Path,
    ) -> None:
        """Copy ``session.json`` from the flat root to the tree output directory.

        A no-op when the source ``session.json`` does not exist (rare but
        possible if the session was partially initialised).

        Args:
            session_id (str): Session identifier.
            output_dir (Path): Destination directory for the copied file.
        """
        source_path: Path = self._flat_root / session_id / "session.json"
        if not source_path.exists():
            _logger.warning(
                "TreeMigrator: no session.json found at %s — skipping copy",
                source_path,
            )
            return

        dest_path: Path = output_dir / "session.json"
        raw_text: str = source_path.read_text(encoding="utf-8")
        tmp_path: Path = dest_path.with_suffix(dest_path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(raw_text)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.chmod(_FILE_MODE)
        tmp_path.replace(dest_path)

    def _atomic_rewrite(self, *, path: Path, lines: list[str]) -> None:
        """Write ``lines`` to ``path`` atomically via a ``.tmp`` sibling.

        Each element in ``lines`` is written as a complete JSONL line
        followed by a newline character. The ``.tmp`` file is fsynced before
        being renamed so a crash cannot leave a partial file at ``path``.

        Args:
            path (Path): Target file path.
            lines (list[str]): Serialised JSON strings, one per event.
        """
        tmp_path: Path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            for line in lines:
                handle.write(line)
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.chmod(_FILE_MODE)
        tmp_path.replace(path)
