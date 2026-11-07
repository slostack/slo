"""Offline headless orchestrator admission and child launch-policy proofs."""

import asyncio
import json
from pathlib import Path
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from typing import Any

import pytest

from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.cli.headless import HeadlessRunner
from tests.cli.test_claude_bridge import ScriptedClaudeTransport, scripted_adapter_class


@pytest.mark.parametrize("system_prompt", [None, "custom parent instructions"])
async def test_headless_orchestrator_on_bridge_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    system_prompt: str | None,
) -> None:
    """A11: actual headless assembly attaches spawn only, including custom instructions."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport()
    prepared: list[SloAgentSession] = []
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="claude-bridge:claude-haiku-5-5",
        reasoning_level="off",
        session_id="headless-parent",
        history_root=tmp_path / "history",
        system_prompt=system_prompt,
    )

    async def prepare(config: SessionConfigDAO) -> SloAgentSession:
        """Keep real preparation, native adapter, graph and filesystem persistence."""
        session = await SloAgentSession.prepare(
            config=config, bridge_adapter_class=scripted_adapter_class(transport=transport)
        )
        prepared.append(session)
        return session

    async with asyncio.timeout(10):
        code = await HeadlessRunner(config=config, orchestrator_mode=True, session_preparer=prepare).invoke(
            prompt="hello"
        )
    # Headless JSONL is a heterogeneous external wire envelope.
    output: list[dict[str, Any]] = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 0, output
    [session] = prepared
    assert {tool.name for tool in session.orchestration_tools} == {"spawn_sub_agents"}
    assert len(transport.initialized_tools) == 11
    assert sum(event["kind"] == "run_completed" for event in output) == 1
    assert transport.closed and transport.close_calls == 1
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore

    stored: list[SessionHistoryEventDAO] = await FilesystemSessionHistoryStore(
        root=tmp_path / "history"
    ).load_events(session_id="headless-parent")
    assert [event.payload.content for event in stored if event.kind == "user_message"] == ["hello"]
    assert [event.payload.content for event in stored if event.kind == "assistant_message"] == [
        "Hello bridge"
    ]
    assert sum(event.kind == "run_completed" for event in stored) == 1
    assert not any(event.kind in {"run_failed", "run_aborted"} for event in stored)


def test_child_command_and_environment_for_bridge_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A12: qualified route and opt-in/HOME survive while account API secrets do not."""
    from src.agents.slo_agent.orchestrator.process import SubAgentProcess
    from src.agents.slo_agent.orchestrator.registry import ProcessRegistry
    from src.agents.slo_agent.orchestrator.dao import SubAgentTaskDAO
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    monkeypatch.setenv(name="ANTHROPIC_API_KEY", value="synthetic-never-forward")
    monkeypatch.setenv(name="HOME", value=str(tmp_path / "home"))

    async def relay(event: AgentStreamEventDAO) -> None:
        """Accept no events; this static policy check never starts a process."""

    task = SubAgentTaskDAO(
        task_id="child",
        task_summary="Inspect launch configuration",
        prompt="Inspect configuration",
        model="claude-bridge:claude-haiku-5-5",
    )
    process = SubAgentProcess(
        task=task,
        session_id="child",
        model=task.model,
        relay=relay,
        registry=ProcessRegistry(),
        execution_id="synthetic",
        history_root=tmp_path / "history",
    )
    argv: list[str] = process._build_argv()
    assert argv[argv.index("--model") + 1] == "claude-bridge:claude-haiku-5-5"
    env: dict[str, str] = process._build_child_spawn_env()
    assert env["HOME"] == str(tmp_path / "home")
    assert env["SLO_CLAUDE_BRIDGE_ENABLED"] == "1"
    assert "ANTHROPIC_API_KEY" not in env
