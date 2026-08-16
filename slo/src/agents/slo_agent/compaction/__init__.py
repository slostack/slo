"""Compaction package for session history (sub-spec 01.a).

Contains ``TokenEstimator`` and the compaction pipeline components
that derive context-window size from the event log and prune history
when the window is near capacity.

Pipeline (Checker → Compacter → Updater):

- ``CompactionChecker`` — decides *whether* to compact (pure local sum).
- ``Compacter`` — decides *where* to cut and produces the LLM summary,
  returning a ``CompactionResult``.
- ``CompactedSessionUpdater`` — persists the ``CompactionResult`` as a
  ``compaction_summary`` event via the store.

``TokenEstimator`` stamps per-event token estimates the checker reads.
``KEEP_RECENT_TOKENS`` / ``RESERVED_TOKEN_LIMIT`` govern the budget.
"""

from src.agents.slo_agent.compaction.token_estimator import TokenEstimator
from src.agents.slo_agent.compaction.constants import (
    DEFAULT_CONTEXT_WINDOW,
    KEEP_RECENT_TOKENS,
    RESERVED_TOKEN_LIMIT,
)
from src.agents.slo_agent.compaction.compaction_checker import CompactionChecker
from src.agents.slo_agent.compaction.compacter import Compacter, CompactionResult
from src.agents.slo_agent.compaction.compacted_session_updater import (
    CompactedSessionUpdater,
)
from src.agents.slo_agent.compaction.context_window import (
    ContextWindowSnapshotDAO,
    ContextWindowSnapshotService,
)

__all__ = [
    "TokenEstimator",
    "DEFAULT_CONTEXT_WINDOW",
    "KEEP_RECENT_TOKENS",
    "RESERVED_TOKEN_LIMIT",
    "CompactionChecker",
    "Compacter",
    "CompactionResult",
    "CompactedSessionUpdater",
    "ContextWindowSnapshotDAO",
    "ContextWindowSnapshotService",
]
