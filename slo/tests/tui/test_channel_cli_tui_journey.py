"""X1 (108.5 §8): ``slo channel send --wait`` to a TUI session returns the reply.

Both tests run the real ``SloTUI`` (Textual Pilot) with a real session, real
history store and the shared queue at ``$SLO_HOME/channels/channels.db``
(per-test ``SLO_HOME``). The only substitute is the LLM provider
(``FauxChatModel``); nothing reaches a real provider.

- ``TestX1CliToTuiIntegration`` drives the CLI runtime (``ChannelDispatch.send``,
  its own event loop and SQLite connection) from a worker thread.
- ``TestX1CliToTuiEndToEnd`` (``e2e``, off by default) runs the real
  ``python -m src.cli channel send`` in a separate process.

Not proven: a real terminal and a real provider.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelMessageDAO
from src.channels.gateway import ChannelGateway
from src.cli.channel_dispatch import ChannelDispatch
from src.tui.app import SloTUI

_ANSWER: str = "Today: 3 commits on worktree/channels"
_REPO_ROOT: Path = Path(__file__).resolve().parents[2]


def _session(*, tmp_path: Path) -> SloAgentSession:
    return SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(responses=[AIMessage(content=_ANSWER)]), cwd=str(tmp_path), tools=[]
        ),
        workdir=tmp_path,
        session_id=str(uuid4()),
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        enable_history=True,
    )


async def _wait_for_poller(*, app: SloTUI, session: SloAgentSession) -> None:
    async with asyncio.timeout(20.0):
        while app.channel_adapter is None or session.channel_poller is None:
            await asyncio.sleep(0.05)


async def _assert_tui_answered(*, gateway: ChannelGateway, agent_id: UUID) -> None:
    rows: list[ChannelMessageDAO] = await gateway.conversation(agent_session_id=agent_id)
    prompts: list[ChannelMessageDAO] = [row for row in rows if row.message_type == "prompt"]
    replies: list[ChannelMessageDAO] = [row for row in rows if row.message_type == "reply"]
    assert [row.message_contents for row in prompts] == ["summarise today's changes"]
    assert prompts[0].sender_name.endswith("(cli)")
    assert prompts[0].accepted_at is not None  # the TUI session ran it
    assert len(replies) == 1 and replies[0].in_reply_to_id == prompts[0].id
    assert replies[0].message_contents == _ANSWER
    assert replies[0].accepted_at is not None  # the CLI delivered (printed) it


class TestX1CliToTuiIntegration:
    async def test_x1_cli_send_wait_gets_the_tui_sessions_reply(self, tmp_path: Path) -> None:
        """The printed reply line is asserted by the CliRunner X1 test and the e2e below.

        Textual's ``run_test`` owns ``sys.stdout`` while the app runs, so the
        dispatch's printed line is not capturable here; the reply's
        ``accepted_at`` proves the CLI received and delivered it.
        """
        session: SloAgentSession = _session(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=session, channel_gateway=ChannelGateway.at_default_path())
        observer: ChannelGateway = await ChannelGateway.default()
        agent_id: UUID = channel_participant_id_for_session(session_id=session.session_id)
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                await _wait_for_poller(app=app, session=session)

                exit_code: int = await asyncio.to_thread(
                    ChannelDispatch.send,
                    to=str(agent_id)[:8],
                    text="summarise today's changes",
                    force=False,
                    wait=True,
                    timeout=30.0,
                )

                assert exit_code == 0
                await _assert_tui_answered(gateway=observer, agent_id=agent_id)
        finally:
            await observer.close()


@pytest.mark.e2e
class TestX1CliToTuiEndToEnd:
    async def test_x1_slo_channel_send_wait_process_gets_the_tui_reply(self, tmp_path: Path) -> None:
        session: SloAgentSession = _session(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=session, channel_gateway=ChannelGateway.at_default_path())
        observer: ChannelGateway = await ChannelGateway.default()
        agent_id: UUID = channel_participant_id_for_session(session_id=session.session_id)
        env: dict[str, str] = dict(os.environ)
        env["PYTHONPATH"] = str(_REPO_ROOT)
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                await _wait_for_poller(app=app, session=session)

                process: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "src.cli",
                    "channel",
                    "send",
                    "--to",
                    str(agent_id)[:8],
                    "--wait",
                    "--timeout",
                    "60",
                    "summarise today's changes",
                    cwd=str(_REPO_ROOT),
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=90.0)

                assert process.returncode == 0, stderr.decode()
                assert f"  {_ANSWER}" in stdout.decode()
                assert "sent  " in stdout.decode()
                await _assert_tui_answered(gateway=observer, agent_id=agent_id)
        finally:
            await observer.close()
