"""ChildDirectory — the children an orchestrator may message, by task id (108.4).

Inside a dispatch the ``send_message`` tool accepts a child's ``task_id`` as an
alias for its session id. This module owns that mapping and each child's
messaging liveness, derived from the pool's ``ProcessRegistry``; it never
stores state of its own.
"""

from __future__ import annotations

from uuid import UUID

from src.agents.slo_agent.channel_delivery.poller import (
    channel_participant_id_for_session,
)
from src.agents.slo_agent.orchestrator.dao import (
    TERMINAL_STATUSES,
    ChildDirectoryEntryDAO,
    ChildDirectoryState,
    SubAgentStatusDAO,
)
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry

__all__ = ["ChildDirectory"]


class ChildDirectory:
    """Read-only projection of one pool's registry into addressable children.

    Promises:
        - One entry per ``task_id``, so a task-id alias is never ambiguous.
          When several children share a task id, a running child wins over a
          finished one; otherwise the later-registered child wins.
        - Entries keep registry (registration) order.
        - ``session_id`` is the child's channel participant id, the same id
          the child registers under (``channel_participant_id_for_session``).
        - ``running`` covers pending and running children; ``finished`` means
          the incarnation is terminal (completed, failed or aborted).
    """

    def __init__(self, *, registry: ProcessRegistry) -> None:
        """Bind the directory to the pool-owned registry it projects.

        Args:
            registry (ProcessRegistry): The pool's live process registry.
        """
        self._registry: ProcessRegistry = registry

    def entries(self) -> list[ChildDirectoryEntryDAO]:
        """Return the addressable children of the pool, one per task id.

        WHAT: Projects the registry snapshot and collapses repeated task ids
            under the rules in the class docstring.
        WHO: ``SubAgentPool.child_directory`` for the messaging policy.
        WHEN: On demand, e.g. on every ``send_message`` call; no side effects.

        Returns:
            list[ChildDirectoryEntryDAO]: Children in registration order.
        """
        chosen_by_task_id: dict[str, tuple[int, ChildDirectoryEntryDAO]] = {}
        for position, status in enumerate(self._registry.snapshot()):
            entry: ChildDirectoryEntryDAO = self._entry_for(status=status)
            current: tuple[int, ChildDirectoryEntryDAO] | None = chosen_by_task_id.get(entry.task_id)
            if current is None or self._replaces(candidate=entry, current=current[1]):
                chosen_by_task_id[entry.task_id] = (position, entry)
        return [entry for _, entry in sorted(chosen_by_task_id.values(), key=lambda chosen: chosen[0])]

    @staticmethod
    def _entry_for(*, status: SubAgentStatusDAO) -> ChildDirectoryEntryDAO:
        """Build the directory entry for one registry status row."""
        state: ChildDirectoryState = "finished" if status.status in TERMINAL_STATUSES else "running"
        participant_id: UUID = channel_participant_id_for_session(session_id=status.session_id)
        return ChildDirectoryEntryDAO(task_id=status.task_id, session_id=participant_id, state=state)

    @staticmethod
    def _replaces(*, candidate: ChildDirectoryEntryDAO, current: ChildDirectoryEntryDAO) -> bool:
        """Return whether a later-registered child takes over a shared task id.

        Args:
            candidate (ChildDirectoryEntryDAO): Later-registered child.
            current (ChildDirectoryEntryDAO): Child currently holding the task id.

        Returns:
            bool: False only when the current child runs and the candidate finished.
        """
        return not (current.state == "running" and candidate.state == "finished")
