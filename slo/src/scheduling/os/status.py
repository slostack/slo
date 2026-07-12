"""Shared status DAOs for OS scheduler integration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ScheduleInstallStatusDAO", "ScheduleLogPathsDAO"]


class ScheduleLogPathsDAO(BaseModel):
    """Resolved stdout/stderr log paths for one OS-triggered schedule."""

    model_config = ConfigDict(frozen=True)

    stdout: Path = Field(description="Stdout log path.")
    stderr: Path = Field(description="Stderr log path.")


class ScheduleInstallStatusDAO(BaseModel):
    """Install/uninstall/status result for one schedule."""

    model_config = ConfigDict(frozen=True)

    schedule_id: str = Field(description="Schedule identifier.")
    platform: Literal["darwin", "linux"] = Field(description="Platform handler used.")
    installed: bool = Field(description="Whether the schedule is installed after the operation.")
    detail: Optional[str] = Field(default=None, description="Human-readable status detail.")
