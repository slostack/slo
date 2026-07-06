"""Shared numeric constants for the slo auto-compaction pipeline.

These values govern when compaction triggers (``RESERVED_TOKEN_LIMIT``)
and how many tokens of recent conversation are preserved verbatim after
compaction (``KEEP_RECENT_TOKENS``).
"""

from __future__ import annotations

__all__ = [
    "COMPACTION_INPUT_SAFETY_DIVISOR",
    "KEEP_RECENT_TOKENS",
    "RESERVED_TOKEN_LIMIT",
]

RESERVED_TOKEN_LIMIT: int = 16_384
"""Tokens withheld from the compaction threshold.

When ``total_tokens > context_window - RESERVED_TOKEN_LIMIT`` the
compaction pipeline fires. The reserved headroom ensures the compaction
turn itself — which sends history to the model for summarisation — does
not immediately violate the context window.
"""

COMPACTION_INPUT_SAFETY_DIVISOR: int = 3
"""Divisor applied to the model context window to compute the safe compaction input budget.

When the compaction LLM call is built, the estimated token count (chars/4) for
tool outputs and code-heavy content underestimates the real token count by up to
3×. Dividing the context window by this factor before capping the compaction
input ensures the summarisation call never itself overflows the model.

For a 1M-context model: cap ≈ (1_050_000 − 16_384) / 3 ≈ 344_538 token-units.
For a 200k-context model: cap ≈ (200_000 − 16_384) / 3 ≈  61_205 token-units.
"""

KEEP_RECENT_TOKENS: int = 20_000
"""Token budget for the verbatim tail preserved after compaction.

The ``Compacter`` walks events newest-to-oldest, accumulating token
usage until this budget is exhausted. Everything beyond the cut point
is replaced by the compaction summary. Value chosen so one full
back-and-forth coding exchange (user + large tool output + assistant)
is always kept verbatim.
"""
