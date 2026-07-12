"""Scheduling DAOs — schedule definitions, state, triggers, and run records."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional, TypeAlias, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic import model_validator

__all__ = [
    "ActiveSessionDelivery",
    "CalendarTriggerDAO",
    "CoalescingMode",
    "CronTriggerDAO",
    "DeliveryPath",
    "DeliveryState",
    "FireStatus",
    "InactiveSessionDelivery",
    "IntervalTriggerDAO",
    "LoadedScheduleDAO",
    "NotificationTargetDAO",
    "OneShotTriggerDAO",
    "ScheduleDefinitionDAO",
    "ScheduleRunRecordDAO",
    "ScheduleSessionPolicyDAO",
    "ScheduleStateDAO",
    "SessionMode",
    "SlackTargetDAO",
    "TriggerDAO",
    "WebhookTargetDAO",
]


SessionMode: TypeAlias = Literal["fresh", "continuous"]
FireStatus: TypeAlias = Literal["running", "completed", "aborted", "failed"]
CoalescingMode: TypeAlias = Literal["none", "latest_by_key"]
ActiveSessionDelivery: TypeAlias = Literal["session_inbox"]
InactiveSessionDelivery: TypeAlias = Literal["resume"]
DeliveryPath: TypeAlias = Literal["fresh_headless", "resume_headless", "session_inbox", "none"]
DeliveryState: TypeAlias = Literal[
    "executed",
    "queued",
    "coalesced",
    "skipped_disabled",
    "skipped_overlapping",
]


class OneShotTriggerDAO(BaseModel):
    """Fire exactly once at ``run_at``, then the schedule auto-disables."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["one_shot"] = "one_shot"
    run_at: datetime = Field(description="The single timezone-aware instant to fire at.")


class IntervalTriggerDAO(BaseModel):
    """Fire every ``every_seconds`` starting at ``anchor`` or first interval after creation."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["interval"] = "interval"
    every_seconds: int = Field(gt=0, description="Seconds between fires; must be positive.")
    anchor: Optional[datetime] = Field(
        default=None,
        description="Optional phase anchor; when None the first fire is one interval after creation.",
    )


class CronTriggerDAO(BaseModel):
    """Fire on a 5-field cron expression evaluated in ``tz``."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["cron"] = "cron"
    expression: str = Field(description="A 5-field cron expression, e.g. '0 17 * * 5'.")
    tz: str = Field(default="UTC", description="IANA timezone the expression is evaluated in.")


class CalendarTriggerDAO(BaseModel):
    """Fire on an RRULE, minus holidays and explicit blackout dates."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["calendar"] = "calendar"
    rrule: str = Field(description="An iCalendar RRULE, e.g. 'FREQ=WEEKLY;BYDAY=FR;BYHOUR=17;BYMINUTE=0'.")
    tz: str = Field(default="UTC", description="IANA timezone the RRULE is evaluated in.")
    exclude_holidays: Optional[str] = Field(
        default=None,
        description="ISO country code for the holidays library, e.g. 'US'. None disables holiday skipping.",
    )
    blackout_dates: list[str] = Field(
        default_factory=list,
        description="Explicit YYYY-MM-DD dates to skip in addition to holidays.",
    )


TriggerDAO = Annotated[
    Union[OneShotTriggerDAO, IntervalTriggerDAO, CronTriggerDAO, CalendarTriggerDAO],
    Field(discriminator="kind"),
]


class WebhookTargetDAO(BaseModel):
    """POST the rendered outcome to an arbitrary URL."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["webhook"] = "webhook"
    url: str = Field(description="Absolute URL the outcome is POSTed to.")
    template: Optional[str] = Field(
        default=None,
        description="Optional payload template; None sends the default JSON outcome envelope.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Extra request headers such as an auth header.",
    )


class SlackTargetDAO(BaseModel):
    """POST the outcome to a Slack incoming webhook read from an env var."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["slack"] = "slack"
    webhook_url_env: str = Field(
        description="Name of the env var holding the Slack incoming-webhook URL, never the URL itself.",
    )
    channel: Optional[str] = Field(
        default=None,
        description="Optional channel override supported by the webhook.",
    )


NotificationTargetDAO = Annotated[
    Union[WebhookTargetDAO, SlackTargetDAO],
    Field(discriminator="kind"),
]


class ScheduleSessionPolicyDAO(BaseModel):
    """Delivery policy for continuous session-mode schedules."""

    model_config = ConfigDict(frozen=True)

    session_reference: Optional[str] = Field(
        default=None,
        description="Optional target session id or unique session name.",
    )
    active_session_delivery: ActiveSessionDelivery = Field(
        default="session_inbox",
        description="Delivery path for an active TUI-owned target session.",
    )
    inactive_session_delivery: InactiveSessionDelivery = Field(
        default="resume",
        description="Delivery path for an inactive target session.",
    )
    coalescing_mode: CoalescingMode = Field(
        default="none",
        description="Pending-item coalescing strategy for high-frequency schedules.",
    )
    coalescing_key: Optional[str] = Field(
        default=None,
        description="Optional key used to replace older pending items with newer state.",
    )

    @model_validator(mode="after")
    def _validate_coalescing_configuration(self) -> "ScheduleSessionPolicyDAO":
        """Require a coalescing key only when coalescing is enabled.

        Returns:
            ScheduleSessionPolicyDAO: The validated policy.

        Raises:
            ValueError: When the coalescing fields are inconsistent.
        """
        if self.coalescing_mode == "none" and self.coalescing_key is not None:
            raise ValueError(
                "coalescing_key requires coalescing_mode to be set to latest_by_key",
            )
        if self.coalescing_mode == "latest_by_key" and not self.coalescing_key:
            raise ValueError(
                "coalescing_key is required when coalescing_mode is latest_by_key",
            )
        return self


class ScheduleDefinitionDAO(BaseModel):
    """The human-authored, rarely-changing part of a schedule."""

    model_config = ConfigDict(frozen=True)

    schedule_id: str = Field(description="Stable uuid4 hex; the on-disk directory name.")
    name: str = Field(description="Human-friendly label.")
    name_key: str = Field(description="Normalised name for case-insensitive resolve-by-name.")
    enabled: bool = Field(default=True, description="Whether the tick considers this schedule.")
    trigger: TriggerDAO = Field(description="The recurrence rule for the schedule.")
    prompt: str = Field(description="The task prompt fed to the headless run.")
    cwd: Optional[str] = Field(default=None, description="Working directory for the run.")
    model: Optional[str] = Field(default=None, description="Model override; None uses the resolved default.")
    session_mode: SessionMode = Field(default="fresh", description="Either fresh or continuous.")
    session_policy: Optional[ScheduleSessionPolicyDAO] = Field(
        default=None,
        description="Session-targeted delivery policy for continuous schedules.",
    )
    misfire_grace_seconds: int = Field(
        default=300,
        description="Maximum lateness in seconds before a due fire is skipped as a misfire.",
    )
    notifications: list[NotificationTargetDAO] = Field(
        default_factory=list,
        description="Notification targets fired after each run.",
    )

    @model_validator(mode="after")
    def _validate_session_policy(self) -> "ScheduleDefinitionDAO":
        """Enforce fresh-vs-continuous session policy rules.

        Returns:
            ScheduleDefinitionDAO: The validated definition.

        Raises:
            ValueError: When ``session_mode`` and ``session_policy`` disagree.
        """
        if self.session_mode == "fresh" and self.session_policy is not None:
            raise ValueError("session_policy is not allowed when session_mode is fresh")
        if self.session_mode == "continuous" and self.session_policy is None:
            raise ValueError("session_policy is required when session_mode is continuous")
        return self


class ScheduleStateDAO(BaseModel):
    """The machine-authored run-state of a schedule."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = Field(default=1, description="State schema version.")
    next_run_at: Optional[datetime] = Field(
        default=None, description="Next fire instant; None means terminal."
    )
    last_run_at: Optional[datetime] = Field(default=None, description="Start of the last fire.")
    last_status: Optional[FireStatus] = Field(default=None, description="Outcome of the last fire.")
    last_session_id: Optional[str] = Field(default=None, description="Session id of the last fire.")
    last_delivery_path: Optional[DeliveryPath] = Field(
        default=None,
        description="How the most recent fire was delivered.",
    )
    last_delivery_state: Optional[DeliveryState] = Field(
        default=None,
        description="Whether the most recent fire executed, queued, coalesced, or skipped.",
    )
    run_count: int = Field(default=0, ge=0, description="Total fires so far.")


class ScheduleRunRecordDAO(BaseModel):
    """One immutable record of a single fire."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(description="uuid4 hex identifying this fire.")
    schedule_id: str = Field(description="The schedule this fire belongs to.")
    started_at: datetime = Field(description="When the fire began.")
    finished_at: datetime = Field(description="When the fire ended.")
    status: Optional[FireStatus] = Field(
        default=None,
        description="Terminal child-run outcome when a subprocess actually executed.",
    )
    delivery_path: DeliveryPath = Field(description="How the fire was delivered.")
    delivery_state: DeliveryState = Field(
        description="Whether the fire executed, queued, coalesced, or skipped."
    )
    session_id: Optional[str] = Field(
        default=None, description="Actual session id created or resumed by the fire."
    )
    target_session_id: Optional[str] = Field(
        default=None,
        description="Resolved target session id for continuous-session scheduling.",
    )
    exit_code: Optional[int] = Field(
        default=None,
        description="POSIX exit code of the child process when one ran.",
    )
    summary: str = Field(default="", description="Truncated final assistant text.")
    stdout_summary: str = Field(default="", description="Clipped stdout summary for reporting.")
    stderr_summary: str = Field(default="", description="Clipped stderr summary for reporting.")
    skipped_reason: Optional[str] = Field(
        default=None,
        description="Why the fire was skipped instead of executed.",
    )
    coalesced_fire_count: int = Field(
        default=0,
        ge=0,
        description="How many older pending fires were collapsed into this record.",
    )


class LoadedScheduleDAO(BaseModel):
    """One schedule loaded from disk with its definition and state."""

    model_config = ConfigDict(frozen=True)

    schedule_id: str = Field(description="Stable uuid4 hex; the on-disk directory name.")
    definition: ScheduleDefinitionDAO = Field(description="The human-authored definition.")
    state: ScheduleStateDAO = Field(description="The machine-authored run-state.")
