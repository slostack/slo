"""Channel domain DAOs (108.1; model rule: overview §3.0).

Every attribute of every model carries ``Field(..., description="…")``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ChannelDAO",
    "SentMessageRowDAO",
    "ChannelKind",
    "ChannelMessageDAO",
    "MessageType",
    "NewMessageDAO",
    "ParticipantDAO",
    "ParticipantKind",
    "utc_now",
]

ChannelKind = Literal["tui", "cli", "telegram", "desktop", "http", "scheduler", "agent"]
"""Platform types a channel can connect (overview §2.1)."""

ParticipantKind = Literal["user", "agent", "system"]
"""Who sends or receives: a human through one channel, one Slo session, or a system sender."""

MessageType = Literal["prompt", "note", "notice", "reply"]
"""What the recipient should do with a message (overview §3.2)."""


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


class ChannelDAO(BaseModel):
    """One platform connection registered in the queue database."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(description="Unique id of this platform connection.")
    kind: ChannelKind = Field(description="Type of platform this channel connects.")
    name: str = Field(description="Human-readable label, e.g. 'tui@host'.")
    created_at: datetime = Field(description="UTC time the channel was first registered.")
    last_seen_at: datetime = Field(description="UTC time of the adapter's latest heartbeat.")


class ParticipantDAO(BaseModel):
    """Anyone who sends or receives messages: a user, an agent session, or a system sender."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(description="Unique participant id; equals the session id for agents.")
    kind: ParticipantKind = Field(
        description="Whether this is a human user, a Slo agent session, or a system sender."
    )
    name: str = Field(description="Display name copied into messages as sender/recipient name.")
    channel_id: Optional[UUID] = Field(description="Channel a user or system talks through; None for agents.")
    external_ref: Optional[str] = Field(
        description="Platform-side identity, e.g. a Telegram user id; unique per channel."
    )
    status: Literal["open", "closed"] = Field(
        description="Whether this participant can currently receive messages."
    )
    last_seen_at: datetime = Field(description="UTC time of the latest heartbeat or activity.")
    created_at: datetime = Field(description="UTC time the participant was registered.")


class NewMessageDAO(BaseModel):
    """What a sender supplies to enqueue one message."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(
        default_factory=uuid4,
        description="Message id; a sender may fix it so retries are idempotent.",
    )
    sender_id: UUID = Field(description="Participant sending the message.")
    recipient_id: UUID = Field(description="Participant that should receive the message.")
    message_contents: str = Field(
        min_length=1,
        max_length=65_536,
        description="Message text, at most 64 KiB.",
    )
    message_type: MessageType = Field(
        default="prompt",
        description="What the recipient should do with it (overview §3.2).",
    )
    in_reply_to_id: Optional[UUID] = Field(
        default=None,
        description="Id of the message this one answers, if any.",
    )
    channel_id: Optional[UUID] = Field(
        default=None,
        description="Channel the message was sent from; used to route replies.",
    )
    force: bool = Field(
        default=False,
        description="True sets forced_at so the message enters the current run (108.2).",
    )
    coalesce_key: Optional[str] = Field(
        default=None,
        description="Key under which a newer pending message replaces an older one (108.3).",
    )
    sent_at: datetime = Field(
        default_factory=utc_now,
        description="UTC time on the sender's clock when it was sent.",
    )


class SentMessageRowDAO(BaseModel):
    """One composer list row: a message you sent and its derived state (108.3 §4)."""

    model_config = ConfigDict(frozen=True)

    message_id: UUID = Field(description="Id of the message you sent.")
    preview: str = Field(max_length=80, description="First 80 characters of the message.")
    forced: bool = Field(description="Whether it was sent forced (Ctrl+Enter).")
    state: Literal["queued", "accepted", "cancelled"] = Field(
        description="Delivery state derived from accepted_at / cancelled_at."
    )
    reply_preview: Optional[str] = Field(
        default=None,
        description="First 80 characters of the reply, once one exists.",
    )


class ChannelMessageDAO(BaseModel):
    """One stored queue row, all columns (overview §3.1)."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(description="Unique message id.")
    agent_session_id: UUID = Field(description="Conversation the row belongs to (overview §2.4).")
    sender_id: UUID = Field(description="Participant that sent the message.")
    sender_name: str = Field(description="Sender's display name at send time.")
    recipient_id: UUID = Field(description="Participant that receives the message.")
    recipient_name: str = Field(description="Recipient's display name at send time.")
    sent_at: datetime = Field(description="UTC time on the sender's clock.")
    accepted_at: Optional[datetime] = Field(
        description="When the agent took it into its loop, or the channel delivered it; None while pending."
    )
    message_contents: str = Field(description="Message text.")
    created_at: datetime = Field(description="UTC time the row was inserted.")
    message_index: int = Field(description="Gapless 1-based order within agent_session_id.")
    forced_at: Optional[datetime] = Field(
        description="When the message was forced into the current run; None for normal messages."
    )
    message_type: MessageType = Field(description="What the recipient should do with it.")
    in_reply_to_id: Optional[UUID] = Field(description="Id of the message this one answers.")
    channel_id: Optional[UUID] = Field(description="Channel the message was sent from.")
    cancelled_at: Optional[datetime] = Field(
        description="When it was cancelled before acceptance; None otherwise."
    )
    cancel_reason: Optional[str] = Field(
        description="Why it was cancelled, e.g. 'operator', 'recipient_closed', 'superseded'."
    )
    coalesce_key: Optional[str] = Field(
        description="Key under which a newer pending message replaced this one, if any."
    )
