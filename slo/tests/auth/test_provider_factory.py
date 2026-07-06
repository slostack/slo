"""Tests for ``OAuthFlowFactory`` (02.b.4)."""
import pytest

from src.auth.credential_dao import ProviderName
from src.auth.oauth_flow import OAuthFlow
from src.auth.provider_factory import OAuthFlowFactory
from src.auth.providers import AnthropicOAuthProvider, OpenAICodexOAuthProvider


class TestForProvider:
    """``for_provider`` returns a ready ``OAuthFlow`` for known providers."""

    def test_returns_flow_for_anthropic(self) -> None:
        """Anthropic provider → ``OAuthFlow`` wired to ``AnthropicOAuthProvider``."""
        flow = OAuthFlowFactory.for_provider(provider=ProviderName.ANTHROPIC)

        assert isinstance(flow, OAuthFlow)
        assert isinstance(flow._provider, AnthropicOAuthProvider)

    def test_returns_flow_for_openai(self) -> None:
        """OpenAI provider → ``OAuthFlow`` wired to ``OpenAICodexOAuthProvider``."""
        flow = OAuthFlowFactory.for_provider(provider=ProviderName.OPENAI)

        assert isinstance(flow, OAuthFlow)
        assert isinstance(flow._provider, OpenAICodexOAuthProvider)

    def test_raises_value_error_for_unknown_provider(self) -> None:
        """Unknown ``ProviderName`` → ``ValueError`` (acceptance criterion 7)."""
        unknown: ProviderName = "unsupported-provider"  # type: ignore[assignment]

        with pytest.raises(ValueError, match="No OAuth provider implemented"):
            OAuthFlowFactory.for_provider(provider=unknown)
