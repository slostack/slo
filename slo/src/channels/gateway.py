"""ChannelGateway — the one API every channel caller uses (108.1).

Adapters, the TUI, headless orchestrators and (later) the CLI all talk to the
queue through this application service; only the repository below it knows SQL.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from config.cfg import cfg

from typing import Literal

from src.channels.dao import (
    ChannelDAO,
    ChannelKind,
    ChannelMessageDAO,
    NewMessageDAO,
    ParticipantDAO,
    SentMessageRowDAO,
    utc_now,
)
from src.channels.errors import (
    AmbiguousAgentError,
    MessageCancelledError,
    ReplyTimeoutError,
    UnknownAgentError,
    UnknownMessageError,
)
from src.channels.repository import ChannelRepository

__all__ = ["ChannelGateway"]

_AGENT_PREFIX_PATTERN: re.Pattern[str] = re.compile(r"^[0-9a-f-]{1,36}$")
"""An agent id prefix: lowercase UUID text characters only (no SQL wildcards)."""

_WAIT_POLL_SECONDS: float = 0.2
"""How often ``wait_for_reply`` / ``wait_for_acceptance`` re-read the queue."""


class ChannelGateway:
    """Application service over the channel repository."""

    def __init__(self, *, repository: ChannelRepository) -> None:
        """Compose the gateway over one repository.

        Args:
            repository (ChannelRepository): Open (or to-be-opened) repository.
        """
        self._repository: ChannelRepository = repository
        self._wakes: dict[UUID, asyncio.Event] = {}

    @property
    def repository(self) -> ChannelRepository:
        """Return the repository (composition seam for adapters/tests).

        Returns:
            ChannelRepository: The repository this gateway wraps.
        """
        return self._repository

    @property
    def recovery_path(self) -> Optional[Path]:
        """Return the corrupt database copy preserved during the last successful open.

        Returns:
            Optional[Path]: The recovery copy path, or ``None`` if opening did
                not recover a corrupt database.
        """
        return self._repository.recovery_path

    @classmethod
    def default_channels_dir(cls) -> Path:
        """Return ``$SLO_HOME/channels``, where the queue and adapter files live.

        Adapter configuration (``telegram.json``) and attachment files sit next
        to ``channels.db`` in this directory (108.5 §2).

        Returns:
            Path: The channels directory for this user; it may not exist yet.
        """
        slo_home: Path = Path(str(cfg(key="SLO_HOME") or Path.home() / ".slo"))
        return slo_home / "channels"

    @classmethod
    def at_default_path(cls) -> "ChannelGateway":
        """Build (without opening) the gateway on ``$SLO_HOME/channels/channels.db``.

        Owners that must bind tools before they can await (the TUI builds its
        session tools in its constructor) create the gateway here and
        ``open()`` it later.

        Returns:
            ChannelGateway: A gateway whose repository is not open yet.
        """
        return cls(repository=ChannelRepository(db_path=cls.default_channels_dir() / "channels.db"))

    @staticmethod
    def stable_channel_id(*, kind: ChannelKind, name: str) -> UUID:
        """Return the deterministic channel id for one adapter instance (108.5 §6).

        An external adapter keeps the same ``channels`` row across restarts, so
        its users and their pending outbound rows survive while it is offline.
        Two adapters of the same kind with different names get different rows.

        Args:
            kind (ChannelKind): Platform type, e.g. ``telegram``.
            name (str): Adapter instance name, e.g. ``telegram``.

        Returns:
            UUID: A ``uuid5`` derived from the kind and the name.
        """
        return uuid5(NAMESPACE_URL, f"slo-channel:{kind}:{name}")

    @classmethod
    async def default(cls) -> "ChannelGateway":
        """Open the shared process gateway on ``$SLO_HOME/channels/channels.db``.

        Returns:
            ChannelGateway: A gateway whose repository is open on the shared
                database file for this user.
        """
        gateway: ChannelGateway = cls.at_default_path()
        await gateway.open()
        return gateway

    async def open(self) -> None:
        """Open the repository and retain any recovery-copy path for inspection.

        The path is available through ``recovery_path`` after a successful open;
        it is ``None`` when startup did not replace a corrupt database.
        """
        await self._repository.open()

    async def close(self) -> None:
        """Close the underlying repository."""
        await self._repository.close()

    async def register_channel(
        self,
        *,
        kind: ChannelKind,
        name: str,
        channel_id: Optional[UUID] = None,
    ) -> ChannelDAO:
        """Register (idempotently) one platform channel.

        Args:
            kind (ChannelKind): Platform type, e.g. ``tui``.
            name (str): Human-readable label, e.g. ``tui@host``.
            channel_id (Optional[UUID]): Stable id when the adapter persists
                one (TUI stores it in ``channels/tui.json``); otherwise new.

        Returns:
            ChannelDAO: The stored channel.
        """
        now = utc_now()
        channel: ChannelDAO = ChannelDAO(
            id=channel_id or uuid4(),
            kind=kind,
            name=name,
            created_at=now,
            last_seen_at=now,
        )
        return await self._repository.upsert_channel(channel=channel)

    async def register_user(
        self,
        *,
        channel_id: UUID,
        name: str,
        external_ref: Optional[str] = None,
    ) -> ParticipantDAO:
        """Register (idempotently) the user talking through one channel.

        Reuses the existing occupant of the channel's ``external_ref`` slot
        (refreshing its name and heartbeat) so a restarted adapter keeps its
        identity; pending rows addressed to it survive the restart.

        Args:
            channel_id (UUID): Channel the user talks through.
            name (str): Display name, e.g. ``sid (tui)``.
            external_ref (Optional[str]): Platform-side identity.

        Returns:
            ParticipantDAO: The stored participant.
        """
        if external_ref is not None:
            existing: Optional[ParticipantDAO] = await self._repository.participant_by_external_ref(
                channel_id=channel_id,
                external_ref=external_ref,
            )
            if existing is not None:
                refreshed: ParticipantDAO = existing.model_copy(
                    update={"name": name, "status": "open", "last_seen_at": utc_now()}
                )
                return await self._repository.upsert_participant(participant=refreshed)
        now = utc_now()
        participant: ParticipantDAO = ParticipantDAO(
            id=uuid4(),
            kind="user",
            name=name,
            channel_id=channel_id,
            external_ref=external_ref,
            status="open",
            last_seen_at=now,
            created_at=now,
        )
        return await self._repository.upsert_participant(participant=participant)

    async def register_system(self, *, channel_id: UUID, name: str, external_ref: str) -> ParticipantDAO:
        """Register (idempotently) one system sender talking through one channel.

        WHAT: The sender's identity is the channel's ``external_ref`` slot
            (``UNIQUE(channel_id, external_ref)``), so every process registering
            the same slot gets the same participant. Re-registration refreshes
            the name and heartbeat and reopens it; a slot still held by a
            ``user`` (a scheduler sender stored before system registration
            existed) converts in place, keeping its id and its pending rows.
        WHO: ``ScheduleChannelSender`` for every schedule fire.
        WHEN: Before each send; the upsert is a single atomic statement.

        A system sender is not an operator: a closed interactive session keeps
        its rows in the durable inbox (108.3 §6), and poller recovery never
        pauses on them (108.1 §6).

        Args:
            channel_id (UUID): Registered channel the sender talks through,
                e.g. the shared ``scheduler`` channel.
            name (str): Display name, e.g. ``scheduler Nightly``.
            external_ref (str): Stable sender identity within the channel,
                e.g. the schedule id.

        Returns:
            ParticipantDAO: The stored system participant.
        """
        now = utc_now()
        return await self._repository.claim_system_slot(
            participant=ParticipantDAO(
                id=uuid4(),
                kind="system",
                name=name,
                channel_id=channel_id,
                external_ref=external_ref,
                status="open",
                last_seen_at=now,
                created_at=now,
            )
        )

    async def register_agent(
        self, *, session_id: UUID, name: str, durable_inbox: bool = False
    ) -> ParticipantDAO:
        """Register (idempotently) one agent session participant, open.

        The agent's participant id IS its session id (overview §2.3).

        Args:
            session_id (UUID): Agent session id.
            name (str): Display name, e.g. ``slo <short id>``.
            durable_inbox (bool): ``True`` for an interactive session whose
                inbox outlives a closed process (108.3 §6); ``False`` for an
                agent that finishes for good (workflow, child).

        Returns:
            ParticipantDAO: The stored participant.
        """
        now = utc_now()
        participant: ParticipantDAO = ParticipantDAO(
            id=session_id,
            kind="agent",
            name=name,
            channel_id=None,
            external_ref=None,
            status="open",
            last_seen_at=now,
            created_at=now,
            durable_inbox=durable_inbox,
        )
        return await self._repository.upsert_participant(participant=participant)

    async def close_agent(self, *, session_id: UUID, reason: str) -> int:
        """Close one agent participant and cancel its pending inbound rows.

        The participant flip and the pending-row cancellation commit together
        (108.3 §2), so a send racing this close either inserts against the
        open participant or is refused by the closed one.

        Args:
            session_id (UUID): Agent session to close.
            reason (str): Cancellation reason for pending rows, e.g.
                ``session_closed``.

        Returns:
            int: Number of pending inbound rows cancelled.
        """
        return await self._repository.close_agent_atomic(participant_id=session_id, reason=reason)

    async def count_participants(self) -> int:
        """Count stored participants.

        Returns:
            int: Number of participant rows.
        """
        return await self._repository.count_participants()

    async def list_agents(self, *, open_only: bool = True) -> list[ParticipantDAO]:
        """Return agent participants, most recently seen first (108.5 ``slo channel agents``).

        Args:
            open_only (bool): ``True`` (default) lists only open agents.

        Returns:
            list[ParticipantDAO]: Agent participants, newest heartbeat first.
        """
        return await self._repository.list_agents(open_only=open_only)

    async def resolve_agent(self, *, prefix: str) -> ParticipantDAO:
        """Resolve an agent id prefix such as ``9b1e`` to one agent participant.

        WHAT: Matches the prefix (trimmed, case-insensitive) against agent ids.
        One open match wins even when closed agents share the prefix, so a
        stale closed session never shadows a live one. With no open match a
        single closed match is returned so callers can report "closed" rather
        than "unknown".
        WHO: ``slo channel send/follow --to`` and the adapter host's
        ``/attach <prefix>``.

        Args:
            prefix (str): Id prefix as typed by the user.

        Returns:
            ParticipantDAO: The resolved agent (``status`` may be ``closed``).

        Raises:
            UnknownAgentError: The prefix is empty, is not UUID text, or
                matches no agent.
            AmbiguousAgentError: Several open agents (or, with no open
                match, several closed agents) match.
        """
        normalized: str = prefix.strip().lower()
        if not _AGENT_PREFIX_PATTERN.fullmatch(normalized):
            raise UnknownAgentError(prefix=prefix)
        matches: list[ParticipantDAO] = await self._repository.agents_with_id_prefix(prefix=normalized)
        open_matches: list[ParticipantDAO] = [agent for agent in matches if agent.status == "open"]
        candidates: list[ParticipantDAO] = open_matches or matches
        if not candidates:
            raise UnknownAgentError(prefix=prefix)
        if len(candidates) > 1:
            raise AmbiguousAgentError(prefix=prefix, match_count=len(candidates))
        return candidates[0]

    async def wait_for_reply(self, *, message_id: UUID, timeout: float) -> ChannelMessageDAO:
        """Wait until a ``reply`` row answers one message, and return it.

        WHAT: Re-reads the queue every 200 ms (the reply is usually written by
        another process). Returns the earliest correlated reply in its stored
        state, which may be pending, accepted or cancelled. Callers should
        deliver only pending replies and accept one only after delivery.
        WHO: ``slo channel send --wait``.

        Args:
            message_id (UUID): The request whose reply to wait for.
            timeout (float): Seconds to wait before giving up.

        Returns:
            ChannelMessageDAO: The first reply row answering the request.

        Raises:
            UnknownMessageError: The request is not in the queue.
            MessageCancelledError: The request was cancelled before a reply
                arrived (for example the agent closed: ``recipient_closed``).
            ReplyTimeoutError: No reply arrived within ``timeout``.
        """

        async def _reply_or_none() -> Optional[ChannelMessageDAO]:
            reply: Optional[ChannelMessageDAO] = await self._repository.reply_for(message_id=message_id)
            if reply is not None:
                return reply
            await self._ensure_awaited_message_live(message_id=message_id, accepted_is_final=False)
            return None

        return await self._poll_until(probe=_reply_or_none, message_id=message_id, timeout=timeout)

    async def wait_for_acceptance(self, *, message_id: UUID, timeout: float) -> ChannelMessageDAO:
        """Wait until one message is accepted, and return the accepted row.

        A forced message gets no reply row; its acknowledgement is
        ``accepted_at`` (108.3 §2), so ``slo channel send --force --wait``
        waits for this instead of a reply.

        Args:
            message_id (UUID): The message to watch.
            timeout (float): Seconds to wait before giving up.

        Returns:
            ChannelMessageDAO: The row with ``accepted_at`` set.

        Raises:
            UnknownMessageError: The message is not in the queue.
            MessageCancelledError: The message was cancelled first.
            ReplyTimeoutError: It was not accepted within ``timeout``.
        """

        async def _accepted_or_none() -> Optional[ChannelMessageDAO]:
            return await self._ensure_awaited_message_live(message_id=message_id, accepted_is_final=True)

        return await self._poll_until(probe=_accepted_or_none, message_id=message_id, timeout=timeout)

    async def channel_users(self, *, channel_id: UUID) -> list[ParticipantDAO]:
        """Return the users who talk through one channel (adapter host outbound loop).

        Args:
            channel_id (UUID): The adapter's channel.

        Returns:
            list[ParticipantDAO]: User participants of that channel.
        """
        return await self._repository.channel_users(channel_id=channel_id)

    async def get_channel(self, *, channel_id: UUID) -> Optional[ChannelDAO]:
        """Return one stored channel.

        Args:
            channel_id (UUID): Channel to look up.

        Returns:
            Optional[ChannelDAO]: The stored channel, or ``None``.
        """
        return await self._repository.get_channel(channel_id=channel_id)

    async def last_message_index(self, *, agent_session_id: UUID) -> int:
        """Return the newest ``message_index`` of one conversation (``slo channel follow``).

        Args:
            agent_session_id (UUID): Conversation to inspect.

        Returns:
            int: The newest index, or 0 when the conversation is empty.
        """
        return await self._repository.last_message_index(agent_session_id=agent_session_id)

    async def heartbeat_channel(self, *, channel_id: UUID) -> None:
        """Refresh one channel's ``last_seen_at`` (the adapter host's heartbeat).

        Args:
            channel_id (UUID): Channel to stamp.
        """
        await self._repository.heartbeat_channel(channel_id=channel_id)

    async def _ensure_awaited_message_live(
        self, *, message_id: UUID, accepted_is_final: bool
    ) -> Optional[ChannelMessageDAO]:
        """Reject an awaited message that is missing or cancelled.

        Args:
            message_id (UUID): The awaited message.
            accepted_is_final (bool): ``True`` returns the row once accepted
                (acceptance waits); ``False`` never returns it (reply waits).

        Returns:
            Optional[ChannelMessageDAO]: The accepted row when
                ``accepted_is_final`` and it is accepted; otherwise ``None``.

        Raises:
            UnknownMessageError: The message is not in the queue.
            MessageCancelledError: The message was cancelled.
        """
        stored: Optional[ChannelMessageDAO] = await self._repository.get(message_id=message_id)
        if stored is None:
            raise UnknownMessageError(message_id=message_id)
        if stored.cancelled_at is not None:
            raise MessageCancelledError(message_id=message_id, reason=stored.cancel_reason or "cancelled")
        if accepted_is_final and stored.accepted_at is not None:
            return stored
        return None

    async def _poll_until(
        self,
        *,
        probe: Callable[[], Awaitable[Optional[ChannelMessageDAO]]],
        message_id: UUID,
        timeout: float,
    ) -> ChannelMessageDAO:
        """Run ``probe`` every 200 ms until it returns a row or ``timeout`` elapses.

        Args:
            probe (Callable[[], Awaitable[Optional[ChannelMessageDAO]]]): Reads
                the queue once; returns the awaited row or ``None``, or raises.
            message_id (UUID): The awaited message (for the timeout error).
            timeout (float): Seconds before giving up.

        Returns:
            ChannelMessageDAO: The row ``probe`` returned.

        Raises:
            ReplyTimeoutError: ``probe`` returned ``None`` until the deadline.
        """
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        deadline: float = loop.time() + timeout
        while True:
            found: Optional[ChannelMessageDAO] = await probe()
            if found is not None:
                return found
            remaining: float = deadline - loop.time()
            if remaining <= 0:
                raise ReplyTimeoutError(message_id=message_id, timeout=timeout)
            await asyncio.sleep(min(_WAIT_POLL_SECONDS, remaining))

    async def recent_sent_messages(
        self,
        *,
        sender_id: UUID,
        recipient_id: UUID,
        limit: int = 5,
    ) -> list[ChannelMessageDAO]:
        """Return the newest rows one participant sent to another, newest first.

        Args:
            sender_id (UUID): The sending participant (the channel's user).
            recipient_id (UUID): The target agent participant.
            limit (int): Maximum rows to return.

        Returns:
            list[ChannelMessageDAO]: Rows newest first.
        """
        return await self._repository.recent_sent_messages(
            sender_id=sender_id,
            recipient_id=recipient_id,
            limit=limit,
        )

    async def reply_for(self, *, message_id: UUID) -> Optional[ChannelMessageDAO]:
        """Return the earliest reply row answering one message, regardless of delivery state.

        Lookup includes pending, accepted and cancelled replies; it neither
        filters for deliverability nor changes the row's state. Callers decide
        whether to deliver a pending reply and accept it only after delivery
        succeeds.

        Args:
            message_id (UUID): The message the reply must answer.

        Returns:
            Optional[ChannelMessageDAO]: The reply row, or ``None``.
        """
        return await self._repository.reply_for(message_id=message_id)

    async def sent_rows(
        self,
        *,
        sender_id: UUID,
        recipient_id: UUID,
        limit: int = 5,
    ) -> list[SentMessageRowDAO]:
        """Return composer rows for what one participant sent to another (108.3 §4).

        State derives from ``accepted_at`` / ``cancelled_at``; the reply
        preview comes from the earliest reply row, including while pending.

        Args:
            sender_id (UUID): The sending participant (the channel's user).
            recipient_id (UUID): The target agent participant.
            limit (int): Maximum rows to return.

        Returns:
            list[SentMessageRowDAO]: Composer rows, newest first.
        """
        rows: list[ChannelMessageDAO] = await self._repository.recent_sent_messages(
            sender_id=sender_id,
            recipient_id=recipient_id,
            limit=limit,
        )
        result: list[SentMessageRowDAO] = []
        for row in rows:
            reply: Optional[ChannelMessageDAO] = await self._repository.reply_for(message_id=row.id)
            state: Literal["queued", "accepted", "cancelled"]
            if row.cancelled_at is not None:
                state = "cancelled"
            elif row.accepted_at is not None:
                state = "accepted"
            else:
                state = "queued"
            result.append(
                SentMessageRowDAO(
                    message_id=row.id,
                    preview=row.message_contents[:80],
                    forced=row.forced_at is not None,
                    state=state,
                    reply_preview=reply.message_contents[:80] if reply is not None else None,
                    cancel_reason=row.cancel_reason,
                )
            )
        return result

    async def recent_notes_to(self, *, recipient_id: UUID, limit: int = 5) -> list[ChannelMessageDAO]:
        """Return the newest notes addressed to one agent, newest first (108.4 C3).

        Args:
            recipient_id (UUID): The viewed agent participant.
            limit (int): Maximum rows to return.

        Returns:
            list[ChannelMessageDAO]: Note rows newest first.
        """
        return await self._repository.recent_notes_to(recipient_id=recipient_id, limit=limit)

    async def get_participant(self, *, participant_id: UUID) -> Optional[ParticipantDAO]:
        """Return one participant by id.

        Args:
            participant_id (UUID): Participant to look up.

        Returns:
            Optional[ParticipantDAO]: The stored participant, or ``None``.
        """
        return await self._repository.get_participant(participant_id=participant_id)

    async def send(self, *, new: NewMessageDAO) -> ChannelMessageDAO:
        """Insert one message and wake the in-process poller if there is one.

        Args:
            new (NewMessageDAO): Sender-supplied message data.

        Returns:
            ChannelMessageDAO: The stored row.
        """
        stored: ChannelMessageDAO = await self._repository.insert_message(new=new)
        wake: Optional[asyncio.Event] = self._wakes.get(stored.recipient_id)
        if wake is not None:
            wake.set()
        return stored

    async def conversation(
        self,
        *,
        agent_session_id: UUID,
        after_index: int = 0,
        limit: int = 200,
    ) -> list[ChannelMessageDAO]:
        """Return one conversation's rows after an index, in order (test support).

        Args:
            agent_session_id (UUID): Conversation to read.
            after_index (int): Only rows with ``message_index`` greater than this.
            limit (int): Maximum rows to return.

        Returns:
            list[ChannelMessageDAO]: Rows in ``message_index`` order.
        """
        return await self._repository.conversation(
            agent_session_id=agent_session_id,
            after_index=after_index,
            limit=limit,
        )

    async def cancel(self, *, message_id: UUID, by: Optional[UUID] = None, reason: str = "operator") -> bool:
        """Cancel a pending row on behalf of a participant or the recipient agent.

        When ``by`` is given, only the sender or the recipient may cancel, and
        only while the row is neither accepted nor cancelled. When ``by`` is
        ``None`` the call is an internal system cancellation (the recipient
        agent's poller, e.g. ``start_failed``); no actor check applies.

        Args:
            message_id (UUID): Row to cancel.
            by (Optional[UUID]): Participant requesting the cancellation.
            reason (str): Cancellation reason recorded on the row.

        Returns:
            bool: ``True`` when the row was cancelled by this call.
        """
        stored: Optional[ChannelMessageDAO] = await self._repository.get(message_id=message_id)
        if stored is None:
            return False
        if by is not None and by not in (stored.sender_id, stored.recipient_id):
            return False
        return await self._repository.cancel(message_id=message_id, reason=reason)

    async def force(self, *, message_id: UUID, by: UUID) -> bool:
        """Force a pending row into the current run at its next boundary (108.2).

        Only the sender or the recipient may force, and only while the row is
        neither accepted nor cancelled. Forcing an already-forced row is a
        no-op success. The recipient's in-process poller is woken so an idle
        agent starts the forced row at once (108.2 F3).

        Args:
            message_id (UUID): Row to force.
            by (UUID): Participant requesting the force.

        Returns:
            bool: ``True`` when the row is now forced; ``False`` when it was
                accepted, cancelled, unknown, or ``by`` is an outside actor.
        """
        stored: Optional[ChannelMessageDAO] = await self._repository.get(message_id=message_id)
        if stored is None:
            return False
        if by not in (stored.sender_id, stored.recipient_id):
            return False
        forced: bool = await self._repository.force(message_id=message_id)
        if forced:
            wake: Optional[asyncio.Event] = self._wakes.get(stored.recipient_id)
            if wake is not None:
                wake.set()
        return forced

    async def accept(self, *, message_id: UUID) -> bool:
        """Accept a row exactly once (see repository).

        Args:
            message_id (UUID): Row to accept.

        Returns:
            bool: Whether this call performed the acceptance.
        """
        return await self._repository.accept(message_id=message_id)

    async def get(self, *, message_id: UUID) -> Optional[ChannelMessageDAO]:
        """Return one stored row.

        Args:
            message_id (UUID): Row to look up.

        Returns:
            Optional[ChannelMessageDAO]: The stored row, or ``None``.
        """
        return await self._repository.get(message_id=message_id)

    async def pending_inbound(self, *, recipient_id: UUID) -> list[ChannelMessageDAO]:
        """Return pending inbound rows for one recipient, FIFO.

        Args:
            recipient_id (UUID): Recipient to check.

        Returns:
            list[ChannelMessageDAO]: Pending rows in index order.
        """
        return await self._repository.pending_inbound(recipient_id=recipient_id)

    async def pending_outbound(self, *, recipient_ids: list[UUID]) -> list[ChannelMessageDAO]:
        """Return pending outbound rows addressed to any of the recipients.

        Args:
            recipient_ids (list[UUID]): Recipients to check.

        Returns:
            list[ChannelMessageDAO]: Pending outbound rows.
        """
        return await self._repository.pending_outbound(recipient_ids=recipient_ids)

    async def heartbeat(self, *, participant_id: UUID) -> None:
        """Refresh one participant's heartbeat.

        Args:
            participant_id (UUID): Participant to stamp.
        """
        await self._repository.heartbeat(participant_id=participant_id)

    def local_wake(self, *, recipient_id: UUID) -> asyncio.Event:
        """Return the shared wake event for one recipient's in-process poller.

        ``send()`` sets this event when the recipient matches, so a local
        send wakes the poller without waiting for the next poll tick.

        Args:
            recipient_id (UUID): Participant whose poller waits on the event.

        Returns:
            asyncio.Event: The shared wake event for that recipient.
        """
        wake: Optional[asyncio.Event] = self._wakes.get(recipient_id)
        if wake is None:
            wake = asyncio.Event()
            self._wakes[recipient_id] = wake
        return wake
