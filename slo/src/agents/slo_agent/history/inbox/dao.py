"""Filesystem-backed session-inbox and ownership DAOs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional, TypeAlias
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "InboxDeliveryMode",
    "InboxEnqueueResultDAO",
    "InboxMessageKind",
    "InboxPriority",
    "SessionInboxMessageDAO",
    "SessionInboxStoreResult",
    "SessionOwnershipLeaseDAO",
]


InboxMessageKind: TypeAlias = Literal[
    "monitor_update",
    "monitor_alert",
    "scheduled_prompt",
    "system_notice",
    # Detached-workflow lifecycle (spec 57.a.3 writer / 57.a.4 receive path):
    "workflow_started",
    "workflow_phase_update",
    "workflow_completed",
    "workflow_failed",
]
InboxPriority: TypeAlias = Literal["low", "normal", "high"]
InboxDeliveryMode: TypeAlias = Literal["ui_notice", "transcript_note", "chat_turn", "context_note"]
SessionInboxStoreResult: TypeAlias = Literal["queued", "coalesced"]


class SessionOwnershipLeaseDAO(BaseModel):
    """Renewable ownership record for one active TUI session."""

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(description="Session currently owned by the TUI.")
    owner_kind: Literal["tui"] = Field(default="tui", description="The only supported owner kind in v1.")
    owner_id: str = Field(description="Stable owner identifier for this TUI process.")
    pid: int = Field(description="Owning process id.")
    host: str = Field(description="Owning hostname.")
    acquired_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC time when the lease was first acquired.",
    )
    heartbeat_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC time of the most recent lease heartbeat.",
    )
    expires_at: datetime = Field(description="UTC time after which the lease is stale.")


class SessionInboxMessageDAO(BaseModel):
    """One scheduler-originated work item destined for a session inbox."""

    model_config = ConfigDict(frozen=True)

    message_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Stable identifier for this inbox message.",
    )
    session_id: str = Field(description="Target session id.")
    schedule_id: str = Field(description="Schedule that produced this message.")
    run_id: str = Field(description="Schedule-fire identifier that produced this message.")
    kind: InboxMessageKind = Field(description="High-level inbox message category.")
    priority: InboxPriority = Field(default="normal", description="Relative delivery importance.")
    delivery_mode: InboxDeliveryMode = Field(
        default="ui_notice",
        description="How the TUI should surface this item.",
    )
    coalesce_key: Optional[str] = Field(
        default=None,
        description="Stable key used to replace older pending items with newer state.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC time the message was created.",
    )
    title: Optional[str] = Field(default=None, description="Optional short title for display.")
    text: str = Field(description="Primary display or prompt text.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque structured payload for consumers.",
    )


class InboxEnqueueResultDAO(BaseModel):
    """Outcome of one enqueue attempt."""

    model_config = ConfigDict(frozen=True)

    result: SessionInboxStoreResult = Field(description="Whether the item was queued or coalesced.")
    message: SessionInboxMessageDAO = Field(description="The message now stored in pending or done.")
    replaced_message_id: Optional[str] = Field(
        default=None,
        description="Message id replaced by coalescing, if any.",
    )
