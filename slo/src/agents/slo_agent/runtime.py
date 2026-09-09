"""Session-owned runtime context for introspection and plugins.

``SloRuntimeContext`` collects references to session facts and evidence stores.
It is built once by ``SloAgentSession`` and is never persisted itself.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.agents.slo_agent.orchestrator.dao import SubAgentStatusDAO
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore
from src.agents.slo_agent.orchestrator.status_store import OrchestratorStatusStore
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore
from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO
from src.agents.slo_agent.skills.dao import SkillEntryDAO

__all__ = ["SloRuntimeContext"]


class SloRuntimeContext(BaseModel):
    """By-reference bundle of session facts and evidence stores.

    WHAT: Provides the sanctioned session seam for introspection tools and
        plugins without exposing private session attributes.
    WHO: Built by ``SloAgentSession`` and consumed by Feature 75 plugins and
        Feature 76 self-awareness tools.
    WHEN: Constructed once during session initialization, before consumers load.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    workdir: Path
    history_root: Path
    fleet_store: Optional[FleetStore] = None
    status_store: Optional[OrchestratorStatusStore] = None
    handle_store: Optional[WorkflowHandleStore] = None
    live_fleet: Callable[[], list[SubAgentStatusDAO]] = Field(exclude=True)
    usage_snapshot: Callable[[], SessionUsageSnapshotDAO] = Field(exclude=True)
    loaded_skills: Callable[[], list[SkillEntryDAO]] = Field(exclude=True)
    tool_names: Callable[[], list[str]] = Field(exclude=True)
