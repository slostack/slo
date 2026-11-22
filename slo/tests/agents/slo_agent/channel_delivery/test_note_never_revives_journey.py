"""R1 / O2 journey: a note never revives a stopping run through a stale forced snapshot.

A run's stop decision reads the boundary inbox's cached forced-row snapshot.
When that cached forced row is cancelled and a note is pending instead, the
revive boundary must take nothing (no extra provider call). The note stays
pending and reaches the next naturally continuing model call exactly once; a
genuine forced prompt still revives the run. Real SQLite queue, real session
with a real filesystem history store; ``FauxChatModel`` at the provider
boundary only.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import AsyncIterator, Optional
from uuid import UUID, uuid4

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import BaseTool
from pydantic import Field, PrivateAttr

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.boundary_inbox import BoundaryDeliveryDAO
from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository


class GatedRecordingFauxChatModel(FauxChatModel):
    """Provider-boundary double: holds the first call, records every call's texts."""

    first_call_release: asyncio.Event = Field(description="Set by the test to release the first call.")
    first_call_entered: asyncio.Event = Field(description="Set once the first call has started.")
    recorded_contexts: list[list[str]] = Field(
        default_factory=list,
        description="Texts of the messages passed to each model call, in call order.",
    )
    _held_call_done: bool = PrivateAttr(default=False)

    def __init__(self, *, responses: Sequence[AIMessage], **data: object) -> None:
        """Queue the scripted responses; the remaining fields pass through to pydantic."""
        super().__init__(responses=responses, **data)  # type: ignore[arg-type]

    def bind_tools(
        self,
        tools: Sequence[dict[str, object] | type | Callable[..., object] | BaseTool],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: object,
    ) -> "GatedRecordingFauxChatModel":
        """Clone preserving the gate, the recorder and the remaining script."""
        clone: GatedRecordingFauxChatModel = GatedRecordingFauxChatModel(
            responses=list(self.queue),
            first_call_release=self.first_call_release,
            first_call_entered=self.first_call_entered,
        )
        # Assigned after construction: validation would copy the list.
        clone.recorded_contexts = self.recorded_contexts
        clone.bound_tools = list(tools)
        clone._held_call_done = self._held_call_done
        return clone

    async def _astream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Hold the very first call until released; record every call's texts."""
        self.recorded_contexts.append([str(message.content) for message in messages])
        if not self._held_call_done:
            self.first_call_entered.set()
            await self.first_call_release.wait()
            self._held_call_done = True
        async for chunk in super()._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


async def _open_world(
    *, tmp_path: Path, session_id: UUID
) -> tuple[ChannelGateway, ParticipantDAO, ParticipantDAO]:
    """Open a real queue and register the operator and the agent participant."""
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    gateway: ChannelGateway = ChannelGateway(repository=repository)
    channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
    user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
    agent: ParticipantDAO = await gateway.register_agent(session_id=session_id, name="slo agent")
    return gateway, user, agent


async def _drain(*, session: SloAgentSession, text: str) -> list[str]:
    """Run one turn through the real session and return its event kinds."""
    return [event.kind async for event in session.invoke(text=text)]


async def test_cancelled_cached_forced_row_with_pending_note_makes_no_extra_provider_call(
    tmp_path: Path,
) -> None:
    """A stale forced snapshot plus a pending note stops the run; the note waits for the next call."""
    session_id: UUID = uuid4()
    gateway, user, agent = await _open_world(tmp_path=tmp_path, session_id=session_id)
    inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
    model: GatedRecordingFauxChatModel = GatedRecordingFauxChatModel(
        responses=[AIMessage(content="first answer"), AIMessage(content="second answer")],
        first_call_release=asyncio.Event(),
        first_call_entered=asyncio.Event(),
    )
    history_store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path / "history")
    session: SloAgentSession = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[], boundary_inbox=inbox),
        workdir=tmp_path,
        session_id=str(session_id),
        history_store=history_store,
        enable_history=True,
    )
    try:
        first_run: asyncio.Task[list[str]] = asyncio.create_task(_drain(session=session, text="start"))
        await asyncio.wait_for(model.first_call_entered.wait(), timeout=10.0)
        forced: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(sender_id=user.id, recipient_id=agent.id, message_contents="forced", force=True)
        )
        await inbox.refresh()
        assert inbox.has_forced() is True
        # The forced row is withdrawn and a note arrives; the cached snapshot
        # is not refreshed before the run's stop decision.
        await gateway.cancel(message_id=forced.id, reason="operator")
        note: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id, recipient_id=agent.id, message_contents="fyi note", message_type="note"
            )
        )
        model.first_call_release.set()
        first_kinds: list[str] = await asyncio.wait_for(first_run, timeout=10.0)

        assert "run_completed" in first_kinds
        assert "steering_applied" not in first_kinds
        assert len(model.recorded_contexts) == 1
        pending_note: Optional[ChannelMessageDAO] = await gateway.get(message_id=note.id)
        assert pending_note is not None and pending_note.accepted_at is None

        # The next naturally continuing call carries the note exactly once.
        await asyncio.wait_for(_drain(session=session, text="next"), timeout=10.0)
        assert len(model.recorded_contexts) == 2
        assert model.recorded_contexts[1].count("fyi note") == 1
        accepted_note: Optional[ChannelMessageDAO] = await gateway.get(message_id=note.id)
        assert accepted_note is not None and accepted_note.accepted_at is not None
    finally:
        await gateway.close()


async def test_genuine_forced_prompt_still_revives_a_stopping_run(tmp_path: Path) -> None:
    """A pending forced prompt at the stop decision gives the run one more provider call."""
    session_id: UUID = uuid4()
    gateway, user, agent = await _open_world(tmp_path=tmp_path, session_id=session_id)
    inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
    model: GatedRecordingFauxChatModel = GatedRecordingFauxChatModel(
        responses=[AIMessage(content="first answer"), AIMessage(content="revived answer")],
        first_call_release=asyncio.Event(),
        first_call_entered=asyncio.Event(),
    )
    session: SloAgentSession = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[], boundary_inbox=inbox),
        workdir=tmp_path,
        session_id=str(session_id),
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        enable_history=True,
    )
    try:
        run: asyncio.Task[list[str]] = asyncio.create_task(_drain(session=session, text="start"))
        await asyncio.wait_for(model.first_call_entered.wait(), timeout=10.0)
        note: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id,
                recipient_id=agent.id,
                message_contents="ride-along note",
                message_type="note",
            )
        )
        forced: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id, recipient_id=agent.id, message_contents="also do X", force=True
            )
        )
        await inbox.refresh()
        model.first_call_release.set()
        kinds: list[str] = await asyncio.wait_for(run, timeout=10.0)

        assert kinds.count("steering_applied") == 2
        assert len(model.recorded_contexts) == 2
        revived_context: list[str] = model.recorded_contexts[1]
        assert revived_context.count("also do X") == 1
        assert revived_context.index("ride-along note") < revived_context.index("also do X")
        for row_id in (note.id, forced.id):
            stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=row_id)
            assert stored is not None and stored.accepted_at is not None
    finally:
        await gateway.close()


async def test_taken_deliveries_carry_their_kind(tmp_path: Path) -> None:
    """The boundary delivery keeps whether it is a note or a forced prompt."""
    session_id: UUID = uuid4()
    gateway, user, agent = await _open_world(tmp_path=tmp_path, session_id=session_id)
    inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
    try:
        await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id, recipient_id=agent.id, message_contents="n", message_type="note"
            )
        )
        assert await inbox.take(iteration=1, require_forced_prompt=True) == []
        await gateway.send(
            new=NewMessageDAO(sender_id=user.id, recipient_id=agent.id, message_contents="f", force=True)
        )
        deliveries: list[BoundaryDeliveryDAO] = await inbox.take(iteration=2, require_forced_prompt=True)
        assert [delivery.kind for delivery in deliveries] == ["note", "forced_prompt"]
    finally:
        await gateway.close()
