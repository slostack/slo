"""Host semantic-prefix rejection through the real bridge and SDK transport."""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.bridges.claude.bridge import SloClaudeBridge
from src.bridges.dao import SloBridgeSessionOptionsDAO
from tests.cli.test_claude_bridge import ToolRoundTransport, scripted_adapter_class
from src.bridges.claude.sdk.dao import ClaudeBridgeConfigurationDAO


@pytest.mark.parametrize(
    "mutation", ["human-content", "assistant-content", "assistant-arguments", "new-user", "closed"]
)
async def test_mutated_consumed_prefix_never_delivers_results(mutation: str, tmp_path: Path) -> None:
    """EF14-03: no native continuation may follow any changed semantic content."""
    transport = ToolRoundTransport(path=tmp_path / "model.txt")
    adapter = scripted_adapter_class(transport=transport).register(
        configuration=ClaudeBridgeConfigurationDAO()
    )
    model = SloClaudeBridge(model_name="claude-bridge:claude-haiku-5-5", bridge_adapter=adapter)
    from src.agents.tools.bundles import create_read_only_tools

    model.bind_tools(tools=create_read_only_tools())
    model.configure_session(
        session_options=SloBridgeSessionOptionsDAO(
            session_id="host", working_directory=tmp_path, instructions="test"
        )
    )
    human = HumanMessage(content="Read project")
    try:
        assistant = await model.ainvoke(input=[human])
        assert isinstance(assistant, AIMessage)
        result = ToolMessage(content="synthetic", tool_call_id="exact-native-id")
        messages = [human, assistant, result]
        if mutation == "human-content":
            human.content = "changed"
        elif mutation == "assistant-content":
            assistant.content = "changed"
        elif mutation == "assistant-arguments":
            assistant.tool_calls[0]["args"]["path"] = "changed"
        elif mutation == "new-user":
            messages.append(HumanMessage(content="Another prompt"))
        else:
            await model.close()
        with pytest.raises((ValueError, RuntimeError)):
            await model.ainvoke(input=messages)
        assert transport.prompts == ["Read project"]
        assert transport.tool_results == []
    finally:
        await model.close()
