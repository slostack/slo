"""``CompactionChecker`` — stateless compaction-trigger decision (sub-spec 01.a.6).

Answers one question: given the current event log and the active model,
is it time to compact? The check is a pure local computation — no LLM
call, no I/O. All cost comes from summing a list.

Per-model context windows resolve through ``ModelCatalogService`` first,
including canonical names, aliases, and discovered models. The legacy
``MODEL_DEFAULTS`` mapping remains only as a compatibility fallback, so the
compaction trigger stays aligned with the rest of the harness.
"""

from __future__ import annotations

from typing import Optional

from config.ai_model_config import MODEL_DEFAULTS, ModelDefaults
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.slo_agent.compaction.constants import DEFAULT_CONTEXT_WINDOW
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO

__all__ = ["CompactionChecker"]


def _get_context_window(*, model_name: str) -> int:
    """Return the input context-window token limit for ``model_name``.

    Resolved from ``ModelCatalogService`` first, including aliases and
    discovered models, then from legacy ``MODEL_DEFAULTS`` for compatibility.
    This keeps the compaction trigger aligned with the routed model catalog.

    Args:
        model_name (str): Model identifier as used by the session
            configuration (e.g. ``"gpt-5.4"``, ``"claude-sonnet-4-6"``).

    Returns:
        int: Context-window size in tokens. Falls back to
            ``DEFAULT_CONTEXT_WINDOW`` when the model is unlisted
            or carries no explicit ``context_window``.
    """
    try:
        entry = ModelCatalogService.entry_for_model(model_name=model_name)
    except ValueError:
        entry = None
    if entry is not None:
        return entry.runtime_profile.context_window
    defaults: Optional[ModelDefaults] = MODEL_DEFAULTS.get(model_name)
    if defaults is None:
        return DEFAULT_CONTEXT_WINDOW
    return defaults.get("context_window", DEFAULT_CONTEXT_WINDOW)


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
            context_window (Optional[int]): Override catalog resolution. Pass
                an explicit value in tests or when the caller already knows
                the window size. Defaults to ``None`` (resolve the catalog).

        Returns:
            bool: ``True`` when total token usage exceeds the threshold
                and the compaction pipeline should be invoked.
        """
        total_tokens: int = sum(event.payload.token_usage or 0 for event in events)

        effective_window: int = (
            context_window if context_window is not None else _get_context_window(model_name=model_name)
        )

        threshold: int = int(effective_window * 0.70)

        return total_tokens >= threshold
