"""Sender process for the 108.1 A1 queue matrix; launched only by test_channel_process_matrix.py.

Each invocation opens its own SQLite connection to the shared ``channels.db``
and sends ``--count`` prompts from one sender to one recipient, so several
invocations exercise the real cross-process ``BEGIN IMMEDIATE`` index assignment.
This file is a helper, not a test module (its name does not start with ``test_``).
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import UUID

from src.channels.dao import NewMessageDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository


def parse_arguments() -> argparse.Namespace:
    """Read the named sender options from the command line.

    Returns:
        argparse.Namespace: The parsed ``db``, ``sender``, ``recipient``, ``label`` and ``count`` options.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="Shared channels.db path.")
    parser.add_argument("--sender", required=True, type=UUID, help="Sender participant id.")
    parser.add_argument("--recipient", required=True, type=UUID, help="Recipient agent participant id.")
    parser.add_argument("--channel", required=True, type=UUID, help="Channel the sends come from.")
    parser.add_argument("--label", required=True, help="Prefix written into every message body.")
    parser.add_argument("--count", required=True, type=int, help="Number of prompts to send.")
    return parser.parse_args()


async def send_all(*, options: argparse.Namespace) -> None:
    """Send ``count`` prompts through a fresh gateway connection.

    Args:
        options (argparse.Namespace): Parsed sender options.
    """
    gateway: ChannelGateway = ChannelGateway(repository=ChannelRepository(db_path=options.db))
    await gateway.open()
    try:
        for index in range(options.count):
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=options.sender,
                    recipient_id=options.recipient,
                    message_contents=f"{options.label}-{index}",
                    channel_id=options.channel,
                )
            )
    finally:
        await gateway.close()


if __name__ == "__main__":
    asyncio.run(send_all(options=parse_arguments()))
