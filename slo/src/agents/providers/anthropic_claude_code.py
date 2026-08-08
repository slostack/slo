"""Anthropic Claude Code subscription runtime lane.

Routes Anthropic OAuth credentials through a Claude Code-shaped
``ChatAnthropic`` specialization that uses bearer auth semantics,
Claude Code headers / beta flags, an identity prelude, and tool-name
normalization in both directions.
"""

from __future__ import annotations

from functools import cached_property
from typing import Any, Optional, cast

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.agents.reasoning_capabilities import ResolvedReasoningConfigDAO
from src.auth.credential_dao import CredentialDAO

__all__ = [
    "ClaudeCodeChatAnthropic",
    "anthropic_thinking_payload",
    "build_claude_code_backed_chat_anthropic",
    "_ThinkingPatchedChatAnthropic",
]


_CLAUDE_CODE_IDENTITY_PRELUDE: str = "You are Claude Code, Anthropic's official CLI for Claude."
_CLAUDE_CODE_USER_AGENT: str = "claude-cli/2.1.75"
_CLAUDE_CODE_APP_HEADER: str = "cli"
_CLAUDE_CODE_BETAS: tuple[str, ...] = (
    "claude-code-20250219",
    "oauth-2025-04-20",
)
_TEMPERATURE_UNSUPPORTED_MODELS: frozenset[str] = frozenset({"claude-opus-4-7"})
_OUTBOUND_TOOL_NAME_MAP: dict[str, str] = {
    "read": "Read",
    "write": "Write",
    "edit": "Edit",
    "bash": "Bash",
    "grep": "Grep",
}


def _patch_thinking_blocks(*, messages: list[dict[str, Any]]) -> None:
    """Ensure every ``thinking`` content block carries a ``thinking`` field.

    When Claude uses adaptive thinking with no visible text (signature-only
    streaming), LangChain accumulates an incomplete block that omits the
    ``thinking`` key entirely. The Anthropic API rejects these with a 400
    ``thinking.thinking: Field required``. Patching to an empty string
    satisfies the schema requirement without altering actual content.

    Args:
        messages (list[dict[str, Any]]): Anthropic request messages list,
            mutated in place.
    """
    for message in messages:
        content: Any = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "thinking"
                and "thinking" not in block
            ):
                block["thinking"] = ""


class _ThinkingPatchedChatAnthropic(ChatAnthropic):
    """ChatAnthropic that patches incomplete thinking blocks before each API request.

    Covers the Anthropic API-key credential path. The OAuth (Claude Code) path
    subclasses this so the fix applies to both lanes.
    """

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: Optional[list[str]] = None,
        **kwargs: dict,
    ) -> dict:
        """Build the Anthropic request payload and patch any incomplete thinking blocks.

        Args:
            input_ (LanguageModelInput): LangChain input history.
            stop (Optional[list[str]]): Optional stop sequences.
            **kwargs (dict): Additional provider kwargs.

        Returns:
            dict: Anthropic request payload with thinking blocks patched.
        """
        payload: dict[str, Any] = super()._get_request_payload(
            input_=input_,
            stop=stop,
            **kwargs,
        )
        _patch_thinking_blocks(messages=payload.get("messages", []))
        return payload


class ClaudeCodeChatAnthropic(_ThinkingPatchedChatAnthropic):
    """Anthropic chat model specialized for Claude Code OAuth tokens."""

    @cached_property
    def _client_params(self) -> dict[str, Any]:
        """Build Anthropic client kwargs using bearer-auth semantics.

        Returns:
            dict[str, Any]: Client parameters for the underlying
                Anthropic SDK.
        """
        client_params: dict[str, Any] = {
            "auth_token": self.anthropic_api_key.get_secret_value(),
            "base_url": self.anthropic_api_url,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers or None,
        }
        if self.default_request_timeout is None or self.default_request_timeout > 0:
            client_params["timeout"] = self.default_request_timeout
        return client_params

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: Optional[list[str]] = None,
        **kwargs: dict,
    ) -> dict:
        """Inject Claude Code identity, canonicalize tool names, and patch thinking blocks.

        Thinking block patching is inherited from ``_ThinkingPatchedChatAnthropic``
        via ``super()``, so it runs for both the API-key and OAuth paths.

        Args:
            input_ (LanguageModelInput): LangChain input history.
            stop (Optional[list[str]]): Optional stop sequences.
            **kwargs (dict): Additional provider kwargs.

        Returns:
            dict: Anthropic request payload.
        """
        payload: dict[str, Any] = super()._get_request_payload(
            input_=input_,
            stop=stop,
            **kwargs,
        )
        payload["system"] = self._prepend_identity_prelude(
            system=payload.get("system"),
        )
        if payload.get("tools"):
            payload["tools"] = [
                self._canonicalize_tool_schema(tool=tool)
                for tool in cast(list[dict[str, Any]], payload["tools"])
            ]
        return payload

    def _format_output(self, data: Any, **kwargs: Any) -> ChatResult:
        """Normalize inbound Claude Code tool names back to Slo names.

        Args:
            data (Any): Raw Anthropic SDK response object.
            **kwargs (Any): LangChain extension hook kwargs.

        Returns:
            ChatResult: Normalized chat result.
        """
        result: ChatResult = super()._format_output(data, **kwargs)
        message: BaseMessage = result.generations[0].message
        if not isinstance(message, AIMessage) or not message.tool_calls:
            return result

        available_tool_names: list[str] = self._tool_name_candidates()
        normalized_tool_calls: list[dict[str, Any]] = []
        for tool_call in message.tool_calls:
            normalized_tool_call: dict[str, Any] = dict(tool_call)
            normalized_tool_call["name"] = self._normalize_inbound_tool_name(
                tool_name=str(tool_call["name"]),
                available_tool_names=available_tool_names,
            )
            normalized_tool_calls.append(normalized_tool_call)

        normalized_content: list[Any] = []
        for block in cast(list[Any], message.content):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                normalized_block: dict[str, Any] = dict(block)
                normalized_block["name"] = self._normalize_inbound_tool_name(
                    tool_name=str(block["name"]),
                    available_tool_names=available_tool_names,
                )
                normalized_content.append(normalized_block)
                continue
            normalized_content.append(block)

        normalized_message: AIMessage = AIMessage(
            content=normalized_content,
            tool_calls=normalized_tool_calls,
            usage_metadata=message.usage_metadata,
            response_metadata=message.response_metadata,
            additional_kwargs=message.additional_kwargs,
            id=message.id,
        )
        result.generations[0] = ChatGeneration(message=normalized_message)
        return result

    def _prepend_identity_prelude(self, *, system: Any) -> Any:
        """Prepend the Claude Code identity line to the system content.

        Args:
            system (Any): Existing Anthropic ``system`` payload.

        Returns:
            Any: Updated system payload.
        """
        if system is None:
            return _CLAUDE_CODE_IDENTITY_PRELUDE
        if isinstance(system, str):
            return f"{_CLAUDE_CODE_IDENTITY_PRELUDE}\n\n{system}"
        if isinstance(system, list):
            return [
                {"type": "text", "text": _CLAUDE_CODE_IDENTITY_PRELUDE},
                *system,
            ]
        return system

    def _canonicalize_tool_schema(self, *, tool: dict[str, Any]) -> dict[str, Any]:
        """Map Slo tool names to Claude Code's preferred casing.

        Args:
            tool (dict[str, Any]): One outbound Anthropic tool schema.

        Returns:
            dict[str, Any]: Tool schema with a canonicalized ``name``.
        """
        canonicalized_tool: dict[str, Any] = dict(tool)
        tool_name: str = str(tool.get("name", ""))
        canonicalized_tool["name"] = _OUTBOUND_TOOL_NAME_MAP.get(
            tool_name.lower(),
            tool_name,
        )
        return canonicalized_tool

    def _tool_name_candidates(self) -> list[str]:
        """Return the currently bound Slo tool names.

        Returns:
            list[str]: Tool names available on the model instance.
        """
        tool_payloads: list[dict[str, Any]] = cast(
            list[dict[str, Any]],
            getattr(self, "tools", None) or self.kwargs.get("tools", []) or [],
        )
        return [
            str(tool.get("name")) for tool in tool_payloads if isinstance(tool, dict) and tool.get("name")
        ]

    def _normalize_inbound_tool_name(
        self,
        *,
        tool_name: str,
        available_tool_names: list[str],
    ) -> str:
        """Normalize one inbound tool-call name back to Slo's registry.

        Args:
            tool_name (str): Tool name returned by Anthropic.
            available_tool_names (list[str]): Bound Slo tool names.

        Returns:
            str: The matching Slo tool name, or the original name when
                no match exists.
        """
        for candidate in available_tool_names:
            if candidate.lower() == tool_name.lower():
                return candidate
        for slo_name, canonical_name in _OUTBOUND_TOOL_NAME_MAP.items():
            if canonical_name.lower() == tool_name.lower():
                for candidate in available_tool_names:
                    if candidate.lower() == slo_name:
                        return candidate
                return slo_name
        return tool_name


def anthropic_thinking_payload(
    *,
    reasoning: Optional[ResolvedReasoningConfigDAO],
) -> Optional[dict[str, Any]]:
    """Build the Anthropic ``thinking`` payload from resolved config.

    The Anthropic API uses adaptive thinking (``thinking.type = "adaptive"``)
    with a separate ``output_config.effort`` parameter for effort control.
    The old ``type = "enabled"`` / ``budget_tokens`` format is no longer
    supported for current Claude models.

    Args:
        reasoning (Optional[ResolvedReasoningConfigDAO]): Resolved
            reasoning config for the active model.

    Returns:
        Optional[dict[str, Any]]: Anthropic ``thinking`` payload, or
            ``None`` when reasoning is disabled.
    """
    if reasoning is None or not reasoning.enabled:
        return None
    return {"type": "adaptive"}


def build_claude_code_backed_chat_anthropic(
    *,
    model_name: str,
    cred: CredentialDAO,
    temperature: Optional[float] = None,
    reasoning: Optional[ResolvedReasoningConfigDAO] = None,
    streaming: bool = True,
    max_retries: int = 3,
    max_tokens: Optional[int] = None,
    model_kwargs: Optional[dict[str, Any]] = None,
) -> ClaudeCodeChatAnthropic:
    """Build the Claude Code-backed Anthropic runtime lane.

    Args:
        model_name (str): API model name sent to the provider. Callers resolve
            it from the canonical model name via
            ``ModelCatalogService.api_model_name_for`` before building.
        cred (CredentialDAO): OAuth credential resolved for Anthropic.
        temperature (Optional[float]): Forwarded to ``ChatAnthropic``
            when reasoning is disabled.
        reasoning (Optional[ResolvedReasoningConfigDAO]): Resolved
            provider-ready reasoning config.
        streaming (bool): Streaming flag.
        max_retries (int): SDK retry count.
        max_tokens (Optional[int]): Optional max token cap.
        model_kwargs (Optional[dict[str, Any]]): Provider extras.

    Returns:
        ClaudeCodeChatAnthropic: Configured Claude Code-backed model.
    """
    thinking: Optional[dict[str, Any]] = anthropic_thinking_payload(reasoning=reasoning)
    merged_model_kwargs: dict[str, Any] = dict(model_kwargs or {})
    if thinking is not None and reasoning is not None and reasoning.provider_effort is not None:
        merged_model_kwargs["output_config"] = {"effort": reasoning.provider_effort}
    kwargs: dict[str, Any] = {
        "model": model_name,
        "streaming": streaming,
        "max_retries": max_retries,
        "anthropic_api_key": cred.access_token,
        "model_kwargs": merged_model_kwargs,
        "default_headers": {
            "anthropic-dangerous-direct-browser-access": "true",
            "user-agent": _CLAUDE_CODE_USER_AGENT,
            "x-app": _CLAUDE_CODE_APP_HEADER,
        },
        "betas": list(_CLAUDE_CODE_BETAS),
    }
    if thinking is not None:
        kwargs["thinking"] = thinking
    if temperature is not None and thinking is None and model_name not in _TEMPERATURE_UNSUPPORTED_MODELS:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return ClaudeCodeChatAnthropic(**kwargs)
