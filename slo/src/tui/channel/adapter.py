"""TuiChannelAdapter — the TUI is the first channel (108.1).

Every prompt the operator sends becomes a queue row through
``send_prompt``; the session's poller runs the rows in order. Outbound
``reply`` rows for TUI-sent prompts need no rendering (the stream already
showed the answer) and are accepted in place; ``notice`` rows render as
transcript notices.
"""

from __future__ import annotations

import asyncio
import json
import os
import getpass
import socket
from pathlib import Path
from typing import Optional, TYPE_CHECKING
from uuid import UUID, uuid4

from config.logger import log_warning

from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.channels.dao import (
    ChannelDAO,
    ChannelMessageDAO,
    NewMessageDAO,
    ParticipantDAO,
    SentMessageRowDAO,
)
from src.channels.gateway import ChannelGateway
from src.tui.components.chat_transcript.commands import TranscriptNoticeDAO

if TYPE_CHECKING:
    from src.tui.app import SloTUI
    from src.tui.components.chat_transcript.component import ChatTranscriptComponent


NOTE_DISPLAY_PREFIX: str = "⊛"
"""Transcript prefix for channel notes and notices arriving live (108.3)."""

REPLY_DISPLAY_PREFIX: str = "↩"
"""Transcript prefix for a reply from another agent (108.3)."""


class TuiDisplaySink:
    """Shows channel notes and notices as live ``⊛`` transcript lines (108.3 §3).

    The poller calls ``show`` the moment it sees a row that must be displayed
    but never run; acceptance is the poller's job (108.3 §5).
    """

    def __init__(self, *, transcript: Optional["ChatTranscriptComponent"]) -> None:
        """Bind the sink to the mounted transcript.

        Args:
            transcript (Optional[ChatTranscriptComponent]): The mounted chat
                transcript, or ``None`` while it is not mounted (rows are
                then dropped without display).
        """
        self._transcript: Optional["ChatTranscriptComponent"] = transcript

    async def show(self, *, message: ChannelMessageDAO) -> None:
        """Display one channel row as a ``⊛`` transcript line.

        Args:
            message (ChannelMessageDAO): The note or notice being displayed.
        """
        if self._transcript is None:
            return
        await self._transcript.handle(
            command=TranscriptNoticeDAO(
                content=f"{NOTE_DISPLAY_PREFIX} {message.sender_name}: {message.message_contents}",
                classes="sub-agent-notice",
            )
        )

__all__ = ["TuiChannelAdapter", "TuiDisplaySink"]

_POLL_SECONDS: float = 0.5


class TuiChannelAdapter:
    """Channel adapter connecting the mounted TUI to the shared queue."""

    def __init__(self, *, app: "SloTUI", gateway: ChannelGateway) -> None:
        """Compose the adapter around the app and the shared gateway.

        Args:
            app (SloTUI): The mounted TUI app.
            gateway (ChannelGateway): The process-local shared gateway.
        """
        self._app: "SloTUI" = app
        self._gateway: ChannelGateway = gateway
        self._channel: Optional[ChannelDAO] = None
        self._user: Optional[ParticipantDAO] = None
        self._outbound_task: Optional[asyncio.Task[None]] = None
        self._stopping: bool = False

    @property
    def channel(self) -> ChannelDAO:
        """Return the registered TUI channel.

        Returns:
            ChannelDAO: The registered channel.

        Raises:
            RuntimeError: The adapter has not been started.
        """
        if self._channel is None:
            raise RuntimeError("TuiChannelAdapter is not started.")
        return self._channel

    @property
    def user_participant(self) -> ParticipantDAO:
        """Return the registered TUI user participant.

        Returns:
            ParticipantDAO: The registered user.

        Raises:
            RuntimeError: The adapter has not been started.
        """
        if self._user is None:
            raise RuntimeError("TuiChannelAdapter is not started.")
        return self._user

    async def start(self) -> None:
        """Register the channel and its user, and start the outbound loop.

        The TUI channel id is per-install, persisted under
        ``<SLO_HOME>/channels/tui.json`` so a restarted TUI keeps its identity.
        """
        channel_id: UUID = self._load_or_create_channel_id()
        self._channel = await self._gateway.register_channel(
            kind="tui",
            name=f"tui@{socket.gethostname()}",
            channel_id=channel_id,
        )
        self._user = await self._gateway.register_user(
            channel_id=self._channel.id,
            name=f"{getpass.getuser()} (tui)",
            external_ref="operator",
        )
        self._stopping = False
        self._outbound_task = asyncio.create_task(self._outbound_loop())

    async def stop(self) -> None:
        """Stop the outbound delivery loop."""
        self._stopping = True
        task: Optional[asyncio.Task[None]] = self._outbound_task
        self._outbound_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def send_prompt(self, *, text: str, force: bool = False) -> ChannelMessageDAO:
        """Enqueue one operator prompt for the session's agent.

        Pressing Enter only inserts a row; a run starts when the session's
        poller picks it up (108.1 §2: send, then run).

        Args:
            text (str): The prompt text.
            force (bool): True marks the row forced (108.2 wiring; normal
                sends pass False).

        Returns:
            ChannelMessageDAO: The stored row.
        """
        return await self._gateway.send(
            new=NewMessageDAO(
                sender_id=self.user_participant.id,
                recipient_id=channel_participant_id_for_session(session_id=self._app._session.session_id),
                message_contents=text,
                channel_id=self.channel.id,
                force=force,
            )
        )

    async def deliver(self, *, message: ChannelMessageDAO) -> None:
        """Deliver one outbound row to the operator.

        ``reply`` rows for TUI-sent prompts need no rendering when they come
        from the session's own agent (the stream already showed the answer);
        a reply from another agent renders as a ``↩`` transcript line.
        ``notice`` rows render as transcript notices, then everything is
        accepted.

        Args:
            message (ChannelMessageDAO): Outbound row addressed to the TUI user.
        """
        transcript = self._app._chat_transcript
        if message.message_type == "reply":
            own_agent: UUID = channel_participant_id_for_session(
                session_id=self._app._session.session_id
            )
            if message.sender_id != own_agent and transcript is not None:
                await transcript.handle(
                    command=TranscriptNoticeDAO(
                        content=(
                            f"{REPLY_DISPLAY_PREFIX} {message.sender_name}: "
                            f"{message.message_contents}"
                        ),
                        classes="tool-result",
                    )
                )
        elif message.message_type == "notice":
            if transcript is not None:
                await transcript.handle(
                    command=TranscriptNoticeDAO(
                        content=message.message_contents,
                        classes="tool-result",
                    )
                )
        await self._gateway.accept(message_id=message.id)

    async def queued(self) -> list[ChannelMessageDAO]:
        """Return the session's pending inbound rows, for the queued list.

        Returns:
            list[ChannelMessageDAO]: Pending rows for the session's agent, FIFO.
        """
        return await self._gateway.pending_inbound(
            recipient_id=channel_participant_id_for_session(session_id=self._app._session.session_id),
        )

    async def cancel(self, *, message_id: UUID) -> bool:
        """Cancel one queued row on the operator's behalf (108.1 §5.5).

        Args:
            message_id (UUID): The queued row's id.

        Returns:
            bool: Whether the row was cancelled; ``False`` when it is no
                longer pending (already running or already gone).
        """
        return await self._gateway.cancel(message_id=message_id)

    async def send_prompt_to_agent(
        self,
        *,
        session_id: str,
        text: str,
        force: bool = False,
    ) -> ChannelMessageDAO:
        """Enqueue one operator prompt for another agent (the orchestrator, 108.3).

        The row belongs to the target agent's conversation; its poller or
        runner picks it up. Sending to a closed agent raises.

        Args:
            session_id (str): Target agent session id (canonical or legacy).
            text (str): The prompt text.
            force (bool): True marks the row forced (Ctrl+Enter).

        Returns:
            ChannelMessageDAO: The stored row.

        Raises:
            RecipientClosedError: The target agent is closed.
        """
        return await self._gateway.send(
            new=NewMessageDAO(
                sender_id=self.user_participant.id,
                recipient_id=channel_participant_id_for_session(session_id=session_id),
                message_contents=text,
                channel_id=self.channel.id,
                force=force,
            )
        )

    async def sent_to_agent(self, *, session_id: str, limit: int = 5) -> list[SentMessageRowDAO]:
        """Return the composer rows for what this user sent to one agent.

        Args:
            session_id (str): Target agent session id.
            limit (int): Maximum rows, newest first. Defaults to 5.

        Returns:
            list[SentMessageRowDAO]: Composer rows with derived state and
                reply previews.
        """
        return await self._gateway.sent_rows(
            sender_id=self.user_participant.id,
            recipient_id=channel_participant_id_for_session(session_id=session_id),
            limit=limit,
        )

    async def agent_participant_status(self, *, session_id: str) -> Optional[str]:
        """Return one agent participant's status, or ``None`` when unknown.

        Args:
            session_id (str): Agent session id to look up.

        Returns:
            Optional[str]: ``open`` or ``closed``, or ``None`` when the
                participant has never registered.
        """
        participant: Optional[ParticipantDAO] = await self._gateway.get_participant(
            participant_id=channel_participant_id_for_session(session_id=session_id),
        )
        return participant.status if participant is not None else None

    async def _outbound_loop(self) -> None:
        """Poll for outbound rows addressed to the TUI user and deliver them."""
        while not self._stopping:
            try:
                rows: list[ChannelMessageDAO] = await self._gateway.pending_outbound(
                    recipient_ids=[self.user_participant.id],
                )
                for row in rows:
                    await self.deliver(message=row)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — delivery must survive a bad row
                log_warning(msg=f"tui channel outbound delivery failed: {exc}")
            await asyncio.sleep(_POLL_SECONDS)

    def _load_or_create_channel_id(self) -> UUID:
        """Load the per-install TUI channel id, creating it when missing.

        Returns:
            UUID: The stable channel id for this installation.
        """
        identity_path: Path = self._gateway.repository.db_path.parent / "tui.json"
        try:
            stored = json.loads(identity_path.read_text(encoding="utf-8"))
            return UUID(str(stored["channel_id"]))
        except (FileNotFoundError, ValueError, KeyError):
            channel_id: UUID = uuid4()
            identity_path.parent.mkdir(parents=True, exist_ok=True)
            identity_path.write_text(
                json.dumps({"channel_id": str(channel_id)}),
                encoding="utf-8",
            )
            os.chmod(path=identity_path, mode=0o600)
            return channel_id
