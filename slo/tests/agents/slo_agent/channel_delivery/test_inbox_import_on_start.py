"""Journey: ``ChannelPoller.start`` imports a legacy file inbox before its first poll (108.6 §5).

A real ``SloAgentSession`` with a real filesystem history root owns a legacy
``inbox/`` left by a pre-108.6 scheduler. Starting the session's poller moves
the items into a real SQLite ``channels.db``; the imported scheduled prompt is
then run like any queued row. The ``RecordingTurnRunner`` is the injected
``TurnRunner`` seam (no patching); ``FauxChatModel`` sits at the LLM boundary.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
from src.agents.slo_agent.channel_delivery.poller import ChannelPoller
from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.channels.dao import ChannelMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.channels.inbox_import import InboxImporter, InboxImportReportDAO
from src.channels.repository import ChannelRepository
from tests.agents.slo_agent.channel_delivery.test_channel_poller import SessionTurnRunner


class RecordingTurnRunner:
    """TurnRunner stub recording which rows ran, accepting each at its first event."""

    def __init__(self) -> None:
        """Start with no recorded runs."""
        self.ran: list[UUID] = []

    async def run(
        self,
        *,
        message: ChannelMessageDAO,
        on_started: Callable[[], Awaitable[None]],
    ) -> TurnOutcomeDAO:
        """Record the row, accept it, and report completion.

        Args:
            message (ChannelMessageDAO): The prompt row being run.
            on_started (Callable[[], Awaitable[None]]): Acceptance callback.

        Returns:
            TurnOutcomeDAO: A completed outcome.
        """
        self.ran.append(message.id)
        await on_started()
        return TurnOutcomeDAO(status="completed", final_text="done")


def _write_legacy_pending_prompt(*, session_dir: Path, message_id: str) -> None:
    """Write one retired-format scheduled ``chat_turn`` into ``inbox/pending``.

    Args:
        session_dir (Path): ``<history root>/<session id>``.
        message_id (str): Inbox message id.
    """
    pending_dir: Path = session_dir / "inbox" / "pending"
    pending_dir.mkdir(parents=True)
    created_at: datetime = datetime(year=2026, month=11, day=21, hour=8, tzinfo=timezone.utc)
    (pending_dir / f"{created_at.strftime('%Y%m%dT%H%M%S.%fZ')}-{message_id}.json").write_text(
        json.dumps(
            {
                "message_id": message_id,
                "session_id": session_dir.name,
                "schedule_id": "sched-nightly",
                "run_id": str(uuid4()),
                "kind": "scheduled_prompt",
                "delivery_mode": "chat_turn",
                "created_at": created_at.isoformat(),
                "title": "Nightly",
                "text": "Run the nightly checks.",
                "payload": {"cwd": "/tmp/project", "model": "gpt-5.4"},
            }
        ),
        encoding="utf-8",
    )


async def _wait_until(*, predicate: Callable[[], bool], timeout_seconds: float = 10.0) -> None:
    """Poll ``predicate`` until it holds or the timeout expires.

    Args:
        predicate (Callable[[], bool]): Condition to wait for.
        timeout_seconds (float): Upper bound. Defaults to 10 seconds.
    """
    async with asyncio.timeout(timeout_seconds):
        while not predicate():
            await asyncio.sleep(0.01)


class TestPollerStartImportsLegacyInbox:
    async def test_start_imports_the_legacy_inbox_then_runs_the_imported_prompt(self, tmp_path: Path) -> None:
        """The pre-108.6 scheduled prompt runs once through the queue; ``inbox/`` is retired."""
        session_id: UUID = uuid4()
        message_id: str = str(uuid4())
        history_root: Path = tmp_path / "history"
        session_dir: Path = history_root / str(session_id)
        _write_legacy_pending_prompt(session_dir=session_dir, message_id=message_id)
        gateway: ChannelGateway = ChannelGateway(
            repository=ChannelRepository(db_path=tmp_path / "channels.db")
        )
        await gateway.open()
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(
                llm=FauxChatModel(responses=[AIMessage(content="unused")]), cwd=str(tmp_path), tools=[]
            ),
            workdir=tmp_path,
            session_id=str(session_id),
            history_store=FilesystemSessionHistoryStore(root=history_root),
            enable_history=True,
        )
        runner: RecordingTurnRunner = RecordingTurnRunner()
        poller: ChannelPoller = ChannelPoller(
            gateway=gateway,
            session=session,
            runner=runner,
            replies=ReplyWriter(gateway=gateway),
            boundary_inbox=ChannelBoundaryInbox(gateway=gateway, agent_id=session_id),
            interval=0.02,
            durable_inbox=True,
        )
        try:
            await poller.start()
            imported_row = await gateway.find_message(message_id=UUID(message_id))
            assert imported_row is not None
            assert imported_row.message_type == "prompt"
            assert imported_row.sender_name == "scheduler Nightly"
            assert not (session_dir / "inbox").exists()
            assert len(list(session_dir.glob("inbox.migrated-*"))) == 1
            assert poller.paused is None
            await _wait_until(predicate=lambda: runner.ran == [UUID(message_id)])
            accepted = await gateway.find_message(message_id=UUID(message_id))
            assert accepted is not None and accepted.accepted_at is not None
        finally:
            await poller.stop(reason="test_done")
            await gateway.close()

    async def test_session_without_history_starts_without_touching_any_inbox(self, tmp_path: Path) -> None:
        """A history-disabled session has no inbox to import; start still registers and polls."""
        session_id: UUID = uuid4()
        gateway: ChannelGateway = ChannelGateway(
            repository=ChannelRepository(db_path=tmp_path / "channels.db")
        )
        await gateway.open()
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(
                llm=FauxChatModel(responses=[AIMessage(content="unused")]), cwd=str(tmp_path), tools=[]
            ),
            workdir=tmp_path,
            session_id=str(session_id),
            enable_history=False,
        )
        poller: ChannelPoller = ChannelPoller(
            gateway=gateway,
            session=session,
            runner=RecordingTurnRunner(),
            replies=ReplyWriter(gateway=gateway),
            boundary_inbox=ChannelBoundaryInbox(gateway=gateway, agent_id=session_id),
            interval=0.02,
        )
        try:
            await poller.start()
            participant = await gateway.find_participant(participant_id=session_id)
            assert participant is not None and participant.status == "open"
            assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
                path.name for path in tmp_path.iterdir() if path.name.startswith("channels.db")
            )
        finally:
            await poller.stop(reason="test_done")
            await gateway.close()


def _build_history_session(
    *, tmp_path: Path, session_id: UUID, responses: list[AIMessage]
) -> SloAgentSession:
    """Build a real history-backed session whose provider is the scripted faux model.

    Args:
        tmp_path (Path): Test-owned root; history lives under ``history/``.
        session_id (UUID): Session id (also the agent participant id).
        responses (list[AIMessage]): Scripted provider answers, one per run.

    Returns:
        SloAgentSession: The session.
    """
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=responses), cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=str(session_id),
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        enable_history=True,
    )


def _build_session_poller(*, gateway: ChannelGateway, session: SloAgentSession) -> ChannelPoller:
    """Build a poller whose turns really run through ``session.invoke`` (the production seam).

    Args:
        gateway (ChannelGateway): Open gateway.
        session (SloAgentSession): Session the poller delivers to.

    Returns:
        ChannelPoller: A not-yet-started durable-inbox poller.
    """
    return ChannelPoller(
        gateway=gateway,
        session=session,
        runner=SessionTurnRunner(session=session),
        replies=ReplyWriter(gateway=gateway),
        boundary_inbox=ChannelBoundaryInbox(gateway=gateway, agent_id=UUID(session.session_id)),
        interval=0.02,
        durable_inbox=True,
    )


async def _linked_user_messages(*, session: SloAgentSession, message_id: str) -> list[SessionHistoryEventDAO]:
    """Return the ``user_message`` history events linked to one channel row.

    Args:
        session (SloAgentSession): History-backed session.
        message_id (str): Channel row id.

    Returns:
        list[SessionHistoryEventDAO]: Linked user messages, in history order.
    """
    assert session.history_store is not None
    events: list[SessionHistoryEventDAO] = await session.history_store.load_events(
        session_id=session.session_id
    )
    return [
        event
        for event in events
        if event.kind == "user_message" and event.payload.metadata.get("channel_message_id") == message_id
    ]


async def _replies_to(
    *, gateway: ChannelGateway, session_id: UUID, message_id: str
) -> list[ChannelMessageDAO]:
    """Return every reply row answering one request in the session's conversation.

    Args:
        gateway (ChannelGateway): Open gateway.
        session_id (UUID): Conversation id.
        message_id (str): Request row id.

    Returns:
        list[ChannelMessageDAO]: Reply rows in index order.
    """
    rows: list[ChannelMessageDAO] = await gateway.list_conversation_messages(agent_session_id=session_id)
    return [row for row in rows if row.message_type == "reply" and str(row.in_reply_to_id) == message_id]


class TestImportedChatTurnDeliveredOnce:
    """108.1-R02 under 108.6: a legacy ``chat_turn`` keeps its id and runs exactly once."""

    async def test_imported_chat_turn_runs_once_with_history_link_and_reply_and_a_rerun_adds_nothing(
        self, tmp_path: Path
    ) -> None:
        """Import → one run linked in history → one reply to the system sender; a re-import is inert."""
        session_id: UUID = uuid4()
        message_id: str = str(uuid4())
        session_dir: Path = tmp_path / "history" / str(session_id)
        _write_legacy_pending_prompt(session_dir=session_dir, message_id=message_id)
        crash_copy: Path = tmp_path / "inbox-before-rename"
        shutil.copytree(src=session_dir / "inbox", dst=crash_copy)
        gateway: ChannelGateway = ChannelGateway(
            repository=ChannelRepository(db_path=tmp_path / "channels.db")
        )
        await gateway.open()
        session: SloAgentSession = _build_history_session(
            tmp_path=tmp_path, session_id=session_id, responses=[AIMessage(content="nightly checks pass")]
        )
        first_poller: ChannelPoller = _build_session_poller(gateway=gateway, session=session)
        second_poller: ChannelPoller = _build_session_poller(gateway=gateway, session=session)
        try:
            await first_poller.start()
            await _wait_until_replied(gateway=gateway, session_id=session_id, message_id=message_id)
            await first_poller.stop(reason="session_closed")
            rows_after_run: list[ChannelMessageDAO] = await gateway.list_conversation_messages(
                agent_session_id=session_id
            )
            shutil.copytree(src=crash_copy, dst=session_dir / "inbox")

            await second_poller.start()
            await asyncio.sleep(0.2)
            rows_after_rerun: list[ChannelMessageDAO] = await gateway.list_conversation_messages(
                agent_session_id=session_id
            )
            imported: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=UUID(message_id))
            assert imported is not None
            sender: Optional[ParticipantDAO] = await gateway.find_participant(
                participant_id=imported.sender_id
            )
            linked: list[SessionHistoryEventDAO] = await _linked_user_messages(
                session=session, message_id=message_id
            )
            replies: list[ChannelMessageDAO] = await _replies_to(
                gateway=gateway, session_id=session_id, message_id=message_id
            )
        finally:
            await second_poller.stop(reason="test_done")
            await gateway.close()

        assert imported.accepted_at is not None and imported.cancelled_at is None
        assert sender is not None and sender.kind == "system"
        assert [event.payload.content for event in linked] == ["Run the nightly checks."]
        assert [(reply.recipient_id, reply.message_contents) for reply in replies] == [
            (imported.sender_id, "nightly checks pass")
        ]
        assert [row.id for row in rows_after_rerun] == [row.id for row in rows_after_run]
        assert second_poller.paused is None
        assert not (session_dir / "inbox").exists()
        assert len(list(session_dir.glob("inbox.migrated-*"))) == 2

    async def test_an_import_left_pending_by_a_crash_runs_once_without_pausing_recovery(
        self, tmp_path: Path
    ) -> None:
        """A crash after import but before the first poll: restart recovery runs the system row once.

        Recovery pauses only for operator leftovers (108.1 §6); an imported
        scheduler prompt is a system row, so the restarted poller runs it.
        """
        session_id: UUID = uuid4()
        message_id: str = str(uuid4())
        session_dir: Path = tmp_path / "history" / str(session_id)
        _write_legacy_pending_prompt(session_dir=session_dir, message_id=message_id)
        gateway: ChannelGateway = ChannelGateway(
            repository=ChannelRepository(db_path=tmp_path / "channels.db")
        )
        await gateway.open()
        await gateway.register_agent(session_id=session_id, name="slo crashed", durable_inbox=True)
        report: InboxImportReportDAO = await InboxImporter(
            session_dir=session_dir, gateway=gateway, agent_id=session_id
        ).run()
        session: SloAgentSession = _build_history_session(
            tmp_path=tmp_path, session_id=session_id, responses=[AIMessage(content="nightly checks pass")]
        )
        poller: ChannelPoller = _build_session_poller(gateway=gateway, session=session)
        try:
            await poller.start()
            paused_after_start: Optional[str] = poller.paused
            await _wait_until_replied(gateway=gateway, session_id=session_id, message_id=message_id)
            linked: list[SessionHistoryEventDAO] = await _linked_user_messages(
                session=session, message_id=message_id
            )
        finally:
            await poller.stop(reason="test_done")
            await gateway.close()

        assert report == InboxImportReportDAO(imported=1, duplicates=0, unreadable=[])
        assert paused_after_start is None
        assert len(linked) == 1


async def _wait_until_replied(*, gateway: ChannelGateway, session_id: UUID, message_id: str) -> None:
    """Wait (bounded) until one reply row answers the request.

    Args:
        gateway (ChannelGateway): Open gateway.
        session_id (UUID): Conversation id.
        message_id (str): Request row id.
    """
    async with asyncio.timeout(10.0):
        while not await _replies_to(gateway=gateway, session_id=session_id, message_id=message_id):
            await asyncio.sleep(0.02)
