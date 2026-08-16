"""Session-owned runtime usage status for the Slo TUI — sessions/usage.py.

Canonical location for ``TokenUsageTotalsDAO`` and ``SessionUsageSnapshotDAO``.
Moved from the top-level ``session_usage_dao.py`` as part of the sessions/
submodule (spec 04).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.agents.slo_agent.compaction.context_window import ContextWindowSnapshotDAO

__all__ = [
    "SessionUsageSnapshotDAO",
    "TokenUsageTotalsDAO",
]


class TokenUsageTotalsDAO(BaseModel):
    """Known token totals for one turn or one session."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cache_creation_input_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None

    def add(self, *, other: "TokenUsageTotalsDAO") -> "TokenUsageTotalsDAO":
        """Return a new totals object with ``other`` added in.

        Args:
            other (TokenUsageTotalsDAO): Another totals record.

        Returns:
            TokenUsageTotalsDAO: Summed totals where values are known.
        """
        return TokenUsageTotalsDAO(
            input_tokens=self._sum_known_values(left=self.input_tokens, right=other.input_tokens),
            output_tokens=self._sum_known_values(left=self.output_tokens, right=other.output_tokens),
            total_tokens=self._sum_known_values(left=self.total_tokens, right=other.total_tokens),
            cache_creation_input_tokens=self._sum_known_values(
                left=self.cache_creation_input_tokens,
                right=other.cache_creation_input_tokens,
            ),
            cache_read_input_tokens=self._sum_known_values(
                left=self.cache_read_input_tokens,
                right=other.cache_read_input_tokens,
            ),
        )

    @staticmethod
    def _sum_known_values(*, left: Optional[int], right: Optional[int]) -> Optional[int]:
        """Return the sum of known values, or ``None`` when both are unknown.

        Args:
            left (Optional[int]): Left operand.
            right (Optional[int]): Right operand.

        Returns:
            Optional[int]: Summed value or ``None``.
        """
        if left is None and right is None:
            return None
        return (left or 0) + (right or 0)


class SessionUsageSnapshotDAO(BaseModel):
    """TUI-facing usage and limit status for the active session."""

    model_config = ConfigDict(extra="forbid")

    active_model_name: str
    active_reasoning_level: str
    provider_effort: Optional[str] = None
    provider_budget_tokens: Optional[int] = None
    output_cap_tokens: Optional[int] = None
    requests_per_minute_limit: Optional[int] = None
    tokens_per_minute_limit: Optional[int] = None
    cooldown_seconds_remaining: Optional[int] = None
    latest_turn: TokenUsageTotalsDAO = Field(default_factory=TokenUsageTotalsDAO)
    session_totals: TokenUsageTotalsDAO = Field(default_factory=TokenUsageTotalsDAO)
    usage_available: bool = False
    context_window_snapshot: Optional[ContextWindowSnapshotDAO] = None
