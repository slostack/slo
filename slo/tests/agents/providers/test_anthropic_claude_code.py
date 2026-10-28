"""Tests for the Claude Code-backed Anthropic runtime lane."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables.base import RunnableBinding

from src.agents.providers.anthropic_claude_code import (
    ClaudeCodeChatAnthropic,
    build_claude_code_backed_chat_anthropic,
)
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName


def _oauth_cred() -> CredentialDAO:
    """Build an Anthropic OAuth credential for runtime-lane tests.

    Returns:
        CredentialDAO: OAuth credential with refresh metadata.
    """
    return CredentialDAO(
        provider=ProviderName.ANTHROPIC,
        auth_type=AuthType.OAUTH,
        access_token="sk-ant-oat01-test",
        refresh_token="refresh-test",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


class TestBuildClaudeCodeBackedChatAnthropic:
    """Constructor-level assertions for the Claude Code builder."""

    def test_uses_bearer_auth_client_params(self) -> None:
        """The builder stores the OAuth token under ``auth_token`` not ``api_key``."""
        chat: ClaudeCodeChatAnthropic = build_claude_code_backed_chat_anthropic(
            model_name="claude-sonnet-4-6",
            cred=_oauth_cred(),
            temperature=0.2,
            streaming=True,
            max_retries=5,
            max_tokens=777,
            model_kwargs={"x": "y"},
        )

        assert chat._client_params["auth_token"] == "sk-ant-oat01-test"
        assert "api_key" not in chat._client_params

    def test_omits_temperature_for_claude_opus_4_7(self) -> None:
        """`claude-opus-4-7` is built without the deprecated temperature field."""
        chat: ClaudeCodeChatAnthropic = build_claude_code_backed_chat_anthropic(
            model_name="claude-opus-4-7",
            cred=_oauth_cred(),
            temperature=0.2,
        )

        assert chat.model == "claude-opus-4-7"
        assert chat.temperature is None

    def test_keeps_temperature_for_other_supported_claude_models(self) -> None:
        """Models other than `claude-opus-4-7` still receive explicit temperature."""
        chat: ClaudeCodeChatAnthropic = build_claude_code_backed_chat_anthropic(
            model_name="claude-sonnet-4-6",
            cred=_oauth_cred(),
            temperature=0.2,
        )

        assert chat.temperature == 0.2

    def test_sets_required_headers_and_betas(self) -> None:
        """Claude Code headers and beta flags are present on the model."""
        chat: ClaudeCodeChatAnthropic = build_claude_code_backed_chat_anthropic(
            model_name="claude-sonnet-4-6",
            cred=_oauth_cred(),
        )

        assert chat.default_headers == {
            "anthropic-dangerous-direct-browser-access": "true",
            "user-agent": "claude-cli/2.1.75",
            "x-app": "cli",
        }
        assert chat.betas == ["claude-code-20250219", "oauth-2025-04-20"]


class TestClaudeCodePayloadShaping:
    """Request payload changes for Claude Code parity."""

    def test_prepends_identity_prelude_ahead_of_existing_system_prompt(self) -> None:
        """The Claude Code identity line comes before Slo's own system prompt."""
        chat: ClaudeCodeChatAnthropic = build_claude_code_backed_chat_anthropic(
            model_name="claude-sonnet-4-6",
            cred=_oauth_cred(),
        )

        payload: dict[str, Any] = chat._get_request_payload(
            input_=[
                SystemMessage(content="Slo system prompt."),
                HumanMessage(content="hello"),
            ]
        )

        assert payload["system"].startswith("You are Claude Code, Anthropic's official CLI for Claude.")
        assert "Slo system prompt." in payload["system"]

    def test_canonicalizes_shared_tool_names_on_outbound_payload(self) -> None:
        """Shared Slo tool names are title-cased to Claude Code's naming."""
        bound = build_claude_code_backed_chat_anthropic(
            model_name="claude-sonnet-4-6",
            cred=_oauth_cred(),
        ).bind_tools(
            tools=[
                {
                    "name": "read",
                    "description": "Read a file.",
                    "input_schema": {"type": "object", "properties": {}},
                },
                {
                    "name": "bash",
                    "description": "Run bash.",
                    "input_schema": {"type": "object", "properties": {}},
                },
            ]
        )
        assert isinstance(bound, RunnableBinding)
        chat = bound.bound
        assert isinstance(chat, ClaudeCodeChatAnthropic)

        payload: dict[str, Any] = chat._get_request_payload(
            input_=[HumanMessage(content="use tools")],
            **bound.kwargs,
        )

        assert [tool["name"] for tool in payload["tools"]] == ["Read", "Bash"]

    def test_patches_thinking_blocks_missing_thinking_field(self) -> None:
        """Signature-only thinking blocks get an empty thinking field to satisfy the API schema.

        When Claude uses adaptive thinking with no visible text, LangChain
        accumulates a block missing the required 'thinking' key. The Anthropic
        API rejects this with 400 'thinking.thinking: Field required'. The
        payload patcher adds 'thinking: ""' to unblock continuation requests.
        """
        from langchain_core.messages import AIMessage, ToolMessage

        chat: ClaudeCodeChatAnthropic = build_claude_code_backed_chat_anthropic(
            model_name="claude-sonnet-4-6",
            cred=_oauth_cred(),
        )
        # Simulate the AIMessage LangChain produces when Anthropic returns a
        # signature-only thinking block (no thinking_delta, only signature_delta).
        ai_msg = AIMessage(
            content=[
                {"type": "thinking", "signature": "sig-abc", "index": 0},
                {"type": "tool_use", "id": "call_1", "name": "bash", "input": {"cmd": "ls"}},
            ],
            tool_calls=[{"id": "call_1", "name": "bash", "args": {"cmd": "ls"}, "type": "tool_call"}],
        )
        tool_msg = ToolMessage(content="file.txt", tool_call_id="call_1", name="bash")

        payload: dict[str, Any] = chat._get_request_payload(
            input_=[HumanMessage(content="go"), ai_msg, tool_msg],
        )

        assistant_blocks: list[dict[str, Any]] = [
            m["content"] for m in payload["messages"] if m.get("role") == "assistant"
        ][0]
        thinking_block: dict[str, Any] = next(b for b in assistant_blocks if b.get("type") == "thinking")
        assert "thinking" in thinking_block
        assert thinking_block["thinking"] == ""
        assert thinking_block["signature"] == "sig-abc"

    def test_does_not_overwrite_existing_thinking_content(self) -> None:
        """Thinking blocks with existing content are not modified by the patcher."""
        from langchain_core.messages import AIMessage, ToolMessage

        chat: ClaudeCodeChatAnthropic = build_claude_code_backed_chat_anthropic(
            model_name="claude-sonnet-4-6",
            cred=_oauth_cred(),
        )
        ai_msg = AIMessage(
            content=[
                {
                    "type": "thinking",
                    "thinking": "Let me read the file first.",
                    "signature": "sig-xyz",
                    "index": 0,
                },
                {"type": "tool_use", "id": "call_2", "name": "read", "input": {"path": "a.py"}},
            ],
            tool_calls=[{"id": "call_2", "name": "read", "args": {"path": "a.py"}, "type": "tool_call"}],
        )
        tool_msg = ToolMessage(content="content", tool_call_id="call_2", name="read")

        payload: dict[str, Any] = chat._get_request_payload(
            input_=[HumanMessage(content="go"), ai_msg, tool_msg],
        )

        assistant_blocks: list[dict[str, Any]] = [
            m["content"] for m in payload["messages"] if m.get("role") == "assistant"
        ][0]
        thinking_block: dict[str, Any] = next(b for b in assistant_blocks if b.get("type") == "thinking")
        assert thinking_block["thinking"] == "Let me read the file first."


class TestClaudeCodeOutputNormalization:
    """Inbound tool calls are normalized back to Slo tool names."""

    def test_normalizes_inbound_tool_call_names_back_to_lowercase(self) -> None:
        """Claude Code's tool names are mapped back before graph execution."""
        chat: ClaudeCodeChatAnthropic = build_claude_code_backed_chat_anthropic(
            model_name="claude-sonnet-4-6",
            cred=_oauth_cred(),
        )
        response: Any = SimpleNamespace(
            model_dump=lambda: {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Read",
                        "input": {"path": "README.md"},
                    }
                ],
                "model": "claude-sonnet-4-6",
            },
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )

        with patch.object(
            ClaudeCodeChatAnthropic,
            "_tool_name_candidates",
            return_value=["read", "bash"],
        ):
            result = chat._format_output(response)

        message = result.generations[0].message
        assert isinstance(message, AIMessage)
        assert message.tool_calls[0]["name"] == "read"
        assert isinstance(message.content, list)
        block = message.content[0]
        assert isinstance(block, dict)
        assert block["name"] == "read"
