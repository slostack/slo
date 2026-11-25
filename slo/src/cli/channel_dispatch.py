"""Runtime for ``slo channel …`` (108.5 §5 CLI): one shell user talking to agents.

``src/cli/channel_commands.py`` parses arguments; this module opens the shared
queue, does the work and maps outcomes to exit codes. Data goes to stdout,
errors to stderr.

| Command | Exit codes |
|---|---|
| ``agents`` | 0 |
| ``send --to PREFIX [--force] [--wait [--timeout S]] TEXT`` | 0 sent/replied · 3 closed · 5 unknown · 124 timeout · 1 other |
| ``follow --to PREFIX`` | 0 · 5 unknown |
| ``run telegram`` / ``run --adapter pkg.mod:Class`` | 0 · 1 config error |

The CLI user is ``$USER (cli)`` on one ``cli@<host>`` channel per machine.
"""

from __future__ import annotations

import asyncio
import getpass
import socket
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from pydantic import ValidationError

from src.channels.adapters.registry import AdapterRegistry
from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO, utc_now
from src.channels.errors import (
    AdapterConfigError,
    AmbiguousAgentError,
    MessageCancelledError,
    RecipientClosedError,
    ReplyTimeoutError,
    UnknownAgentError,
)
from src.channels.gateway import ChannelGateway
from src.channels.host import AdapterHost, describe_agent
from src.channels.protocol import ChannelAdapter

__all__ = ["ChannelDispatch"]

EXIT_OK: int = 0
EXIT_FAILED: int = 1
EXIT_CLOSED: int = 3
EXIT_UNKNOWN: int = 5
EXIT_TIMEOUT: int = 124

DEFAULT_WAIT_TIMEOUT_S: float = 300.0
"""``--wait`` without ``--timeout`` waits this long."""

_FOLLOW_POLL_SECONDS: float = 0.5
_CLOSED_REASONS: frozenset[str] = frozenset({"recipient_closed", "session_closed", "aborted"})
"""Cancel reasons that mean "the agent finished" (exit 3) rather than another failure."""


class ChannelDispatch:
    """Sync entry points for ``slo channel``; each runs one asyncio loop."""

    @classmethod
    def agents(cls) -> int:
        """Print one line per open agent.

        Returns:
            int: ``0``.
        """
        return cls._with_gateway(operation=cls._agents)

    @classmethod
    def send(cls, *, to: str, text: str, force: bool, wait: bool, timeout: Optional[float]) -> int:
        """Send one prompt as ``$USER (cli)``; with ``wait``, print the answer.

        A normal prompt's answer is its ``reply`` row (accepted once printed). A
        forced prompt gets no reply, so ``--force --wait`` waits for acceptance.

        Args:
            to (str): Agent id prefix.
            text (str): Prompt text.
            force (bool): Force it into the agent's current run.
            wait (bool): Wait for the reply (or the acceptance, when forced).
            timeout (Optional[float]): Seconds to wait; only with ``wait``.

        Returns:
            int: 0 sent/answered, 3 agent closed, 5 unknown agent, 124 timeout,
                1 any other failure.

        Raises:
            typer.BadParameter: ``timeout`` without ``wait``, or text over 64 KiB.
        """
        if timeout is not None and not wait:
            raise typer.BadParameter("--timeout needs --wait", param_hint="--timeout")
        wait_timeout: Optional[float] = (
            (timeout if timeout is not None else DEFAULT_WAIT_TIMEOUT_S) if wait else None
        )

        async def _operation(gateway: ChannelGateway) -> int:
            return await cls._send(gateway=gateway, to=to, text=text, force=force, wait_timeout=wait_timeout)

        return cls._with_gateway(operation=_operation)

    @classmethod
    def follow(cls, *, to: str, history: int) -> int:
        """Print the agent's conversation, then new rows until it closes (or Ctrl+C).

        Args:
            to (str): Agent id prefix.
            history (int): How many earlier rows to print first.

        Returns:
            int: 0, or 5 for an unknown agent.
        """

        async def _operation(gateway: ChannelGateway) -> int:
            return await cls._follow(gateway=gateway, to=to, history=history)

        try:
            return cls._with_gateway(operation=_operation)
        except KeyboardInterrupt:
            return EXIT_OK

    @classmethod
    def run_adapter(
        cls, *, builtin: Optional[str], reference: Optional[str], config_path: Optional[Path]
    ) -> int:
        """Run one adapter in the foreground with ``AdapterHost`` until SIGINT/SIGTERM.

        Args:
            builtin (Optional[str]): Built-in adapter name (``telegram``).
            reference (Optional[str]): Custom adapter ``pkg.mod:Class``.
            config_path (Optional[Path]): Config file for a built-in adapter.

        Returns:
            int: 0 after a clean stop, 1 for a configuration or start error.
        """
        try:
            adapter: ChannelAdapter = AdapterRegistry.load(
                builtin=builtin, reference=reference, config_path=config_path
            )
        except AdapterConfigError as exc:
            typer.echo(f"config error: {exc}", err=True)
            return EXIT_FAILED

        async def _operation(gateway: ChannelGateway) -> int:
            return await AdapterHost(adapter=adapter, gateway=gateway).run()

        return cls._with_gateway(operation=_operation)

    @classmethod
    def _with_gateway(cls, *, operation: Callable[[ChannelGateway], Awaitable[int]]) -> int:
        """Open the shared queue, run ``operation`` and close the queue.

        Args:
            operation (Callable[[ChannelGateway], Awaitable[int]]): The command body.

        Returns:
            int: The operation's exit code, or 1 when the queue cannot be opened.
        """

        async def _run() -> int:
            try:
                gateway: ChannelGateway = await ChannelGateway.default()
            except (sqlite3.Error, OSError) as exc:
                typer.echo(f"channel queue unavailable: {exc}", err=True)
                return EXIT_FAILED
            try:
                return await operation(gateway)
            finally:
                await gateway.close()

        return asyncio.run(_run())

    @classmethod
    async def _agents(cls, gateway: ChannelGateway) -> int:
        """Print the open agents.

        Args:
            gateway (ChannelGateway): The open queue.

        Returns:
            int: ``0``.
        """
        agents: list[ParticipantDAO] = await gateway.list_agents(open_only=True)
        if not agents:
            typer.echo("No open agents.")
            return EXIT_OK
        now: datetime = utc_now()
        for agent in agents:
            typer.echo(describe_agent(agent=agent, now=now))
        return EXIT_OK

    @classmethod
    async def _send(
        cls, *, gateway: ChannelGateway, to: str, text: str, force: bool, wait_timeout: Optional[float]
    ) -> int:
        """Resolve the agent, send the prompt and optionally wait for its answer.

        Args:
            gateway (ChannelGateway): The open queue.
            to (str): Agent id prefix.
            text (str): Prompt text.
            force (bool): Force it into the current run.
            wait_timeout (Optional[float]): Seconds to wait, or ``None`` not to wait.

        Returns:
            int: The ``send`` exit code.
        """
        agent: Optional[ParticipantDAO] = await cls._resolve(gateway=gateway, to=to)
        if agent is None:
            return EXIT_UNKNOWN
        if agent.status != "open":
            return cls._report_closed(agent=agent)
        channel, user = await cls._register_cli_user(gateway=gateway)
        try:
            sent: ChannelMessageDAO = await gateway.send(
                new=cls._build_prompt(user=user, channel=channel, agent=agent, text=text, force=force)
            )
        except RecipientClosedError:
            return cls._report_closed(agent=agent)
        typer.echo(
            f"sent  {str(sent.id)[:8]}  ({'forced' if force else 'queued'}, index {sent.message_index})"
        )
        if wait_timeout is None:
            return EXIT_OK
        return await cls._wait(gateway=gateway, sent=sent, forced=force, timeout=wait_timeout)

    @classmethod
    def _build_prompt(
        cls, *, user: ParticipantDAO, channel: ChannelDAO, agent: ParticipantDAO, text: str, force: bool
    ) -> NewMessageDAO:
        """Build the prompt row, turning an invalid text into a usage error.

        Args:
            user (ParticipantDAO): The CLI user.
            channel (ChannelDAO): The CLI channel.
            agent (ParticipantDAO): The recipient agent.
            text (str): Prompt text.
            force (bool): Force it into the current run.

        Returns:
            NewMessageDAO: The row to send.

        Raises:
            typer.BadParameter: The text is empty or over 64 KiB.
        """
        try:
            return NewMessageDAO(
                sender_id=user.id,
                recipient_id=agent.id,
                message_contents=text,
                channel_id=channel.id,
                force=force,
            )
        except ValidationError:
            raise typer.BadParameter("TEXT must be 1 to 65536 characters", param_hint="TEXT") from None

    @classmethod
    async def _wait(
        cls, *, gateway: ChannelGateway, sent: ChannelMessageDAO, forced: bool, timeout: float
    ) -> int:
        """Wait for a reply (normal) or acceptance (forced) and print it.

        Args:
            gateway (ChannelGateway): The open queue.
            sent (ChannelMessageDAO): The sent prompt.
            forced (bool): Whether it was forced.
            timeout (float): Seconds to wait.

        Returns:
            int: 0 answered, 3 cancelled because the agent finished, 124
                timeout, 1 cancelled for another reason.
        """
        try:
            if forced:
                accepted: ChannelMessageDAO = await gateway.wait_for_acceptance(
                    message_id=sent.id, timeout=timeout
                )
                typer.echo(f"accepted {str(accepted.id)[:8]}")
                return EXIT_OK
            reply: ChannelMessageDAO = await gateway.wait_for_reply(message_id=sent.id, timeout=timeout)
        except ReplyTimeoutError:
            typer.echo(f"no reply within {timeout:g} s (the message stays queued)", err=True)
            return EXIT_TIMEOUT
        except MessageCancelledError as cancelled:
            typer.echo(f"message cancelled ({cancelled.reason})", err=True)
            return EXIT_CLOSED if cancelled.reason in _CLOSED_REASONS else EXIT_FAILED
        typer.echo(f"reply {str(reply.id)[:8]}  {reply.message_contents}")
        await gateway.accept(message_id=reply.id)
        return EXIT_OK

    @classmethod
    async def _follow(cls, *, gateway: ChannelGateway, to: str, history: int) -> int:
        """Print the last ``history`` rows, then stream new rows until the agent closes.

        Args:
            gateway (ChannelGateway): The open queue.
            to (str): Agent id prefix.
            history (int): Earlier rows to print first.

        Returns:
            int: 0, or 5 for an unknown agent.
        """
        agent: Optional[ParticipantDAO] = await cls._resolve(gateway=gateway, to=to)
        if agent is None:
            return EXIT_UNKNOWN
        cursor: int = max(0, await gateway.last_message_index(agent_session_id=agent.id) - max(0, history))
        while True:
            rows: list[ChannelMessageDAO] = await gateway.list_conversation_messages(
                agent_session_id=agent.id, after_index=cursor
            )
            for row in rows:
                typer.echo(cls._format_row(row=row))
                cursor = row.message_index
            if rows:
                continue
            current: Optional[ParticipantDAO] = await gateway.find_participant(participant_id=agent.id)
            if current is None or current.status != "open":
                typer.echo(f"— {agent.name} finished —")
                return EXIT_OK
            await asyncio.sleep(_FOLLOW_POLL_SECONDS)

    @classmethod
    async def _resolve(cls, *, gateway: ChannelGateway, to: str) -> Optional[ParticipantDAO]:
        """Resolve ``--to``, printing why when it fails.

        Args:
            gateway (ChannelGateway): The open queue.
            to (str): Agent id prefix.

        Returns:
            Optional[ParticipantDAO]: The agent, or ``None`` (unknown or ambiguous).
        """
        try:
            return await gateway.resolve_agent(prefix=to)
        except (UnknownAgentError, AmbiguousAgentError) as exc:
            typer.echo(f"{exc} (slo channel agents lists them)", err=True)
            return None

    @classmethod
    async def _register_cli_user(cls, *, gateway: ChannelGateway) -> tuple[ChannelDAO, ParticipantDAO]:
        """Register this machine's CLI channel and this shell user.

        Args:
            gateway (ChannelGateway): The open queue.

        Returns:
            tuple[ChannelDAO, ParticipantDAO]: The channel and the user.
        """
        channel_name: str = f"cli@{socket.gethostname()}"
        channel: ChannelDAO = await gateway.register_channel(
            kind="cli",
            name=channel_name,
            channel_id=ChannelGateway.stable_channel_id(kind="cli", name=channel_name),
        )
        login: str = getpass.getuser()
        user: ParticipantDAO = await gateway.register_user(
            channel_id=channel.id, name=f"{login} (cli)", external_ref=login
        )
        return channel, user

    @classmethod
    def _report_closed(cls, *, agent: ParticipantDAO) -> int:
        """Print that the agent has finished.

        Args:
            agent (ParticipantDAO): The closed agent.

        Returns:
            int: ``3``.
        """
        typer.echo(f"agent {agent.name} ({str(agent.id)[:8]}) has finished", err=True)
        return EXIT_CLOSED

    @classmethod
    def _format_row(cls, *, row: ChannelMessageDAO) -> str:
        """Format one conversation row for ``follow``.

        Args:
            row (ChannelMessageDAO): The row.

        Returns:
            str: e.g. ``#3 12:01:02 sid (cli) → slo 9b1e [prompt, forced] text``.
        """
        flags: list[str] = [row.message_type]
        if row.forced_at is not None:
            flags.append("forced")
        if row.cancelled_at is not None:
            flags.append(f"cancelled: {row.cancel_reason}")
        stamp: str = row.created_at.strftime("%H:%M:%S")
        return f"#{row.message_index} {stamp} {row.sender_name} → {row.recipient_name} [{', '.join(flags)}] {row.message_contents}"
