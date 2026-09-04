"""ProcessRegistry — observable lifecycle tracking for sub-agent processes.

The registry is the in-memory write authority. A bound FleetStore mirrors its
lifecycle transitions to durable fleet evidence.

Sub-spec 71.a.2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from src.agents.slo_agent.orchestrator.dao import (
    SubAgentStatus,
    SubAgentStatusDAO,
    SubAgentTaskDAO,
    TerminalReason,
    TerminatedBy,
    terminal_reason_for_status,
)

if TYPE_CHECKING:
    from src.agents.slo_agent.orchestrator.fleet_store import FleetStore

__all__ = ["ProcessRegistry"]


class ProcessRegistry:
    """In-memory lifecycle authority for one pool, optionally mirrored to fleet.json."""

    def __init__(self, *, fleet_store: Optional["FleetStore"] = None) -> None:
        """Initialize an empty registry with an optional durable projection.

        WHAT: Creates the pool-owned lifecycle authority and retains its mirror.
        WHO: Called by SubAgentPool once per orchestrator session.
        WHEN: Before the pool accepts its first child task.

        Args:
            fleet_store (Optional[FleetStore]): Durable projection target; None keeps
                direct callers in legacy in-memory-only mode.
        """
        self._store: dict[str, SubAgentStatusDAO] = {}
        self._fleet_store: Optional[FleetStore] = fleet_store

    def register(self, *, task_id: str, session_id: str, task: SubAgentTaskDAO) -> None:
        """Register a pending child and persist its fleet transition.

        WHAT: Builds the initial fleet entry from the task identity and preview.
        WHO: Called by SubAgentPool before it emits a spawned event.
        WHEN: Once for every accepted child task.

        Args:
            task_id (str): Caller-assigned child task identifier.
            session_id (str): Pool-assigned child session identifier.
            task (SubAgentTaskDAO): Child task that supplies the prompt preview.
        """
        self._store[session_id] = SubAgentStatusDAO(
            task_id=task_id,
            session_id=session_id,
            status="pending",
            prompt_preview=task.prompt[:120],
        )
        self._persist()

    def mark_running(self, *, session_id: str, pid: int = 0, started_at: float = 0.0) -> None:
        """Record a spawned child process identity and persist its running transition.

        WHAT: Moves a registered entry to running with its pid and spawn time.
        WHO: Called by SubAgentProcess immediately after child subprocess creation.
        WHEN: Once after a successful spawn; legacy direct callers retain zero defaults.

        Args:
            session_id (str): Registered child session identifier.
            pid (int): Spawned process id. Defaults to 0 for legacy direct callers.
            started_at (float): Wall-clock spawn time. Defaults to 0.0 for legacy callers.
        """
        entry: Optional[SubAgentStatusDAO] = self._store.get(session_id)
        if entry is None:
            return
        self._store[session_id] = entry.model_copy(
            update={"status": "running", "pid": pid, "started_at": started_at}
        )
        self._persist()

    def record_heartbeat(self, *, session_id: str, phase: str, at_seconds: float) -> None:
        """Record accepted heartbeat telemetry without a high-frequency durable write.

        WHAT: Updates the latest heartbeat time and phase in memory.
        WHO: Called by SubAgentProcess after it accepts same-session stderr telemetry.
        WHEN: On each recognized headless_status event.

        Args:
            session_id (str): Registered child session identifier.
            phase (str): Latest heartbeat phase label.
            at_seconds (float): Monotonic telemetry receipt time.
        """
        entry: Optional[SubAgentStatusDAO] = self._store.get(session_id)
        if entry is None:
            return
        self._store[session_id] = entry.model_copy(
            update={"last_heartbeat_at": at_seconds, "heartbeat_phase": phase}
        )

    def record_stdout(self, *, session_id: str, at_seconds: float) -> None:
        """Record stdout receipt telemetry without a high-frequency durable write.

        WHAT: Updates the latest stdout time in memory.
        WHO: Called by SubAgentProcess before it parses a stdout line.
        WHEN: Once for every non-empty child stdout line.

        Args:
            session_id (str): Registered child session identifier.
            at_seconds (float): Monotonic stdout receipt time.
        """
        entry: Optional[SubAgentStatusDAO] = self._store.get(session_id)
        if entry is None:
            return
        self._store[session_id] = entry.model_copy(update={"last_stdout_at": at_seconds})

    def update_last_text(self, *, session_id: str, text: str) -> None:
        """Update the latest visible child text without a high-frequency durable write.

        WHAT: Retains the most recent text_delta in the in-memory fleet entry.
        WHO: Called by SubAgentProcess while relaying parsed child stdout.
        WHEN: On each visible text delta.

        Args:
            session_id (str): Registered child session identifier.
            text (str): Latest visible child text fragment.
        """
        entry: Optional[SubAgentStatusDAO] = self._store.get(session_id)
        if entry is None:
            return
        self._store[session_id] = entry.model_copy(update={"last_text": text})

    def mark_terminal(
        self,
        *,
        session_id: str,
        status: SubAgentStatus,
        answer: str,
        exit_code: int = -1,
        terminal_reason: Optional[TerminalReason] = None,
        terminated_by: Optional[TerminatedBy] = None,
    ) -> None:
        """Record terminal child evidence and persist the fleet transition.

        WHAT: Stores terminal status, answer, exit code, and cleanup ownership.
        WHO: Called by SubAgentPool after the process wrapper returns a result.
        WHEN: Once for every child that reaches a terminal state.

        Args:
            session_id (str): Registered child session identifier.
            status (SubAgentStatus): Completed, failed, or aborted terminal status.
            answer (str): Final answer or redacted failure message.
            exit_code (int): Child process exit code. Defaults to -1 for legacy callers.
            terminal_reason (Optional[TerminalReason]): Ending reason; inferred when absent.
            terminated_by (Optional[TerminatedBy]): Reaper identity; None for legacy callers.
        """
        entry: Optional[SubAgentStatusDAO] = self._store.get(session_id)
        if entry is None:
            return
        if entry.status in {"completed", "failed", "aborted"}:
            return
        resolved_reason: TerminalReason = terminal_reason or terminal_reason_for_status(status=status)  # type: ignore[assignment]
        self._store[session_id] = entry.model_copy(
            update={
                "status": status,
                "last_text": answer,
                "exit_code": exit_code,
                "terminal_reason": resolved_reason,
                "terminated_by": terminated_by,
            }
        )
        self._persist()

    def _persist(self) -> None:
        """Mirror the current registry snapshot when a fleet store is bound.

        WHAT: Sends one complete ordered snapshot to the optional durable projection.
        WHO: Called by lifecycle transition methods after their memory update.
        WHEN: Never for high-frequency stdout, heartbeat, or text updates.
        """
        if self._fleet_store is None:
            return
        self._fleet_store.persist(entries=self.snapshot())

    def snapshot(self) -> list[SubAgentStatusDAO]:
        """Return registered fleet entries in registration order.

        WHAT: Provides a point-in-time projection of the in-memory registry.
        WHO: Called by fleet persistence and observer surfaces.
        WHEN: After lifecycle updates and while readers render fleet state.

        Returns:
            list[SubAgentStatusDAO]: Current entries in registration order.
        """
        return list(self._store.values())

    def get(self, *, session_id: str) -> Optional[SubAgentStatusDAO]:
        """Return one fleet entry when the session is registered.

        WHAT: Looks up a child entry without mutating the registry.
        WHO: Called by tests and observer surfaces.
        WHEN: While resolving one child status.

        Args:
            session_id (str): Child session identifier to look up.

        Returns:
            Optional[SubAgentStatusDAO]: Matching entry, or None when unknown.
        """
        return self._store.get(session_id)

    @property
    def count(self) -> int:
        """Return the total number of registered fleet entries."""
        return len(self._store)

    @property
    def running_count(self) -> int:
        """Return the number of entries currently marked running."""
        return sum(1 for entry in self._store.values() if entry.status == "running")
