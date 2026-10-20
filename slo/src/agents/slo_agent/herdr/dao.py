"""Frozen Herdr boundaries; private carriers must never enter public serializers."""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional, Protocol, runtime_checkable
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ModelWrapValidatorHandler,
    field_validator,
    model_validator,
)
from src.agents.slo_agent.sessions.dao import OperatorAttentionReason, SessionReportingStateDAO
from src.agents.reasoning_capabilities import ReasoningLevel
from src.auth.credential_dao import ProviderName

HerdrDestination = Literal["platform", "herdr", "unavailable"]
HerdrDisplayKey = Literal[
    "model",
    "session_tokens",
    "context",
    "cooldown",
    "session",
    "provider",
    "reasoning",
    "effort",
    "turn",
    "in",
    "out",
    "cache_read",
    "cache_write",
    "context_left",
    "rpm",
    "tpm",
    "out_cap",
    "budget",
]


class HerdrDAO(BaseModel):
    """Immutable closed structural boundary with hidden validation inputs."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    @field_validator("schema_version", mode="before", check_fields=False)
    @classmethod
    def _strict_version(cls, value: object) -> object:
        """Do not accept bool as the integer schema version."""
        if type(value) is not int:
            raise ValueError("Invalid schema version.")
        return value

    @model_validator(mode="wrap")
    @classmethod
    def _safe_validation(cls, value: object, handler: ModelWrapValidatorHandler[HerdrDAO]) -> HerdrDAO:
        """Discard private inputs, locations and causes from structural errors."""
        try:
            return handler(value)
        except ValidationError:
            raise ValidationError.from_exception_data(
                title="Herdr validation",
                hide_input=True,
                line_errors=[
                    {
                        "type": "value_error",
                        "loc": (),
                        "input": None,
                        "ctx": {"error": ValueError("Invalid Herdr data.")},
                    }
                ],
            ) from None


class HerdrDisplayTokenDAO(HerdrDAO):
    """One bounded already-redacted display value."""

    key: HerdrDisplayKey = Field(description="Owned publication inventory key.")
    value: str = Field(description="Generated single-line display value.")

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: str) -> str:
        """Reject complete unsafe tokens, never truncate them."""
        if not cls._safe_token_value(value=value):
            raise ValueError("Invalid display token.")
        return value

    @classmethod
    def _safe_token_value(cls, *, value: str) -> bool:
        """Check generated telemetry bounds without normalizing or truncating.

        Args:
            value (str): Generated numeric telemetry or a fixed vocabulary value.

        Returns:
            bool: Whether the complete token satisfies character and byte bounds.
        """
        if not value or len(value) > 80:
            return False
        if any(unicodedata.category(c).startswith("C") or (c.isspace() and c != " ") for c in value):
            return False
        try:
            return len(value.encode(encoding="utf-8")) <= 128
        except UnicodeError:
            return False


class HerdrReportSnapshotDAO(SessionReportingStateDAO):
    """Public facts, structurally incapable of carrying restore policy."""

    session_id: str = Field(description="Session identity for this observation.")
    tokens: tuple[HerdrDisplayTokenDAO, ...] = Field(description="Ordered unique display tokens.")

    @field_validator("tokens")
    @classmethod
    def _unique_tokens(cls, value: tuple[HerdrDisplayTokenDAO, ...]) -> tuple[HerdrDisplayTokenDAO, ...]:
        """Refuse duplicate inventory keys."""
        if len({token.key for token in value}) != len(value):
            raise ValueError("Duplicate display keys.")
        return value


class HerdrRestorePoolEntryDAO(HerdrDAO):
    """Exact scalar copy of a validated configured pool entry."""

    model_name: str = Field(repr=False, description="Configured model identity.")
    provider: ProviderName = Field(repr=False, description="Configured provider identity.")
    priority: int = Field(strict=True, repr=False, description="Configured routing priority.")
    cooldown_seconds: int = Field(strict=True, repr=False, description="Credit cooldown in seconds.")
    rate_limit_cooldown_seconds: int = Field(
        strict=True, repr=False, description="Transient cooldown in seconds."
    )


class HerdrRestorePoolDAO(HerdrDAO):
    """Ordered recursively immutable pool policy, not live cooldown state."""

    entries: tuple[HerdrRestorePoolEntryDAO, ...] = Field(
        min_length=2, repr=False, description="Exact configured entry order."
    )


class HerdrRestoreConfigDAO(HerdrDAO):
    """Allowed private restore policy; serialize only in the restore store."""

    session_id: str = Field(repr=False, description="Exact captured session identity.")
    model_name: str = Field(repr=False, description="Configured model rather than routed fallback.")
    model_pool_dao: Optional[HerdrRestorePoolDAO] = Field(
        default=None, repr=False, description="Exact configured pool policy."
    )
    reasoning_level: ReasoningLevel = Field(repr=False, description="Effective configured reasoning level.")
    workdir: Path = Field(repr=False, description="Session-resolved working directory.")
    workspace_file: Optional[Path] = Field(
        default=None, repr=False, description="Session-resolved workspace file."
    )
    plugin_paths: tuple[Path, ...] = Field(
        default=(), repr=False, description="Ordered session-resolved plugin paths."
    )


class HerdrRestoreCaptureDAO(HerdrDAO):
    """Memory-only exact configuration capture, with no generated reference."""

    config: HerdrRestoreConfigDAO = Field(repr=False, description="Immutable private restore configuration.")


class HerdrPublicationDAO(HerdrDAO):
    """Private atomic public-facts and exact-policy handoff."""

    configuration_generation: int = Field(ge=0, strict=True, description="Session-owned policy generation.")
    snapshot: HerdrReportSnapshotDAO = Field(description="Already-redacted public facts.")
    restore_capture: Optional[HerdrRestoreCaptureDAO] = Field(
        default=None, repr=False, description="Exact capture; absent means ineligible."
    )

    @model_validator(mode="after")
    def _same_identity(self) -> HerdrPublicationDAO:
        """Require capture and observation to refer to the same session."""
        if (
            self.restore_capture is not None
            and self.restore_capture.config.session_id != self.snapshot.session_id
        ):
            raise ValueError("Invalid publication identity.")
        return self


class HerdrRestoreReferenceDAO(HerdrDAO):
    """Opaque revision identity independent of private configuration."""

    restore_reference: str = Field(
        pattern=r"^r1-[0-9a-f]{32}$",
        min_length=35,
        max_length=35,
        repr=False,
        description="Canonical random revision reference.",
    )


class HerdrRestoreRecordDAO(HerdrRestoreReferenceDAO):
    """Private persisted envelope; no history or runtime objects."""

    schema_version: Literal[1] = Field(description="Private restore schema version.")
    config: HerdrRestoreConfigDAO = Field(repr=False, description="Exact private policy for this revision.")


class HerdrSavedRestoreDAO(HerdrDAO):
    """Save result bound to its exact input capture and generation."""

    configuration_generation: int = Field(
        ge=0, strict=True, repr=False, description="Captured policy generation."
    )
    capture: HerdrRestoreCaptureDAO = Field(repr=False, description="Exact saved input capture.")
    reference: HerdrRestoreReferenceDAO = Field(repr=False, description="Persisted immutable revision.")


class HerdrRemoteBindingDAO(HerdrDAO):
    """Last admitted remote claim, retained until confirmed release."""

    configuration_generation: int = Field(
        ge=0, strict=True, repr=False, description="Claim policy generation."
    )
    session_id: str = Field(repr=False, description="Claimed session identity.")
    capture: Optional[HerdrRestoreCaptureDAO] = Field(
        repr=False, description="Exact potentially installed capture."
    )
    reference: Optional[HerdrRestoreReferenceDAO] = Field(
        repr=False, description="Potentially installed revision."
    )
    certainty: Literal["possible", "confirmed"] = Field(description="Remote claim certainty.")


HerdrCommandStatus = Literal[
    "ok", "unavailable", "timeout", "rejected", "malformed", "cancelled", "suppressed"
]


class HerdrCommandOutcomeDAO(HerdrDAO):
    """Safe transport outcome, never raw output or exception text."""

    status: HerdrCommandStatus = Field(description="Fixed command outcome category.")
    exit_code: Optional[int] = Field(
        default=None, strict=True, description="Numeric child exit status when known."
    )


class HerdrCommandResultDAO(HerdrDAO):
    """Private bounded parser input and admission accounting."""

    outcome: HerdrCommandOutcomeDAO = Field(description="Safe transport result.")
    json_bytes: Optional[bytes] = Field(
        default=None,
        max_length=16384,
        repr=False,
        description="Bounded successful JSON stdout for private parsing only.",
    )
    admitted: bool = Field(default=False, description="Whether spawn admission committed.")
    spawn_failed: bool = Field(default=False, description="Definitive failure to create the admitted child.")

    @model_validator(mode="after")
    def _valid_result(self) -> HerdrCommandResultDAO:
        """Forbid failed output and ambiguous spawn-failure claims."""
        if self.outcome.status != "ok" and self.json_bytes is not None:
            raise ValueError("Invalid command output.")
        if self.spawn_failed and not (self.admitted and self.outcome.status == "unavailable"):
            raise ValueError("Invalid spawn outcome.")
        return self


class HerdrReporterCloseOutcomeDAO(HerdrDAO):
    """Remote replacement evidence separate from final local disposal evidence.

    Intermediate reporter close leaves resources at its default; it is not disposal
    permission. Only final session close aggregates transport, leases and viewer.
    """

    replacement: Literal["safe", "uncertain"] = Field(description="Whether a replacement reporter is safe.")
    resources: Literal["drained", "retained"] = Field(
        default="drained", description="Final local resource quarantine evidence."
    )

    @model_validator(mode="after")
    def _retention_is_uncertain(self) -> HerdrReporterCloseOutcomeDAO:
        """Retained ownership is never permission to replace."""
        if self.resources == "retained" and self.replacement != "uncertain":
            raise ValueError("Invalid close outcome.")
        return self


HerdrReportOperation = Literal[
    "claim",
    "lifecycle",
    "restore",
    "clear",
    "set",
    "replace_release",
    "shutdown_release",
    "shutdown_clear",
    "activation_release",
]


class HerdrReportTicketDAO(HerdrDAO):
    """Immutable command authority captured before transport lock wait."""

    configuration_generation: int = Field(ge=0, strict=True, description="Captured policy generation.")
    report_revision: int = Field(ge=0, strict=True, description="Captured reporter revision.")
    operation: HerdrReportOperation = Field(description="Single authorized report operation.")
    sequence: int = Field(ge=0, strict=True, description="Durably reserved source sequence.")
    saved: Optional[HerdrSavedRestoreDAO] = Field(
        default=None, repr=False, description="Exact saved restore pair."
    )
    binding: Optional[HerdrRemoteBindingDAO] = Field(
        default=None, repr=False, description="Exact binding targeted for release."
    )
    close_token: Optional[int] = Field(
        default=None, ge=0, strict=True, description="Shutdown authority token."
    )
    publication: Optional[HerdrPublicationDAO] = Field(
        default=None, repr=False, description="Captured ordinary publication."
    )
    display_final: bool = Field(
        default=False, description="Whether this clear or set completes the display batch."
    )

    @model_validator(mode="after")
    def _operation_shape(self) -> HerdrReportTicketDAO:
        """Separate ordinary publication from activation/shutdown authority."""
        ordinary = self.operation not in ("activation_release", "shutdown_release", "shutdown_clear")
        if ordinary != (self.publication is not None):
            raise ValueError("Invalid ticket publication.")
        if self.display_final and self.operation not in ("clear", "set"):
            raise ValueError("Invalid final display ticket.")
        return self


class HerdrLifecycleAcknowledgementDAO(SessionReportingStateDAO):
    """Acknowledged semantic state, independent of display revision."""

    configuration_generation: int = Field(ge=0, strict=True, description="Acknowledged policy generation.")
    session_id: str = Field(description="Acknowledged session identity.")


HerdrViewerOperation = Literal["split", "rename", "run"]


class HerdrVisualizerRequestDAO(HerdrDAO):
    """Typed viewer request shared by attached and detached paths."""

    parent_session_id: str = Field(description="Requested parent session identity.")
    history_root: Path = Field(repr=False, description="Captured session history root.")


class VisualizerLaunchOutcomeDAO(HerdrDAO):
    """Safe viewer outcome without command output."""

    status: Literal["opened", "submitted", "reused", "skipped", "failed"] = Field(
        description="Observed viewer launch outcome."
    )
    pane_id: Optional[str] = Field(default=None, description="Known viewer pane when available.")


class HerdrVisualizerAttemptDAO(HerdrDAO):
    """Immutable one-shot viewer reservation and admitted operation ledger."""

    state: Literal["split_attempted", "uncertain", "pane_known"] = Field(
        description="Reservation certainty after split."
    )
    pane_id: Optional[str] = Field(default=None, description="Pane identity only when known.")
    admitted_operations: frozenset[HerdrViewerOperation] = Field(
        default=frozenset(), description="Operations already admitted exactly once."
    )

    @model_validator(mode="after")
    def _pane_matches_state(self) -> HerdrVisualizerAttemptDAO:
        """Require pane identity exactly for the known-pane state."""
        if (self.state == "pane_known") != (self.pane_id is not None):
            raise ValueError("Invalid viewer attempt.")
        return self


class HerdrReporterConfigDAO(HerdrDAO):
    """Captured configuration; executable security is checked off-loop at start."""

    pane_id: str = Field(
        min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$", description="Safe opaque owner pane identifier."
    )
    binary_path: Path = Field(repr=False, description="Captured absolute executable path.")
    socket_path: Optional[str] = Field(default=None, repr=False, description="Captured optional socket path.")
    state_root: Path = Field(repr=False, description="Resolved integration state root.")
    metadata_profile: Literal["compact", "detail"] = Field(
        description="Requested metadata projection profile."
    )
    command_timeout_seconds: float = Field(
        default=1.0, ge=1.0, le=1.0, description="Fixed lock-inclusive deadline in seconds."
    )
    terminate_grace_seconds: float = Field(
        default=0.25, ge=0.25, le=0.25, description="Fixed terminate grace in seconds."
    )
    close_timeout_seconds: float = Field(
        default=2.0, ge=2.0, le=2.0, description="Fixed remote close budget in seconds."
    )

    @field_validator("binary_path", "state_root")
    @classmethod
    def _absolute_path(cls, value: Path) -> Path:
        """Validate shape without probing the filesystem."""
        if not value.is_absolute():
            raise ValueError("Invalid integration path.")
        return value


class HerdrSequenceStateDAO(HerdrDAO):
    """Durable independent source sequence counters."""

    schema_version: Literal[1] = Field(description="Counter file schema version.")
    lifecycle_sequence: int = Field(ge=0, strict=True, description="Last lifecycle sequence reservation.")
    display_sequence: int = Field(ge=0, strict=True, description="Last display sequence reservation.")


class HerdrCliCommandDAO(HerdrDAO):
    """Private semantic argv; never carries a caller-selected executable."""

    argv: tuple[str, ...] = Field(repr=False, description="Validated pane subcommand and its arguments.")
    capture_json: bool = Field(default=False, description="Whether bounded private JSON stdout is required.")

    @field_validator("argv")
    @classmethod
    def _semantic_command(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Allow only the specified pane command inventory."""
        if (
            len(value) < 2
            or value[0] != "pane"
            or value[1] not in ("report-agent", "release-agent", "report-metadata", "split", "rename", "run")
            or any("\x00" in item for item in value)
        ):
            raise ValueError("Invalid Herdr command.")
        return value


RESTORE_UNAVAILABLE_MESSAGE = (
    "Saved Herdr restore configuration is unavailable; use ordinary --resume explicitly."
)


class HerdrRestoreUnavailableError(Exception):
    """Fixed private storage boundary failure with no raw cause text."""

    def __init__(self, message: str = RESTORE_UNAVAILABLE_MESSAGE) -> None:
        """Ignore caller text and preserve the canonical safe diagnostic.

        Args:
            message (str, optional): Compatibility input, never retained or rendered.
                Defaults to RESTORE_UNAVAILABLE_MESSAGE.
        """
        super().__init__(RESTORE_UNAVAILABLE_MESSAGE)


class HerdrRestoreStoreProtocol(Protocol):
    """Reporter-owned save consumer; load belongs exclusively to the CLI."""

    def save(self, *, config: HerdrRestoreConfigDAO) -> HerdrRestoreReferenceDAO:
        """Persist a new immutable revision off-loop without modifying history.

        Args:
            config (HerdrRestoreConfigDAO): Exact captured private policy.

        Returns:
            HerdrRestoreReferenceDAO: Confirmed durable opaque revision identity.

        Raises:
            HerdrRestoreUnavailableError: Save or cleanup cannot establish success.
        """
        ...


@runtime_checkable
class HerdrRestoreResourceOwner(Protocol):
    """Optional cleanup contract for save collaborators that own local resources."""

    @property
    def retains_external_resources(self) -> bool:
        """Report unresolved ownership after the save task has joined."""
        ...

    def close(self) -> None:
        """Drain off-loop after saves join; never abandon unresolved ownership.

        Raises:
            HerdrRestoreUnavailableError: Cleanup or operation overlap prevents
                proving release. Caller must retain this resource owner.
        """
        ...


class HerdrCommandAdmission(Protocol):
    """Synchronous one-shot authority checked under the transport lock."""

    def try_admit(self) -> bool:
        """Decide synchronously under the transport lock with no intervening await.

        Returns:
            bool: One-shot permission to register spawn, or suppression without I/O.
        """
        ...

    def complete(self, *, result: HerdrCommandResultDAO) -> None:
        """Account synchronously once before unlock, even after supersession.

        Args:
            result (HerdrCommandResultDAO): Actual admitted result including uncertain
                cancellation/failure, never another invocation's evidence.
        """
        ...


class HerdrReporterProtocol(Protocol):
    """Session-facing reporting lifetime without a concrete adapter dependency."""

    async def start(self) -> None:
        """Attempt integration-only activation for the owning session.

        Construction is inert. Real activation acquires the pane lease before
        remote work and starts producers only after confirmed withdrawal;
        repeated starts join the same attempt. Ordinary failures become an
        unavailable destination, not permission for platform fallback. Null
        reporters perform no work. The session retains final cleanup ownership.

        Raises:
            asyncio.CancelledError: Real activation joins its owned attempt and
                reporter close before propagation; final transport cleanup still
                belongs to the session.
        """
        ...

    def publish(self, *, publication: HerdrPublicationDAO) -> None:
        """Replace pending private facts synchronously without I/O.

        Args:
            publication (HerdrPublicationDAO): Frozen session facts and exact capture.

        Raises:
            ValueError: Real reporter rejects generation rollback or conflicting
                same-generation policy; null reporter discards facts without work.
        """
        ...

    async def close(self) -> HerdrReporterCloseOutcomeDAO:
        """Seal publication and join remote withdrawal before final transport close.

        Returns:
            HerdrReporterCloseOutcomeDAO: Remote/sticky-defect evidence only;
                default drained resources are not disposal permission.

        Raises:
            asyncio.CancelledError: Caller cancellation after retained work joins.
        """
        ...

    async def close_transport(self) -> HerdrReporterCloseOutcomeDAO:
        """Drain transport and leases after viewer and reporter close.

        Returns:
            HerdrReporterCloseOutcomeDAO: Final local disposal evidence with sticky
                uncertainty. Retained resources require keeping the owner reachable.

        Raises:
            asyncio.CancelledError: Caller cancellation after retained work joins.
        """
        ...

    async def drain_retained_external_resources(self) -> HerdrReporterCloseOutcomeDAO:
        """Join one retained local cleanup attempt without reopening transport.

        Returns:
            HerdrReporterCloseOutcomeDAO: Actual resource evidence, never permission
                to erase prior remote uncertainty or retry withdrawal.

        Raises:
            asyncio.CancelledError: Caller cancellation after retained work joins.
        """
        ...

    def build_visualizer(self) -> HerdrVisualizerLauncher:
        """Build the shared viewer or raise fixed HerdrRestoreUnavailableError.

        Null owners always raise; callers select the destination before invoking.

        Returns:
            HerdrVisualizerLauncher: Session-owned inert viewer on the shared transport.

        Raises:
            HerdrRestoreUnavailableError: No current viewer authority.
        """
        ...

    def revoke_viewer_admission(self) -> None:
        """Synchronously revoke viewer authority before session cleanup begins."""
        ...

    def record_publication_failure(self) -> None:
        """Record fixed diagnostics without exposing private publication inputs."""
        ...

    def allows_viewer_admission(self) -> bool:
        """Read current pane authority, never a captured Boolean."""
        ...

    @property
    def destination(self) -> HerdrDestination:
        """Return current platform, Herdr or unavailable routing."""
        ...

    @property
    def retains_external_resources(self) -> bool:
        """Report whether local cleanup still owns resources."""
        ...


if TYPE_CHECKING:
    from src.agents.slo_agent.herdr.visualizer import HerdrVisualizerLauncher
