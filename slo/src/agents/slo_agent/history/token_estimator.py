"""Compatibility shim — TokenEstimator moved to compaction package (sub-spec 01.a.1).

Import from ``src.agents.slo_agent.compaction.token_estimator`` instead.
"""

from src.agents.slo_agent.compaction.token_estimator import TokenEstimator

# Backward-compatible alias kept for any external callers.
TokenUsageEstimator = TokenEstimator

__all__ = ["TokenEstimator", "TokenUsageEstimator"]
