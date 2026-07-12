"""Runtime DAOs for schedule execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.scheduling.dao import DeliveryPath, DeliveryState, FireStatus

__all__ = [
    "ResolvedSessionTargetDAO",
    "ScheduleExecutionOutcomeDAO",
    "ScheduleSubprocessResultDAO",
]


class ResolvedSessionTargetDAO(BaseModel):
    """Resolved target-session information for one continuous fire."""

    model_config = ConfigDict(frozen=True)

    resolved_reference: Optional[str] = Field(
        default=None,
        description="Existing session reference suitable for `--resume`, when known.",
    )
    target_session_id: Optional[str] = Field(
        default=None,
        description="Canonical target session id when it can be determined.",
    )
    explicit_session_id: Optional[str] = Field(
        default=None,
        description="Fresh session id to seed on the first continuous fire, when needed.",
    )


class ScheduleSubprocessResultDAO(BaseModel):
    """Result of one headless child-process invocation."""

    model_config = ConfigDict(frozen=True)

    status: FireStatus = Field(description="Terminal child-run outcome.")
    exit_code: int = Field(description="POSIX exit code returned by the child process.")
    session_id: Optional[str] = Field(
        default=None,
        description="Session id created or resumed by the child run.",
    )
    summary: str = Field(default="", description="High-level summary extracted from stdout.")
    stdout_summary: str = Field(default="", description="Clipped stdout for reports.")
    stderr_summary: str = Field(default="", description="Clipped stderr for reports.")


class ScheduleExecutionOutcomeDAO(BaseModel):
    """Normalized scheduler outcome used for reporting/state updates."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Optional[FireStatus] = Field(default=None, description="Executed child-run outcome, when any.")
    delivery_path: DeliveryPath = Field(description="How the fire was delivered.")
    delivery_state: DeliveryState = Field(
        description="Whether the fire executed, queued, coalesced, or skipped."
    )
    session_id: Optional[str] = Field(default=None, description="Session created or resumed by the fire.")
    target_session_id: Optional[str] = Field(default=None, description="Resolved target session id.")
    exit_code: Optional[int] = Field(default=None, description="POSIX child-process exit code, when any.")
    summary: str = Field(default="", description="High-level outcome summary.")
    stdout_summary: str = Field(default="", description="Clipped stdout for reports.")
    stderr_summary: str = Field(default="", description="Clipped stderr for reports.")
    skipped_reason: Optional[str] = Field(default=None, description="Why the fire was skipped.")
    coalesced_fire_count: int = Field(
        default=0, ge=0, description="Older pending fires replaced by this outcome."
    )
