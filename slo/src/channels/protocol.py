"""The public channel adapter protocol (108.1 minimal; full version 108.5 §5).

A channel adapter is code that connects one platform (TUI, CLI, Telegram, a
desktop app, …) to the queue. An external adapter is run by ``AdapterHost``
(``slo channel run``):

1. The host registers the adapter's channel and calls ``start(ctx=…)``. The
   adapter begins reading its platform and hands every user message to
   ``ctx.inbound(item=InboundTextDAO(...))``. The host resolves the user, applies
   ``/attach``, ``/detach``, ``/agents`` and ``/force``, and otherwise sends the
   text to the user's attached agent. When ``inbound`` returns a string the
   adapter sends that short text back to the user (help, errors).
2. The host polls ``list_pending_outbound_messages`` for this channel's users and calls
   ``deliver(message=…, user=…)`` for each row. ``True`` means the platform
   took the message and the host accepts the row; ``False`` (or an exception)
   leaves the row pending and the host retries with backoff (1 s → 60 s).
3. On SIGINT/SIGTERM the host calls ``stop()``.

Adapters run on the same machine as the same user as every other Slo process;
nothing in this protocol listens for inbound network connections.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.channels.dao import ChannelDAO, ChannelMessageDAO, InboundTextDAO, ParticipantDAO

__all__ = ["AdapterContext", "ChannelAdapter"]


@runtime_checkable
class AdapterContext(Protocol):
    """What the adapter host gives an adapter in ``start`` (108.5 §5)."""

    @property
    def channel(self) -> ChannelDAO:
        """Return the channel row the host registered for this adapter."""
        ...

    async def inbound(self, *, item: InboundTextDAO) -> ChannelMessageDAO | str:
        """Handle one platform message from one user.

        Registers (or refreshes) the user, then applies the adapter commands
        ``/attach <id-prefix>``, ``/detach``, ``/agents`` and ``/force <text>``.
        Any other text is sent to the user's attached agent. The adapter checks
        its own allow-list before calling this.

        Args:
            item (InboundTextDAO): The user's message.

        Returns:
            ChannelMessageDAO | str: The stored queue row when the text was
                sent to an agent; otherwise a short text the adapter should
                send back to the user (help, command results, errors).
        """
        ...

    def log(self, *, msg: str, **fields: object) -> None:
        """Write one line to the host's log (stderr and the Slo log).

        Args:
            msg (str): What happened. Never include secrets.
            **fields (object): Extra ``key=value`` context, e.g. ``user_id=42``.
        """
        ...


@runtime_checkable
class ChannelAdapter(Protocol):
    """Contract every channel adapter satisfies (108.5 §5).

    ``kind`` must be one of the queue's channel kinds (``ChannelKind``).
    ``name`` identifies this adapter instance: the host derives a stable
    channel id from ``(kind, name)``, so two adapters of one kind need two
    names.
    """

    @property
    def kind(self) -> str:
        """Return the platform type, e.g. ``telegram``."""
        ...

    @property
    def name(self) -> str:
        """Return the adapter instance name, e.g. ``telegram``."""
        ...

    async def start(self, *, ctx: AdapterContext) -> None:
        """Begin reading the platform; return once reading has started.

        Args:
            ctx (AdapterContext): The host context to hand platform input to.

        Raises:
            AdapterConfigError: The adapter is not configured (host exits 1).
        """
        ...

    async def deliver(self, *, message: ChannelMessageDAO, user: ParticipantDAO) -> bool:
        """Deliver one outbound row to one platform user.

        Args:
            message (ChannelMessageDAO): Pending row addressed to ``user``.
            user (ParticipantDAO): The channel user it is addressed to; its
                ``external_ref`` is the platform identity.

        Returns:
            bool: ``True`` when the platform took the message (the host then
                accepts the row); ``False`` to leave it pending for a retry.
        """
        ...

    async def stop(self) -> None:
        """Stop reading the platform and release adapter resources."""
        ...
