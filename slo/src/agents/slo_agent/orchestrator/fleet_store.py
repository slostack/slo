"""FleetStore — durable projections of a ProcessRegistry.

The registry remains the in-memory write authority. This store gives TUI,
visualizer, reconcile, and sweep readers a durable post-mortem snapshot in the
released ``fleet.json`` shape, plus the feature-94 versioned identity
projections: ``execution-index.v1.json`` beside fleet.json and one
``children/<id>/execution.v1.json`` sibling per child. Old readers ignore the
versioned files; new readers trust old-shaped child files only through
``load_verified_execution``.

Sub-spec 71.a.2; feature 94.a.4 (T02).
"""

from __future__ import annotations

import hashlib
import io
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from config.logger import log_warning
from src.agents.slo_agent.history.atomic_io import AtomicFileWriter
from src.agents.slo_agent.orchestrator.dao import (
    ChildExecutionEvidenceDAO,
    ExecutionIndexDAO,
    FleetSnapshotDAO,
    StdoutCaptureIdentityDAO,
    SubAgentStatusDAO,
)
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout

__all__ = ["FleetStore", "MAX_EVIDENCE_BYTES"]

MAX_EVIDENCE_BYTES: int = 64 * 1024
"""Decode bound for the execution sibling and execution index only; digested
old-shaped child files are hashed by streaming with no bound."""


class FleetStore:
    """Persist and load the durable projection for one orchestrator fleet."""

    def __init__(
        self,
        *,
        history_root: Path,
        orchestrator_session_id: str,
        workflow_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> None:
        """Bind a store to one orchestrator session's fleet path.

        WHAT: Retains the identity needed to build and load one fleet snapshot and,
            for a writer bound to a run, its versioned identity projections.
        WHO: Called by SubAgentPool while it builds its ProcessRegistry, and by
            read-only post-mortem readers without a run identity.
        WHEN: Once for each orchestrator session.

        Args:
            history_root (Path): Root containing session history directories.
            orchestrator_session_id (str): Session that owns this fleet.
            workflow_id (Optional[str]): Detached workflow identifier when known.
            run_id (Optional[str]): Pool composition run UUID. None keeps a legacy
                fleet-only store that writes no execution index.
        """
        self._history_root: Path = history_root
        self._orchestrator_session_id: str = orchestrator_session_id
        self._workflow_id: Optional[str] = workflow_id
        self._run_id: Optional[str] = run_id
        self._snapshot_path: Path = OrchestrationLayout.fleet_path(
            history_root=history_root,
            orchestrator_session_id=orchestrator_session_id,
        )

    def persist(self, *, entries: list[SubAgentStatusDAO]) -> None:
        """Persist a complete fleet snapshot without interrupting the run path.

        WHAT: Writes the run's execution index first, then the registry's current
            entries in the released fleet.json shape, both through the shared
            atomic writer. Each write failure is logged with a fixed reason only.
        WHO: Called by ProcessRegistry after durable lifecycle transitions.
        WHEN: On registration, running, terminal, and explicit flush transitions.

        Args:
            entries (list[SubAgentStatusDAO]): Current entries in registration order.
        """
        self._persist_index(entries=entries)
        snapshot: FleetSnapshotDAO = FleetSnapshotDAO(
            orchestrator_session_id=self._orchestrator_session_id,
            workflow_id=self._workflow_id,
            entries=entries,
            updated_at=datetime.now(tz=timezone.utc).isoformat(),
        )
        try:
            AtomicFileWriter.write_json(path=self._snapshot_path, model=snapshot)
        except OSError as exc:
            log_warning(
                msg="fleet_snapshot_persist_failed",
                orchestrator_session_id=self._orchestrator_session_id,
                error=str(exc),
            )

    def _persist_index(self, *, entries: list[SubAgentStatusDAO]) -> None:
        """Write the session-to-incarnation index for a run-bound writer.

        WHAT: Projects each entry's runtime execution_id into execution-index.v1.json.
        WHO: Called only by persist, before fleet.json is replaced.
        WHEN: On every durable registry transition; skipped for legacy stores.

        Args:
            entries (list[SubAgentStatusDAO]): Current entries in registration order.
        """
        if self._run_id is None:
            return
        index: ExecutionIndexDAO = ExecutionIndexDAO(
            orchestrator_session_id=self._orchestrator_session_id,
            run_id=self._run_id,
            executions={entry.session_id: entry.execution_id for entry in entries if entry.execution_id},
            updated_at=datetime.now(tz=timezone.utc).isoformat(),
        )
        try:
            AtomicFileWriter.write_json(
                path=OrchestrationLayout.execution_index_path(
                    history_root=self._history_root,
                    orchestrator_session_id=self._orchestrator_session_id,
                ),
                model=index,
            )
        except OSError:
            log_warning(
                msg="execution_index_persist_failed", orchestrator_session_id=self._orchestrator_session_id
            )

    def publish_execution(self, *, evidence: ChildExecutionEvidenceDAO) -> bool:
        """Replace one child's versioned execution sibling.

        WHAT: Atomically writes ``children/<id>/execution.v1.json`` for the evidence.
        WHO: Called by ProcessRegistry for pending, running and terminal phases.
        WHEN: Pending before the pending fleet row; running after fresh context and
            capture exist; terminal after the exact status.json bytes are written.

        Args:
            evidence (ChildExecutionEvidenceDAO): Complete phase evidence to publish.

        Returns:
            bool: True when the sibling committed; False after a logged write failure,
                which leaves disk observation stale but never falsely complete.
        """
        try:
            AtomicFileWriter.write_json(
                path=OrchestrationLayout.child_execution_path(
                    history_root=self._history_root,
                    parent_session_id=self._orchestrator_session_id,
                    child_session_id=evidence.session_id,
                ),
                model=evidence,
            )
        except OSError:
            log_warning(
                msg="execution_evidence_publish_failed",
                orchestrator_session_id=self._orchestrator_session_id,
                session_id=evidence.session_id,
                phase=evidence.phase,
            )
            return False
        return True

    @classmethod
    def load_verified_execution(
        cls,
        *,
        history_root: Path,
        orchestrator_session_id: str,
        child_session_id: str,
    ) -> Optional[ChildExecutionEvidenceDAO]:
        """Return a child's sibling only when every identity check agrees.

        WHAT: Requires the run index to map the child to the sibling's execution_id,
            then checks the stdout capture (device, inode), the spawn-context digest
            and, when terminal, the status.json digest against current bytes, and
            finally requires the sibling to be byte-identical after those reads.
        WHO: Called by new progress/session readers before trusting old-shaped
            child files; old readers never call it.
        WHEN: On every observation of one child.

        Args:
            history_root (Path): Root containing session history directories.
            orchestrator_session_id (str): Parent session owning the fleet.
            child_session_id (str): Child whose incarnation evidence is verified.

        Returns:
            Optional[ChildExecutionEvidenceDAO]: Verified evidence, or None when any
                evidence is missing, oversized, malformed, stale or changed.
        """
        try:
            sibling_path: Path = OrchestrationLayout.child_execution_path(
                history_root=history_root,
                parent_session_id=orchestrator_session_id,
                child_session_id=child_session_id,
            )
            index_path: Path = OrchestrationLayout.execution_index_path(
                history_root=history_root, orchestrator_session_id=orchestrator_session_id
            )
            sibling_before: bytes = cls._read_bounded(path=sibling_path)
            evidence = ChildExecutionEvidenceDAO.model_validate_json(sibling_before)
            index = ExecutionIndexDAO.model_validate_json(cls._read_bounded(path=index_path))
        except (OSError, ValueError, ValidationError):
            return None
        files_match: bool = index.executions.get(
            child_session_id
        ) == evidence.execution_id and cls._files_match(child_dir=sibling_path.parent, evidence=evidence)
        if not files_match or cls._read_bounded_or_empty(path=sibling_path) != sibling_before:
            return None
        return evidence

    @classmethod
    def _files_match(cls, *, child_dir: Path, evidence: ChildExecutionEvidenceDAO) -> bool:
        """Check capture identity and exact-byte digests named by the evidence.

        Args:
            child_dir (Path): Child capture directory holding the old-shaped files.
            evidence (ChildExecutionEvidenceDAO): Decoded sibling to verify.

        Returns:
            bool: True when every identity the evidence names matches current files.
        """
        checks: list[tuple[Optional[str], Path]] = [
            (evidence.spawn_context_sha256, child_dir / "spawn_context.json"),
            (evidence.status_sha256, child_dir / "status.json"),
        ]
        digests_match: bool = all(
            digest is None or cls._digest_or_empty(path=path) == digest for digest, path in checks
        )
        return digests_match and cls._capture_matches(
            stdout_path=child_dir / "stdout.jsonl", identity=evidence.stdout_identity
        )

    @staticmethod
    def _capture_matches(*, stdout_path: Path, identity: Optional[StdoutCaptureIdentityDAO]) -> bool:
        """Return whether the stdout capture is the exact file the evidence names.

        Args:
            stdout_path (Path): Current stdout capture path.
            identity (Optional[StdoutCaptureIdentityDAO]): Expected identity; None
                means no capture is trusted, which trivially matches.

        Returns:
            bool: True when no identity is required or the (device, inode) match.
        """
        if identity is None:
            return True
        try:
            capture_stat: os.stat_result = os.stat(stdout_path, follow_symlinks=False)
        except OSError:
            return False
        return (capture_stat.st_dev, capture_stat.st_ino) == (identity.device, identity.inode)

    @classmethod
    def _digest_or_empty(cls, *, path: Path) -> str:
        """Return the streamed SHA-256 of a digested child file, or empty when unreadable.

        Digested old-shaped files (status.json, spawn_context.json) carry unbounded
        answers and prompts, so they are hashed in chunks with no decode bound.
        """
        try:
            with cls._open_regular(path=path) as handle:
                return hashlib.file_digest(handle, "sha256").hexdigest()
        except OSError:
            return ""

    @classmethod
    def _read_bounded_or_empty(cls, *, path: Path) -> bytes:
        """Return bounded file bytes, or empty bytes when unreadable or oversized."""
        try:
            return cls._read_bounded(path=path)
        except (OSError, ValueError):
            return b""

    @classmethod
    def _read_bounded(cls, *, path: Path) -> bytes:
        """Read a sibling or index file, refusing it once it exceeds the decode bound.

        Reads at most one byte past MAX_EVIDENCE_BYTES, so an oversized or hostile
        file is never loaded whole.

        Args:
            path (Path): Execution sibling or execution index file.

        Returns:
            bytes: Complete file bytes.

        Raises:
            OSError: If the file is absent, a symlink, not regular, or unreadable.
            ValueError: If the file exceeds MAX_EVIDENCE_BYTES.
        """
        with cls._open_regular(path=path) as handle:
            data: bytes = handle.read(MAX_EVIDENCE_BYTES + 1)
        if len(data) > MAX_EVIDENCE_BYTES:
            raise ValueError("evidence file exceeds the decode bound")
        return data

    @staticmethod
    def _open_regular(*, path: Path) -> io.BufferedReader:
        """Open an evidence file read-only without following a final symlink.

        Opening with ``O_NOFOLLOW`` and checking the opened descriptor removes the
        check-then-read race; ``O_NONBLOCK`` keeps a planted FIFO from blocking.

        Args:
            path (Path): Evidence or digested child file.

        Returns:
            io.BufferedReader: Buffered reader over the opened regular file.

        Raises:
            OSError: If the path is absent, a symlink, not a regular file, or unreadable.
        """
        descriptor: int = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise OSError("evidence path is not a regular file")
        return os.fdopen(descriptor, "rb")

    def load(self) -> Optional[FleetSnapshotDAO]:
        """Load this store's fleet snapshot when durable evidence exists.

        WHAT: Delegates parsing to the path-level reader and returns no snapshot on failure.
        WHO: Called by post-mortem fleet readers such as reconcile and visualizer views.
        WHEN: After an orchestrator may have exited.

        Returns:
            Optional[FleetSnapshotDAO]: Parsed durable fleet snapshot, if valid.
        """
        return self.load_snapshot(path=self._snapshot_path)

    @classmethod
    def load_snapshot(cls, *, path: Path) -> Optional[FleetSnapshotDAO]:
        """Load one fleet snapshot path without raising reader-facing errors.

        WHAT: Parses a durable fleet file and logs corrupt or unreadable content.
        WHO: Called by FleetStore.load and future filesystem-only fleet readers.
        WHEN: Whenever a reader needs durable fleet evidence.

        Args:
            path (Path): Canonical fleet JSON file path.

        Returns:
            Optional[FleetSnapshotDAO]: Parsed snapshot, or None when absent or invalid.
        """
        if not path.exists():
            return None
        try:
            return FleetSnapshotDAO.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log_warning(msg="fleet_snapshot_load_failed", path=str(path), error=str(exc))
            return None
