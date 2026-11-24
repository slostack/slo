"""Unit tests for ``MessagingPolicy`` — who may message whom (108.4 §2, C4).

The policy is pure: it reads the sender's own identity, its parent, its live
child directory and the workflows it launched, and decides which recipient a
``to`` string addresses and how the message is delivered. No mocks.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID, uuid4

import pytest

from src.agents.slo_agent.channel_delivery.policy import (
    MessageAddressDAO,
    MessagingPolicy,
)
from src.agents.slo_agent.orchestrator.dao import ChildDirectoryEntryDAO


class _Family:
    """One orchestrator W with children, its launcher S, and outsiders."""

    def __init__(self) -> None:
        """Create the ids of a small session family."""
        self.tui_session: UUID = uuid4()
        self.orchestrator: UUID = uuid4()
        self.review_child: UUID = uuid4()
        self.test_child: UUID = uuid4()
        self.finished_child: UUID = uuid4()
        self.unrelated: UUID = uuid4()
        self.directory: list[ChildDirectoryEntryDAO] = [
            ChildDirectoryEntryDAO(task_id="review-1", session_id=self.review_child, state="running"),
            ChildDirectoryEntryDAO(task_id="tests-1", session_id=self.test_child, state="running"),
            ChildDirectoryEntryDAO(task_id="lint-1", session_id=self.finished_child, state="finished"),
        ]

    def orchestrator_policy(self) -> MessagingPolicy:
        """Policy of W: no parent, three children, no launched workflows."""
        return MessagingPolicy(
            self_id=self.orchestrator,
            parent_id=None,
            children=lambda: list(self.directory),
            launched_workflows=lambda: [],
        )

    def child_policy(self) -> MessagingPolicy:
        """Policy of the review child: parent W, no children."""
        return MessagingPolicy(
            self_id=self.review_child,
            parent_id=self.orchestrator,
            children=lambda: [],
            launched_workflows=lambda: [],
        )

    def tui_policy(self) -> MessagingPolicy:
        """Policy of the TUI session S: launched W, no parent, no children."""
        return MessagingPolicy(
            self_id=self.tui_session,
            parent_id=None,
            children=lambda: [],
            launched_workflows=lambda: [self.orchestrator],
        )


class TestResolveAllowedEdges:
    def test_child_resolves_parent_alias_to_its_parent(self) -> None:
        """A child addresses its orchestrator with ``to='parent'``."""
        family: _Family = _Family()
        assert family.child_policy().resolve(to="parent") == family.orchestrator

    def test_orchestrator_resolves_task_id_alias_and_child_session_id(self) -> None:
        """W reaches its child by task id alias or by the child's session id."""
        family: _Family = _Family()
        policy: MessagingPolicy = family.orchestrator_policy()
        assert policy.resolve(to="review-1") == family.review_child
        assert policy.resolve(to=str(family.test_child)) == family.test_child

    def test_tui_session_resolves_a_workflow_it_launched(self) -> None:
        """S may message the orchestrators it launched."""
        family: _Family = _Family()
        assert family.tui_policy().resolve(to=str(family.orchestrator)) == family.orchestrator

    def test_child_directory_is_read_live_on_every_resolve(self) -> None:
        """A child spawned after the policy was built is reachable at once."""
        family: _Family = _Family()
        policy: MessagingPolicy = family.orchestrator_policy()
        late_child: UUID = uuid4()
        assert policy.resolve(to="docs-1") is None
        family.directory.append(
            ChildDirectoryEntryDAO(task_id="docs-1", session_id=late_child, state="running")
        )
        assert policy.resolve(to="docs-1") == late_child

    def test_task_id_alias_prefers_the_running_retry_over_the_finished_attempt(self) -> None:
        """A retried child keeps its task id; the alias reaches the live attempt."""
        family: _Family = _Family()
        retry_child: UUID = uuid4()
        family.directory.append(
            ChildDirectoryEntryDAO(task_id="lint-1", session_id=retry_child, state="running")
        )
        address: MessageAddressDAO = family.orchestrator_policy().address(to="lint-1", kind=None, force=None)
        assert (address.status, address.recipient_id) == ("allowed", retry_child)


class TestResolveRefusedEdges:
    """C4: sibling, unrelated session and grandparent are not allowed."""

    def test_child_cannot_reach_a_sibling_by_session_id_or_task_id(self) -> None:
        """A sibling is neither the parent nor a child of the sender."""
        family: _Family = _Family()
        policy: MessagingPolicy = family.child_policy()
        assert policy.resolve(to=str(family.test_child)) is None
        assert policy.resolve(to="tests-1") is None

    def test_child_cannot_reach_its_grandparent(self) -> None:
        """The TUI session that launched W is not the child's parent."""
        family: _Family = _Family()
        assert family.child_policy().resolve(to=str(family.tui_session)) is None

    def test_no_sender_can_reach_an_unrelated_session(self) -> None:
        """An unrelated agent session is never an edge."""
        family: _Family = _Family()
        for policy in (family.child_policy(), family.orchestrator_policy(), family.tui_policy()):
            assert policy.resolve(to=str(family.unrelated)) is None

    def test_tui_session_cannot_reach_children_of_its_workflow(self) -> None:
        """S's edge stops at W; W's children are W's to message."""
        family: _Family = _Family()
        assert family.tui_policy().resolve(to=str(family.review_child)) is None
        assert family.tui_policy().resolve(to="review-1") is None

    def test_parent_alias_without_a_parent_and_self_and_garbage_are_refused(self) -> None:
        """No parent means no ``parent`` edge; self and junk resolve to nothing."""
        family: _Family = _Family()
        policy: MessagingPolicy = family.orchestrator_policy()
        assert policy.resolve(to="parent") is None
        assert policy.resolve(to=str(family.orchestrator)) is None
        assert policy.resolve(to="") is None
        assert policy.resolve(to="not-a-task") is None


class TestAddressDefaults:
    def test_prompt_to_a_running_child_is_forced_by_default(self) -> None:
        """Children have no follow-up turns, so prompts to them default to forced."""
        family: _Family = _Family()
        address: MessageAddressDAO = family.orchestrator_policy().address(
            to="review-1", kind=None, force=None
        )
        assert address == MessageAddressDAO(
            status="allowed", recipient_id=family.review_child, message_type="prompt", force=True
        )

    def test_explicit_normal_prompt_to_a_child_is_respected(self) -> None:
        """``force=False`` overrides the children default."""
        family: _Family = _Family()
        address: MessageAddressDAO = family.orchestrator_policy().address(
            to="review-1", kind=None, force=False
        )
        assert address.force is False

    def test_child_to_parent_defaults_to_an_unforced_note(self) -> None:
        """Children default to ``note``; notes are never forced."""
        family: _Family = _Family()
        address: MessageAddressDAO = family.child_policy().address(to="parent", kind=None, force=None)
        assert address == MessageAddressDAO(
            status="allowed", recipient_id=family.orchestrator, message_type="note", force=False
        )

    def test_child_may_ask_its_parent_with_an_explicit_prompt(self) -> None:
        """A child question can be an explicit prompt; it is normal unless forced."""
        family: _Family = _Family()
        address: MessageAddressDAO = family.child_policy().address(to="parent", kind="prompt", force=None)
        assert (address.message_type, address.force) == ("prompt", False)

    def test_a_note_is_never_forced_even_when_asked(self) -> None:
        """Notes are not forceable (overview §3.2); they join at the next boundary anyway."""
        family: _Family = _Family()
        address: MessageAddressDAO = family.orchestrator_policy().address(
            to="review-1", kind="note", force=True
        )
        assert (address.message_type, address.force) == ("note", False)

    def test_tui_to_launched_workflow_defaults_to_a_normal_prompt(self) -> None:
        """Non-children default to normal prompts; explicit force is honoured."""
        family: _Family = _Family()
        policy: MessagingPolicy = family.tui_policy()
        normal: MessageAddressDAO = policy.address(to=str(family.orchestrator), kind=None, force=None)
        forced: MessageAddressDAO = policy.address(to=str(family.orchestrator), kind=None, force=True)
        assert (normal.message_type, normal.force) == ("prompt", False)
        assert forced.force is True


class TestAddressRefusals:
    def test_finished_child_is_recipient_closed(self) -> None:
        """A child the directory reports finished cannot receive messages."""
        family: _Family = _Family()
        address: MessageAddressDAO = family.orchestrator_policy().address(to="lint-1", kind=None, force=None)
        assert (address.status, address.recipient_id) == ("recipient_closed", family.finished_child)

    @pytest.mark.parametrize("to_kind", ["sibling", "grandparent", "unrelated"])
    def test_refused_edges_are_not_allowed_without_a_recipient(self, to_kind: str) -> None:
        """C4 through ``address``: refusals carry no recipient id."""
        family: _Family = _Family()
        targets: dict[str, UUID] = {
            "sibling": family.test_child,
            "grandparent": family.tui_session,
            "unrelated": family.unrelated,
        }
        address: MessageAddressDAO = family.child_policy().address(
            to=str(targets[to_kind]), kind=None, force=None
        )
        recipient: Optional[UUID] = address.recipient_id
        assert (address.status, recipient) == ("not_allowed", None)


class TestEnsureSender:
    def test_matching_sender_passes_and_other_identity_is_rejected(self) -> None:
        """The tool may only send as the identity the policy was built for."""
        family: _Family = _Family()
        policy: MessagingPolicy = family.child_policy()
        policy.ensure_sender(sender_id=family.review_child)
        with pytest.raises(ValueError):
            policy.ensure_sender(sender_id=family.orchestrator)
