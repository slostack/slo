"""Canonical persisted-history DAOs (sub-spec 05.a §5, §7.1).

These are the on-disk shapes for ``events.jsonl`` and ``session.json``
under ``~/.slo/sessions/history/<session_id>/``. The store and projectors
must agree on these shapes; runtime trace events (05.b) and runtime
session orchestration (05.c) map onto them.

Keep the schema additive: every persisted line carries
``schema_version`` so future projectors can branch on it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.agents.providers.message_extension import ProviderMessageExtensionDAO

__all__ = [
    "HistoryEventKind",
    "HISTORY_OBSERVATION_MAX_BYTES",
    "HISTORY_OBSERVATION_MAX_EVENTS",
    "HistoryObservationAvailability",
    "HistoryObservationWindowDAO",
    "SessionHistoryEventPayloadDAO",
    "SessionHistoryEventDAO",
    "SessionHistoryMetadataDAO",
]


HistoryEventKind = Literal[
    "session_started",
    "run_started",
    "user_message",
    "steering_message",
    "assistant_message",
    "assistant_delta",
    "tool_call",
    "tool_output_update",
    "tool_result",
    "run_retrying",  # a wait-and-retry decision (preflight / pool / rate limit) — 37.a.6
    "preflight_bypassed",  # advisory local TPM audit — spec 77
    "provider_limit_observed",  # provider-authoritative rejection audit — spec 77
    "route_switched",  # a ModelPool route switch (audit) — 37.a.6
    "stream_reconnecting",  # provider stream reconnect audit — spec 70
    # LLM-driven recovery (feature 50):
    "run_recovering",  # audit: a recovery decision (excluded from model context)
    "recovery_observation",  # the synthetic observation message (included on replay)
    "run_completed",
    "run_aborted",
    "run_failed",
    "slash_command",
    # Orchestrator / sub-agent lifecycle (sub-spec 01-sub-agents 01.f):
    "orchestrator_started",  # a spawn_sub_agents batch began
    "sub_agent_spawned",  # one child session was created
    "sub_agent_completed",  # one child reached a terminal state
    # Compaction (sub-spec 01.a.1):
    "compaction_summary",  # LLM-generated summary of the compacted history portion
    # Detached workflow feedback (spec 57.a.4) — included in model context on replay.
    # Persisted as a synthetic completed turn: one event, a fresh turn_id, terminal
    # by construction (no run envelope). Payload: content = the note text;
    # metadata carries {"workflow_id": …, "inbox_message_id": …} (idempotency key).
    "workflow_update",
]


class SessionHistoryEventPayloadDAO(BaseModel):
    """Payload stored inside one canonical history event.

    Fields are intentionally optional because each event kind uses a
    different subset. Replay and context projectors branch on
    ``event.kind`` and read the fields relevant to that kind.
    """

    model_config = ConfigDict(extra="ignore")

    role: Optional[str] = None
    content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None
    tool_input: Optional[dict[str, Any]] = None
    tool_output: Optional[str] = None
    message: Optional[str] = None
    error_message: Optional[str] = None
    model_name: Optional[str] = None
    workdir: Optional[str] = None
    delta_kind: Optional[str] = None
    block_id: Optional[str] = None
    delta: Optional[str] = None
    redacted: Optional[bool] = None
    tool_arguments_delta: Optional[str] = None
    provider_message_extension: Optional[ProviderMessageExtensionDAO] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    token_usage: Optional[int] = None


class SessionHistoryEventDAO(BaseModel):
    """One canonical persisted session event written to ``events.jsonl``.

    Fields:
        schema_version (int): Bumped when the on-disk shape changes.
        event_id (str): Unique id for the event (UUID4).
        session_id (str): The session that owns this event.
        turn_id (Optional[str]): The ``invoke`` turn this
            event belongs to. ``None`` only for ``session_started``-like
            envelope events that pre-date the first turn.
        sequence (int): Monotonically increasing within a session,
            assigned by the store at append time.
        kind (HistoryEventKind): Event kind discriminator.
        iteration (int): ReAct iteration counter (mirrors
            ``SloAgent._current_iteration``).
        recorded_at (datetime): UTC timestamp when the event was built.
        payload (SessionHistoryEventPayloadDAO): Event-specific payload.
            The payload carries ``token_usage`` (Optional[int]) — set
            by the store at append time via ``TokenEstimator``.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    turn_id: Optional[str] = None
    sequence: int = 0
    kind: HistoryEventKind
    iteration: int = 0
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: SessionHistoryEventPayloadDAO = Field(default_factory=SessionHistoryEventPayloadDAO)


class SessionHistoryMetadataDAO(BaseModel):
    """Per-session metadata stored in ``session.json``.

    Fields:
        schema_version (int): Bumped when the metadata shape changes.
        session_id (str): The session identifier.
        workdir (Path): Resolved workdir captured at session creation.
        model_name (Optional[str]): Active model at session creation.
        created_at (datetime): UTC timestamp at first ``ensure_session``.
        updated_at (datetime): UTC timestamp of the latest write.
        latest_sequence (int): Highest ``sequence`` ever assigned in
            this session's event log.
        last_completed_turn_id (Optional[str]): The most recently
            ``run_completed`` turn id, when known.
        startup_notice_shown_at (Optional[datetime]): UTC timestamp when
            the one-time startup notice was first rendered.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    session_id: str
    workdir: Path
    model_name: Optional[str] = None
    workspace_file: Optional[Path] = None
    session_name: Optional[str] = None
    session_name_key: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    latest_sequence: int = 0
    last_completed_turn_id: Optional[str] = None
    startup_notice_shown_at: Optional[datetime] = None


# Upper bounds for one progress observation (spec 94.a.3); callers may ask for less, never more.
HISTORY_OBSERVATION_MAX_BYTES: int = 2_097_152
HISTORY_OBSERVATION_MAX_EVENTS: int = 2_000

HistoryObservationAvailability = Literal["available", "empty", "unavailable"]


class HistoryObservationWindowDAO(BaseModel):
    """Bounded, read-only suffix of one session's canonical history.

    An observation envelope returned by ``load_observation_window`` for progress
    views; it is never persisted and never feeds inference replay.

    Fields:
        events (tuple[SessionHistoryEventDAO, ...]): Valid complete records from the
            bounded suffix, in ascending ``sequence`` order.
        revision (str): ``device:inode:size:mtime_ns:start`` of the file generation
            read; empty when nothing was observed.
        truncated (bool): True when bytes or records were omitted from the window.
        availability (HistoryObservationAvailability): ``empty`` for an existing
            zero-byte log, ``unavailable`` for a missing, refused or changing source.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    events: tuple[SessionHistoryEventDAO, ...]
    revision: str
    truncated: bool
    availability: HistoryObservationAvailability

    @classmethod
    def unavailable(cls) -> HistoryObservationWindowDAO:
        """Build the observation of a source that could not be read safely this poll.

        WHAT: Carries no events and no revision so callers keep their last good view.
        WHO: Built by FilesystemSessionHistoryStore for missing, refused or changed files.
        WHEN: Whenever one bounded observation cannot observe a single file generation.

        Returns:
            HistoryObservationWindowDAO: The empty unavailable envelope.
        """
        return cls(events=(), revision="", truncated=False, availability="unavailable")
