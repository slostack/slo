"""Canonical persisted-history DAOs (sub-spec 05.a §5, §7.1).

These are the on-disk shapes for ``events.jsonl`` and ``session.json``
under ``~/.slo/sessions/history/<session_id>/``. The store and projectors
must agree on these shapes; runtime trace events (05.b) and runtime
session orchestration (05.c) map onto them.

Keep the schema additive: every persisted line carries
``schema_version`` so future projectors can branch on it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.agents.providers.message_extension import ProviderMessageExtensionDAO
from src.agents.slo_agent.tool_execution.dao import ToolGroupMetadataDAO

__all__ = [
    "CooperativeHistoryEventValidator",
    "CooperativeYieldMetadataDAO",
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

    def application_sha256(self) -> str:
        """Hash supplied application fields, excluding only assigned sequence/token usage.

        Journal, raw-history verification and replay conflict detection share this
        normalization. No tree metadata, timestamps or provenance are discarded.

        Returns:
            str: SHA256 of canonical UTF-8 JSON.
        """
        data: object = json.loads(
            self.model_dump_json(exclude={"sequence": True, "payload": {"token_usage"}})
        )
        encoded: str = json.dumps(
            obj=data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        return hashlib.sha256(string=encoded.encode(encoding="utf-8")).hexdigest()


_COOPERATIVE_YIELD_SCHEMA_VERSION: Literal[1] = 1


def _require_canonical_uuid(*, value: str, field_name: str) -> None:
    """Reject a UUID that is not already in canonical lowercase string form."""
    try:
        parsed: UUID = UUID(value)
    except (AttributeError, ValueError) as error:
        raise ValueError(f"cooperative_yield_metadata_invalid_{field_name}") from error
    if str(parsed) != value:
        raise ValueError(f"cooperative_yield_metadata_invalid_{field_name}")


class CooperativeYieldMetadataDAO(BaseModel):
    """Diagnostic ``cooperative_yield_v1`` metadata for trusted yield history notices.

    WHAT: Correlates a requested, deferred or interrupted cooperative yield
        with the exact logical run, cached boundary, session attempt and
        iteration without carrying bodies, credentials or provider anchors.
    WHO: Session history writers attach it under ``payload.metadata`` on
        cooperative ``run_retrying`` diagnostics and corresponding stream notices.
    WHEN: Only trusted settlement diagnostics; it is never an applied receipt.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = Field(
        default=_COOPERATIVE_YIELD_SCHEMA_VERSION,
        description="Cooperative-yield metadata schema version; unknown versions fail closed.",
    )
    run_id: str = Field(description="Canonical A.1 logical message-run UUID.")
    boundary_index: int = Field(
        ge=0,
        description="Cached delivery boundary snapshot, not a live recomputation.",
    )
    attempt_turn_id: str = Field(description="Exact canonical history attempt UUID.")
    iteration: int = Field(ge=0, description="Exact outer ReAct iteration.")
    urgent_high_water: int = Field(
        ge=0,
        description="Urgent high-water sequence captured at boundary selection.",
    )
    reason: Literal[
        "provider",
        "noninterruptible_tool",
        "concurrent_batch",
        "dispatch",
    ] = Field(description="Fixed public cooperative-yield reason.")
    disposition: Literal["requested", "deferred", "interrupted"] = Field(
        description="Diagnostic-only disposition; never an applied or rollback receipt.",
    )
    group_id: Optional[str] = Field(
        default=None,
        description="Tool-group UUID5 required for a deferred group and optional for provider interruption.",
    )

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, value: str) -> str:
        """Require a canonical logical run UUID string."""
        _require_canonical_uuid(value=value, field_name="run_id")
        return value

    @field_validator("attempt_turn_id")
    @classmethod
    def _validate_attempt_turn_id(cls, value: str) -> str:
        """Require a canonical session attempt UUID string."""
        _require_canonical_uuid(value=value, field_name="attempt_turn_id")
        return value

    @field_validator("group_id")
    @classmethod
    def _validate_group_id(cls, value: Optional[str]) -> Optional[str]:
        """Require canonical UUID form whenever a group identity is present."""
        if value is None:
            return None
        _require_canonical_uuid(value=value, field_name="group_id")
        return value

    @model_validator(mode="after")
    def _validate_group_correlation(self) -> "CooperativeYieldMetadataDAO":
        """Require a group for defers and bind any group to its attempt/iteration."""
        if self.disposition == "deferred" and self.group_id is None:
            raise ValueError("cooperative_yield_metadata_invalid_group_id")
        if self.group_id is not None:
            expected_group_id: str = str(
                uuid5(
                    namespace=UUID(self.attempt_turn_id),
                    name="tool-group:" + str(self.iteration),
                )
            )
            if self.group_id != expected_group_id:
                raise ValueError("cooperative_yield_metadata_invalid_group_id")
        return self


class CooperativeHistoryEventValidator:
    """Admission policy for restricted cooperative append-once history events.

    WHAT: Centralises the marker/kind discrimination and deterministic identity,
        correlation, opening-array and no-start checks for the cooperative
        history subset.
    WHO: The filesystem history owner calls :meth:`validate` before applying the
        shared raw append-once mechanics; the tree adapter delegates to the same
        store entry point.
    WHEN: Once per cooperative append attempt, never for ordinary history or
        message-application events.
    """

    @classmethod
    def validate(cls, *, event: SessionHistoryEventDAO) -> None:
        """Validate the restricted cooperative append-once event contract.

        Args:
            event (SessionHistoryEventDAO): Candidate canonical history event.

        Raises:
            ValueError: The event is unmarked, mis-kinded, non-deterministic or
                correlated to a different attempt/iteration.
        """
        if event.kind in ("tool_call", "tool_result"):
            cls._validate_marked_tool_event(event=event)
            return
        if event.kind == "run_retrying":
            cls._validate_run_retrying_event(event=event)
            return
        raise ValueError("cooperative_yield_event_invalid_kind")

    @classmethod
    def _validate_run_retrying_event(cls, *, event: SessionHistoryEventDAO) -> None:
        """Dispatch a ``run_retrying`` record to its no-start or diagnostic check."""
        has_no_start: bool = "tool_group_v1" in event.payload.metadata
        has_diagnostic: bool = "cooperative_yield_v1" in event.payload.metadata
        if has_no_start == has_diagnostic:
            raise ValueError("cooperative_yield_event_invalid_metadata")
        if has_no_start:
            cls._validate_no_start_event(event=event)
            return
        cls._validate_diagnostic_event(event=event)

    @classmethod
    def _validate_marked_tool_event(cls, *, event: SessionHistoryEventDAO) -> None:
        """Validate one marked tool event against its deterministic identity."""
        if "tool_group_v1" not in event.payload.metadata or "cooperative_yield_v1" in event.payload.metadata:
            raise ValueError("cooperative_yield_event_invalid_metadata")
        raw_group: object = event.payload.metadata["tool_group_v1"]
        group: ToolGroupMetadataDAO = ToolGroupMetadataDAO.model_validate_json(
            json.dumps(obj=raw_group, allow_nan=False)
        )
        if group.disposition != "opening":
            raise ValueError("cooperative_yield_event_invalid_disposition")
        if event.turn_id != group.attempt_turn_id or event.iteration != group.iteration:
            raise ValueError("cooperative_yield_event_invalid_correlation")
        call_id: Optional[str] = event.payload.tool_call_id
        if call_id is None or call_id not in group.tool_call_ids:
            raise ValueError("cooperative_yield_event_invalid_call_id")
        if event.kind == "tool_call":
            if group.tool_result_status is not None:
                raise ValueError("cooperative_yield_event_invalid_status")
            cls._validate_opening_call_array(event=event, group=group)
            expected_name: str = "call:" + call_id
        else:
            if group.tool_result_status is None:
                raise ValueError("cooperative_yield_event_invalid_status")
            expected_name = "result:" + call_id
        expected_id: str = str(uuid5(namespace=UUID(group.group_id), name=expected_name))
        if event.event_id != expected_id:
            raise ValueError("cooperative_yield_event_invalid_event_id")

    @classmethod
    def _validate_opening_call_array(
        cls, *, event: SessionHistoryEventDAO, group: ToolGroupMetadataDAO
    ) -> None:
        """Require the opening to carry the complete ordered call array and selected call.

        WHAT: Checks the source-ordered call IDs against the group metadata, each
            call's name and argument mapping, and agreement of the selected
            ``tool_name``/``tool_input`` payload fields with its array entry.
        WHO: The marked-tool admission validator calls it for openings only.
        WHEN: Before a cooperative opening is persisted; results reuse the opening.

        Args:
            event (SessionHistoryEventDAO): Candidate marked ``tool_call`` event.
            group (ToolGroupMetadataDAO): Parsed tool-group metadata for the event.

        Raises:
            ValueError: The array is absent, incomplete, reordered, malformed or
                disagrees with the selected payload identity.
        """
        calls: Optional[list[dict[str, Any]]] = event.payload.tool_calls
        if not calls or [call.get("id") for call in calls] != list(group.tool_call_ids):
            raise ValueError("cooperative_yield_event_invalid_tool_calls")
        for call in calls:
            if not isinstance(call.get("name"), str) or not call["name"]:
                raise ValueError("cooperative_yield_event_invalid_tool_calls")
            if not isinstance(call.get("args"), dict):
                raise ValueError("cooperative_yield_event_invalid_tool_calls")
        selected: dict[str, Any] = next(call for call in calls if call["id"] == event.payload.tool_call_id)
        if event.payload.tool_name != selected["name"] or event.payload.tool_input != selected["args"]:
            raise ValueError("cooperative_yield_event_invalid_selected_call")

    @classmethod
    def _validate_diagnostic_event(cls, *, event: SessionHistoryEventDAO) -> None:
        """Validate one cooperative diagnostic ``run_retrying`` record."""
        diagnostic: CooperativeYieldMetadataDAO = CooperativeYieldMetadataDAO.model_validate_json(
            json.dumps(obj=event.payload.metadata["cooperative_yield_v1"], allow_nan=False)
        )
        if event.turn_id != diagnostic.attempt_turn_id or event.iteration != diagnostic.iteration:
            raise ValueError("cooperative_yield_event_invalid_correlation")
        expected_id: str = str(
            uuid5(
                namespace=UUID(diagnostic.attempt_turn_id),
                name="cooperative-yield:" + str(diagnostic.iteration) + ":" + diagnostic.disposition,
            )
        )
        if event.event_id != expected_id:
            raise ValueError("cooperative_yield_event_invalid_event_id")

    @classmethod
    def _validate_no_start_event(cls, *, event: SessionHistoryEventDAO) -> None:
        """Validate the affirmative no-start marker without inventing a tool result."""
        if event.payload.metadata.get("reason") != "cooperative_yield":
            raise ValueError("cooperative_yield_event_invalid_reason")
        group: ToolGroupMetadataDAO = ToolGroupMetadataDAO.model_validate_json(
            json.dumps(obj=event.payload.metadata["tool_group_v1"], allow_nan=False)
        )
        if group.disposition != "not_started":
            raise ValueError("cooperative_yield_event_invalid_disposition")
        if event.turn_id != group.attempt_turn_id or event.iteration != group.iteration:
            raise ValueError("cooperative_yield_event_invalid_correlation")
        if event.payload.tool_call_id is not None or event.payload.tool_output is not None:
            raise ValueError("cooperative_yield_event_invalid_no_start")
        expected_id: str = str(uuid5(namespace=UUID(group.group_id), name="not-started"))
        if event.event_id != expected_id:
            raise ValueError("cooperative_yield_event_invalid_event_id")


class MessageCompactionSelectionDAO(BaseModel):
    """Exact removed application membership bound to the summary source snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    snapshot_sha256: str = Field(description="Canonical source event-list SHA256, including sequence.")
    message_ids: tuple[str, ...] = Field(description="Removed messaging identities in event order.")
    observation_ids: tuple[str, ...] = Field(description="Removed internal observation identities.")


class MessageHistoryEvidenceDAO(BaseModel):
    """One bounded page of validated raw active history, before replay healing."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    events: tuple[SessionHistoryEventDAO, ...] = Field(
        description="Validated raw active events in sequence order, before replay healing."
    )
    next_sequence: Optional[int] = Field(
        default=None,
        description="Exclusive sequence cursor for the next bounded page; None means no remaining events.",
    )


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
