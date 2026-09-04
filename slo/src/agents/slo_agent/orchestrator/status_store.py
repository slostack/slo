"""Persist self-reported ``orchestrator.json`` evidence for one headless run.

HeadlessRunner writes through this store during watchdog ticks and terminal
handling. Reconcile, the TUI, and the visualizer load the evidence later.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.logger import log_warning
from src.agents.slo_agent.history.atomic_io import AtomicFileWriter
from src.agents.slo_agent.orchestrator.dao import OrchestratorRunState, OrchestratorStatusDAO
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout

__all__ = ["OrchestratorStatusStore"]


class OrchestratorStatusStore:
    """Persist and load one orchestrator's self-reported status evidence."""

    def __init__(self, *, history_root: Path, orchestrator_session_id: str, workflow_id: str) -> None:
        """Bind this single-writer store to one workflow and status path.

        Args:
            history_root (Path): Root containing session history directories.
            orchestrator_session_id (str): Session identifier of this run.
            workflow_id (str): Detached workflow identifier.
        """
        self._orchestrator_session_id: str = orchestrator_session_id
        self._workflow_id: str = workflow_id
        self._status_path: Path = OrchestrationLayout.orchestrator_status_path(
            history_root=history_root,
            orchestrator_session_id=orchestrator_session_id,
        )

    @classmethod
    def load_status(cls, *, path: Path) -> Optional[OrchestratorStatusDAO]:
        """Load durable orchestrator evidence without raising to its readers.

        WHAT: Parses one status file or returns no evidence after absence or corruption.
        WHO: Called by workflow reconciliation, the TUI, and the visualizer.
        WHEN: Whenever those readers evaluate self-reported workflow state.

        Args:
            path (Path): Canonical orchestrator status path.

        Returns:
            Optional[OrchestratorStatusDAO]: Parsed status, or ``None`` when unavailable.
        """
        if not path.exists():
            return None
        try:
            return OrchestratorStatusDAO.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log_warning(msg="orchestrator_status_load_failed", path=str(path), error=str(exc))
            return None

    def load(self) -> Optional[OrchestratorStatusDAO]:
        """Load this store's current durable orchestrator status.

        WHAT: Reads the status record bound to this store without exposing its path.
        WHO: Called by workflow notification guards before they publish progress.
        WHEN: On a possible post-terminal child lifecycle event.

        Returns:
            Optional[OrchestratorStatusDAO]: Current status, or None when unavailable.
        """
        return self.load_status(path=self._status_path)

    def write_running(self, *, phase: str) -> None:
        """Persist one running heartbeat without interrupting HeadlessWatchdog.

        Args:
            phase (str): Current safe phase label from the runner.
        """
        self._write(state="running", phase=phase, exit_code=None)

    def write_terminal(self, *, state: OrchestratorRunState, exit_code: int, phase: str) -> None:
        """Persist terminal workflow evidence without interrupting HeadlessRunner.

        Args:
            state (OrchestratorRunState): Completed, failed, or aborted terminal state.
            exit_code (int): POSIX exit code for the terminal stream event.
            phase (str): Last safe runner phase label.
        """
        self._write(state=state, phase=phase, exit_code=exit_code)

    def _write(self, *, state: OrchestratorRunState, phase: str, exit_code: Optional[int]) -> None:
        """Atomically persist one current status record and swallow filesystem errors."""
        status: OrchestratorStatusDAO = OrchestratorStatusDAO(
            workflow_id=self._workflow_id,
            orchestrator_session_id=self._orchestrator_session_id,
            pid=os.getpid(),
            state=state,
            phase=phase,
            updated_at=datetime.now(tz=timezone.utc).isoformat(),
            exit_code=exit_code,
        )
        try:
            AtomicFileWriter.write_json(path=self._status_path, model=status)
        except OSError as exc:
            log_warning(msg="orchestrator_status_write_failed", error=str(exc))
