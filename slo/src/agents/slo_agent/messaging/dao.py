"""Canonical messaging DAOs and safe internal errors (feature 96, sub-spec A.1).

This module is the single source of messaging vocabulary shared by the
UI, the session, the queue and the storage adapter. It separates:

- what the sender asks (``MessageSubmissionDAO``),
- who the recipient has authenticated (``MessagePrincipalDAO``), and
- what was actually accepted (``MessageEnvelopeDAO`` / ``MessageReceiptDAO``).

Contract rules enforced here:

- Every record is strict, immutable and rejects unexpected fields.
- UUIDs are canonical lowercase hyphenated strings validated on decode.
- No sender-supplied admission sequence or authenticated identity exists.
- ``generation`` is a fresh UUID per acquired owner lifetime; managed
  children use their assigned execution UUID instead.
- Internal errors carry only fixed safe codes; no raw SQLite, path or
  credential diagnostics escape this package.

``history.dao`` never imports this module; the dependency points one way.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.orchestrator.dao import FleetSnapshotDAO, OrchestratorResultDAO

__all__ = [
    "Priority",
    "MessageKind",
    "ReceiptState",
    "ErrorCode",
    "MessageDAO",
    "MessageAddressDAO",
    "WorkflowPayloadDAO",
    "TextPayloadDAO",
    "WorkflowMessagePayloadDAO",
    "MessagePayload",
    "MessageSubmissionDAO",
    "MessagePrincipalDAO",
    "MessageEnvelopeDAO",
    "MessageReceiptDAO",
    "MessageErrorDAO",
    "BoundaryDAO",
    "MessageDeliveryDAO",
    "BoundaryDeliveryDAO",
    "QueueSummaryDAO",
    "MessagingLimitsDAO",
    "MessageApplicationMetadataDAO",
    "RecoveryTransferDAO",
    "RecoveryOutcomeDAO",
    "RecoveryConfirmationDAO",
    "VerifiedRecoverySourceDAO",
    "QueueStateDAO",
    "MessageIdentityDAO",
    "CompactionLedgerDAO",
    "InternalObservationDAO",
    "MessageAdmissionError",
    "MessageStoreError",
    "SessionAlreadyOwnedError",
]

Priority = Literal["normal", "urgent"]
MessageKind = Literal["agent_input", "context_note", "ui_notice", "transcript_note"]
ReceiptState = Literal["accepted", "applying", "applied", "cancelled"]
ErrorCode = Literal[
    "invalid_message",
    "conflict",
    "queue_full",
    "sender_limit",
    "storage_unavailable",
    "unauthorized",
    "stale_generation",
    "offline",
    "completing",
    "unsupported",
    "unknown_outcome",
    "not_found",
    "recovery_required",
    "replay_gap",
]

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID_RE = re.compile(r"^[\x20-\x7e]{1,128}$")


def _require_uuid(*, value: str, field: str) -> str:
    """Validate one canonical lowercase hyphenated UUID string.

    Args:
        value (str): The candidate identifier.
        field (str): Field name used in the error message.

    Returns:
        str: The unchanged value when valid.

    Raises:
        ValueError: The value is not a canonical UUID string.
    """
    if not _UUID_RE.fullmatch(value):
        raise ValueError(f"{field} must be a canonical lowercase hyphenated UUID")
    return value


def _require_sha256(*, value: str, field: str) -> str:
    """Validate one 64-character lowercase hexadecimal SHA-256 digest."""
    if not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field} must be a 64-character lowercase hex SHA-256")
    return value


def _require_aware(*, value: datetime, field: str) -> datetime:
    """Reject naive datetimes; all timestamps are canonical UTC ISO8601."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware (UTC)")
    return value.astimezone(timezone.utc)


def _require_source_id(*, value: str, field: str) -> str:
    """Validate a bounded printable non-control source identifier."""
    if not _SOURCE_ID_RE.fullmatch(value):
        raise ValueError(f"{field} must be 1-128 printable non-control characters")
    return value


class MessageDAO(BaseModel):
    """Immutable validated messaging boundary data; never execution authority."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class MessageAddressDAO(MessageDAO):
    """Name a session incarnation and optionally its observation channel."""

    kind: Literal["agent_session", "ui_channel"]
    session_id: str
    generation: str
    channel_id: Optional[str] = None

    @field_validator("session_id", "generation")
    @classmethod
    def _uuid_fields(cls, value: str) -> str:
        return _require_uuid(value=value, field="address id")

    @field_validator("channel_id")
    @classmethod
    def _channel_uuid(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            _require_uuid(value=value, field="channel_id")
        return value

    @model_validator(mode="after")
    def _channel_presence(self) -> "MessageAddressDAO":
        """Require channel_id for ui_channel targets and forbid it otherwise."""
        if self.kind == "ui_channel" and self.channel_id is None:
            raise ValueError("ui_channel targets require channel_id")
        if self.kind == "agent_session" and self.channel_id is not None:
            raise ValueError("agent_session targets forbid channel_id")
        return self


class WorkflowPayloadDAO(MessageDAO):
    """Carry source workflow evidence without parsing presentation text.

    Field presence is per event kind: ``phase`` requires phase_index and
    forbids fleet/result/failure_code; ``fleet`` requires fleet and forbids
    phase_index/result/failure_code; ``started`` forbids all four;
    ``completed`` permits result (None means no dispatch occurred) and
    forbids the others; ``failed`` requires a fixed safe failure_code and
    permits result, forbidding fleet/phase_index.
    """

    event: Literal["started", "phase", "fleet", "completed", "failed"]
    owner_session_id: str
    orchestrator_session_id: str
    orchestrator_generation: str
    workflow_id: str
    revision: int = Field(ge=1)
    phase_index: Optional[int] = Field(default=None, ge=1)
    fleet: Optional[FleetSnapshotDAO] = None
    result: Optional[OrchestratorResultDAO] = None
    failure_code: Optional[str] = None

    @field_validator("owner_session_id", "orchestrator_session_id", "orchestrator_generation")
    @classmethod
    def _uuid_fields(cls, value: str) -> str:
        return _require_uuid(value=value, field="workflow identity")

    @field_validator("workflow_id")
    @classmethod
    def _workflow_id_format(cls, value: str) -> str:
        return _require_source_id(value=value, field="workflow_id")

    @model_validator(mode="after")
    def _event_field_shape(self) -> "WorkflowPayloadDAO":
        """Enforce the closed per-event field combinations."""
        if self.event == "phase":
            if self.phase_index is None:
                raise ValueError("phase events require phase_index")
            if self.fleet is not None or self.result is not None or self.failure_code is not None:
                raise ValueError("phase events forbid fleet, result and failure_code")
        elif self.event == "fleet":
            if self.fleet is None:
                raise ValueError("fleet events require fleet")
            if self.phase_index is not None or self.result is not None or self.failure_code is not None:
                raise ValueError("fleet events forbid phase_index, result and failure_code")
        elif self.event == "started":
            if (
                self.phase_index is not None
                or self.fleet is not None
                or self.result is not None
                or self.failure_code is not None
            ):
                raise ValueError("started events forbid phase_index, fleet, result and failure_code")
        elif self.event == "completed":
            if self.phase_index is not None or self.fleet is not None or self.failure_code is not None:
                raise ValueError("completed events forbid phase_index, fleet and failure_code")
        elif self.event == "failed":
            if self.failure_code is None:
                raise ValueError("failed events require a fixed safe failure_code")
            if self.phase_index is not None or self.fleet is not None:
                raise ValueError("failed events forbid phase_index and fleet")
        return self


class TextPayloadDAO(MessageDAO):
    """Identify ordinary text; its content remains submission.text."""

    type: Literal["text"] = "text"


class WorkflowMessagePayloadDAO(MessageDAO):
    """Wrap the canonical workflow record for discriminated decoding."""

    type: Literal["workflow"] = "workflow"
    workflow: WorkflowPayloadDAO


MessagePayload = Annotated[TextPayloadDAO | WorkflowMessagePayloadDAO, Field(discriminator="type")]


class MessageSubmissionDAO(MessageDAO):
    """Represent immutable sender intent, without authenticated sender authority.

    Retain message_id and all payload bytes across admission retries.
    The recipient derives principal and sequence; neither is caller input.
    """

    message_id: str
    target: MessageAddressDAO
    kind: MessageKind
    text: str = Field(min_length=1)
    priority: Priority = "normal"
    reply_to: Optional[str] = None
    workflow_id: Optional[str] = None
    dispatch_id: Optional[str] = None
    source_event_id: Optional[str] = None
    payload: MessagePayload = Field(default_factory=TextPayloadDAO)

    @field_validator("message_id", "reply_to", "dispatch_id")
    @classmethod
    def _uuid_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            _require_uuid(value=value, field="message identity")
        return value

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be whitespace-only")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("text must be valid UTF-8") from None
        return value

    @field_validator("workflow_id", "source_event_id")
    @classmethod
    def _source_ids(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            _require_source_id(value=value, field="source identifier")
        return value

    @model_validator(mode="after")
    def _kind_and_payload_rules(self) -> "MessageSubmissionDAO":
        """Enforce the closed kind/priority/target/payload combinations."""
        if self.priority == "urgent" and self.kind != "agent_input":
            raise ValueError("only agent_input may be urgent")
        if self.kind in ("context_note", "transcript_note") and self.target.kind != "agent_session":
            raise ValueError("notes require agent-session targets")
        if self.kind == "ui_notice" and self.target.kind != "ui_channel":
            raise ValueError("notices require channel targets")
        if isinstance(self.payload, WorkflowMessagePayloadDAO):
            workflow = self.payload.workflow
            if self.kind != "agent_input" and workflow.event in ("completed", "failed"):
                raise ValueError("terminal workflow events require agent_input")
            if self.kind != "context_note" and workflow.event in ("started", "phase", "fleet"):
                raise ValueError("start/phase/fleet workflow events require context_note")
            if self.workflow_id is None or self.workflow_id != workflow.workflow_id:
                raise ValueError("outer workflow_id must equal payload workflow_id")
            expected_source = (
                f"workflow:{workflow.workflow_id}:" f"{workflow.orchestrator_generation}:{workflow.revision}"
            )
            if self.source_event_id != expected_source:
                raise ValueError("workflow submissions require the canonical source_event_id")
        if len(canonical_submission_bytes(submission=self)) > 65536:
            raise ValueError("complete submission exceeds 64 KiB")
        return self


class MessagePrincipalDAO(MessageDAO):
    """Recipient-authenticated principal, not a field accepted from tool arguments."""

    principal_id: str = Field(description="Bounded recipient-authenticated principal key.")
    kind: Literal["human", "agent", "scheduler", "workflow"]
    session_id: Optional[str] = None
    generation: Optional[str] = None

    @field_validator("principal_id")
    @classmethod
    def _principal_key(cls, value: str) -> str:
        """Keep authenticated keys printable and bounded in lifetime evidence."""
        return _require_source_id(value=value, field="principal_id")

    @field_validator("session_id", "generation")
    @classmethod
    def _uuid_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            _require_uuid(value=value, field="principal identity")
        return value


class MessageEnvelopeDAO(MessageDAO):
    """Durably admitted input and its recipient-assigned ordering."""

    submission: MessageSubmissionDAO
    sender: MessagePrincipalDAO
    sequence: int = Field(ge=1)
    admitted_at: datetime

    @field_validator("admitted_at")
    @classmethod
    def _aware_timestamps(cls, value: datetime) -> datetime:
        return _require_aware(value=value, field="admitted_at")


class MessageReceiptDAO(MessageDAO):
    """Report insertion progress, never model compliance or tool success."""

    message_id: str
    target: MessageAddressDAO
    state: ReceiptState
    sequence: int = Field(ge=1)
    durable: bool
    admitted_at: datetime
    applied_at: Optional[datetime] = None
    run_id: Optional[str] = None
    retained_for_recovery: bool = False

    @field_validator("message_id", "run_id")
    @classmethod
    def _uuid_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            _require_uuid(value=value, field="receipt identity")
        return value

    @field_validator("admitted_at", "applied_at")
    @classmethod
    def _aware_timestamps(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None:
            return _require_aware(value=value, field="receipt timestamp")
        return value

    @model_validator(mode="after")
    def _state_fields(self) -> "MessageReceiptDAO":
        """Require exactly the receipt fields supported by its insertion state."""
        if (self.state == "applied") != (self.applied_at is not None):
            raise ValueError("applied state requires application time only")
        if self.state in {"applying", "applied"} and self.run_id is None:
            raise ValueError("claimed states require run_id")
        if self.state == "accepted" and self.run_id is not None:
            raise ValueError("accepted state forbids run_id")
        if self.state in {"applied", "cancelled"} and self.retained_for_recovery:
            raise ValueError("terminal states cannot be retained")
        return self


class MessageErrorDAO(MessageDAO):
    """Fixed safe error without payload or credential diagnostics."""

    code: ErrorCode
    message_id: Optional[str] = None

    @field_validator("message_id")
    @classmethod
    def _uuid_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            _require_uuid(value=value, field="message_id")
        return value


class BoundaryDAO(MessageDAO):
    """One application opportunity before a model request, reused on request retry."""

    run_id: str
    boundary_index: int = Field(ge=0)

    @field_validator("run_id")
    @classmethod
    def _uuid_fields(cls, value: str) -> str:
        return _require_uuid(value=value, field="run_id")


class MessageDeliveryDAO(MessageDAO):
    """A recoverable claim; only the owning agent may apply it."""

    envelope: MessageEnvelopeDAO
    boundary: BoundaryDAO
    history_event_id: str
    event: Optional[SessionHistoryEventDAO] = None

    @field_validator("history_event_id")
    @classmethod
    def _uuid_fields(cls, value: str) -> str:
        return _require_uuid(value=value, field="history_event_id")


class BoundaryDeliveryDAO(MessageDAO):
    """Freeze one boundary selection, including an empty or note-only selection."""

    boundary: BoundaryDAO
    urgent_high_water: int = Field(ge=0)
    note: Optional[MessageDeliveryDAO] = None
    instruction: Optional[MessageDeliveryDAO] = None

    @model_validator(mode="after")
    def _slot_rules(self) -> "BoundaryDeliveryDAO":
        """Keep the frozen selection internally consistent."""
        if self.note is not None:
            if self.note.envelope.submission.kind not in ("context_note", "transcript_note"):
                raise ValueError("note must be context_note or transcript_note")
            if self.note.boundary != self.boundary or self.note.event is None:
                raise ValueError("a present note shares the boundary and carries its event")
        if self.instruction is not None:
            if self.instruction.envelope.submission.kind != "agent_input":
                raise ValueError("instruction must be agent_input")
            if self.instruction.boundary != self.boundary or self.instruction.event is None:
                raise ValueError("a present instruction shares the boundary and carries its event")
        return self


class QueueSummaryDAO(MessageDAO):
    """Bounded presentation projection, not a mutable queue or scheduler."""

    pending_count: int = Field(ge=0)
    next_local_message_id: Optional[str] = None
    next_local_text: Optional[str] = None

    @field_validator("next_local_message_id")
    @classmethod
    def _uuid_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            _require_uuid(value=value, field="next_local_message_id")
        return value


class MessagingLimitsDAO(MessageDAO):
    """Construction-time limits shared by local and IPC adapters."""

    payload_bytes: int = Field(default=65536, ge=1, le=65536)
    pending_inputs: int = Field(default=256, ge=1, le=256)
    pending_notes: int = Field(default=256, ge=1, le=256)
    pending_per_sender: int = Field(default=64, ge=1, le=64)
    urgent_per_sender: int = Field(default=16, ge=1, le=16)
    admission_seconds: float = Field(default=5.0, gt=0, le=5.0)
    receipt_days: int = Field(default=7, ge=1, le=7)


class MessageApplicationMetadataDAO(MessageDAO):
    """Preserve original author separately from the current execution generation."""

    message_id: str
    kind: MessageKind
    sender: MessagePrincipalDAO
    sequence: int = Field(ge=1)
    run_id: str
    execution_generation: str

    @field_validator("message_id", "run_id", "execution_generation")
    @classmethod
    def _uuid_fields(cls, value: str) -> str:
        return _require_uuid(value=value, field="application identity")


class RecoveryTransferDAO(MessageDAO):
    """Authorize continuation without rewriting the original submission."""

    transfer_id: str
    original: MessageSubmissionDAO
    original_sender: MessagePrincipalDAO
    original_digest: str
    destination: MessageAddressDAO

    @field_validator("transfer_id")
    @classmethod
    def _uuid_fields(cls, value: str) -> str:
        return _require_uuid(value=value, field="transfer_id")

    @field_validator("original_digest")
    @classmethod
    def _digest_format(cls, value: str) -> str:
        return _require_sha256(value=value, field="original_digest")


class RecoveryOutcomeDAO(MessageDAO):
    """Report explicit transfer and the original logical receipt."""

    transfer_id: str
    execution_generation: str
    receipt: MessageReceiptDAO

    @field_validator("transfer_id", "execution_generation")
    @classmethod
    def _uuid_fields(cls, value: str) -> str:
        return _require_uuid(value=value, field="recovery identity")


class RecoveryConfirmationDAO(MessageDAO):
    """Bind local human consent to a runtime-issued immutable preview."""

    confirmation_id: str
    transfer: RecoveryTransferDAO
    evidence_sha256: str
    expires_at: datetime

    @field_validator("confirmation_id")
    @classmethod
    def _uuid_fields(cls, value: str) -> str:
        return _require_uuid(value=value, field="confirmation_id")

    @field_validator("evidence_sha256")
    @classmethod
    def _digest_format(cls, value: str) -> str:
        return _require_sha256(value=value, field="evidence_sha256")

    @field_validator("expires_at")
    @classmethod
    def _aware_timestamps(cls, value: datetime) -> datetime:
        return _require_aware(value=value, field="expires_at")


class VerifiedRecoverySourceDAO(MessageDAO):
    """Carry runtime-verified source identity; never accepted from wire/tool input."""

    transfer: RecoveryTransferDAO
    source_kind: Literal["recipient", "outbound", "legacy"]
    source_key: str
    evidence_sha256: str

    @field_validator("evidence_sha256")
    @classmethod
    def _digest_format(cls, value: str) -> str:
        return _require_sha256(value=value, field="evidence_sha256")


class QueueStateDAO(MessageDAO):
    """Read eligibility atomically; counts include applying capacity, not retained work."""

    eligible_inputs: int = Field(ge=0)
    eligible_notes: int = Field(ge=0)
    urgent_high_water: int = Field(ge=0)


class MessageIdentityDAO(MessageDAO):
    """Retain enough proof to verify even a pruned terminal application.

    An applied history-bearing kind requires its event ID and hash; a
    cancelled or unclaimed record forbids them; applying permits them.
    ``ui_notice`` is the sole non-history kind.
    """

    receipt: MessageReceiptDAO
    sender: MessagePrincipalDAO
    digest: str
    kind: MessageKind
    history_event_id: Optional[str] = None
    event_sha256: Optional[str] = None
    execution_generation: str

    @field_validator("digest", "event_sha256")
    @classmethod
    def _digest_format(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            _require_sha256(value=value, field="digest")
        return value

    @field_validator("history_event_id", "execution_generation")
    @classmethod
    def _uuid_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            _require_uuid(value=value, field="identity record")
        return value

    @model_validator(mode="after")
    def _evidence_rules(self) -> "MessageIdentityDAO":
        """Enforce the closed evidence combinations by receipt state."""
        if self.kind == "ui_notice":
            if self.history_event_id is not None or self.event_sha256 is not None:
                raise ValueError("ui_notice is the sole non-history kind")
            return self
        if (self.history_event_id is None) != (self.event_sha256 is None):
            raise ValueError("history_event_id and event_sha256 appear together or not at all")
        if self.receipt.state == "applied" and self.history_event_id is None:
            raise ValueError("an applied history-bearing kind requires event evidence")
        if self.receipt.state in ("accepted", "cancelled") and self.history_event_id is not None:
            raise ValueError("cancelled or unclaimed records forbid event evidence")
        return self


class CompactionLedgerDAO(MessageDAO):
    """Exact application membership; preparation alone is not coverage."""

    compaction_id: str
    state: Literal["prepared", "committed", "rolled_back"]
    message_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    summary_event_id: Optional[str] = None

    @field_validator("compaction_id", "summary_event_id")
    @classmethod
    def _uuid_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            _require_uuid(value=value, field="compaction identity")
        return value

    @field_validator("message_ids", "observation_ids")
    @classmethod
    def _uuid_tuples(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            _require_uuid(value=item, field="compaction membership")
        if len(value) != len(set(value)):
            raise ValueError("compaction membership must be unique")
        return value

    @model_validator(mode="after")
    def _summary_state(self) -> "CompactionLedgerDAO":
        """Only committed coverage carries a summary event identity."""
        if (self.state == "committed") != (self.summary_event_id is not None):
            raise ValueError("summary identity must match committed state")
        return self


class InternalObservationDAO(MessageDAO):
    """Keep internal completion identity after its event body is pruned.

    A prepared observation requires its event; an applied observation may
    omit it after verified pruning.
    """

    observation_id: str
    history_event_id: str
    event_sha256: str
    state: Literal["prepared", "applied"]
    event: Optional[SessionHistoryEventDAO] = None

    @field_validator("observation_id", "history_event_id")
    @classmethod
    def _uuid_fields(cls, value: str) -> str:
        return _require_uuid(value=value, field="observation identity")

    @field_validator("event_sha256")
    @classmethod
    def _digest_format(cls, value: str) -> str:
        return _require_sha256(value=value, field="event_sha256")

    @model_validator(mode="after")
    def _event_required_while_prepared(self) -> "InternalObservationDAO":
        if self.state == "prepared" and self.event is None:
            raise ValueError("prepared observations require their event")
        return self


class MessageAdmissionError(Exception):
    """Carry one safe admission error DAO and nothing else."""

    def __init__(self, *, error: MessageErrorDAO) -> None:
        super().__init__(error.code)
        self.error = error


class MessageStoreError(Exception):
    """Report storage failure with fixed safe text and suppressed causes."""

    def __init__(self) -> None:
        super().__init__("storage_unavailable")
        self.error = MessageErrorDAO(code="storage_unavailable")


class SessionAlreadyOwnedError(Exception):
    """Report single-owner contention with a fixed safe code."""

    def __init__(self) -> None:
        super().__init__("session_already_owned")
        self.error = MessageErrorDAO(code="unauthorized")


def canonical_submission_bytes(*, submission: MessageSubmissionDAO) -> bytes:
    """Return the canonical UTF-8 JSON bytes used for the 64 KiB payload bound.

    Canonical form is ``sort_keys=True``, comma/colon separators and
    ``ensure_ascii=False``; byte length, never character length, is measured.

    Args:
        submission (MessageSubmissionDAO): The complete validated submission.

    Returns:
        bytes: Canonical UTF-8 JSON encoding of the submission.
    """
    return json.dumps(
        submission.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def utcnow() -> datetime:
    """Return the current canonical UTC timestamp for messaging records."""
    return datetime.now(timezone.utc)
