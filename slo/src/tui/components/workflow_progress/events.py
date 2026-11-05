"""Narrow observation updates; selection acknowledgement remains a separate bool seam."""

from typing import TypeAlias
from pydantic import BaseModel, ConfigDict
from src.tui.workflows.dao import (
    ChildAbortTargetDAO,
    SessionProgressSnapshotDAO,
    WorkflowSessionKeyDAO,
    WorkflowSessionSnapshotDAO,
)


class SessionsUpdatedDAO(BaseModel):
    """Current owner-scoped list, delivered before its progress read."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    snapshot: WorkflowSessionSnapshotDAO


class ProgressUpdatedDAO(BaseModel):
    """Validated progress for the selected screen."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    snapshot: SessionProgressSnapshotDAO


class MinimizeProgressDAO(BaseModel):
    """Release presentation without cancelling execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class MembershipRemovedDAO(BaseModel):
    """Forget one removed selection and notify the reader."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    key: WorkflowSessionKeyDAO


class ObservationFailedDAO(BaseModel):
    """Retain last-good presentation and announce a refresh failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ConfirmAbortDAO(BaseModel):
    """Ask for confirmation of the exact displayed execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    target: ChildAbortTargetDAO


WorkflowProgressUpdate: TypeAlias = (
    SessionsUpdatedDAO
    | ProgressUpdatedDAO
    | MinimizeProgressDAO
    | MembershipRemovedDAO
    | ObservationFailedDAO
    | ConfirmAbortDAO
)
