"""Recovery taxonomy DAOs for LLM-driven error recovery (Feature 50)."""

from __future__ import annotations

from enum import auto, Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "RecoveryClass",
    "RecoveryDecisionDAO",
]


class RecoveryClass(Enum):
    """How the ReAct loop should treat one escaped iteration exception.

    Members:
        MECHANICAL: Owned by the rate-limit / route-switch / overflow layers;
            recovery treats it as terminal rather than re-handling it.
        LLM_RECOVERABLE: Demote into a recovery observation and let the model try.
        FATAL: Never recover (abort, all-models-exhausted, credential/config error).
    """

    MECHANICAL = auto()
    LLM_RECOVERABLE = auto()
    FATAL = auto()


class RecoveryDecisionDAO(BaseModel):
    """Resolved recovery decision for one escaped iteration exception."""

    model_config = ConfigDict(frozen=True)

    recovery_class: RecoveryClass = Field(description="How the loop should treat the error.")
    reason: str = Field(description="Operator-facing one-line explanation of the classification.")
    observation_hint: Optional[str] = Field(
        default=None,
        description="Optional extra sentence appended to the recovery observation.",
    )
