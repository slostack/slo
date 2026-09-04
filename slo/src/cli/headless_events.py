"""DAO and emission helpers for headless lifecycle events on stderr.

In headless mode the stdout channel is reserved exclusively for
``AgentStreamEventDAO`` JSONL records.  All diagnostic traffic — session
startup, warnings, status pings, completion/failure notices — is written to
**stderr** as ``HeadlessLifecycleEventDAO`` JSONL so that parent orchestrators
and capture pipelines can separate data from diagnostics without parsing
heuristics.

Kind vocabulary:

  headless_session_started          — session boot, before first LLM turn
  headless_session_resolved         — session id confirmed after history lookup
  headless_orchestrator_attached    — sub-agent pool ready (orchestrator mode)
  headless_status                   — periodic in-progress ping
  headless_warning                  — non-fatal advisory
  headless_run_completed            — agent loop finished, exit 0
  headless_run_failed               — agent loop terminated with error, exit 1
  headless_run_aborted              — operator interrupted or budget exhausted, exit 2
  headless_child_stderr             — forwarded line from a child process's stderr
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "HeadlessLifecycleEventDAO",
    "LifecycleKind",
    "emit_lifecycle_event",
]

_LIFECYCLE_WRITE_LOCK: threading.Lock = threading.Lock()
"""Serialize stderr lifecycle writes across the event loop and watchdog thread."""


LifecycleKind = Literal[
    "headless_session_started",
    "headless_session_resolved",
    "headless_orchestrator_attached",
    "headless_status",
    "headless_warning",
    "headless_run_completed",
    "headless_run_failed",
    "headless_run_aborted",
    "headless_child_stderr",
]


class HeadlessLifecycleEventDAO(BaseModel):
    """A single lifecycle event emitted to stderr during a headless run.

    Fields are intentionally minimal — callers place additional context in
    *payload*.  The *session_id* is attached to every event so consumers
    can correlate events from multiple concurrent children.
    """

    model_config = ConfigDict(frozen=True)

    kind: LifecycleKind
    session_id: Optional[str] = None
    message: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp_utc: str = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )


def emit_lifecycle_event(
    *,
    kind: LifecycleKind,
    session_id: Optional[str] = None,
    message: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    """Serialise and write one lifecycle event as JSONL to *stderr*.

    The line is written with a trailing newline and immediately flushed so
    that parent processes reading the child's stderr pipe receive it without
    buffering delay. Thread-safe: concurrent callers serialize complete JSONL
    records before writing.

    Args:
        kind (LifecycleKind): Event kind from the controlled vocabulary.
        session_id (Optional[str]): The current session identifier.  Defaults
            to ``None`` when the session id is not yet resolved.
        message (Optional[str]): Human-readable summary of the event.  ``None``
            for events where the kind alone is sufficient.
        payload (Optional[dict[str, Any]]): Arbitrary key/value pairs for
            structured fields beyond the core DAO schema.  Defaults to an
            empty dict.
    """
    event: HeadlessLifecycleEventDAO = HeadlessLifecycleEventDAO(
        kind=kind,
        session_id=session_id,
        message=message,
        payload=payload or {},
    )
    with _LIFECYCLE_WRITE_LOCK:
        sys.stderr.write(event.model_dump_json() + "\n")
        sys.stderr.flush()
