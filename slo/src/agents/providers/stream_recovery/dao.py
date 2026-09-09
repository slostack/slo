"""Typed decisions for provider stream disconnection recovery (spec 70)."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ProviderStreamFailure",
    "ProviderStreamProgressTimeout",
    "StreamRecoveryAction",
    "StreamRecoveryDecisionDAO",
]


class StreamRecoveryAction(str, Enum):
    """Describe the action the harness may take for a provider stream failure."""

    RETRY_FRESH_CONNECTION = "retry_fresh_connection"
    DO_NOT_REPLAY = "do_not_replay"
    PROPAGATE = "propagate"


class StreamRecoveryDecisionDAO(BaseModel):
    """Immutable recovery outcome produced for one escaped provider stream error."""

    model_config = ConfigDict(frozen=True)

    action: StreamRecoveryAction = Field(description="Recovery verb for the caller.")
    reason_code: str = Field(description="Stable machine-readable cause for diagnostics.")
    retry_delay_seconds: float = Field(default=0.0, description="Backoff before a reconnect in seconds.")
    exception_family: str = Field(default="", description="Short matched exception-family name.")


class ProviderStreamProgressTimeout(TimeoutError):
    """Identify a transport-progress deadline that expired inside one provider attempt."""

    def __init__(self, *, phase: Literal["first_progress", "idle"]) -> None:
        """Create a redacted progress-timeout error for the agent attempt owner.

        Args:
            phase (Literal["first_progress", "idle"]): Deadline that expired.
        """
        super().__init__(f"provider stream {phase} timeout")
        self.phase: Literal["first_progress", "idle"] = phase


class ProviderStreamFailure(RuntimeError):
    """Carry a redacted stream recovery decision from the agent to the session."""

    def __init__(
        self,
        *,
        decision: StreamRecoveryDecisionDAO,
        partial_output_committed: bool,
        attempt_number: int,
    ) -> None:
        """Create the typed failure without retaining raw provider error content.

        Args:
            decision (StreamRecoveryDecisionDAO): Classified recovery decision.
            partial_output_committed (bool): Whether the commit boundary was crossed.
            attempt_number (int): One-indexed provider attempt that failed.
        """
        super().__init__(self._safe_message(decision=decision))
        self.decision: StreamRecoveryDecisionDAO = decision
        self.partial_output_committed: bool = partial_output_committed
        self.attempt_number: int = attempt_number

    @staticmethod
    def _safe_message(*, decision: StreamRecoveryDecisionDAO) -> str:
        """Return content-free exception text for in-process error propagation."""
        if decision.action is StreamRecoveryAction.RETRY_FRESH_CONNECTION:
            return "Provider stream disconnected before output; fresh-connection retry available."
        if decision.action is StreamRecoveryAction.DO_NOT_REPLAY:
            return "Provider stream ended after partial output; automatic replay is disabled."
        return "Provider request failed."
