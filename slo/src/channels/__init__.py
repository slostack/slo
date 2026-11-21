"""Channels — the shared SQLite queue every platform talks through (108.1).

One database file (``$SLO_HOME/channels/channels.db``, WAL mode) shared by every
Slo process: the TUI, headless orchestrators, sub-agents and external adapters
all write rows to and read rows from the ``messages`` table.
"""

from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.errors import ChannelError, RecipientClosedError, UnknownParticipantError
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository

__all__ = [
    "ChannelDAO",
    "ChannelError",
    "ChannelGateway",
    "ChannelMessageDAO",
    "ChannelRepository",
    "NewMessageDAO",
    "ParticipantDAO",
    "RecipientClosedError",
    "UnknownParticipantError",
]
