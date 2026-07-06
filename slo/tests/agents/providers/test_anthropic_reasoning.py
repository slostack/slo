"""Anthropic reasoning payload tests for feature 12 provider wiring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from langchain_core.messages import HumanMessage

from src.agents.providers.anthropic_claude_code import (
    anthropic_thinking_payload,
    build_claude_code_backed_chat_anthropic,
)
from src.agents.reasoning_capabilities import ResolvedReasoningConfigDAO
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName


def _oauth_cred() -> CredentialDAO:
    """Build an Anthropic OAuth credential for reasoning payload tests.

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


def _enabled_reasoning(*, provider_effort: str = "high") -> ResolvedReasoningConfigDAO:
    """Build an enabled resolved Anthropic reasoning config.

    Args:
        provider_effort (str, optional): Provider-native effort level.
            Defaults to ``"high"``.

    Returns:
        ResolvedReasoningConfigDAO: Enabled resolved config for builder tests.
    """
    return ResolvedReasoningConfigDAO(
        enabled=True,
        requested_level="high",
        active_level="high",
        provider_effort=provider_effort,
    )


class TestAnthropicReasoningPayloads:
    """Request-shape coverage for Anthropic reasoning-enabled builds."""

    def test_anthropic_thinking_payload_returns_adaptive_type(self) -> None:
        """Resolved reasoning config produces an adaptive thinking payload."""
        payload: dict[str, Any] = anthropic_thinking_payload(
            reasoning=_enabled_reasoning(provider_effort="medium"),
        )

        assert payload == {"type": "adaptive"}

    def test_builder_omits_temperature_when_reasoning_is_enabled(self) -> None:
        """Thinking-enabled Anthropic requests omit temperature like pi's provider."""
        chat = build_claude_code_backed_chat_anthropic(
            model_name="claude-sonnet-4-6",
            cred=_oauth_cred(),
            temperature=0.2,
            reasoning=_enabled_reasoning(),
        )

        assert chat.temperature is None
        assert chat.thinking == {"type": "adaptive"}

    def test_request_payload_includes_thinking_and_output_config_when_reasoning_is_enabled(
        self,
    ) -> None:
        """The outbound Anthropic payload carries ``thinking`` and ``output_config``."""
        chat = build_claude_code_backed_chat_anthropic(
            model_name="claude-sonnet-4-6",
            cred=_oauth_cred(),
            reasoning=_enabled_reasoning(provider_effort="medium"),
        )

        payload: dict[str, Any] = chat._get_request_payload(
            input_=[HumanMessage(content="hello")],
        )

        assert payload["thinking"] == {"type": "adaptive"}
        assert payload["output_config"] == {"effort": "medium"}
