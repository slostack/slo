"""Typed workflow presentation commands, separate from observation binding."""

from typing import TypeAlias
from pydantic import BaseModel, ConfigDict
from src.tui.components.workflow_progress.events import ConfirmAbortDAO
from src.tui.workflows.dao import WorkflowSessionSnapshotDAO
from src.tui.workflows.progress_coordinator import WorkflowProgressSink


class PresentSessionsDAO(BaseModel):
    """Paint rows only for the exact bound observation sink."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)
    sink: WorkflowProgressSink
    snapshot: WorkflowSessionSnapshotDAO


WorkflowProgressCommand: TypeAlias = PresentSessionsDAO | ConfirmAbortDAO
