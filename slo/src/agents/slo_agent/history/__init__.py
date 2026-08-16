"""Persistent session history package (sub-spec 05.a).

Exposes the canonical persisted-history DAOs, the filesystem-backed
session store, the message-history projector, and the transcript
projector. The store is the only writer; projectors are pure
read-side transformations from canonical events.
"""

from __future__ import annotations

from src.agents.slo_agent.history.dao import (
    HistoryEventKind,
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
    SessionHistoryMetadataDAO,
)
from src.agents.slo_agent.history.filesystem_store import (
    FilesystemSessionHistoryStore,
    HistoryCompactionRecoveryError,
)
from src.agents.slo_agent.history.store_protocol import (
    SessionHistoryStoreProtocol,
)
from src.agents.slo_agent.history.tree_store import (
    TreeBasedFilesystemSessionHistoryStore,
)
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.history.transcript import (
    ReplayEntryProjector,
    TranscriptEntryDAO,
    TranscriptEntryKind,
)

__all__ = [
    "HistoryEventKind",
    "SessionHistoryEventDAO",
    "SessionHistoryEventPayloadDAO",
    "SessionHistoryMetadataDAO",
    "FilesystemSessionHistoryStore",
    "HistoryCompactionRecoveryError",
    "SessionHistoryStoreProtocol",
    "TreeBasedFilesystemSessionHistoryStore",
    "SessionHistoryProjector",
    "ReplayEntryProjector",
    "TranscriptEntryDAO",
    "TranscriptEntryKind",
]
