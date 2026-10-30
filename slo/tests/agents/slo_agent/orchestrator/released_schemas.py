"""Released closed wire schemas for old-reader compatibility tests.

These models are byte-for-byte field copies of the extra-forbid DAOs shipped at
commit d0e3a75, before feature 94 added runtime execution identity. Released
readers decode fleet.json, status.json and spawn_context.json with exactly these
shapes, so a newly written legacy file must still validate against them.
``test_dao.TestReleasedWireSchemas`` guards that the current DAOs serialize no
field outside these sets.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ReleasedFleetSnapshotDAO",
    "ReleasedSpawnContextDAO",
    "ReleasedSubAgentResultDAO",
    "ReleasedSubAgentStatusDAO",
]


class ReleasedSubAgentStatusDAO(BaseModel):
    """Fleet entry shape accepted by released readers."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    session_id: str
    status: Literal["pending", "running", "completed", "failed", "aborted"] = "pending"
    last_text: Optional[str] = None
    prompt_preview: str = ""
    last_heartbeat_at: Optional[float] = None
    last_stdout_at: Optional[float] = None
    pid: Optional[int] = None
    started_at: Optional[float] = None
    heartbeat_phase: Optional[str] = None
    exit_code: Optional[int] = None
    terminal_reason: Optional[
        Literal["completed", "failed", "operator_abort", "orchestrator_died", "reaped_orphan"]
    ] = None
    terminated_by: Optional[Literal["natural", "abort", "watchdog", "sweep"]] = None


class ReleasedFleetSnapshotDAO(BaseModel):
    """fleet.json shape accepted by released readers."""

    model_config = ConfigDict(extra="forbid")

    orchestrator_session_id: str
    workflow_id: Optional[str] = None
    entries: list[ReleasedSubAgentStatusDAO] = Field(default_factory=list)
    updated_at: str


class ReleasedSubAgentResultDAO(BaseModel):
    """status.json shape accepted by released readers."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    session_id: str
    status: Literal["pending", "running", "completed", "failed", "aborted"]
    answer: str = ""
    exit_code: int = -1
    usage: dict[str, int] = Field(default_factory=dict)
    failure_code: Optional[str] = None
    partial_output_committed: Optional[bool] = None
    attempts: Optional[int] = None
    safe_message: Optional[str] = None


class ReleasedSpawnContextDAO(BaseModel):
    """spawn_context.json shape accepted by released readers."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    prompt: str
    model: Optional[str] = None
    reasoning_level: Optional[str] = None
    cwd: Optional[str] = None
    inactivity_timeout_seconds: float
    system_prompt: str
    recorded_at: str
