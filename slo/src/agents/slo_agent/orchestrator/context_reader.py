"""Read existing private orchestrator context without depending on the TUI."""

from pathlib import Path
from typing import Optional

from src.agents.slo_agent.orchestrator.context_dao import OrchestratorContextDAO
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout
from src.agents.slo_agent.sessions.identity import validate_session_id


class OrchestratorContextReader:
    """Own the single tolerant parser shared by viewer discovery and eligibility."""

    @classmethod
    def load(cls, *, history_root: Path, parent_session_id: str) -> Optional[OrchestratorContextDAO]:
        """Read private context using the existing layout and schema.

        Session callers offload this synchronous read; UI discovery may call it
        from its existing worker. No payload or path is logged on failure.

        Args:
            history_root (Path): Existing history root.
            parent_session_id (str): Ordinary session identity, including slugs.

        Returns:
            Optional[OrchestratorContextDAO]: Valid context, otherwise absence.
        """
        try:
            session_id = validate_session_id(value=parent_session_id)
            path = OrchestrationLayout.session_dir(history_root=history_root, session_id=session_id)
            return OrchestratorContextDAO.model_validate_json(
                (path / "orchestrator_context.json").read_bytes()
            )
        except (OSError, ValueError):
            return None
