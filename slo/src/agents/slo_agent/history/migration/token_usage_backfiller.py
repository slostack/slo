"""TokenUsageBackfiller — back-fill token_usage for pre-01.a.1 events.

Reads the raw ``events.jsonl`` for one or more sessions, computes
``token_usage`` for every event line where the field is absent or ``None``,
and atomically rewrites the file via a ``.tmp`` sibling. The source file is
never partially overwritten; a crash between the write and the rename leaves
the original file intact.

Usage::

    backfiller = TokenUsageBackfiller()
    results = backfiller.backfill_last_n_sessions(n=3)
    for session_id, count in results.items():
        print(f"{session_id}: {count} events updated")
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from config.cfg import SLO_HOME as _CFG_SLO_HOME

from src.agents.slo_agent.compaction.token_estimator import TokenEstimator
from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryMetadataDAO,
)

__all__ = ["TokenUsageBackfiller"]

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


class TokenUsageBackfiller:
    """Back-fill ``payload.token_usage`` for events that pre-date sub-spec 01.a.1.

    Reads the raw ``events.jsonl`` for each target session and rewrites it
    atomically. Events whose ``payload.token_usage`` is already set are left
    untouched. Malformed JSON lines are skipped with a warning and left
    unchanged in the output.

    The rewrite is atomic: a ``.tmp`` sibling is written, fsynced, chmoded,
    and then ``os.replace()``-d over the live file. The session's
    ``session.json`` is never touched.

    Example::

        backfiller = TokenUsageBackfiller()
        count = backfiller.backfill_session(session_id="s-abc")
        # count == number of events that received a token_usage value

        results = backfiller.backfill_last_n_sessions(n=5)
        # results == {"s-abc": 12, "s-def": 7, ...}
    """

    def __init__(self, *, root: Optional[Path] = None) -> None:
        """Initialise the backfiller with a history root directory.

        Args:
            root (Optional[Path]): Override the history root. Defaults to
                ``~/.slo/sessions/history`` when ``None``.
        """
        self._root: Path = (root or _default_history_root()).expanduser().resolve()

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def backfill_session(self, *, session_id: str) -> int:
        """Rewrite ``events.jsonl`` for one session, filling in token_usage.

        Reads all lines from the session's ``events.jsonl``. For each line
        where ``payload.token_usage`` is ``None`` or absent, computes the
        token estimate via ``TokenEstimator.estimate()`` and replaces the
        raw JSON dict in memory. After processing all lines, atomically
        rewrites ``events.jsonl`` via a ``.tmp`` sibling.

        Args:
            session_id (str): The session whose events file to process.

        Returns:
            int: The number of event lines that were updated (i.e. received a
                non-None ``token_usage`` value for the first time). Lines that
                were already stamped or that failed JSON parsing are excluded
                from the count.

        Raises:
            FileNotFoundError: When the session directory or ``events.jsonl``
                does not exist.
        """
        events_path: Path = self._events_path(session_id=session_id)
        if not events_path.exists():
            raise FileNotFoundError(
                f"events.jsonl not found for session {session_id!r} at {events_path}"
            )

        raw_text: str = events_path.read_text(encoding="utf-8")
        # JSONL framing is literal LF-delimited. ``splitlines()`` would split
        # on Unicode separators that may appear inside a JSON string payload.
        raw_lines: list[str] = raw_text.split("\n")

        updated_lines: list[str] = []
        updated_count: int = 0

        for line_number, raw_line in enumerate(raw_lines, start=1):
            stripped: str = raw_line.rstrip("\r").strip()
            if not stripped:
                updated_lines.append(raw_line)
                continue

            try:
                raw_dict: dict = json.loads(stripped)
            except json.JSONDecodeError:
                _logger.warning(
                    "TokenUsageBackfiller: skipping malformed JSON on line %d "
                    "of session %r",
                    line_number,
                    session_id,
                )
                updated_lines.append(raw_line)
                continue

            payload_dict: dict = raw_dict.get("payload", {})
            if payload_dict.get("token_usage") is not None:
                # Already stamped — leave the raw line unchanged.
                updated_lines.append(raw_line)
                continue

            try:
                event: SessionHistoryEventDAO = SessionHistoryEventDAO.model_validate(
                    raw_dict
                )
            except Exception:
                _logger.warning(
                    "TokenUsageBackfiller: skipping line %d of session %r — "
                    "DAO validation failed",
                    line_number,
                    session_id,
                    exc_info=True,
                )
                updated_lines.append(raw_line)
                continue

            usage: int = TokenEstimator.estimate(event=event)
            raw_dict["payload"]["token_usage"] = usage
            updated_lines.append(json.dumps(raw_dict, ensure_ascii=False))
            updated_count += 1

        self._atomic_rewrite(path=events_path, lines=updated_lines)
        _logger.info(
            "TokenUsageBackfiller: session %r — %d events updated",
            session_id,
            updated_count,
        )
        return updated_count

    def backfill_last_n_sessions(self, *, n: int = 3) -> dict[str, int]:
        """Discover and back-fill the N most recently active sessions.

        Scans the history root for session directories that contain both
        ``events.jsonl`` and ``session.json``. Sorts the discovered sessions
        by ``updated_at`` descending (most recently active first) and processes
        the first ``n`` entries.

        Sessions whose ``session.json`` cannot be parsed are skipped with a
        warning. Sessions that raise errors during ``backfill_session`` are
        also skipped with a logged error.

        Args:
            n (int): Number of sessions to process. Defaults to 3. Must be
                >= 1.

        Returns:
            dict[str, int]: Mapping of ``session_id`` to count of events
                updated. Sessions that raised errors are absent from the result.

        Raises:
            ValueError: When ``n`` < 1.
        """
        if n < 1:
            raise ValueError(f"n must be >= 1, got {n!r}")

        candidates: list[SessionHistoryMetadataDAO] = self._discover_sessions()
        candidates.sort(key=lambda m: m.updated_at, reverse=True)
        selected: list[SessionHistoryMetadataDAO] = candidates[:n]

        results: dict[str, int] = {}
        for metadata in selected:
            try:
                count: int = self.backfill_session(session_id=metadata.session_id)
                results[metadata.session_id] = count
            except Exception:
                _logger.error(
                    "TokenUsageBackfiller: error backfilling session %r — skipping",
                    metadata.session_id,
                    exc_info=True,
                )
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _session_dir(self, *, session_id: str) -> Path:
        """Return the per-session directory path.

        Args:
            session_id (str): Session identifier.

        Returns:
            Path: Absolute path to the session directory.
        """
        return self._root / session_id

    def _events_path(self, *, session_id: str) -> Path:
        """Return the per-session ``events.jsonl`` path.

        Args:
            session_id (str): Session identifier.

        Returns:
            Path: Absolute path to ``events.jsonl``.
        """
        return self._session_dir(session_id=session_id) / "events.jsonl"

    def _metadata_path(self, *, session_id: str) -> Path:
        """Return the per-session ``session.json`` path.

        Args:
            session_id (str): Session identifier.

        Returns:
            Path: Absolute path to ``session.json``.
        """
        return self._session_dir(session_id=session_id) / "session.json"

    def _discover_sessions(self) -> list[SessionHistoryMetadataDAO]:
        """Scan the history root and return parsed metadata for all valid sessions.

        A valid session is a subdirectory of the history root that contains
        both ``events.jsonl`` and ``session.json``. Subdirectories that are
        missing either file are ignored. ``session.json`` files that fail
        JSON parsing or DAO validation are logged and skipped.

        Returns:
            list[SessionHistoryMetadataDAO]: Parsed metadata records, one per
                valid session. Order is unspecified (callers sort).
        """
        if not self._root.exists():
            return []

        records: list[SessionHistoryMetadataDAO] = []
        for candidate_dir in self._root.iterdir():
            if not candidate_dir.is_dir():
                continue

            events_path: Path = candidate_dir / "events.jsonl"
            metadata_path: Path = candidate_dir / "session.json"
            if not events_path.exists() or not metadata_path.exists():
                continue

            try:
                raw: dict = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata: SessionHistoryMetadataDAO = (
                    SessionHistoryMetadataDAO.model_validate(raw)
                )
                records.append(metadata)
            except Exception:
                _logger.warning(
                    "TokenUsageBackfiller: could not parse session.json at %s — skipping",
                    metadata_path,
                    exc_info=True,
                )
        return records

    def _atomic_rewrite(self, *, path: Path, lines: list[str]) -> None:
        """Write ``lines`` to ``path`` atomically via a ``.tmp`` sibling.

        Writes every line followed by a newline character. The ``.tmp`` file is
        fsynced before being renamed so a power-loss between write and rename
        cannot leave a zero-byte or partial file at ``path``.

        Args:
            path (Path): The target file to overwrite.
            lines (list[str]): Output lines (blank lines are preserved as-is).
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
