"""``CompactionChecker`` — stateless compaction-trigger decision (sub-spec 01.a.6).

Answers one question: given the current event log and the active model,
is it time to compact? The check is a pure local computation — no LLM
call, no I/O. All cost comes from summing a list.

Per-model context windows are read from the canonical model registry
(``config.ai_model_config.MODEL_DEFAULTS``) so the compaction trigger never
drifts from the rest of the harness. There is no second model table here.
"""

from __future__ import annotations

from typing import Optional

from config.ai_model_config import MODEL_DEFAULTS, ModelDefaults
from src.agents.slo_agent.compaction.constants import RESERVED_TOKEN_LIMIT
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO

__all__ = ["CompactionChecker"]


_DEFAULT_CONTEXT_WINDOW: int = 200_000
"""Conservative fallback for models absent from ``MODEL_DEFAULTS`` (or listed
without an explicit ``context_window``).

200_000 matches every current Claude / o-series model. Models with a SMALLER
real window (e.g. ``gpt-4o`` at 128k) must be listed in ``MODEL_DEFAULTS`` so
they are never over-estimated — over-estimating delays compaction past the
provider's hard cap and triggers a context-overflow error.
"""


def _get_context_window(*, model_name: str) -> int:
    """Return the input context-window token limit for ``model_name``.

    Sourced from ``config.ai_model_config.MODEL_DEFAULTS`` — the single
    source of truth for per-model configuration — so the compaction trigger
    always agrees with the factory and rate policy on each model's window.

    Args:
        model_name (str): Model identifier as used by the session
            configuration (e.g. ``"gpt-5.4"``, ``"claude-sonnet-4-6"``).

    Returns:
        int: Context-window size in tokens. Falls back to
            ``_DEFAULT_CONTEXT_WINDOW`` (200 000) when the model is unlisted
            or carries no explicit ``context_window``.
    """
    defaults: Optional[ModelDefaults] = MODEL_DEFAULTS.get(model_name)
    if defaults is None:
        return _DEFAULT_CONTEXT_WINDOW
    return defaults.get("context_window", _DEFAULT_CONTEXT_WINDOW)


class CompactionChecker:
    """Stateless service that decides whether compaction should run.

    All logic is encapsulated in the ``should_compact`` classmethod.
    The class carries no instance state and is never instantiated.
    """

    @classmethod
    async def should_compact(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
        model_name: str,
        context_window: Optional[int] = None,
    ) -> bool:
        """Return ``True`` when the event log has crossed the compaction threshold.

        Sums ``event.payload.token_usage`` across all events (treating
        ``None`` as ``0``), resolves the effective context window for
        ``model_name``, and compares the total against
        ``context_window - RESERVED_TOKEN_LIMIT``.

        Args:
            events (list[SessionHistoryEventDAO]): Full event log for the
                session, as returned by the history store.
            model_name (str): Active model identifier. Used to look up the
                context-window size when ``context_window`` is not supplied.
            context_window (Optional[int]): Override the model-table lookup.
                Pass an explicit value in tests or when the caller already
                knows the window size. Defaults to ``None`` (use the table).

        Returns:
            bool: ``True`` when total token usage exceeds the threshold
                and the compaction pipeline should be invoked.
        """
        total_tokens: int = sum(
            event.payload.token_usage or 0 for event in events
        )

        effective_window: int = (
            context_window
            if context_window is not None
            else _get_context_window(model_name=model_name)
        )

        threshold: int = effective_window - RESERVED_TOKEN_LIMIT

        return total_tokens > threshold
