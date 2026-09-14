"""Build one capability-selected OAuth authentication flow."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from src.auth.credential_dao import CredentialDAO, ProviderName
from src.auth.device_authorization import DeviceAuthorizationFlow
from src.auth.oauth_flow import AuthorizationPresentationDAO, OAuthFlow
from src.auth.oauth_provider import (
    DeviceAuthorizationPresentationDAO,
    OAuthLoginMethod,
    OAuthProvider,
)
from src.auth.providers import AnthropicOAuthProvider, OpenAICodexOAuthProvider

__all__ = ["OAuthAuthenticationFlow", "OAuthFactory", "OAuthFlowFactory"]


class OAuthAuthenticationFlow(Protocol):
    """A selected OAuth interaction with one async application gateway."""

    async def invoke(self) -> CredentialDAO:
        """Complete one selected OAuth interaction."""


class OAuthFactory(Protocol):
    """Build one selected OAuth interaction with injected presentation seams."""

    def __call__(
        self,
        *,
        provider: ProviderName,
        login_method: OAuthLoginMethod,
        present_browser_authorization: Callable[[AuthorizationPresentationDAO], None],
        present_device_authorization: Callable[[DeviceAuthorizationPresentationDAO], None],
        authorization_response_receiver: Callable[[], Awaitable[str]] | None,
        present_callback_unavailable: Callable[[], None] = lambda: None,
    ) -> OAuthAuthenticationFlow:
        """Return a fresh flow for one provider/method selection."""

    def supported_login_methods(self, *, provider: ProviderName) -> frozenset[OAuthLoginMethod]:
        """Return the OAuth interactions the resolved provider has implemented."""


class OAuthFlowFactory:
    """Map a provider and declared capability to a fresh OAuth flow."""

    @classmethod
    def for_provider(
        cls,
        *,
        provider: ProviderName,
        login_method: OAuthLoginMethod,
        present_browser_authorization: Callable[[AuthorizationPresentationDAO], None],
        present_device_authorization: Callable[[DeviceAuthorizationPresentationDAO], None],
        authorization_response_receiver: Callable[[], Awaitable[str]] | None,
        present_callback_unavailable: Callable[[], None] = lambda: None,
    ) -> OAuthAuthenticationFlow:
        """Construct the selected provider interaction after validating capability.

        WHAT: Resolves a provider capability into a fresh browser or device flow.
        WHO: AuthenticationScreen calls this once for a selected method.
        WHEN: Before browser setup or device network activity begins.

        Args:
            provider (ProviderName): Provider selected by the operator.
            login_method (OAuthLoginMethod): Provider capability selected by the operator.
            present_browser_authorization (Callable[[AuthorizationPresentationDAO], None]):
                Browser instruction presentation sink.
            present_device_authorization (Callable[[DeviceAuthorizationPresentationDAO], None]):
                Device instruction presentation sink.
            authorization_response_receiver (Callable[[], Awaitable[str]] | None):
                Browser response receiver, if applicable.
            present_callback_unavailable (Callable[[], None], optional): Browser callback-timeout
                presentation sink. Defaults to a no-op.
        """
        concrete: OAuthProvider = cls._concrete_for(provider=provider)
        cls._validate_login_method(provider=concrete, login_method=login_method)
        if login_method is OAuthLoginMethod.BROWSER_AUTHORIZATION:
            return OAuthFlow(
                provider=concrete,
                present_authorization=present_browser_authorization,
                present_callback_unavailable=present_callback_unavailable,
                authorization_response_receiver=authorization_response_receiver,
            )
        return DeviceAuthorizationFlow(provider=concrete, present=present_device_authorization)

    @classmethod
    def supported_login_methods(cls, *, provider: ProviderName) -> frozenset[OAuthLoginMethod]:
        """Return the OAuth interactions the resolved provider has implemented.

        WHO: AuthenticationScreen calls this once per chosen provider to build
            the MethodSelectWidget capability list (78.a.3 §7.2).
        WHEN: Before method selection renders; no flow is constructed.
        """
        return cls._concrete_for(provider=provider).supported_login_methods()

    @classmethod
    def _validate_login_method(cls, *, provider: OAuthProvider, login_method: OAuthLoginMethod) -> None:
        """Reject an interaction absent from the concrete provider capability set."""
        if login_method in provider.supported_login_methods():
            return
        raise ValueError(f"{provider.provider_name.value} does not support {login_method.value}.")

    @classmethod
    def _concrete_for(cls, *, provider: ProviderName) -> OAuthProvider:
        """Resolve one provider identity without offering Kimi an OAuth route."""
        if provider is ProviderName.ANTHROPIC:
            return AnthropicOAuthProvider()
        if provider is ProviderName.OPENAI:
            return OpenAICodexOAuthProvider()
        raise ValueError(f"No OAuth provider implemented for {provider!r}.")
