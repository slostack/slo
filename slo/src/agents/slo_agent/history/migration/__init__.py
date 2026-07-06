"""Migration utilities for slo session history.

Provides two migration classes:

- ``TokenUsageBackfiller`` — back-fills ``payload.token_usage`` for events
  that pre-date the 01.a.1 DAO extension.
- ``TreeMigrator`` — converts flat JSONL sessions to tree-format sessions
  expected by ``TreeBasedFilesystemSessionHistoryStore``.
"""

from src.agents.slo_agent.history.migration.token_usage_backfiller import (
    TokenUsageBackfiller,
)
from src.agents.slo_agent.history.migration.tree_migrator import (
    MigrationResult,
    TreeMigrator,
)

__all__ = [
    "TokenUsageBackfiller",
    "TreeMigrator",
    "MigrationResult",
]
