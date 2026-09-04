"""FleetStore — durable projection of a ProcessRegistry to ``fleet.json``.

The registry remains the in-memory write authority. This store gives TUI,
visualizer, reconcile, and sweep readers a durable post-mortem snapshot.

Sub-spec 71.a.2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.logger import log_warning
from src.agents.slo_agent.history.atomic_io import AtomicFileWriter
from src.agents.slo_agent.orchestrator.dao import FleetSnapshotDAO, SubAgentStatusDAO
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout

__all__ = ["FleetStore"]


class FleetStore:
    """Persist and load the durable projection for one orchestrator fleet."""

    def __init__(
        self,
        *,
        history_root: Path,
        orchestrator_session_id: str,
        workflow_id: Optional[str] = None,
    ) -> None:
        """Bind a store to one orchestrator session's fleet path.

        WHAT: Retains the identity needed to build and load one fleet snapshot.
        WHO: Called by SubAgentPool while it builds its ProcessRegistry.
        WHEN: Once for each orchestrator session.

        Args:
            history_root (Path): Root containing session history directories.
            orchestrator_session_id (str): Session that owns this fleet.
            workflow_id (Optional[str]): Detached workflow identifier when known.
        """
        self._orchestrator_session_id: str = orchestrator_session_id
        self._workflow_id: Optional[str] = workflow_id
        self._snapshot_path: Path = OrchestrationLayout.fleet_path(
            history_root=history_root,
            orchestrator_session_id=orchestrator_session_id,
        )

    def persist(self, *, entries: list[SubAgentStatusDAO]) -> None:
        """Persist a complete fleet snapshot without interrupting the run path.

        WHAT: Writes the registry's current entries through the shared atomic writer.
        WHO: Called by ProcessRegistry after durable lifecycle transitions.
        WHEN: On registration, running, terminal, and explicit flush transitions.

        Args:
            entries (list[SubAgentStatusDAO]): Current entries in registration order.
        """
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
