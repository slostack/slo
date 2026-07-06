"""``OAuthFlowFactory`` — produces ready-to-start ``OAuthFlow`` instances (02.b.4)."""
from __future__ import annotations

from src.auth.credential_dao import ProviderName
from src.auth.oauth_flow import OAuthFlow
from src.auth.oauth_provider import OAuthProvider
from src.auth.providers import AnthropicOAuthProvider, OpenAICodexOAuthProvider


__all__ = ["OAuthFlowFactory"]


class OAuthFlowFactory:
    """Map a ``ProviderName`` to a ready-to-``start()`` ``OAuthFlow``.

    Imported only by the modal layer (02.b.5) and by integration tests.
    Tests substitute via dependency injection on the modal, not by
    monkeypatching this class.
    """

    @classmethod
    def for_provider(cls, *, provider: ProviderName) -> OAuthFlow:
        """Build an ``OAuthFlow`` wired to the concrete provider for ``provider``.

        Args:
            provider (ProviderName): Which concrete provider to use.

        Returns:
            OAuthFlow: A fresh flow, no state, no calls in flight.

        Raises:
            ValueError: If ``provider`` has no concrete implementation.
        """
        concrete: OAuthProvider = cls._concrete_for(provider=provider)
        return OAuthFlow(provider=concrete)

    @classmethod
    def _concrete_for(cls, *, provider: ProviderName) -> OAuthProvider:
        """Single decision: map ``ProviderName`` to a concrete class.

        Args:
            provider (ProviderName): Which provider to look up.

        Returns:
            OAuthProvider: The concrete provider.

        Raises:
            ValueError: For unknown providers.
        """
        if provider is ProviderName.ANTHROPIC:
            return AnthropicOAuthProvider()
        if provider is ProviderName.OPENAI:
            return OpenAICodexOAuthProvider()
        raise ValueError(f"No OAuth provider implemented for {provider!r}.")
