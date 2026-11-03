"""Typed draft submission records for the component-owned admission adapter.

Every record here is transient, frozen and validated; nothing grants authority
and nothing is persisted. The component owns the draft, its revision, the
binding and its reservations; these records are the exact snapshots that cross
between the editor, the host and the adapter.
"""

from __future__ import annotations

from typing import Literal, Optional, Protocol, TypeAlias, Union, runtime_checkable

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.agents.slo_agent.messaging.dao import (
    ErrorCode,
    MessageAddressDAO,
    MessageErrorDAO,
    MessageReceiptDAO,
    MessageSubmissionDAO,
    _require_uuid,
)

__all__: list[str] = [
    "DraftSubmissionDAO",
    "DraftHandoffDAO",
    "DraftHandoffAckDAO",
    "RetainedDraftUsageDAO",
    "UnresolvedDraftHost",
    "DraftHandoffError",
    "SubmissionOutcomeDAO",
    "RetrySubmissionDAO",
    "RecoverableDraftDAO",
    "SubmissionInput",
    "SubmissionOutcomeReceiver",
    "DraftCapacityError",
    "SubmissionUnavailableError",
]


class _SubmissionDAO(BaseModel):
    """Immutable validated submission boundary data; never recipient authority."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True, frozen=True)


class DraftSubmissionDAO(_SubmissionDAO):
    """The exact draft snapshot that crossed Enter, before any clear commit."""

    message_submission: MessageSubmissionDAO = Field(
        description="Canonical immutable ID, target, text and priority."
    )
    draft_revision: int = Field(ge=0, description="Editor revision at capture.")
    binding_version: int = Field(
        ge=0, description="Component binding lifetime; not the recipient generation."
    )


class DraftHandoffDAO(_SubmissionDAO):
    """Transfer exact retiring-binding snapshots only after host acknowledgement."""

    handoff_id: str = Field(description="Canonical UUID idempotency key.")
    target: MessageAddressDAO = Field(description="Original recipient incarnation.")
    binding_version: int = Field(ge=0, description="Retiring component binding.")
    drafts: tuple[DraftSubmissionDAO, ...] = Field(
        min_length=1, max_length=16, description="Exact memory-only snapshots."
    )

    @field_validator("handoff_id")
    @classmethod
    def _uuid_fields(cls, value: str) -> str:
        """Reject noncanonical handoff identity before host delivery."""
        return _require_uuid(value=value, field="handoff_id")

    @model_validator(mode="after")
    def _validate_draft_budget(self) -> "DraftHandoffDAO":
        """Bound canonical payload bytes using the same reservation cost as capture."""
        if sum(draft_submission_bytes(draft_submission=draft) for draft in self.drafts) > 1_048_576:
            raise ValueError("Draft handoff exceeds 1 MiB")
        return self


class DraftHandoffAckDAO(_SubmissionDAO):
    """Acknowledge all snapshots under one exact handoff ID, or refuse all."""

    handoff_id: str = Field(description="Echoed canonical handoff UUID.")
    accepted: bool = Field(description="Whether ownership transferred to the host.")

    @field_validator("handoff_id")
    @classmethod
    def _uuid_fields(cls, value: str) -> str:
        """Validate the acknowledgement's echoed key."""
        return _require_uuid(value=value, field="handoff_id")


class RetainedDraftUsageDAO(_SubmissionDAO):
    """Report memory reservations owned by the host, not another durable queue."""

    draft_count: int = Field(ge=0, description="Host-held snapshot count.")
    canonical_bytes: int = Field(ge=0, description="Canonical submission byte total.")


@runtime_checkable
class UnresolvedDraftHost(Protocol):
    """Receive exact unresolved snapshots and expose their shared capacity cost."""

    async def retain_unresolved_drafts(self, *, handoff: DraftHandoffDAO) -> DraftHandoffAckDAO:
        """Accept all snapshots idempotently or refuse without taking ownership."""
        ...

    def count_retained_drafts(self) -> RetainedDraftUsageDAO:
        """Report host reservations for the component's synchronous capacity check."""
        ...


class DraftHandoffError(Exception):
    """Refuse retirement without abandoning component-owned drafts."""

    def __init__(self) -> None:
        """Carry only the fixed safe handoff failure notice."""
        super().__init__("Unsent drafts could not be kept")


class SubmissionOutcomeDAO(_SubmissionDAO):
    """Report the recipient's answer for one submitted snapshot."""

    draft_submission: DraftSubmissionDAO = Field(description="Exact submitted snapshot.")
    outcome: MessageReceiptDAO | MessageErrorDAO = Field(
        description="Validated recipient answer; never exception text."
    )


class RetrySubmissionDAO(_SubmissionDAO):
    """Name one retained snapshot for an identical-bytes resubmission."""

    message_id: str = Field(description="Canonical UUID of the retained draft.")

    @field_validator("message_id")
    @classmethod
    def _uuid_fields(cls, value: str) -> str:
        return _require_uuid(value=value, field="message_id")


class RecoverableDraftDAO(_SubmissionDAO):
    """List one tracked or host-held draft for the ``/messages drafts`` view."""

    draft_submission: DraftSubmissionDAO = Field(description="Exact retained snapshot.")
    state: Literal["waiting", "recoverable", "host_held"] = Field(description="Local draft state.")
    last_error_code: Optional[ErrorCode] = Field(
        default=None, description="Last recipient refusal, when one settled."
    )


SubmissionInput: TypeAlias = Union[DraftSubmissionDAO, RetrySubmissionDAO]


class SubmissionOutcomeReceiver(Protocol):
    """Deliver one validated recipient answer to its owning component."""

    async def handle(self, *, command: SubmissionOutcomeDAO) -> None:
        """Apply one outcome before returning; errors propagate to the adapter."""
        ...


class DraftCapacityError(Exception):
    """Refuse one more tracked draft when a bounded budget is exhausted."""

    def __init__(self, *, reason: Literal["in_flight", "recoverable"]) -> None:
        """Carry the exhausted budget name and the fixed user-facing text."""
        super().__init__("Too many prompts are waiting; your text was kept.")
        self.reason: Literal["in_flight", "recoverable"] = reason


class SubmissionUnavailableError(Exception):
    """Refuse capture when there is no binding or the binding is sealed."""

    def __init__(self) -> None:
        """Carry the fixed text; the host renders its own notice."""
        super().__init__("Session is changing; your text was kept.")


def draft_submission_bytes(*, draft_submission: DraftSubmissionDAO) -> int:
    """Return the canonical byte cost of one tracked snapshot for budget accounting.

    Args:
        draft_submission (DraftSubmissionDAO): The exact retained snapshot.

    Returns:
        int: Canonical submission byte length shared with the 64 KiB validation.
    """
    from src.agents.slo_agent.messaging.dao import canonical_submission_bytes

    return len(canonical_submission_bytes(submission=draft_submission.message_submission))
