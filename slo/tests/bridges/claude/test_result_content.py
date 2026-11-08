"""Live terminal content through the real host bridge, official SDK and MCP."""

import asyncio
from pathlib import Path
from typing import Any, Literal

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from src.agents.tools.bundles import create_read_only_tools
from src.bridges.claude.bridge import SloClaudeBridge
from src.bridges.claude.sdk.dao import ClaudeBridgeConfigurationDAO
from src.bridges.dao import SloBridgeSessionOptionsDAO
from tests.cli.test_claude_bridge import ToolRoundTransport, scripted_adapter_class


@pytest.mark.parametrize(
    ("content", "status", "expected_content", "is_error"),
    [
        ("", "success", [{"type": "text", "text": ""}], False),
        ([], "success", [], False),
        (
            ["", {"type": "text", "text": "Error: ordinary prose"}],
            "success",
            [{"type": "text", "text": ""}, {"type": "text", "text": "Error: ordinary prose"}],
            False,
        ),
        ("Error: file not found", "success", [{"type": "text", "text": "Error: file not found"}], False),
        (
            [
                {"type": "text", "text": "before"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "eA=="}},
                {"type": "text", "text": "after"},
            ],
            "success",
            [
                {"type": "text", "text": "before"},
                {"type": "image", "mimeType": "image/png", "data": "eA=="},
                {"type": "text", "text": "after"},
            ],
            False,
        ),
        ("executor denied", "error", [{"type": "text", "text": "executor denied"}], True),
        ("", "error", [{"type": "text", "text": ""}], True),
    ],
)
async def test_terminal_content_reaches_mcp_without_prose_status_inference(
    tmp_path: Path,
    content: str | list[str | dict[str, Any]],
    status: Literal["success", "error"],
    expected_content: list[dict[str, Any]],
    is_error: bool,
) -> None:
    """A9: empty/list/error output preserves exact blocks and semantic terminal status."""
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
            session_id="content", working_directory=tmp_path, instructions="test"
        )
    )
    human = HumanMessage(content="Read project")
    try:
        async with asyncio.timeout(5):
            assistant = await model.ainvoke(input=[human])
            answer = await model.ainvoke(
                input=[
                    human,
                    assistant,
                    ToolMessage(content=content, status=status, tool_call_id="exact-native-id"),
                ]
            )
        assert answer.content == "Hello bridge"
        assert transport.prompts == ["Read project"]
        assert len(transport.tool_results) == 1
        receipt = transport.tool_results[0]["response"]["mcp_response"]["result"]
        assert receipt["content"] == expected_content
        assert receipt["isError"] is is_error
        assert transport.close_calls == 1
    finally:
        await model.close()
