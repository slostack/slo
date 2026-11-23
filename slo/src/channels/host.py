"""AdapterHost — runs one external channel adapter in the foreground (108.5 §5).

``slo channel run <name>`` builds one adapter and hands it to this host. The
host owns the adapter's whole lifecycle:

```text
 run()
  ├─ register the channel (stable id from kind + name)
  ├─ install SIGINT/SIGTERM handlers
  ├─ adapter.start(ctx)                 adapter reads its platform → ctx.inbound(...)
  ├─ loop until a signal or request_stop():
  │    heartbeat the channel every 5 s
  │    pending_outbound(users of this channel) → adapter.deliver → accept
  │    (a failed delivery stays pending; that user backs off 1 s → 60 s)
  └─ adapter.stop(); remove the signal handlers; return the exit code
```

Exit codes: ``0`` after a clean stop, ``1`` when the adapter is misconfigured
or fails to start.
"""

from __future__ import annotations

import asyncio
import signal
import sqlite3
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Optional, get_args
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from config.logger import log_error, log_info, log_warning

from src.channels.attachments import AttachmentStore
from src.channels.dao import (
    AttachmentDAO,
    ChannelDAO,
    ChannelKind,
    ChannelMessageDAO,
    InboundTextDAO,
    NewMessageDAO,
    ParticipantDAO,
    utc_now,
)
from src.channels.errors import (
    AdapterConfigError,
    AmbiguousAgentError,
    RecipientClosedError,
    UnknownAgentError,
    UnknownParticipantError,
)
from src.channels.gateway import ChannelGateway
from src.channels.protocol import ChannelAdapter

__all__ = [
    "AGENT_FINISHED_TEXT",
    "AdapterHost",
    "DeliveryBackoff",
    "HELP_TEXT",
    "HostAdapterContext",
    "NOT_ATTACHED_TEXT",
    "describe_agent",
]

EXIT_OK: int = 0
"""Exit code after a clean stop (signal or ``request_stop``)."""

EXIT_CONFIG_ERROR: int = 1
"""Exit code when the adapter is misconfigured or fails to start."""

NOT_ATTACHED_TEXT: str = "Not attached to an agent — /agents to list them, /attach <id> to pick one."
"""Answer to plain text from a user who has no attached agent."""

AGENT_FINISHED_TEXT: str = "agent finished — /agents to pick another"
"""Answer when the attached (or requested) agent is closed (108.5 §6)."""

HELP_TEXT: str = (
    "Commands: /agents (list open agents), /attach <id> (talk to one), /detach, "
    "/force <text> (send into its current run). Anything else goes to the attached agent."
)
"""Answer to an unknown adapter command."""

TOO_LONG_TEXT: str = "Message too long (max 64 KiB)."
"""Answer when a message exceeds the queue's 64 KiB column limit."""

QUEUE_FAILED_TEXT: str = "Slo could not queue that message; try again."
"""Answer when the queue database refused the write (for example locked > 5 s)."""

_HEARTBEAT_SECONDS: float = 5.0
_COMMAND_WORD_PREFIX: str = "/"


def describe_agent(*, agent: ParticipantDAO, now: datetime) -> str:
    """Return one human line for an agent: id prefix, name, last seen.

    Shared by ``/agents`` and ``slo channel agents`` so both list agents the
    same way.

    Args:
        agent (ParticipantDAO): The agent participant.
        now (datetime): Current UTC time, for the "last seen" age.

    Returns:
        str: e.g. ``9b1e2c4d  slo 9b1e2c4d  last seen 12s ago``.
    """
    seconds: int = max(0, int((now - agent.last_seen_at).total_seconds()))
    age: str
    if seconds < 60:
        age = f"{seconds}s"
    elif seconds < 3600:
        age = f"{seconds // 60}m"
    elif seconds < 86_400:
        age = f"{seconds // 3600}h"
    else:
        age = f"{seconds // 86_400}d"
    return f"{str(agent.id)[:8]}  {agent.name}  last seen {age} ago"


class DeliveryBackoff:
    """Per-recipient retry schedule for failed deliveries (1 s → 60 s, doubling).

    Keyed by the recipient user, so one user whose platform rejects messages
    never delays another user's replies, and one user's rows stay in order.
    """

    def __init__(self, *, initial_s: float, max_s: float) -> None:
        """Configure the schedule.

        Args:
            initial_s (float): Delay after the first failure.
            max_s (float): Upper bound for any delay.
        """
        self._initial_s: float = initial_s
        self._max_s: float = max_s
        self._failures: dict[UUID, int] = {}
        self._not_before: dict[UUID, float] = {}

    def delay_after(self, *, failures: int) -> float:
        """Return the delay after ``failures`` consecutive failures.

        Args:
            failures (int): Consecutive failures so far (at least 1).

        Returns:
            float: ``initial_s * 2 ** (failures - 1)``, capped at ``max_s``.
        """
        return min(self._max_s, self._initial_s * (2 ** max(0, failures - 1)))

    def is_ready(self, *, key: UUID, now: float) -> bool:
        """Return whether a delivery to ``key`` may be attempted at ``now``.

        Args:
            key (UUID): The recipient user.
            now (float): Current loop time in seconds.

        Returns:
            bool: ``True`` when no backoff is pending or it has elapsed.
        """
        return now >= self._not_before.get(key, 0.0)

    def record_failure(self, *, key: UUID, now: float) -> float:
        """Count one failure for ``key`` and start its next delay.

        Args:
            key (UUID): The recipient user.
            now (float): Current loop time in seconds.

        Returns:
            float: The delay before the next attempt.
        """
        failures: int = self._failures.get(key, 0) + 1
        self._failures[key] = failures
        delay: float = self.delay_after(failures=failures)
        self._not_before[key] = now + delay
        return delay

    def record_success(self, *, key: UUID) -> None:
        """Reset ``key`` after a successful delivery.

        Args:
            key (UUID): The recipient user.
        """
        self._failures.pop(key, None)
        self._not_before.pop(key, None)


class HostAdapterContext:
    """The ``AdapterContext`` the host gives its adapter (108.5 §5).

    Owns the inbound policy: user registration, the adapter commands and
    sending text to the attached agent. Attachments live in the injected
    ``AttachmentStore``.
    """

    def __init__(
        self,
        *,
        channel: ChannelDAO,
        gateway: ChannelGateway,
        attachments: AttachmentStore,
        log: Callable[..., None],
    ) -> None:
        """Bind the context to the registered channel and its collaborators.

        Args:
            channel (ChannelDAO): The adapter's registered channel.
            gateway (ChannelGateway): The shared queue API.
            attachments (AttachmentStore): This channel's attachments.
            log (Callable[..., None]): The host's log function
                (``log(msg=..., **fields)``).
        """
        self._channel: ChannelDAO = channel
        self._gateway: ChannelGateway = gateway
        self._attachments: AttachmentStore = attachments
        self._log: Callable[..., None] = log
        self._commands: dict[str, Callable[..., Awaitable[ChannelMessageDAO | str]]] = {
            "/agents": self._list_agents,
            "/attach": self._attach,
            "/detach": self._detach,
            "/force": self._force,
            "/help": self._help,
            "/start": self._help,
        }

    @property
    def channel(self) -> ChannelDAO:
        """Return the adapter's registered channel.

        Returns:
            ChannelDAO: The channel row.
        """
        return self._channel

    def log(self, *, msg: str, **fields: object) -> None:
        """Write one line to the host's log.

        Args:
            msg (str): What happened.
            **fields (object): Extra ``key=value`` context.
        """
        self._log(msg=msg, **fields)

    async def inbound(self, *, item: InboundTextDAO) -> ChannelMessageDAO | str:
        """Register the user, then run an adapter command or send to the attached agent.

        WHAT: ``/agents``, ``/attach <id>``, ``/detach``, ``/force <text>`` and
        ``/help`` are adapter commands; any other ``/word`` gets the help text;
        everything else is a prompt to the attached agent (forced when
        ``item.force``).
        WHO: The adapter, for every message from an allow-listed user.

        Args:
            item (InboundTextDAO): The platform message.

        Returns:
            ChannelMessageDAO | str: The stored row, or a short answer for the user.
        """
        user: ParticipantDAO = await self._gateway.register_user(
            channel_id=self._channel.id,
            name=item.display_name,
            external_ref=item.external_user_ref,
        )
        command, argument = _split_command(text=item.text)
        if command is None:
            return await self._send_to_attached(user=user, item=item, text=item.text, force=item.force)
        handler: Optional[Callable[..., Awaitable[ChannelMessageDAO | str]]] = self._commands.get(command)
        if handler is None:
            return HELP_TEXT
        return await handler(user=user, item=item, argument=argument)

    async def _help(self, *, user: ParticipantDAO, item: InboundTextDAO, argument: str) -> str:
        """Answer ``/help`` (and Telegram's first-contact ``/start``)."""
        return HELP_TEXT

    async def _list_agents(self, *, user: ParticipantDAO, item: InboundTextDAO, argument: str) -> str:
        """Answer ``/agents`` with one line per open agent."""
        agents: list[ParticipantDAO] = await self._gateway.list_agents(open_only=True)
        if not agents:
            return "No open agents."
        now: datetime = utc_now()
        return "\n".join(describe_agent(agent=agent, now=now) for agent in agents)

    async def _attach(self, *, user: ParticipantDAO, item: InboundTextDAO, argument: str) -> str:
        """Attach the user to the agent matching ``argument`` (an id prefix)."""
        if not argument:
            return "Usage: /attach <id> — /agents lists the ids."
        try:
            agent: ParticipantDAO = await self._gateway.resolve_agent(prefix=argument)
        except UnknownAgentError:
            return f"No agent matches {argument!r} — /agents to list them."
        except AmbiguousAgentError as ambiguous:
            return f"{ambiguous.match_count} agents match {argument!r} — use more characters."
        if agent.status != "open":
            return AGENT_FINISHED_TEXT
        self._attachments.attach(participant_id=user.id, agent_id=agent.id)
        return f"Attached to {agent.name} ({str(agent.id)[:8]})."

    async def _detach(self, *, user: ParticipantDAO, item: InboundTextDAO, argument: str) -> str:
        """Detach the user from their agent."""
        self._attachments.detach(participant_id=user.id)
        return "Detached. /attach <id> to talk to an agent again."

    async def _force(
        self, *, user: ParticipantDAO, item: InboundTextDAO, argument: str
    ) -> ChannelMessageDAO | str:
        """Send ``argument`` forced into the attached agent's current run."""
        if not argument:
            return "Usage: /force <text>"
        return await self._send_to_attached(user=user, item=item, text=argument, force=True)

    async def _send_to_attached(
        self, *, user: ParticipantDAO, item: InboundTextDAO, text: str, force: bool
    ) -> ChannelMessageDAO | str:
        """Send one prompt to the user's attached agent.

        A closed or vanished agent clears the attachment and answers
        ``AGENT_FINISHED_TEXT`` (108.5 §6), whether the close is seen before
        the send or raced by it.

        Args:
            user (ParticipantDAO): The sending platform user.
            item (InboundTextDAO): The platform message (for its message ref).
            text (str): The prompt text.
            force (bool): ``True`` forces it into the agent's current run.

        Returns:
            ChannelMessageDAO | str: The stored row, or the answer for the user.
        """
        attachment: Optional[AttachmentDAO] = self._attachments.get(participant_id=user.id)
        if attachment is None or attachment.agent_id is None:
            return NOT_ATTACHED_TEXT
        agent: Optional[ParticipantDAO] = await self._gateway.get_participant(
            participant_id=attachment.agent_id
        )
        if agent is None or agent.status != "open":
            self._attachments.detach(participant_id=user.id)
            return AGENT_FINISHED_TEXT
        try:
            new: NewMessageDAO = self._build_prompt(
                user=user, item=item, agent_id=agent.id, text=text, force=force
            )
        except ValidationError:
            return TOO_LONG_TEXT
        try:
            return await self._gateway.send(new=new)
        except (RecipientClosedError, UnknownParticipantError):
            self._attachments.detach(participant_id=user.id)
            return AGENT_FINISHED_TEXT
        except sqlite3.Error as exc:
            self._log(msg="queue write failed", error=type(exc).__name__)
            return QUEUE_FAILED_TEXT

    def _build_prompt(
        self, *, user: ParticipantDAO, item: InboundTextDAO, agent_id: UUID, text: str, force: bool
    ) -> NewMessageDAO:
        """Build the queue row for one prompt.

        With a platform message ref the row id is a ``uuid5`` of channel, user
        and message ref, so a platform redelivery returns the existing row
        instead of queuing a second run.

        Args:
            user (ParticipantDAO): The sending platform user.
            item (InboundTextDAO): The platform message.
            agent_id (UUID): The attached agent.
            text (str): The prompt text.
            force (bool): ``True`` sets ``forced_at``.

        Returns:
            NewMessageDAO: The row to send.

        Raises:
            ValidationError: ``text`` exceeds 64 KiB.
        """
        fields: dict[str, object] = {
            "sender_id": user.id,
            "recipient_id": agent_id,
            "message_contents": text,
            "channel_id": self._channel.id,
            "force": force,
        }
        if item.external_message_ref is not None:
            fields["id"] = uuid5(
                NAMESPACE_URL,
                f"slo-inbound:{self._channel.id}:{item.external_user_ref}:{item.external_message_ref}",
            )
        return NewMessageDAO.model_validate(fields)


class AdapterHost:
    """Runs one ``ChannelAdapter`` until SIGINT/SIGTERM (``slo channel run``)."""

    def __init__(
        self,
        *,
        adapter: ChannelAdapter,
        gateway: ChannelGateway,
        poll_interval: float = 1.0,
        initial_backoff_s: float = 1.0,
        max_backoff_s: float = 60.0,
        heartbeat_interval_s: float = _HEARTBEAT_SECONDS,
    ) -> None:
        """Compose the host around one adapter and an open gateway.

        Args:
            adapter (ChannelAdapter): The adapter to run.
            gateway (ChannelGateway): An open gateway; the caller closes it.
            poll_interval (float): Seconds between outbound polls.
            initial_backoff_s (float): Retry delay after a first failed delivery.
            max_backoff_s (float): Cap for the doubling retry delay.
            heartbeat_interval_s (float): Seconds between channel heartbeats.
        """
        self._adapter: ChannelAdapter = adapter
        self._gateway: ChannelGateway = gateway
        self._poll_interval: float = poll_interval
        self._heartbeat_interval_s: float = heartbeat_interval_s
        self._backoff: DeliveryBackoff = DeliveryBackoff(initial_s=initial_backoff_s, max_s=max_backoff_s)
        self._stop_requested: asyncio.Event = asyncio.Event()
        self._installed_signals: list[signal.Signals] = []

    def request_stop(self) -> None:
        """Ask a running host to stop after its current tick (same as SIGTERM)."""
        self._stop_requested.set()

    async def run(self) -> int:
        """Run the adapter until a stop signal; return the process exit code.

        Returns:
            int: ``0`` after a clean stop; ``1`` when the adapter kind is not a
                queue channel kind, or the adapter fails to start.
        """
        try:
            channel: ChannelDAO = await self._register_channel()
        except AdapterConfigError as exc:
            self._log(msg=f"config error: {exc}")
            return EXIT_CONFIG_ERROR
        context: HostAdapterContext = HostAdapterContext(
            channel=channel,
            gateway=self._gateway,
            attachments=AttachmentStore(
                path=self._gateway.repository.db_path.parent / f"{channel.id}.json",
                channel_id=channel.id,
            ),
            log=self._log,
        )
        self._install_signal_handlers()
        try:
            if not await self._start_adapter(context=context):
                return EXIT_CONFIG_ERROR
            self._log(msg="running", channel_id=str(channel.id))
            await self._serve(channel=channel)
            return EXIT_OK
        finally:
            await self._stop_adapter()
            self._remove_signal_handlers()

    async def _register_channel(self) -> ChannelDAO:
        """Register the adapter's channel under its stable id.

        Returns:
            ChannelDAO: The stored channel.

        Raises:
            AdapterConfigError: The adapter's kind is not a channel kind.
        """
        kind: str = self._adapter.kind
        known_kinds: tuple[str, ...] = get_args(ChannelKind)
        if kind not in known_kinds:
            raise AdapterConfigError(f"adapter kind {kind!r} is not one of {', '.join(known_kinds)}")
        channel_kind: ChannelKind = kind  # type: ignore[assignment]  # narrowed by the check above
        return await self._gateway.register_channel(
            kind=channel_kind,
            name=self._adapter.name,
            channel_id=ChannelGateway.stable_channel_id(kind=channel_kind, name=self._adapter.name),
        )

    async def _start_adapter(self, *, context: HostAdapterContext) -> bool:
        """Start the adapter, reporting (not raising) a failed start.

        Args:
            context (HostAdapterContext): The context handed to the adapter.

        Returns:
            bool: ``True`` when the adapter started.
        """
        try:
            await self._adapter.start(ctx=context)
        except AdapterConfigError as exc:
            self._log(msg=f"config error: {exc}")
            return False
        except Exception as exc:  # noqa: BLE001 — any start failure is reported as exit 1
            log_error(msg=f"channel adapter {self._adapter.name} failed to start: {exc}")
            self._log(msg=f"failed to start: {type(exc).__name__}: {exc}")
            return False
        return True

    async def _serve(self, *, channel: ChannelDAO) -> None:
        """Heartbeat and deliver outbound rows until a stop is requested.

        Args:
            channel (ChannelDAO): The adapter's channel.
        """
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        next_heartbeat: float = loop.time() + self._heartbeat_interval_s
        while not self._stop_requested.is_set():
            if loop.time() >= next_heartbeat:
                next_heartbeat = loop.time() + self._heartbeat_interval_s
                await self._heartbeat(channel=channel)
            try:
                await self._deliver_pending(channel=channel)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — one bad tick must not stop the adapter
                log_warning(msg=f"channel {channel.name} outbound tick failed: {exc}")
            try:
                await asyncio.wait_for(self._stop_requested.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass

    async def _heartbeat(self, *, channel: ChannelDAO) -> None:
        """Stamp the channel's ``last_seen_at`` (best effort).

        Args:
            channel (ChannelDAO): The adapter's channel.
        """
        try:
            await self._gateway.heartbeat_channel(channel_id=channel.id)
        except sqlite3.Error as exc:
            log_warning(msg=f"channel {channel.name} heartbeat failed: {exc}")

    async def _deliver_pending(self, *, channel: ChannelDAO) -> None:
        """Deliver this channel's pending outbound rows, in order per user.

        A failed delivery leaves the row pending, backs that user off and skips
        their later rows this tick (so they never arrive out of order); other
        users carry on.

        Args:
            channel (ChannelDAO): The adapter's channel.
        """
        users: dict[UUID, ParticipantDAO] = {
            user.id: user for user in await self._gateway.channel_users(channel_id=channel.id)
        }
        rows: list[ChannelMessageDAO] = await self._gateway.pending_outbound(recipient_ids=list(users))
        held: set[UUID] = set()
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        for row in rows:
            if self._stop_requested.is_set():
                return
            if row.recipient_id in held or not self._backoff.is_ready(key=row.recipient_id, now=loop.time()):
                held.add(row.recipient_id)
                continue
            if await self._deliver_one(row=row, user=users[row.recipient_id]):
                await self._gateway.accept(message_id=row.id)
                self._backoff.record_success(key=row.recipient_id)
                continue
            delay: float = self._backoff.record_failure(key=row.recipient_id, now=loop.time())
            held.add(row.recipient_id)
            self._log(msg="delivery failed; will retry", message_id=str(row.id)[:8], retry_in_s=f"{delay:g}")

    async def _deliver_one(self, *, row: ChannelMessageDAO, user: ParticipantDAO) -> bool:
        """Hand one row to the adapter; an exception counts as a failed delivery.

        Args:
            row (ChannelMessageDAO): The pending outbound row.
            user (ParticipantDAO): Its recipient.

        Returns:
            bool: Whether the platform took the message.
        """
        try:
            return bool(await self._adapter.deliver(message=row, user=user))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a platform error leaves the row pending
            self._log(msg="deliver raised", error=f"{type(exc).__name__}: {exc}")
            return False

    async def _stop_adapter(self) -> None:
        """Stop the adapter, logging (not raising) a failed stop."""
        try:
            await self._adapter.stop()
        except Exception as exc:  # noqa: BLE001 — shutdown must finish
            log_warning(msg=f"channel adapter {self._adapter.name} failed to stop cleanly: {exc}")
        self._log(msg="stopped")

    def _install_signal_handlers(self) -> None:
        """Make SIGINT and SIGTERM request a clean stop (main thread only)."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, self.request_stop)
            except (NotImplementedError, RuntimeError, ValueError):
                continue  # not the main thread (embedded use); request_stop() still works
            self._installed_signals.append(signum)

    def _remove_signal_handlers(self) -> None:
        """Restore the signal dispositions the host replaced."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        for signum in self._installed_signals:
            loop.remove_signal_handler(signum)
        self._installed_signals = []

    def _log(self, *, msg: str, **fields: object) -> None:
        """Write one ``[channel <name>] msg key=value`` line to stderr and the Slo log.

        Args:
            msg (str): What happened.
            **fields (object): Extra context.
        """
        details: str = " ".join(f"{key}={value}" for key, value in fields.items())
        line: str = f"[channel {self._adapter.name}] {msg}" + (f" {details}" if details else "")
        log_info(msg=line)
        print(line, file=sys.stderr, flush=True)


def _split_command(*, text: str) -> tuple[Optional[str], str]:
    """Split ``/word rest`` into ``("/word", "rest")``; other text gives ``(None, text)``.

    A command word is ``/`` followed by letters, digits or ``_``; a Telegram
    ``@botname`` suffix is dropped. Text such as ``/tmp/x is broken`` is not
    a command.

    Args:
        text (str): The raw platform text.

    Returns:
        tuple[Optional[str], str]: The lowercased command word (or ``None``)
            and the remaining argument text, stripped.
    """
    stripped: str = text.strip()
    head, _, rest = stripped.partition(" ")
    word: str = head.split("@", 1)[0]
    if not word.startswith(_COMMAND_WORD_PREFIX) or not word[1:] or not word[1:].replace("_", "").isalnum():
        return None, text
    return word.lower(), rest.strip()
