"""History-disabled sessions use the same fresh-prompt policy for every model."""

from pathlib import Path
from typing import Any
from src.agents.slo_agent.events.stream import AgentStreamEventDAO

# SDK constructor kwargs are heterogeneous vendor inputs, not an internal DAO.

import pytest
from claude_agent_sdk import ClaudeSDKClient

from src.bridges.claude.sdk import sdk_runtime
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.bridges.claude.test_shared_history import AnswerTransport
from tests.cli.test_claude_bridge import scripted_adapter_class


async def test_history_off_prompts_do_not_share_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A15: the second prompt carries no private bridge history and never resumes."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    resumes: list[str | None] = []

    class RecordingSDKClient(ClaudeSDKClient):
        """Observe native session selection through the vendor construction boundary."""

        def __init__(self, **kwargs: Any) -> None:
            """Record each SDK resume option, preserving real runtime behavior."""
            resumes.append(kwargs["options"].resume)
            super().__init__(**kwargs)

    monkeypatch.setattr(target=sdk_runtime, name="ClaudeSDKClient", value=RecordingSDKClient)
    transport = AnswerTransport()
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="history-off",
            enable_history=False,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        first: list[AgentStreamEventDAO] = [
            event async for event in session.invoke(text="first private prompt")
        ]
        assert first[-1].kind == "run_completed"
        assert await session._load_message_history() == []
        second: list[AgentStreamEventDAO] = [
            event async for event in session.invoke(text="second independent prompt")
        ]
        assert second[-1].kind == "run_completed"
        assert resumes == [None, None]
        assert transport.recorded == ["first private prompt", "second independent prompt"]
        assert not (tmp_path / "history" / "history-off" / "events.jsonl").exists()
        from src.agents.providers.faux import FauxChatModel
        from src.agents.slo_agent.agent import SloAgent

        direct = SloAgentSession(
            agent=SloAgent(
                llm=FauxChatModel(
                    responses=[
                        FauxChatModel.assistant_message(content="one"),
                        FauxChatModel.assistant_message(content="two"),
                    ]
                ),
                cwd=str(tmp_path),
                tools=[],
            ),
            workdir=tmp_path,
            session_id="direct-off",
            enable_history=False,
        )
        try:
            direct_first: list[AgentStreamEventDAO] = [
                event async for event in direct.invoke(text="first private prompt")
            ]
            assert direct_first[-1].kind == "run_completed"
            assert await direct._load_message_history() == []
            direct_second: list[AgentStreamEventDAO] = [
                event async for event in direct.invoke(text="second independent prompt")
            ]
            assert direct_second[-1].kind == "run_completed"
            assert [event.kind for event in first] == [event.kind for event in direct_first]
            assert [event.kind for event in second] == [event.kind for event in direct_second]
        finally:
            await direct.close_agent_resources()
    finally:
        await session.close_agent_resources()
