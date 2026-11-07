"""Host semantic-prefix rejection through the real bridge and SDK transport."""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.bridges.claude.bridge import SloClaudeBridge
from src.bridges.dao import SloBridgeSessionOptionsDAO
from tests.cli.test_claude_bridge import ToolRoundTransport, scripted_adapter_class
from src.bridges.claude.sdk.dao import ClaudeBridgeConfigurationDAO


@pytest.mark.parametrize(
    "mutation",
    [
        "human-content",
        "assistant-content",
        "assistant-arguments",
        "closed",
        "unsupported-block",
        "unsupported-source",
        "unknown-result",
        "duplicate-result",
    ],
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
        elif mutation == "unknown-result":
            messages.append(ToolMessage(content="foreign", tool_call_id="unknown"))
        elif mutation == "duplicate-result":
            messages.append(ToolMessage(content="synthetic", tool_call_id="exact-native-id"))
        elif mutation == "unsupported-block":
            result.content = [{"type": "text", "text": "must not deliver"}, {"type": "audio", "data": "x"}]
        elif mutation == "unsupported-source":
            result.content = [{"type": "image", "source": {"type": "url", "url": "https://invalid.test/x"}}]
        else:
            await model.close()
        with pytest.raises((ValueError, RuntimeError)):
            await model.ainvoke(input=messages)
        assert transport.prompts == ["Read project"]
        assert transport.tool_results == []
        assert transport.closed
    finally:
        await model.close()


async def test_nested_earlier_result_mutation_rejects_next_round_without_delivery(tmp_path: Path) -> None:
    """A13: nested accepted result content is detached across later response boundaries."""
    from src.agents.tools.bundles import create_read_only_tools

    transport = ToolRoundTransport(path=tmp_path / "model.txt", multiple_rounds=True)
    model = SloClaudeBridge(
        model_name="claude-bridge:claude-haiku-5-5",
        bridge_adapter=scripted_adapter_class(transport=transport).register(
            configuration=ClaudeBridgeConfigurationDAO()
        ),
    )
    model.bind_tools(tools=create_read_only_tools())
    model.configure_session(
        session_options=SloBridgeSessionOptionsDAO(
            session_id="host", working_directory=tmp_path, instructions="test"
        )
    )
    human = HumanMessage(content="Read project")
    try:
        first = await model.ainvoke(input=[human])
        result = ToolMessage(content=[{"type": "text", "text": "accepted"}], tool_call_id="exact-native-id-1")
        second = await model.ainvoke(input=[human, first, result])
        assert isinstance(result.content, list)
        assert isinstance(result.content[0], dict)
        result.content[0]["text"] = "changed nested prior result"
        with pytest.raises(ValueError, match="prefix changed"):
            await model.ainvoke(
                input=[
                    human,
                    first,
                    result,
                    second,
                    ToolMessage(content="next", tool_call_id="exact-native-id-2"),
                ]
            )
        assert transport.prompts == ["Read project"] and len(transport.tool_results) == 1
        assert transport.round == 2 and transport.closed
    finally:
        await model.close()


async def test_missing_host_results_remain_parked_until_complete_submission(tmp_path: Path) -> None:
    """A8: a correctable missing set does not close or advance the retained invocation."""
    from src.agents.tools.bundles import create_read_only_tools

    transport = ToolRoundTransport(path=tmp_path / "model.txt")
    model = SloClaudeBridge(
        model_name="claude-bridge:claude-haiku-5-5",
        bridge_adapter=scripted_adapter_class(transport=transport).register(
            configuration=ClaudeBridgeConfigurationDAO()
        ),
    )
    model.bind_tools(tools=create_read_only_tools())
    model.configure_session(
        session_options=SloBridgeSessionOptionsDAO(
            session_id="host",
            working_directory=tmp_path,
            instructions="test",
        )
    )
    human = HumanMessage(content="Read project")
    try:
        assistant = await model.ainvoke(input=[human])
        # The ordered planner rejects an empty suffix as an invalid prompt,
        # before native admission; the parked round remains correctable.
        with pytest.raises(ValueError, match="human prompt"):
            await model.ainvoke(input=[human, assistant])
        assert not transport.closed and transport.tool_results == []
        final = await model.ainvoke(
            input=[
                human,
                assistant,
                ToolMessage(content="synthetic", tool_call_id="exact-native-id"),
            ]
        )
        assert final.content == "Hello bridge"
        assert transport.prompts == ["Read project"]
        assert len(transport.tool_results) == 1 and transport.closed
    finally:
        await model.close()
