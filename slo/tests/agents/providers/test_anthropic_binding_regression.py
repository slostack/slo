"""Offline public binding regression for request-owned tool normalization."""

from unittest.mock import AsyncMock, patch

import pytest
from anthropic.types import Message
from langchain_core.messages import AIMessage

from src.agents.providers.anthropic_claude_code import ClaudeCodeChatAnthropic
from tests.agents.providers.test_anthropic_claude_code import _oauth_cred
from src.agents.providers.anthropic_claude_code import build_claude_code_backed_chat_anthropic


@pytest.mark.parametrize(
    "bound_name,returned_name,expected",
    [(None, "Read", "read"), ("myTool", "MYTOOL", "myTool"), ("read", "Read", "read")],
)
async def test_public_binding_owns_tool_candidates(
    bound_name: str | None, returned_name: str, expected: str
) -> None:
    """Normalize from this invocation's binding without storing tools on the model."""
    chat = build_claude_code_backed_chat_anthropic(
        model_name="claude-sonnet-4-6", cred=_oauth_cred(), streaming=False
    )
    response = Message.model_validate(
        {
            "id": "msg-test",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-6",
            "content": [{"type": "tool_use", "id": "call-test", "name": returned_name, "input": {}}],
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )
    runnable = (
        chat
        if bound_name is None
        else chat.bind_tools(
            tools=[
                {
                    "name": bound_name,
                    "description": "Offline tool",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ]
        )
    )
    with patch.object(ClaudeCodeChatAnthropic, "_acreate", new=AsyncMock(return_value=response)) as create:
        message = await runnable.ainvoke("use tool")
    assert isinstance(message, AIMessage)
    assert message.tool_calls[0]["name"] == expected
    assert isinstance(message.content, list)
    block = message.content[0]
    assert isinstance(block, dict)
    assert block["name"] == expected
    payload = create.call_args.args[0]
    if bound_name is None:
        assert "tools" not in payload
    else:
        assert payload["tools"][0]["name"] == ("Read" if bound_name == "read" else bound_name)
    assert "tools" not in chat.__dict__
