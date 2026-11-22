"""MessagingPolicy — who may message whom through ``send_message`` (108.4 §2).

The allowed edges are:

```text
 S (TUI agent) ──► the workflows it launched
 W (orchestrator) ──► its own children (by task_id alias or session id)
 C (child) ──► its parent ('parent')
```

Every other target (siblings, grandparents, unrelated sessions, self) is
refused. The policy also owns the delivery defaults. A prompt to a child is
forced by default, because children have no follow-up turns. A child's message
to its parent is a ``note`` by default. A note is never forced.

The policy is pure and in-memory. The child directory and the
launched-workflow list are callables read on every decision, so a child spawned
after the policy was built can be reached at once. Users messaging through a
channel do not go through this policy (any open agent is reachable for them).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.agents.slo_agent.orchestrator.dao import ChildDirectoryEntryDAO

__all__ = [
    "PARENT_ALIAS",
    "AddressStatus",
    "MessageAddressDAO",
    "MessageKind",
    "MessagingPolicy",
]

PARENT_ALIAS: str = "parent"
"""The ``to`` value a child uses to address its parent orchestrator."""

MessageKind = Literal["prompt", "note"]
"""Message types an agent may send with ``send_message`` (overview §3.2)."""

AddressStatus = Literal["allowed", "not_allowed", "recipient_closed"]
"""Outcome of addressing one target under the policy."""


class MessageAddressDAO(BaseModel):
    """The policy's decision for one ``send_message`` target."""

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    status: AddressStatus = Field(
        description="'allowed' when the edge exists and the recipient may receive; otherwise why not."
    )
    recipient_id: Optional[UUID] = Field(
        default=None,
        description="Resolved recipient participant id; None when the target is not allowed.",
    )
    message_type: MessageKind = Field(description="Message type to store after applying the defaults.")
    force: bool = Field(description="Whether the message is forced into the recipient's current run.")


class MessagingPolicy:
    """Decides which recipients one agent session may message, and how (108.4 §2)."""

    def __init__(
        self,
        *,
        self_id: UUID,
        parent_id: Optional[UUID],
        children: Callable[[], list[ChildDirectoryEntryDAO]],
        launched_workflows: Callable[[], list[UUID]],
    ) -> None:
        """Bind the policy to one sender and its live relations.

        Args:
            self_id (UUID): Participant id of the sending agent session.
            parent_id (Optional[UUID]): Parent orchestrator session id
                (``SLO_CHANNEL_PARENT_ID``); ``None`` for non-children.
            children (Callable[[], list[ChildDirectoryEntryDAO]]): Live child
                directory of this session (``SubAgentPool.child_directory``).
            launched_workflows (Callable[[], list[UUID]]): Orchestrator session
                ids this session launched with ``launch_workflow``.
        """
        self._self_id: UUID = self_id
        self._parent_id: Optional[UUID] = parent_id
        self._children: Callable[[], list[ChildDirectoryEntryDAO]] = children
        self._launched_workflows: Callable[[], list[UUID]] = launched_workflows

    def ensure_sender(self, *, sender_id: UUID) -> None:
        """Reject a sender identity other than the one this policy was built for.

        Args:
            sender_id (UUID): Identity a caller intends to send as.

        Raises:
            ValueError: ``sender_id`` is not this policy's ``self_id``.
        """
        if sender_id != self._self_id:
            raise ValueError(f"MessagingPolicy for {self._self_id} cannot send as {sender_id}")

    def resolve(self, *, to: str) -> Optional[UUID]:
        """Resolve a ``to`` value to an allowed recipient id.

        ``'parent'`` addresses the parent. A child ``task_id`` is an alias for
        that child's session id. Any other value must be the session id of the
        parent, a child, or a launched workflow.

        Args:
            to (str): ``'parent'``, a child task id, or an agent session id.

        Returns:
            Optional[UUID]: The recipient id, or ``None`` when the target is
                unknown or not an allowed edge.
        """
        target: str = to.strip()
        if target == PARENT_ALIAS:
            return self._parent_id
        child: Optional[ChildDirectoryEntryDAO] = self._child_by_task_id(task_id=target)
        if child is not None:
            return child.session_id
        return self._allowed_session_id(target=target)

    def address(self, *, to: str, kind: Optional[MessageKind], force: Optional[bool]) -> MessageAddressDAO:
        """Decide whether and how one message to ``to`` is delivered.

        Args:
            to (str): ``'parent'``, a child task id, or an agent session id.
            kind (Optional[MessageKind]): Requested type; ``None`` means
                ``note`` towards the parent and ``prompt`` otherwise.
            force (Optional[bool]): Requested forcing; ``None`` means forced
                for a child recipient and normal otherwise. Notes are never
                forced (overview §3.2).

        Returns:
            MessageAddressDAO: ``not_allowed`` for a refused edge,
                ``recipient_closed`` for a finished child, else ``allowed``
                with the resolved recipient and effective type and forcing.
        """
        recipient_id: Optional[UUID] = self.resolve(to=to)
        message_type: MessageKind = kind or self._default_kind(recipient_id=recipient_id)
        if recipient_id is None:
            return MessageAddressDAO(status="not_allowed", message_type=message_type, force=False)
        child: Optional[ChildDirectoryEntryDAO] = self._child_by_session_id(session_id=recipient_id)
        status: AddressStatus = (
            "recipient_closed" if child is not None and child.state == "finished" else "allowed"
        )
        return MessageAddressDAO(
            status=status,
            recipient_id=recipient_id,
            message_type=message_type,
            force=message_type == "prompt" and (force if force is not None else child is not None),
        )

    def _default_kind(self, *, recipient_id: Optional[UUID]) -> MessageKind:
        """Return ``note`` for a child messaging its parent, else ``prompt``.

        Args:
            recipient_id (Optional[UUID]): The resolved recipient, if any.

        Returns:
            MessageKind: The default message type.
        """
        is_to_parent: bool = recipient_id is not None and recipient_id == self._parent_id
        return "note" if is_to_parent else "prompt"

    def _allowed_session_id(self, *, target: str) -> Optional[UUID]:
        """Return ``target`` as a session id when it names an allowed recipient.

        Args:
            target (str): Candidate session id text.

        Returns:
            Optional[UUID]: The id when it is the parent, a child or a launched
                workflow; ``None`` for anything else, including self.
        """
        try:
            session_id: UUID = UUID(target)
        except ValueError:
            return None
        allowed: set[UUID] = {child.session_id for child in self._children()} | set(
            self._launched_workflows()
        )
        if self._parent_id is not None:
            allowed.add(self._parent_id)
        allowed.discard(self._self_id)
        return session_id if session_id in allowed else None

    def _child_by_task_id(self, *, task_id: str) -> Optional[ChildDirectoryEntryDAO]:
        """Return the child whose task id is ``task_id``, preferring a running one.

        A retried child keeps its task id under a new session id (108.4 §6),
        so the alias addresses the running attempt rather than the closed one.

        Args:
            task_id (str): Task id alias.

        Returns:
            Optional[ChildDirectoryEntryDAO]: The running match, else the
                newest match, else ``None``.
        """
        matches: list[ChildDirectoryEntryDAO] = [
            child for child in self._children() if child.task_id == task_id
        ]
        running: Optional[ChildDirectoryEntryDAO] = next(
            (child for child in matches if child.state == "running"), None
        )
        return running or (matches[-1] if matches else None)

    def _child_by_session_id(self, *, session_id: UUID) -> Optional[ChildDirectoryEntryDAO]:
        """Return the child whose session id is ``session_id``, if any.

        Args:
            session_id (UUID): Child session id.

        Returns:
            Optional[ChildDirectoryEntryDAO]: The matching child entry.
        """
        return next((child for child in self._children() if child.session_id == session_id), None)
