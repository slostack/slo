"""Claude bridge usage reaches session totals like any other model (101.a.3)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO, TokenUsageTotalsDAO
from src.tui.widgets.usage_status_bar import UsageStatusBar
from tests.cli.test_claude_bridge import ScriptedClaudeTransport, scripted_adapter_class
from tests.cli.test_claude_bridge_coding import CodingRoundsTransport

TOOL_ROUND_START: dict[str, int] = {
    "input_tokens": 100,
    "output_tokens": 1,
    "cache_creation_input_tokens": 20,
    "cache_read_input_tokens": 10,
}
TOOL_ROUND_DELTA: dict[str, int] = {**TOOL_ROUND_START, "output_tokens": 30}
FINAL_START: dict[str, int] = {
    "input_tokens": 50,
    "output_tokens": 1,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 70,
}
FINAL_DELTA: dict[str, int] = {**FINAL_START, "output_tokens": 12}


def bridge_config(*, tmp_path: Path, session_id: str) -> SessionConfigDAO:
    """Real bridge-route session without history persistence."""
    return SessionConfigDAO(
        workdir=tmp_path,
        model_name="claude-bridge:claude-haiku-5-5",
        reasoning_level="off",
        session_id=session_id,
        enable_history=False,
    )


async def run_bridge(
    *, tmp_path: Path, transport: ScriptedClaudeTransport, session_id: str
) -> tuple[SessionUsageSnapshotDAO, list[str]]:
    """Run one prompt through the real session and return its usage snapshot and event kinds."""
    session = await SloAgentSession.prepare(
        config=bridge_config(tmp_path=tmp_path, session_id=session_id),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(20):
            kinds: list[str] = [event.kind async for event in session.invoke(text="Read the file")]
        return session.refresh_usage_snapshot(), kinds
    finally:
        await session.close_agent_resources()


async def test_usage_reaches_session_totals_like_any_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-response stream usage sums across rounds and equals a direct model given the same shape."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "note.txt"
    target.write_text("hello\n")
    transport = CodingRoundsTransport(
        rounds=[("exact-read", "read", {"path": str(target)})],
        round_usages=[(TOOL_ROUND_START, TOOL_ROUND_DELTA)],
    )
    transport.start_usage, transport.delta_usage = FINAL_START, FINAL_DELTA
    snapshot, kinds = await run_bridge(tmp_path=tmp_path, transport=transport, session_id="usage-bridge")
    assert kinds[-1] == "run_completed"
    expected = TokenUsageTotalsDAO(
        input_tokens=(100 + 20 + 10) + (50 + 0 + 70),
        output_tokens=30 + 12,
        total_tokens=(130 + 30) + (120 + 12),
        cache_creation_input_tokens=20,
        cache_read_input_tokens=80,
    )
    assert snapshot.usage_available
    assert snapshot.session_totals == expected
    rendered = UsageStatusBar._usage_text(snapshot=snapshot)
    assert "cache write 20" in rendered and "cache read 80" in rendered

    direct = await direct_model_totals(tmp_path=tmp_path, target=target)
    assert direct == snapshot.session_totals


async def direct_model_totals(*, tmp_path: Path, target: Path) -> TokenUsageTotalsDAO:
    """Run a FauxChatModel with the LangChain direct-Anthropic usage shape for the same two responses."""
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "read", "args": {"path": str(target)}, "id": "direct-read"}],
            usage_metadata={
                "input_tokens": 130,
                "output_tokens": 30,
                "total_tokens": 160,
                "input_token_details": {"cache_read": 10, "cache_creation": 20},
            },
        ),
        AIMessage(
            content="done",
            usage_metadata={
                "input_tokens": 120,
                "output_tokens": 12,
                "total_tokens": 132,
                "input_token_details": {"cache_read": 70, "cache_creation": 0},
            },
        ),
    ]
    session = SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=responses), cwd=str(tmp_path)),
        workdir=tmp_path,
        session_id="usage-direct",
        enable_history=False,
    )
    async for _ in session.invoke(text="Read the file"):
        pass
    return session.refresh_usage_snapshot().session_totals


@pytest.mark.parametrize(
    "start_usage, delta_usage",
    [
        (None, None),
        ({"input_tokens": -1, "output_tokens": "x"}, {"output_tokens": -5, "input_tokens": True}),
    ],
    ids=["absent", "malformed"],
)
async def test_missing_or_malformed_usage_is_unavailable_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, start_usage: Any, delta_usage: Any
) -> None:
    """Telemetry problems never fail the answer; the snapshot says usage is unavailable."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport()
    transport.start_usage, transport.delta_usage = start_usage, delta_usage
    snapshot, kinds = await run_bridge(tmp_path=tmp_path, transport=transport, session_id="usage-missing")
    assert kinds[-1] == "run_completed"
    assert not snapshot.usage_available
    assert snapshot.session_totals == TokenUsageTotalsDAO()
