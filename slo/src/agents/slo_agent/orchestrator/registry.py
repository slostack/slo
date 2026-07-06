"""ProcessRegistry — observable lifecycle tracking for sub-agent processes.

One registry is owned by each ``SubAgentPool``. The pool and the processes it
spawns write lifecycle transitions; observers (TUI slash handler, orchestrator
progress lines, tests) read via ``snapshot()`` or ``get()``.

Sub-spec 01-sub-agents 01.c.
"""

from __future__ import annotations

from typing import Optional

from src.agents.slo_agent.orchestrator.dao import (
    SubAgentStatus,
    SubAgentStatusDAO,
    SubAgentTaskDAO,
)

__all__ = ["ProcessRegistry"]


class ProcessRegistry:
    """In-memory observable lifecycle store for all sub-agent processes.

    Keyed by ``session_id`` (the child process's stable UUID). Every sub-agent
    lifecycle transition is written here by the pool; every observer reads via
    ``snapshot()`` or ``get()``. All operations are synchronous and O(1).

    One registry instance is created per ``SubAgentPool`` (i.e., per orchestrator
    session). It resets when the session ends — there is no on-disk persistence
    in v1.
    """

    def __init__(self) -> None:
        """Initialise an empty registry."""
        self._store: dict[str, SubAgentStatusDAO] = {}

    # ── Write API (called by SubAgentPool and SubAgentProcess) ──────────────

    def register(
        self,
        *,
        task_id: str,
        session_id: str,
        task: SubAgentTaskDAO,
    ) -> None:
        """Record a new sub-agent in ``pending`` state.

        Called by ``SubAgentPool._run_one`` immediately before emitting the
        ``sub_agent_spawned`` stream event and acquiring the concurrency
        semaphore.

        Args:
            task_id (str): Caller-assigned task identifier (from the task DAO).
            session_id (str): Pre-assigned child session UUID.
            task (SubAgentTaskDAO): Full task definition; ``prompt_preview``
                is derived from ``task.prompt[:120]``.
        """
        self._store[session_id] = SubAgentStatusDAO(
            task_id=task_id,
            session_id=session_id,
            status="pending",
            prompt_preview=task.prompt[:120],
        )

    def mark_running(self, *, session_id: str) -> None:
        """Transition a sub-agent from ``pending`` to ``running``.

        Called by ``SubAgentPool._run_one`` after acquiring the concurrency
        semaphore and just before ``SubAgentProcess.run()`` is awaited.
        A no-op when ``session_id`` is not registered.

        Args:
            session_id (str): The child session to transition.
        """
        entry: Optional[SubAgentStatusDAO] = self._store.get(session_id)
        if entry is not None:
            self._store[session_id] = entry.model_copy(update={"status": "running"})

    def update_last_text(self, *, session_id: str, text: str) -> None:
        """Update the latest visible text fragment for a running sub-agent.

        Called by ``SubAgentProcess._handle_line`` on each ``text_delta`` event
        so the registry reflects what the child is actively producing. Used by
        the TUI's fleet status display and orchestrator progress lines.
        A no-op when ``session_id`` is not registered.

        Args:
            session_id (str): The child session to update.
            text (str): The latest visible text fragment from the child.
        """
        entry: Optional[SubAgentStatusDAO] = self._store.get(session_id)
        if entry is not None:
            self._store[session_id] = entry.model_copy(update={"last_text": text})

    def mark_terminal(
        self,
        *,
        session_id: str,
        status: SubAgentStatus,
        answer: str,
    ) -> None:
        """Transition a sub-agent to its terminal state.

        Called by ``SubAgentPool._run_one`` after ``SubAgentProcess.run()``
        returns and the ``SubAgentResultDAO`` is ready.
        A no-op when ``session_id`` is not registered.

        Args:
            session_id (str): The child session to transition.
            status (SubAgentStatus): Terminal status: ``completed``,
                ``failed``, or ``aborted``.
            answer (str): The child's final answer or error message.
        """
        entry: Optional[SubAgentStatusDAO] = self._store.get(session_id)
        if entry is not None:
            self._store[session_id] = entry.model_copy(
                update={"status": status, "last_text": answer}
            )

    # ── Read API (called by TUI, orchestrator, tests) ───────────────────────

    def snapshot(self) -> list[SubAgentStatusDAO]:
        """Return a point-in-time snapshot of all registered sub-agents.

        The returned list is ordered by insertion order (Python 3.7+ dict
        guarantees). Each element is a copy; mutations to the returned list
        do not affect the store.

        Returns:
            list[SubAgentStatusDAO]: One entry per registered sub-agent,
                ordered by registration time.
        """
        return list(self._store.values())

    def get(self, *, session_id: str) -> Optional[SubAgentStatusDAO]:
        """Return the status snapshot for one sub-agent by ``session_id``.

        Returns ``None`` when the session id is not registered.

        Args:
            session_id (str): The child session to look up.

        Returns:
            Optional[SubAgentStatusDAO]: The snapshot, or ``None``.
        """
        return self._store.get(session_id)

    @property
    def count(self) -> int:
        """Return the total number of registered sub-agents across all statuses.

        Returns:
            int: Total registered count.
        """
        return len(self._store)

    @property
    def running_count(self) -> int:
        """Return the number of sub-agents currently in ``running`` state.

        Returns:
            int: Count of sub-agents whose status is ``running``.
        """
        return sum(1 for entry in self._store.values() if entry.status == "running")
