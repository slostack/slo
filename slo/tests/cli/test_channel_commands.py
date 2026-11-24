"""``slo channel agents / send / follow / run`` (108.5 §5 CLI table, X1 CLI half, X5 CLI).

Level: the real Typer app (``CliRunner``) → ``ChannelDispatch`` → real
``ChannelGateway`` on ``$SLO_HOME/channels/channels.db`` (the per-test
``SLO_HOME`` from the suite conftest). The agent side is a second process-like
actor: ``AgentResponder`` runs its own event loop and SQLite connection in a
thread and answers prompts with the real ``ReplyWriter``. The X5 CLI journey
runs ``python -m src.cli channel run`` as a real subprocess.
"""

from __future__ import annotations

import asyncio
import getpass
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional, TypeVar
from uuid import UUID, uuid4

import pytest
from typer.testing import CliRunner, Result

from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.channels.dao import ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.cli.app import app

_T = TypeVar("_T")
_REPO_ROOT: Path = Path(__file__).resolve().parents[2]


def _db(operation: Callable[[ChannelGateway], Awaitable[_T]]) -> _T:
    """Run one operation against the default queue on a fresh connection."""

    async def _run() -> _T:
        gateway: ChannelGateway = await ChannelGateway.default()
        try:
            return await operation(gateway)
        finally:
            await gateway.close()

    return asyncio.run(_run())


def _register_agent(*, name: str, session_id: Optional[UUID] = None) -> ParticipantDAO:
    return _db(lambda gateway: gateway.register_agent(session_id=session_id or uuid4(), name=name))


def _close_agent(*, agent_id: UUID) -> None:
    _db(lambda gateway: gateway.close_agent(session_id=agent_id, reason="recipient_closed"))


def _conversation(*, agent_id: UUID) -> list[ChannelMessageDAO]:
    return _db(lambda gateway: gateway.conversation(agent_session_id=agent_id))


def _invoke(*args: str) -> Result:
    return CliRunner().invoke(app, ["channel", *args])


class AgentResponder:
    """Plays one agent in a thread with its own loop and connection.

    Normal prompts are accepted and answered with the real ``ReplyWriter``;
    forced prompts are only accepted (their ack is ``accepted_at``, 108.3 §2).
    ``close_after_first`` closes the agent instead of answering.
    """

    def __init__(self, *, agent_id: UUID, answer: str = "answered", close_instead: bool = False) -> None:
        self._agent_id: UUID = agent_id
        self._answer: str = answer
        self._close_instead: bool = close_instead
        self._stop: threading.Event = threading.Event()
        self._thread: threading.Thread = threading.Thread(
            target=lambda: asyncio.run(self._serve()), daemon=True
        )
        self.handled: list[ChannelMessageDAO] = []

    def __enter__(self) -> "AgentResponder":
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        self._thread.join(timeout=10.0)

    async def _serve(self) -> None:
        gateway: ChannelGateway = await ChannelGateway.default()
        try:
            while not self._stop.is_set():
                for row in await gateway.pending_inbound(recipient_id=self._agent_id):
                    await self._handle(gateway=gateway, row=row)
                await asyncio.sleep(0.05)
        finally:
            await gateway.close()

    async def _handle(self, *, gateway: ChannelGateway, row: ChannelMessageDAO) -> None:
        self.handled.append(row)
        if self._close_instead:
            await gateway.close_agent(session_id=self._agent_id, reason="recipient_closed")
            return
        await gateway.accept(message_id=row.id)
        if row.forced_at is None:
            await ReplyWriter(gateway=gateway).write(
                request=row, outcome=TurnOutcomeDAO(status="completed", final_text=self._answer)
            )


class TestAgentsCommand:
    def test_lists_open_agents_with_id_prefix_name_and_last_seen(self) -> None:
        live: ParticipantDAO = _register_agent(name="slo live one")
        done: ParticipantDAO = _register_agent(name="slo finished")
        _close_agent(agent_id=done.id)

        result: Result = _invoke("agents")

        assert result.exit_code == 0, result.output
        assert str(live.id)[:8] in result.stdout
        assert "slo live one" in result.stdout and "last seen" in result.stdout
        assert "slo finished" not in result.stdout

    def test_no_agents(self) -> None:
        result: Result = _invoke("agents")

        assert result.exit_code == 0
        assert "No open agents" in result.stdout


class TestSendCommand:
    def test_send_queues_a_prompt_as_the_cli_user(self) -> None:
        agent: ParticipantDAO = _register_agent(name="slo target")

        result: Result = _invoke("send", "--to", str(agent.id)[:6], "summarise today's changes")

        assert result.exit_code == 0, result.output
        rows: list[ChannelMessageDAO] = _conversation(agent_id=agent.id)
        assert len(rows) == 1
        row: ChannelMessageDAO = rows[0]
        assert row.message_contents == "summarise today's changes"
        assert row.sender_name == f"{getpass.getuser()} (cli)"
        assert row.forced_at is None
        assert row.channel_id is not None
        assert f"sent  {str(row.id)[:8]}  (queued, index 1)" in result.stdout

    def test_force_marks_the_row_forced(self) -> None:
        agent: ParticipantDAO = _register_agent(name="slo target")

        result: Result = _invoke("send", "--to", str(agent.id), "--force", "stop now")

        assert result.exit_code == 0, result.output
        assert _conversation(agent_id=agent.id)[0].forced_at is not None
        assert "(forced, index 1)" in result.stdout

    def test_x1_wait_prints_the_reply_and_accepts_it(self) -> None:
        """X1 (CLI half): ``send --wait`` returns the agent's reply; exit 0."""
        agent: ParticipantDAO = _register_agent(name="slo target")

        with AgentResponder(agent_id=agent.id, answer="Today: 3 commits on worktree/channels"):
            result: Result = _invoke(
                "send", "--to", str(agent.id)[:8], "--wait", "--timeout", "20", "summarise"
            )

        assert result.exit_code == 0, result.output
        rows: list[ChannelMessageDAO] = _conversation(agent_id=agent.id)
        request, reply = rows
        assert reply.in_reply_to_id == request.id
        assert reply.accepted_at is not None  # delivered to the CLI user
        assert f"reply {str(reply.id)[:8]}  Today: 3 commits on worktree/channels" in result.stdout

    def test_forced_wait_returns_on_acceptance(self) -> None:
        agent: ParticipantDAO = _register_agent(name="slo target")

        with AgentResponder(agent_id=agent.id):
            result: Result = _invoke(
                "send", "--to", str(agent.id), "--force", "--wait", "--timeout", "20", "now"
            )

        assert result.exit_code == 0, result.output
        row: ChannelMessageDAO = _conversation(agent_id=agent.id)[0]
        assert f"accepted {str(row.id)[:8]}" in result.stdout

    def test_wait_times_out_with_124_and_leaves_the_row_queued(self) -> None:
        agent: ParticipantDAO = _register_agent(name="slo silent")

        result: Result = _invoke("send", "--to", str(agent.id), "--wait", "--timeout", "0.5", "anyone?")

        assert result.exit_code == 124
        assert "no reply within 0.5 s" in result.stderr
        row: ChannelMessageDAO = _conversation(agent_id=agent.id)[0]
        assert row.accepted_at is None and row.cancelled_at is None

    def test_agent_closing_during_the_wait_exits_3(self) -> None:
        agent: ParticipantDAO = _register_agent(name="slo closing")

        with AgentResponder(agent_id=agent.id, close_instead=True):
            result: Result = _invoke("send", "--to", str(agent.id), "--wait", "--timeout", "20", "hello")

        assert result.exit_code == 3, result.output
        assert "recipient_closed" in result.stderr

    def test_closed_agent_exits_3_without_a_row(self) -> None:
        agent: ParticipantDAO = _register_agent(name="slo finished")
        _close_agent(agent_id=agent.id)

        result: Result = _invoke("send", "--to", str(agent.id)[:8], "hello")

        assert result.exit_code == 3
        assert "finished" in result.stderr
        assert _conversation(agent_id=agent.id) == []

    @pytest.mark.parametrize("prefix", ["ffffffff", "not-hex!"])
    def test_unknown_agent_exits_5(self, prefix: str) -> None:
        _register_agent(name="slo other", session_id=UUID("11111111-0000-4000-8000-000000000000"))

        result: Result = _invoke("send", "--to", prefix, "hello")

        assert result.exit_code == 5
        assert "No agent matches" in result.stderr

    def test_ambiguous_prefix_exits_5(self) -> None:
        _register_agent(name="slo a", session_id=UUID("abab0000-0000-4000-8000-000000000001"))
        _register_agent(name="slo b", session_id=UUID("abab0000-0000-4000-8000-000000000002"))

        result: Result = _invoke("send", "--to", "abab", "hello")

        assert result.exit_code == 5
        assert "2 agents match" in result.stderr

    def test_timeout_without_wait_is_a_usage_error(self) -> None:
        agent: ParticipantDAO = _register_agent(name="slo target")

        result: Result = _invoke("send", "--to", str(agent.id), "--timeout", "5", "hello")

        assert result.exit_code == 2
        assert _conversation(agent_id=agent.id) == []

    def test_oversized_text_is_a_usage_error(self) -> None:
        agent: ParticipantDAO = _register_agent(name="slo target")

        result: Result = _invoke("send", "--to", str(agent.id), "x" * 70_000)

        assert result.exit_code == 2
        assert _conversation(agent_id=agent.id) == []


class TestFollowCommand:
    def test_prints_the_conversation_and_ends_when_the_agent_closes(self) -> None:
        agent: ParticipantDAO = _register_agent(name="slo followed")
        _invoke("send", "--to", str(agent.id), "first question")

        def _late_activity() -> None:
            time.sleep(0.8)

            async def _act(gateway: ChannelGateway) -> None:
                request: ChannelMessageDAO = (await gateway.pending_inbound(recipient_id=agent.id))[0]
                await gateway.accept(message_id=request.id)
                await ReplyWriter(gateway=gateway).write(
                    request=request, outcome=TurnOutcomeDAO(status="completed", final_text="late answer")
                )
                await gateway.close_agent(session_id=agent.id, reason="recipient_closed")

            _db(_act)

        actor: threading.Thread = threading.Thread(target=_late_activity, daemon=True)
        actor.start()
        result: Result = _invoke("follow", "--to", str(agent.id)[:8])
        actor.join(timeout=10.0)

        assert result.exit_code == 0, result.output
        lines: list[str] = result.stdout.splitlines()
        assert any("first question" in line and "[prompt]" in line for line in lines)
        assert any("late answer" in line and "[reply]" in line and "slo followed" in line for line in lines)
        assert "finished" in result.stdout.splitlines()[-1]

    def test_history_limits_the_backlog(self) -> None:
        agent: ParticipantDAO = _register_agent(name="slo chatty")
        for index in range(5):
            _invoke("send", "--to", str(agent.id), f"message {index}")
        _close_agent(agent_id=agent.id)

        result: Result = _invoke("follow", "--to", str(agent.id), "--history", "2")

        assert result.exit_code == 0
        assert "message 2" not in result.stdout
        assert "message 3" in result.stdout and "message 4" in result.stdout

    def test_unknown_agent_exits_5(self) -> None:
        assert _invoke("follow", "--to", "ffffffff").exit_code == 5


class TestRunCommand:
    def test_neither_name_nor_adapter_is_a_config_error(self) -> None:
        result: Result = _invoke("run")

        assert result.exit_code == 1
        assert "choose exactly one adapter" in result.stderr

    def test_both_name_and_adapter_is_a_config_error(self) -> None:
        assert _invoke("run", "telegram", "--adapter", "tests.fixtures:EchoAdapter").exit_code == 1

    def test_telegram_without_config_exits_1_naming_the_file(self) -> None:
        result: Result = _invoke("run", "telegram")

        assert result.exit_code == 1
        assert "telegram.json" in result.stderr

    def test_telegram_without_token_exits_1_naming_the_variable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("SLO_TELEGRAM_BOT_TOKEN", raising=False)
        config: Path = tmp_path / "telegram.json"
        config.write_text(json.dumps({"allowed_user_ids": [1]}), encoding="utf-8")
        os.chmod(config, 0o600)

        result: Result = _invoke("run", "telegram", "--config", str(config))

        assert result.exit_code == 1
        assert "SLO_TELEGRAM_BOT_TOKEN" in result.stderr

    def test_unloadable_adapter_reference_exits_1(self) -> None:
        result: Result = _invoke("run", "--adapter", "no_such_module_for_slo:Thing")

        assert result.exit_code == 1
        assert "cannot import" in result.stderr

    def test_x5_custom_adapter_subprocess_round_trips_and_stops_on_sigterm(self, tmp_path: Path) -> None:
        """X5 (CLI): ``slo channel run --adapter tests.fixtures:EchoAdapter`` in its own process."""
        agent: ParticipantDAO = _register_agent(name="slo echo target")
        outbox: Path = tmp_path / "outbox.jsonl"
        env: dict[str, str] = dict(os.environ)
        env["SLO_ECHO_ADAPTER_SCRIPT"] = json.dumps(
            {"user_ref": "u-9", "texts": [f"/attach {agent.id}", "ping"]}
        )
        env["SLO_ECHO_ADAPTER_OUTBOX"] = str(outbox)
        env["PYTHONPATH"] = str(_REPO_ROOT)
        process: subprocess.Popen[str] = subprocess.Popen(
            [sys.executable, "-m", "src.cli", "channel", "run", "--adapter", "tests.fixtures:EchoAdapter"],
            cwd=str(_REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            with AgentResponder(agent_id=agent.id, answer="pong"):
                deadline: float = time.monotonic() + 60.0
                while not _delivered_records(path=outbox):
                    assert process.poll() is None, process.communicate()[1]
                    assert time.monotonic() < deadline, "no delivery from the adapter subprocess"
                    time.sleep(0.1)
            process.send_signal(signal.SIGTERM)
            _stdout, stderr = process.communicate(timeout=30.0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

        assert process.returncode == 0, stderr
        assert "[channel echo] stopped" in stderr
        delivered: list[dict[str, object]] = _delivered_records(path=outbox)
        assert [record["text"] for record in delivered] == ["pong"]
        rows: list[ChannelMessageDAO] = _conversation(agent_id=agent.id)
        assert [row.message_type for row in rows] == ["prompt", "reply"]
        assert rows[1].accepted_at is not None


def _delivered_records(*, path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records: list[dict[str, object]] = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    return [record for record in records if record["kind"] == "delivered"]


class TestChannelHelp:
    def test_channel_group_is_a_root_subcommand(self) -> None:
        result: Result = CliRunner().invoke(app, ["channel", "--help"])

        assert result.exit_code == 0
        for command in ("agents", "send", "follow", "run"):
            assert command in result.stdout
