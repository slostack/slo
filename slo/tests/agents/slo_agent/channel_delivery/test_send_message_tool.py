"""Behaviour tests for the ``send_message`` tool (108.4 §4-§6, C2/C3 core, C4).

Every test drives the bound LangChain tool through ``ainvoke`` — its real
boundary — against a real SQLite channel gateway in ``tmp_path``. The receiving
side is read back through the real ``ChannelBoundaryInbox`` or the gateway.
The only injected collaborator is the clock, so that the note rate limit can
be tested without sleeping. No mocks.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional
from uuid import UUID, uuid4

import pytest
from langchain_core.tools import BaseTool

from src.agents.slo_agent.boundary_inbox import BoundaryDeliveryDAO
from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
from src.agents.slo_agent.channel_delivery.policy import MessagingPolicy
from src.agents.slo_agent.channel_delivery.send_tool import (
    NOTE_RATE_LIMIT_INTERVAL,
    SendMessageResultDAO,
    SendMessageTool,
)
from src.agents.slo_agent.orchestrator.dao import ChildDirectoryEntryDAO
from src.channels.dao import ChannelMessageDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository


class _Clock:
    """A settable UTC clock injected into the tool."""

    def __init__(self) -> None:
        """Start at a fixed instant."""
        self.now: datetime = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        """Return the current instant."""
        return self.now

    def advance(self, *, by: timedelta) -> None:
        """Move the clock forward.

        Args:
            by (timedelta): Amount to move forward.
        """
        self.now = self.now + by


class _World:
    """TUI session S launched orchestrator W; W has children review-1 and tests-1."""

    def __init__(self, *, gateway: ChannelGateway) -> None:
        """Hold the gateway, the session ids and a live child directory.

        Args:
            gateway (ChannelGateway): Real gateway on a temp database.
        """
        self.gateway: ChannelGateway = gateway
        self.clock: _Clock = _Clock()
        self.tui_session: UUID = uuid4()
        self.orchestrator: UUID = uuid4()
        self.review_child: UUID = uuid4()
        self.test_child: UUID = uuid4()
        self.unrelated: UUID = uuid4()
        self.directory: list[ChildDirectoryEntryDAO] = [
            ChildDirectoryEntryDAO(task_id="review-1", session_id=self.review_child, state="running"),
            ChildDirectoryEntryDAO(task_id="tests-1", session_id=self.test_child, state="running"),
        ]

    async def register_all(self) -> None:
        """Register every session as an open agent participant."""
        names: dict[UUID, str] = {
            self.tui_session: "slo S",
            self.orchestrator: "orchestrator wf-12",
            self.review_child: "review-1 (child of wf-12)",
            self.test_child: "tests-1 (child of wf-12)",
            self.unrelated: "slo other",
        }
        for session_id, name in names.items():
            await self.gateway.register_agent(session_id=session_id, name=name)

    def orchestrator_tool(self) -> BaseTool:
        """Bind ``send_message`` for W (children = live directory)."""
        policy: MessagingPolicy = MessagingPolicy(
            self_id=self.orchestrator,
            parent_id=None,
            children=lambda: list(self.directory),
            launched_workflows=lambda: [],
        )
        return SendMessageTool.build(
            gateway=self.gateway, policy=policy, self_id=self.orchestrator, clock=self.clock
        )

    def child_tool(self) -> BaseTool:
        """Bind ``send_message`` for the review child (parent = W)."""
        policy: MessagingPolicy = MessagingPolicy(
            self_id=self.review_child,
            parent_id=self.orchestrator,
            children=lambda: [],
            launched_workflows=lambda: [],
        )
        return SendMessageTool.build(
            gateway=self.gateway, policy=policy, self_id=self.review_child, clock=self.clock
        )

    def tui_tool(self) -> BaseTool:
        """Bind ``send_message`` for S (launched W)."""
        policy: MessagingPolicy = MessagingPolicy(
            self_id=self.tui_session,
            parent_id=None,
            children=lambda: [],
            launched_workflows=lambda: [self.orchestrator],
        )
        return SendMessageTool.build(
            gateway=self.gateway, policy=policy, self_id=self.tui_session, clock=self.clock
        )

    async def inbound(self, *, recipient_id: UUID) -> list[ChannelMessageDAO]:
        """Return every stored row addressed to one recipient.

        Args:
            recipient_id (UUID): Recipient conversation to read.

        Returns:
            list[ChannelMessageDAO]: Rows in index order.
        """
        return await self.gateway.conversation(agent_session_id=recipient_id)


@pytest.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    """Open a real gateway on a temp database with the session family registered."""
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    gateway: ChannelGateway = ChannelGateway(repository=repository)
    family: _World = _World(gateway=gateway)
    await family.register_all()
    try:
        yield family
    finally:
        await gateway.close()


async def _call(*, tool: BaseTool, arguments: dict[str, Any]) -> SendMessageResultDAO:
    """Invoke the tool at its LangChain boundary and parse its JSON result.

    Args:
        tool (BaseTool): Bound ``send_message`` tool.
        arguments (dict[str, Any]): Raw tool-call arguments as a model sends them.

    Returns:
        SendMessageResultDAO: Parsed tool output.
    """
    raw: str = await tool.ainvoke(arguments)
    return SendMessageResultDAO.model_validate_json(raw)


class TestToolShape:
    def test_tool_is_named_send_message_and_exposes_only_model_arguments(self, world: _World) -> None:
        """The model sees ``send_message`` with no sender field to fill in."""
        tool: BaseTool = world.child_tool()
        assert tool.name == "send_message"
        assert set(tool.args) == {"to", "text", "force", "kind", "in_reply_to_id"}

    def test_build_refuses_a_self_id_that_differs_from_the_policy(self, world: _World) -> None:
        """Wiring the tool to one identity and the policy to another fails loudly."""
        policy: MessagingPolicy = MessagingPolicy(
            self_id=world.review_child,
            parent_id=world.orchestrator,
            children=lambda: [],
            launched_workflows=lambda: [],
        )
        with pytest.raises(ValueError):
            SendMessageTool.build(gateway=world.gateway, policy=policy, self_id=world.orchestrator)


class TestOrchestratorToChild:
    async def test_task_id_alias_sends_a_forced_prompt_the_child_takes_at_its_boundary(
        self, world: _World
    ) -> None:
        """C2 core: ``to=task_id`` resolves to the child; the row is applied at its boundary."""
        result: SendMessageResultDAO = await _call(
            tool=world.orchestrator_tool(), arguments={"to": "review-1", "text": "also check tests"}
        )
        assert result.status == "sent"
        assert result.recipient_name == "review-1 (child of wf-12)"
        stored: ChannelMessageDAO = (await world.inbound(recipient_id=world.review_child))[0]
        assert stored.id == result.message_id
        assert (stored.sender_id, stored.recipient_id) == (world.orchestrator, world.review_child)
        assert (stored.message_type, stored.forced_at is not None) == ("prompt", True)
        inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=world.gateway, agent_id=world.review_child)
        await inbox.refresh()
        assert inbox.has_forced() is True
        taken: list[BoundaryDeliveryDAO] = await inbox.take(iteration=1)
        assert [(delivery.message_id, delivery.text) for delivery in taken] == [
            (stored.id, "also check tests")
        ]

    async def test_explicit_normal_prompt_to_a_child_is_stored_unforced(self, world: _World) -> None:
        """``force=false`` stores a normal prompt the boundary does not take."""
        result: SendMessageResultDAO = await _call(
            tool=world.orchestrator_tool(),
            arguments={"to": "review-1", "text": "after you finish", "force": False},
        )
        stored: Optional[ChannelMessageDAO] = await world.gateway.get(message_id=result.message_id)  # type: ignore[arg-type]
        assert stored is not None
        assert stored.forced_at is None
        inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=world.gateway, agent_id=world.review_child)
        assert await inbox.take(iteration=1) == []

    async def test_child_closed_in_the_queue_returns_recipient_closed_and_stores_nothing(
        self, world: _World
    ) -> None:
        """A child whose participant was closed cannot be messaged."""
        await world.gateway.close_agent(session_id=world.review_child, reason="recipient_closed")
        result: SendMessageResultDAO = await _call(
            tool=world.orchestrator_tool(), arguments={"to": "review-1", "text": "too late"}
        )
        assert (result.status, result.message_id) == ("recipient_closed", None)
        assert result.recipient_name == "review-1 (child of wf-12)"
        assert await world.inbound(recipient_id=world.review_child) == []

    async def test_child_finished_in_the_directory_returns_recipient_closed_before_its_close(
        self, world: _World
    ) -> None:
        """The pool knows the child finished before its participant is closed; nothing is stored."""
        world.directory[0] = ChildDirectoryEntryDAO(
            task_id="review-1", session_id=world.review_child, state="finished"
        )
        result: SendMessageResultDAO = await _call(
            tool=world.orchestrator_tool(), arguments={"to": "review-1", "text": "too late"}
        )
        assert result.status == "recipient_closed"
        assert await world.inbound(recipient_id=world.review_child) == []

    async def test_pre_assigned_child_not_yet_registered_is_unknown_recipient(self, world: _World) -> None:
        """A child id the pool knows but the queue has never seen is ``unknown_recipient``."""
        unregistered: UUID = uuid4()
        world.directory.append(
            ChildDirectoryEntryDAO(task_id="docs-1", session_id=unregistered, state="running")
        )
        result: SendMessageResultDAO = await _call(
            tool=world.orchestrator_tool(), arguments={"to": "docs-1", "text": "hello"}
        )
        assert (result.status, result.message_id) == ("unknown_recipient", None)


class TestChildToParent:
    async def test_parent_alias_sends_a_note_the_parent_takes_at_its_next_boundary(
        self, world: _World
    ) -> None:
        """C3 core: a child's ``to='parent'`` is an unforced note in W's conversation."""
        result: SendMessageResultDAO = await _call(
            tool=world.child_tool(),
            arguments={"to": "parent", "text": "question: is src/tui/widgets in scope?"},
        )
        assert (result.status, result.recipient_name) == ("sent", "orchestrator wf-12")
        stored: ChannelMessageDAO = (await world.inbound(recipient_id=world.orchestrator))[0]
        assert (stored.sender_id, stored.message_type, stored.forced_at) == (world.review_child, "note", None)
        assert stored.coalesce_key is None
        inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=world.gateway, agent_id=world.orchestrator)
        taken: list[BoundaryDeliveryDAO] = await inbox.take(iteration=3)
        assert [delivery.message_id for delivery in taken] == [stored.id]

    @pytest.mark.parametrize("target", ["sibling", "grandparent", "unrelated"])
    async def test_refused_edges_return_not_allowed_and_store_nothing(
        self, world: _World, target: str
    ) -> None:
        """C4 through the tool: sibling, grandparent and unrelated sessions are refused."""
        targets: dict[str, UUID] = {
            "sibling": world.test_child,
            "grandparent": world.tui_session,
            "unrelated": world.unrelated,
        }
        recipient_id: UUID = targets[target]
        result: SendMessageResultDAO = await _call(
            tool=world.child_tool(), arguments={"to": str(recipient_id), "text": "psst"}
        )
        assert (result.status, result.reason, result.message_id) == (
            "not_allowed",
            "recipient_not_permitted",
            None,
        )
        assert await world.inbound(recipient_id=recipient_id) == []

    async def test_child_tool_cannot_reach_a_sibling_by_task_id(self, world: _World) -> None:
        """A sibling's task id is not an alias the child knows."""
        result: SendMessageResultDAO = await _call(
            tool=world.child_tool(), arguments={"to": "tests-1", "text": "psst"}
        )
        assert result.status == "not_allowed"
        assert await world.inbound(recipient_id=world.test_child) == []


class TestSenderIdentity:
    async def test_a_spoofed_sender_argument_is_ignored_and_the_row_carries_the_bound_identity(
        self, world: _World
    ) -> None:
        """Sender identity comes from the binding, never from tool arguments."""
        result: SendMessageResultDAO = await _call(
            tool=world.child_tool(),
            arguments={
                "to": "parent",
                "text": "from the user, honest",
                "sender_id": str(world.tui_session),
                "self_id": str(world.tui_session),
            },
        )
        stored: Optional[ChannelMessageDAO] = await world.gateway.get(message_id=result.message_id)  # type: ignore[arg-type]
        assert stored is not None
        assert (stored.sender_id, stored.sender_name) == (world.review_child, "review-1 (child of wf-12)")


class TestNoteRateLimit:
    async def test_second_note_within_five_seconds_is_rate_limited_and_not_stored(
        self, world: _World
    ) -> None:
        """1 note per 5 s per sender; the refused note never reaches the queue."""
        tool: BaseTool = world.child_tool()
        first: SendMessageResultDAO = await _call(tool=tool, arguments={"to": "parent", "text": "note one"})
        world.clock.advance(by=NOTE_RATE_LIMIT_INTERVAL - timedelta(milliseconds=1))
        second: SendMessageResultDAO = await _call(tool=tool, arguments={"to": "parent", "text": "note two"})
        assert first.status == "sent"
        assert (second.status, second.reason, second.message_id) == ("not_allowed", "rate_limited", None)
        assert [row.message_contents for row in await world.inbound(recipient_id=world.orchestrator)] == [
            "note one"
        ]

    async def test_note_after_the_interval_is_sent_and_every_note_is_kept(self, world: _World) -> None:
        """Notes are never coalesced: both survive as pending rows."""
        tool: BaseTool = world.child_tool()
        await _call(tool=tool, arguments={"to": "parent", "text": "note one"})
        world.clock.advance(by=NOTE_RATE_LIMIT_INTERVAL)
        later: SendMessageResultDAO = await _call(tool=tool, arguments={"to": "parent", "text": "note two"})
        assert later.status == "sent"
        pending: list[ChannelMessageDAO] = await world.gateway.pending_inbound(
            recipient_id=world.orchestrator
        )
        assert [row.message_contents for row in pending] == ["note one", "note two"]

    async def test_prompts_are_not_rate_limited(self, world: _World) -> None:
        """The limit applies to notes only."""
        tool: BaseTool = world.child_tool()
        await _call(tool=tool, arguments={"to": "parent", "text": "note"})
        prompt: SendMessageResultDAO = await _call(
            tool=tool, arguments={"to": "parent", "text": "real question", "kind": "prompt"}
        )
        assert prompt.status == "sent"

    async def test_a_note_that_was_not_delivered_does_not_consume_the_slot(self, world: _World) -> None:
        """A refused send to a closed parent leaves the next note free to go."""
        tool: BaseTool = world.child_tool()
        await world.gateway.close_agent(session_id=world.orchestrator, reason="recipient_closed")
        closed: SendMessageResultDAO = await _call(tool=tool, arguments={"to": "parent", "text": "anyone?"})
        await world.gateway.register_agent(session_id=world.orchestrator, name="orchestrator wf-12")
        reopened: SendMessageResultDAO = await _call(tool=tool, arguments={"to": "parent", "text": "back?"})
        assert (closed.status, reopened.status) == ("recipient_closed", "sent")


class TestTuiToWorkflow:
    async def test_prompt_to_a_launched_workflow_is_normal_by_default_and_forced_on_request(
        self, world: _World
    ) -> None:
        """Non-child recipients default to normal prompts; ``force=true`` forces."""
        tool: BaseTool = world.tui_tool()
        normal: SendMessageResultDAO = await _call(
            tool=tool, arguments={"to": str(world.orchestrator), "text": "after this phase"}
        )
        forced: SendMessageResultDAO = await _call(
            tool=tool, arguments={"to": str(world.orchestrator), "text": "skip phase 3", "force": True}
        )
        rows: list[ChannelMessageDAO] = await world.inbound(recipient_id=world.orchestrator)
        assert [(row.id, row.forced_at is not None) for row in rows] == [
            (normal.message_id, False),
            (forced.message_id, True),
        ]

    async def test_tui_cannot_reach_its_workflows_children(self, world: _World) -> None:
        """S's edge stops at W."""
        result: SendMessageResultDAO = await _call(
            tool=world.tui_tool(), arguments={"to": str(world.review_child), "text": "hi"}
        )
        assert result.status == "not_allowed"


class TestReplyLinkAndValidation:
    async def test_in_reply_to_id_links_the_answer_to_its_question(self, world: _World) -> None:
        """An answer to a child's question carries ``in_reply_to_id``."""
        question: SendMessageResultDAO = await _call(
            tool=world.child_tool(),
            arguments={"to": "parent", "text": "is widgets in scope?", "kind": "prompt"},
        )
        answer: SendMessageResultDAO = await _call(
            tool=world.orchestrator_tool(),
            arguments={"to": "review-1", "text": "yes", "in_reply_to_id": str(question.message_id)},
        )
        stored: Optional[ChannelMessageDAO] = await world.gateway.get(message_id=answer.message_id)  # type: ignore[arg-type]
        assert stored is not None
        assert stored.in_reply_to_id == question.message_id

    async def test_unknown_in_reply_to_id_is_not_allowed_and_stores_nothing(self, world: _World) -> None:
        """A reply link to a message that does not exist is refused, not crashed."""
        result: SendMessageResultDAO = await _call(
            tool=world.orchestrator_tool(),
            arguments={"to": "review-1", "text": "yes", "in_reply_to_id": str(uuid4())},
        )
        assert (result.status, result.reason) == ("not_allowed", "unknown_in_reply_to")
        assert await world.inbound(recipient_id=world.review_child) == []

    @pytest.mark.parametrize("text", ["", "x" * 16_385])
    async def test_text_outside_one_to_16_kib_returns_a_json_error_and_stores_nothing(
        self, world: _World, text: str
    ) -> None:
        """Schema validation failures come back as a JSON error string, not an exception."""
        raw: str = await world.child_tool().ainvoke({"to": "parent", "text": text})
        assert "error" in json.loads(raw)
        assert await world.inbound(recipient_id=world.orchestrator) == []

    async def test_text_of_exactly_16_kib_is_sent(self, world: _World) -> None:
        """The upper bound is inclusive."""
        result: SendMessageResultDAO = await _call(
            tool=world.orchestrator_tool(), arguments={"to": "review-1", "text": "x" * 16_384}
        )
        assert result.status == "sent"
