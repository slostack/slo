"""End-to-end core Bash partial-output delivery through the real ReAct stream."""

from __future__ import annotations

from pathlib import Path

import pytest
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO


@pytest.mark.asyncio
async def test_real_bash_update_reaches_agent_stream_before_terminal_result(tmp_path: Path) -> None:
    """A real slow Bash call publishes partial events before one terminal ToolMessage.

    This drives the production sequence FauxChatModel -> SloAgent graph ->
    ToolExecutor -> LangChain Bash bridge -> BashTool -> graph queue -> agent
    stream. It intentionally does not call BashTool or the executor directly.

    Args:
        tmp_path (Path): Isolated current working directory for the agent.
    """
    tool_call_id: str = "bash-live-call"
    faux: FauxChatModel = FauxChatModel(
        responses=[
            FauxChatModel.assistant_message(
                tool_calls=[
                    FauxChatModel.tool_call_dict(
                        name="bash",
                        args={"command": "echo first; sleep 0.15; echo second"},
                        call_id=tool_call_id,
                    )
                ],
            ),
            FauxChatModel.assistant_message(content="completed"),
        ]
    )
    agent: SloAgent = SloAgent(llm=faux, cwd=str(tmp_path))

    events: list[AgentStreamEventDAO] = [event async for event in agent.invoke(query="run slow bash")]

    updates: list[AgentStreamEventDAO] = [event for event in events if event.kind == "tool_output_update"]
    results: list[AgentStreamEventDAO] = [event for event in events if event.kind == "tool_result"]
    assert updates
    assert len(results) == 1
    assert {event.tool_call_id for event in updates} == {tool_call_id}
    assert {event.tool_name for event in updates} == {"bash"}
    assert "first" in (updates[-1].content or "")
    assert "second" in (results[0].content or "")
    assert max(events.index(event) for event in updates) < events.index(results[0])

    # ``tool_result`` is the normalized projection of the sole model-visible
    # ToolMessage produced by the executor. Updates are display-only and do not
    # create additional terminal results.
    assert results[0].tool_call_id == tool_call_id
