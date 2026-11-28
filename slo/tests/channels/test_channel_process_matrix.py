"""108.1 A1 / 1081-R07: four real processes share one channels.db without index gaps.

The existing two-connection test in ``test_channels_repository.py`` runs both
connections inside one process. This module starts four separate Python
processes, each with its own SQLite connection, that send 200 prompts apiece
into one agent session, then reads the queue back through a fresh connection.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

from src.channels.dao import ChannelDAO, ChannelMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository

_REPO_ROOT: Path = Path(__file__).resolve().parents[2]
_SENDER_SCRIPT: Path = Path(__file__).resolve().parent / "_channel_sender_process.py"
_PROCESS_COUNT: int = 4
_SENDS_PER_PROCESS: int = 200
_WAIT_SECONDS: float = 120.0
_PAGE_SIZE: int = 200


async def _start_sender(
    *, db_path: Path, user: ParticipantDAO, agent_id: UUID, channel: ChannelDAO, label: str, log_path: Path
) -> asyncio.subprocess.Process:
    """Launch one sender process that writes its prompts to the shared queue.

    Args:
        db_path (Path): Shared ``channels.db`` path.
        user (ParticipantDAO): Sender participant.
        agent_id (UUID): Recipient agent participant (its session id).
        channel (ChannelDAO): Channel the sends come from.
        label (str): Prefix written into each message body.
        log_path (Path): File receiving the child's stderr for failure diagnosis.

    Returns:
        asyncio.subprocess.Process: The running sender process.
    """
    log_handle = log_path.open("wb")
    try:
        return await asyncio.create_subprocess_exec(
            sys.executable,
            str(_SENDER_SCRIPT),
            "--db",
            str(db_path),
            "--sender",
            str(user.id),
            "--recipient",
            str(agent_id),
            "--channel",
            str(channel.id),
            "--label",
            label,
            "--count",
            str(_SENDS_PER_PROCESS),
            cwd=str(_REPO_ROOT),
            env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
            stdout=asyncio.subprocess.DEVNULL,
            stderr=log_handle,
        )
    finally:
        log_handle.close()


async def _reap_senders(*, senders: list[asyncio.subprocess.Process]) -> list[int]:
    """Wait, with a bound, for every sender and kill any that outlive the bound.

    Args:
        senders (list[asyncio.subprocess.Process]): Processes started by the test.

    Returns:
        list[int]: Each sender's exit code, in start order.
    """
    try:
        async with asyncio.timeout(_WAIT_SECONDS):
            await asyncio.gather(*(sender.wait() for sender in senders))
    finally:
        for sender in senders:
            if sender.returncode is None:
                sender.kill()
                await sender.wait()
    exit_codes: list[int] = []
    for sender in senders:
        if sender.returncode is None:
            raise RuntimeError("Channel sender exited without an exit code.")
        exit_codes.append(sender.returncode)
    return exit_codes


async def _read_every_row(*, gateway: ChannelGateway, agent_id: UUID) -> list[ChannelMessageDAO]:
    """Page through one conversation until it is exhausted.

    Args:
        gateway (ChannelGateway): Gateway over the shared queue.
        agent_id (UUID): Agent session whose conversation is read.

    Returns:
        list[ChannelMessageDAO]: Every stored row, in index order.
    """
    rows: list[ChannelMessageDAO] = []
    while True:
        page: list[ChannelMessageDAO] = await gateway.list_conversation_messages(
            agent_session_id=agent_id, after_index=rows[-1].message_index if rows else 0, limit=_PAGE_SIZE
        )
        if not page:
            return rows
        rows.extend(page)


class TestFourProcessesShareOneQueue:
    """A1: concurrent writers from separate processes produce one gapless, complete conversation."""

    async def test_four_processes_sending_200_prompts_each_leave_800_rows_indexed_1_to_800(
        self, tmp_path: Path
    ) -> None:
        """Four processes, one SQLite file: every send lands once, indexes are gapless and unique.

        Each process opens its own connection and sends 200 prompts into the
        same agent session. The parent reads the queue back through a fresh
        connection after all four exit cleanly.
        """
        db_path: Path = tmp_path / "channels.db"
        parent: ChannelGateway = ChannelGateway(repository=ChannelRepository(db_path=db_path))
        await parent.open()
        try:
            channel: ChannelDAO = await parent.register_channel(kind="tui", name="tui@matrix")
            user: ParticipantDAO = await parent.register_user(channel_id=channel.id, name="matrix (tui)")
            agent: ParticipantDAO = await parent.register_agent(session_id=uuid4(), name="slo matrix")
            labels: list[str] = [f"proc{number}" for number in range(_PROCESS_COUNT)]
            senders: list[asyncio.subprocess.Process] = []
            try:
                for label in labels:
                    senders.append(
                        await _start_sender(
                            db_path=db_path,
                            user=user,
                            agent_id=agent.id,
                            channel=channel,
                            label=label,
                            log_path=tmp_path / f"{label}.stderr",
                        )
                    )
                exit_codes: list[int] = await _reap_senders(senders=senders)
            finally:
                for sender in senders:
                    if sender.returncode is None:
                        sender.kill()
                        await sender.wait()

            assert exit_codes == [0] * _PROCESS_COUNT, [
                (tmp_path / f"{label}.stderr").read_text(errors="replace") for label in labels
            ]
            rows: list[ChannelMessageDAO] = await _read_every_row(gateway=parent, agent_id=agent.id)
        finally:
            await parent.close()

        assert len(rows) == _PROCESS_COUNT * _SENDS_PER_PROCESS
        assert [row.message_index for row in rows] == list(range(1, _PROCESS_COUNT * _SENDS_PER_PROCESS + 1))
        assert len({row.id for row in rows}) == len(rows)
        for label in labels:
            bodies: list[str] = [
                row.message_contents for row in rows if row.message_contents.startswith(f"{label}-")
            ]
            assert sorted(bodies) == sorted(f"{label}-{index}" for index in range(_SENDS_PER_PROCESS))
