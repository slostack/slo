"""Schedule DAOs — schedule rows, inputs and trigger rules for `schedules.db`."""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID
from typing import Annotated, Literal, Optional, TypeAlias, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "EngineReadinessPhase",
    "ScheduleEngineReadinessDAO",
    "CronTriggerDAO",
    "DeliveryDecisionDAO",
    "IntervalTriggerDAO",
    "InvocationOutcomeDAO",
    "InvocationStatus",
    "NewScheduleDAO",
    "OneShotTriggerDAO",
    "ScheduleDAO",
    "RetentionResultDAO",
    "ScheduleInvocationDAO",
    "ScheduleReportCountsDAO",
    "ScheduleReportDAO",
    "ScheduleStateFilter",
    "ScheduleSummaryDAO",
    "ScheduleTickResultDAO",
    "SkipReason",
    "TriggerDAO",
]

_MAX_PROMPT_LENGTH: int = 65536
_MIN_INTERVAL_SECONDS: int = 15
_NAME_KEY_SEPARATORS: re.Pattern[str] = re.compile(r"\s+")
_REPEATED_HYPHENS: re.Pattern[str] = re.compile(r"-{2,}")


def _require_aware(value: datetime) -> datetime:
    """Reject a naive datetime value.

    Args:
        value (datetime): The datetime to check.

    Returns:
        datetime: The value unchanged when it carries a timezone.

    Raises:
        ValueError: When the value is naive.
    """
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class OneShotTriggerDAO(BaseModel):
    """Fire exactly once at ``run_at``, then the schedule auto-disables."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["one_shot"] = Field(
        default="one_shot", description="Discriminator for the one-shot trigger."
    )
    run_at: datetime = Field(
        description="The single timezone-aware instant to fire at, stored in UTC. Naive values are rejected."
    )

    @field_validator("run_at")
    @classmethod
    def _reject_naive_run_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware ``run_at``.

        Args:
            value (datetime): The parsed run-at instant.

        Returns:
            datetime: The value unchanged when timezone-aware.

        Raises:
            ValueError: When the value is naive.
        """
        return _require_aware(value)


class IntervalTriggerDAO(BaseModel):
    """Fire every ``every_seconds`` starting at ``anchor`` or one interval after creation."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["interval"] = Field(
        default="interval", description="Discriminator for the interval trigger."
    )
    every_seconds: int = Field(
        ge=_MIN_INTERVAL_SECONDS,
        description="Seconds between fires; at least 15 (D8 interval floor).",
    )
    anchor: Optional[datetime] = Field(
        default=None,
        description="Optional phase anchor; when None the first fire is one interval after creation.",
    )


class CronTriggerDAO(BaseModel):
    """Fire on a 5-field cron expression evaluated in ``tz``."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["cron"] = Field(default="cron", description="Discriminator for the cron trigger.")
    expression: str = Field(description="A 5-field cron expression, e.g. '0 9 * * *', parsed with cronsim.")
    tz: str = Field(default="UTC", description="IANA timezone the expression is evaluated in.")


TriggerDAO: TypeAlias = Annotated[
    Union[OneShotTriggerDAO, IntervalTriggerDAO, CronTriggerDAO],
    Field(discriminator="kind"),
]
"""The schedule trigger union: one-shot, interval or cron (calendar dropped, D8)."""

ScheduleStateFilter: TypeAlias = Literal["active", "disabled"]
"""List filter: ``active`` rows are enabled and not deleted; ``disabled`` rows are enabled = 0."""


class NewScheduleDAO(BaseModel):
    """Input for creating or editing a schedule; validated before any state is checked."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Human-facing schedule name; stored trimmed, never empty.")
    prompt: str = Field(
        min_length=1,
        max_length=_MAX_PROMPT_LENGTH,
        description="Prompt sent on every invocation; 1 to 65,536 characters, never logged.",
    )
    trigger: TriggerDAO = Field(description="When the schedule is due: one-shot, interval or cron.")
    session_mode: Literal["fresh", "continuous"] = Field(
        default="fresh",
        description="fresh runs headless per due time; continuous targets one open session.",
    )
    session_reference: Optional[str] = Field(
        default=None,
        description="Target session id or name for continuous schedules; forbidden for fresh.",
    )
    coalescing_mode: Literal["none", "latest_by_key"] = Field(
        default="none",
        description="Pending-invocation coalescing for continuous schedules; none collapses nothing.",
    )
    coalescing_key: Optional[str] = Field(
        default=None,
        description="Key used with latest_by_key coalescing; forbidden when the mode is none.",
    )
    misfire_grace_seconds: int = Field(
        default=300,
        ge=0,
        description="Maximum lateness still delivered; beyond it the due time is a misfire.",
    )
    cwd: Optional[str] = Field(
        default=None,
        description="Headless fresh-run working directory; ignored by the channel delivery path (D9).",
    )
    model: Optional[str] = Field(
        default=None,
        description="Headless fresh-run model override; ignored by the channel delivery path (D9).",
    )

    @field_validator("name")
    @classmethod
    def _reject_blank_name(cls, value: str) -> str:
        """Strip the name and reject an empty result.

        Args:
            value (str): The raw name.

        Returns:
            str: The trimmed name.

        Raises:
            ValueError: When the name is empty after trimming.
        """
        stripped: str = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @classmethod
    def normalize_name_key(cls, *, name: str) -> str:
        """Normalise a schedule name to its case-insensitive lookup key.

        Args:
            name (str): The human-facing name.

        Returns:
            str: Lower-cased, whitespace-collapsed, hyphenated key; repeated
            hyphens collapse so ``Repo--Watch`` and ``Repo-Watch`` share a key.
        """
        collapsed: str = _NAME_KEY_SEPARATORS.sub("-", name.strip().lower())
        return _REPEATED_HYPHENS.sub("-", collapsed)

    @property
    def name_key(self) -> str:
        """Return the normalised lookup key for the trimmed name.

        Returns:
            str: The case-insensitive key, unique among active rows.
        """
        return self.normalize_name_key(name=self.name)

    @model_validator(mode="after")
    def _validate_session_rules(self) -> "NewScheduleDAO":
        """Enforce the fresh/continuous session rules.

        Returns:
            NewScheduleDAO: The validated input.

        Raises:
            ValueError: When fresh carries a session reference or coalescing, or the
                coalescing mode and key disagree.
        """
        if self.session_mode == "fresh" and (
            self.session_reference is not None
            or self.coalescing_mode != "none"
            or self.coalescing_key is not None
        ):
            raise ValueError("fresh schedules cannot use session_reference or coalescing")
        if self.coalescing_mode == "none" and self.coalescing_key is not None:
            raise ValueError("coalescing_key requires coalescing_mode latest_by_key")
        if self.coalescing_mode == "latest_by_key" and not self.coalescing_key:
            raise ValueError("coalescing_mode latest_by_key requires a non-empty coalescing_key")
        return self


class ScheduleDAO(BaseModel):
    """One persisted schedule row; the only owner of definition, enabled flag and soft deletion."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(description="Stable identity of this schedule row; uuid4 at create.")
    name: str = Field(description="Human-facing schedule name; stored trimmed.")
    name_key: str = Field(description="Normalised name key; unique among active rows.")
    prompt: str = Field(
        min_length=1,
        max_length=_MAX_PROMPT_LENGTH,
        description="Prompt sent on every invocation; never logged.",
    )
    trigger: TriggerDAO = Field(description="When the schedule is due: one-shot, interval or cron.")
    session_mode: Literal["fresh", "continuous"] = Field(
        description="fresh runs headless per due time; continuous targets one open session."
    )
    session_reference: Optional[str] = Field(
        default=None,
        description="Target session id or name for continuous schedules; None for fresh.",
    )
    coalescing_mode: Literal["none", "latest_by_key"] = Field(
        default="none",
        description="Pending-invocation coalescing for continuous schedules.",
    )
    coalescing_key: Optional[str] = Field(
        default=None,
        description="Key used with latest_by_key coalescing; None when the mode is none.",
    )
    cwd: Optional[str] = Field(
        default=None,
        description="Headless fresh-run working directory; ignored by the channel delivery path (D9).",
    )
    model: Optional[str] = Field(
        default=None,
        description="Headless fresh-run model override; ignored by the channel delivery path (D9).",
    )
    misfire_grace_seconds: int = Field(
        default=300,
        ge=0,
        description="Maximum lateness still delivered; beyond it the due time is a misfire.",
    )
    enabled: bool = Field(default=True, description="False stops future due times; NULL next_due_at follows.")
    next_due_at: Optional[datetime] = Field(
        default=None,
        description="Next due instant in UTC; None when disabled, deleted or finished.",
    )
    created_at: datetime = Field(description="Creation instant in UTC.")
    updated_at: datetime = Field(description="Last write instant in UTC.")
    deleted_at: Optional[datetime] = Field(
        default=None,
        description="Soft-deletion instant in UTC; deleted rows never reappear in lists.",
    )

    @field_validator("name")
    @classmethod
    def _reject_blank_name(cls, value: str) -> str:
        """Strip the name and reject an empty result.

        Args:
            value (str): The raw name.

        Returns:
            str: The trimmed name.

        Raises:
            ValueError: When the name is empty after trimming.
        """
        stripped: str = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @classmethod
    def normalize_name_key(cls, *, name: str) -> str:
        """Normalise a schedule name; delegates to the canonical ``NewScheduleDAO`` rule.

        Args:
            name (str): The human-facing name.

        Returns:
            str: Lower-cased, whitespace-collapsed, hyphenated key.
        """
        return NewScheduleDAO.normalize_name_key(name=name)

    @model_validator(mode="after")
    def _validate_state_rules(self) -> "ScheduleDAO":
        """Enforce the session rules and the deleted-row invariants.

        Returns:
            ScheduleDAO: The validated row.

        Raises:
            ValueError: When fresh carries a session reference or coalescing, the
                coalescing mode and key disagree, or a deleted row still claims a
                next due time.
        """
        if self.session_mode == "fresh" and (
            self.session_reference is not None
            or self.coalescing_mode != "none"
            or self.coalescing_key is not None
        ):
            raise ValueError("fresh schedules cannot use session_reference or coalescing")
        if self.coalescing_mode == "none" and self.coalescing_key is not None:
            raise ValueError("coalescing_key requires coalescing_mode latest_by_key")
        if self.coalescing_mode == "latest_by_key" and not self.coalescing_key:
            raise ValueError("coalescing_mode latest_by_key requires a non-empty coalescing_key")
        if self.deleted_at is not None and self.next_due_at is not None:
            raise ValueError("a deleted schedule must not keep a next_due_at")
        return self


InvocationStatus: TypeAlias = Literal[
    "pending",
    "delivered",
    "skipped",
    "failed",
    "running",
    "completed",
    "run_failed",
]
"""Lifecycle status of one invocation row; every final state is terminal."""

SkipReason: TypeAlias = Literal["schedule_disabled", "schedule_deleted", "misfire"]
"""Why an invocation was skipped; never a channel refusal."""


class ScheduleInvocationDAO(BaseModel):
    """One due time of one schedule and its delivery attempt."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(description="Invocation id. Also the channel message id when delivered.")
    schedule_id: UUID = Field(description="Schedule this due time belongs to.")
    due_at: datetime = Field(
        description="Planned due instant, UTC, millisecond precision. Unique per schedule."
    )
    status: InvocationStatus = Field(
        description="pending, delivered, skipped, failed, running, completed or run_failed."
    )
    skip_reason: Optional[SkipReason] = Field(
        default=None,
        description="Why the invocation was skipped. Set only when status is skipped.",
    )
    failure_reason: Optional[str] = Field(
        default=None,
        description="Why delivery was refused. Set only when status is failed.",
    )
    recipient_session_id: Optional[str] = Field(
        default=None,
        description="Agent session that should receive the prompt.",
    )
    channel_message_id: Optional[UUID] = Field(
        default=None,
        description="Channel row written for this invocation. Equals id when delivered.",
    )
    accepted_at: Optional[datetime] = Field(
        default=None,
        description="Acceptance time copied from the channel row by the outcome reconciler.",
    )
    cancelled_at: Optional[datetime] = Field(
        default=None,
        description="Cancel time copied from the channel row by the outcome reconciler.",
    )
    cancel_reason: Optional[str] = Field(
        default=None,
        description="Cancel reason copied from the channel row, for example superseded.",
    )
    reply_message_id: Optional[UUID] = Field(
        default=None,
        description="Id of the reply row, copied by the outcome reconciler.",
    )
    outcome_reconciled_at: Optional[datetime] = Field(
        default=None,
        description="When the outcome snapshot was last refreshed.",
    )
    channel_row_gone_at: Optional[datetime] = Field(
        default=None,
        description="When the reconciler found the channel row pruned. The row is then never read again.",
    )
    run_exit_code: Optional[int] = Field(
        default=None,
        description="Exit code of the fresh run; None until the run ends.",
    )
    created_at: datetime = Field(description="When the invocation row was created, UTC.")
    delivered_at: Optional[datetime] = Field(
        default=None,
        description="When the prompt was delivered to the channel, UTC.",
    )


class InvocationOutcomeDAO(BaseModel):
    """Channel facts copied onto one invocation row by the outcome reconciler."""

    model_config = ConfigDict(frozen=True)

    accepted_at: Optional[datetime] = Field(
        default=None,
        description="Acceptance time copied from the channel row.",
    )
    cancelled_at: Optional[datetime] = Field(
        default=None,
        description="Cancel time copied from the channel row.",
    )
    cancel_reason: Optional[str] = Field(
        default=None,
        description="Cancel reason copied from the channel row.",
    )
    reply_message_id: Optional[UUID] = Field(
        default=None,
        description="Id of the reply row copied from the channel.",
    )


class DeliveryDecisionDAO(BaseModel):
    """One deliver step's decision: deliver, skip, fail or run, with the loaded schedule row."""

    model_config = ConfigDict(frozen=True)

    outcome: Literal["deliver", "skip", "fail", "run"] = Field(
        description="What deliver must do. run starts a fresh headless run."
    )
    skip_reason: Optional[SkipReason] = Field(
        default=None,
        description="Why the invocation was skipped, when outcome is skip.",
    )
    failure_reason: Optional[str] = Field(
        default=None,
        description="Why the invocation failed, when outcome is fail.",
    )
    recipient_session_id: Optional[str] = Field(
        default=None,
        description="Resolved session id to send to, when outcome is deliver.",
    )
    schedule: ScheduleDAO = Field(
        description="The schedule row the decision loaded, so deliver never loads it again."
    )


class ScheduleTickResultDAO(BaseModel):
    """Counts from one tick run; every field is a plain number."""

    model_config = ConfigDict(frozen=True)

    created_count: int = Field(ge=0, description="Pending invocations created in this run.")
    duplicate_count: int = Field(ge=0, description="Due times already covered by an existing invocation.")
    misfire_count: int = Field(ge=0, description="Missed due times recorded as skipped/misfire in this run.")
    enqueued_count: int = Field(ge=0, description="Pending invocations handed to the delivery queue.")
    reconciled_count: int = Field(ge=0, description="Outcome snapshots refreshed in this run.")


class ScheduleSummaryDAO(BaseModel):
    """One list row: the schedule plus its newest invocation status."""

    model_config = ConfigDict(frozen=True)

    schedule: ScheduleDAO = Field(description="The schedule row this summary describes.")
    last_invocation_status: Optional[InvocationStatus] = Field(
        default=None,
        description="Status of the newest invocation; None when the schedule has none.",
    )


class ScheduleReportCountsDAO(BaseModel):
    """Counts for one report window; each is a plain rule over the rows."""

    model_config = ConfigDict(frozen=True)

    total: int = Field(ge=0, description="Invocation rows in the window.")
    pending: int = Field(ge=0, description="Rows still pending.")
    delivered: int = Field(ge=0, description="Rows delivered (channel row stored or run finished).")
    skipped: int = Field(ge=0, description="Rows skipped for any reason.")
    skipped_misfire: int = Field(ge=0, description="Skipped rows whose reason is misfire.")
    failed: int = Field(ge=0, description="Rows whose delivery was refused.")
    accepted: int = Field(ge=0, description="Delivered rows the agent accepted (snapshot).")
    cancelled: int = Field(ge=0, description="Delivered rows later cancelled (snapshot).")
    superseded: int = Field(ge=0, description="Cancelled rows whose reason is superseded (snapshot).")
    replied: int = Field(ge=0, description="Delivered rows that have a reply (snapshot).")
    pending_outcome: int = Field(ge=0, description="Delivered rows the outcome copy has not yet refreshed.")
    outcome_unavailable: int = Field(
        ge=0,
        description=("Delivered rows whose channel row was pruned before the outcome copy ran (D18)."),
    )
    running: int = Field(ge=0, description="Rows whose run started and has not finished (111.a.3).")
    completed: int = Field(ge=0, description="Rows whose run finished with exit code 0 (111.a.3).")
    run_failed: int = Field(ge=0, description="Rows whose run finished with a non-zero exit code (111.a.3).")


class ScheduleReportDAO(BaseModel):
    """One schedule's report for a window: counts plus the newest rows."""

    model_config = ConfigDict(frozen=True)

    schedule_id: UUID = Field(description="Schedule being reported.")
    name: str = Field(description="Schedule name at report time.")
    window_start: datetime = Field(description="Start of the window, UTC; compared with due_at.")
    window_end: datetime = Field(description="End of the window, UTC; compared with due_at.")
    counts: ScheduleReportCountsDAO = Field(description="Counts for the window.")
    recent_invocations: list[ScheduleInvocationDAO] = Field(
        description="At most 20 rows, newest due_at first."
    )


class RetentionResultDAO(BaseModel):
    """Counts from one retention purge run."""

    model_config = ConfigDict(frozen=True)

    deleted_invocations: int = Field(ge=0, description="Invocation rows deleted in this run.")
    deleted_schedules: int = Field(ge=0, description="Soft-deleted schedule rows removed in this run.")


EngineReadinessPhase: TypeAlias = Literal["starting", "ready", "stalled", "retiring", "failed"]


class ScheduleEngineReadinessDAO(BaseModel):
    """What a running engine reports about itself to a health challenge (OPS111-03).

    ``ready`` is True only after restart recovery finished, while the scheduler
    holds its leadership, both the scheduler and the delivery worker loops run
    and a tick pass finished recently. It says the worker can fire due work;
    it never proves an invocation ran.
    """

    model_config = ConfigDict(frozen=True)

    phase: EngineReadinessPhase = Field(
        description="starting before leadership, ready while it leads and ticks progress, stalled when the"
        " loops run without leadership or tick progress, retiring once asked to stop, failed once a loop ended."
    )
    reason: Optional[str] = Field(
        default=None, description="Safe operator-facing explanation when the phase is not ready."
    )
    last_tick_at: Optional[datetime] = Field(
        default=None, description="UTC instant the engine last finished a tick pass; None before the first."
    )

    @property
    def ready(self) -> bool:
        """Return True when the engine can fire due work."""
        return self.phase == "ready"
