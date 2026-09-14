"""Tests for capability-selected OAuthFlowFactory contracts."""

from collections.abc import Awaitable, Callable

import pytest

from src.auth.credential_dao import ProviderName
from src.auth.device_authorization import DeviceAuthorizationFlow
from src.auth.oauth_flow import AuthorizationPresentationDAO, OAuthFlow
from src.auth.oauth_provider import DeviceAuthorizationPresentationDAO, OAuthLoginMethod
from src.auth.provider_factory import OAuthAuthenticationFlow, OAuthFactory, OAuthFlowFactory
from src.auth.providers import AnthropicOAuthProvider, OpenAICodexOAuthProvider


def _browser_presentation(_: AuthorizationPresentationDAO) -> None:
    """Consume test browser instructions without retaining secret URLs."""


def _device_presentation(_: DeviceAuthorizationPresentationDAO) -> None:
    """Consume test device instructions without retaining hidden device IDs."""


class TestOAuthFlowFactoryCall:
    """A factory instance selects a flow using only declared provider capability."""

    def test_returns_browser_flow_for_anthropic(self) -> None:
        """Anthropic browser capability builds OAuthFlow with its concrete provider."""
        flow: OAuthAuthenticationFlow = OAuthFlowFactory()(
            provider=ProviderName.ANTHROPIC,
            login_method=OAuthLoginMethod.BROWSER_AUTHORIZATION,
            present_browser_authorization=_browser_presentation,
            present_device_authorization=_device_presentation,
            authorization_response_receiver=None,
        )

        assert isinstance(flow, OAuthFlow)
        assert isinstance(flow._provider, AnthropicOAuthProvider)

    def test_returns_device_flow_for_openai(self) -> None:
        """OpenAI device capability builds the generic DeviceAuthorizationFlow."""
        flow: OAuthAuthenticationFlow = OAuthFlowFactory()(
            provider=ProviderName.OPENAI,
            login_method=OAuthLoginMethod.DEVICE_AUTHORIZATION,
            present_browser_authorization=_browser_presentation,
            present_device_authorization=_device_presentation,
            authorization_response_receiver=None,
        )

        assert isinstance(flow, DeviceAuthorizationFlow)
        assert isinstance(flow._provider, OpenAICodexOAuthProvider)

    def test_rejects_anthropic_device_before_network(self) -> None:
        """Unsupported declared capability fails before a flow is constructed."""
        with pytest.raises(ValueError, match="does not support"):
            OAuthFlowFactory()(
                provider=ProviderName.ANTHROPIC,
                login_method=OAuthLoginMethod.DEVICE_AUTHORIZATION,
                present_browser_authorization=_browser_presentation,
                present_device_authorization=_device_presentation,
                authorization_response_receiver=None,
            )

    def test_supported_login_methods_returns_concrete_capabilities(self) -> None:
        """The UI query does not construct a flow and exposes truthful sets."""
        assert OAuthFlowFactory.supported_login_methods(provider=ProviderName.ANTHROPIC) == frozenset(
            {OAuthLoginMethod.BROWSER_AUTHORIZATION}
        )
        assert OAuthFlowFactory.supported_login_methods(provider=ProviderName.OPENAI) == frozenset(
            {OAuthLoginMethod.BROWSER_AUTHORIZATION, OAuthLoginMethod.DEVICE_AUTHORIZATION}
        )

    def test_instance_call_satisfies_oauth_factory_protocol(self) -> None:
        """A factory instance is callable with the five-argument protocol AuthenticationScreen uses.

        Regression: the screen's default was the class object, and calling a class with
        these keywords raised ``TypeError: OAuthFlowFactory() takes no arguments`` inside
        an unobserved task, so no instructions or error were ever painted.
        """
        factory: OAuthFactory = OAuthFlowFactory()
        flow: OAuthAuthenticationFlow = factory(
            provider=ProviderName.OPENAI,
            login_method=OAuthLoginMethod.DEVICE_AUTHORIZATION,
            present_browser_authorization=_browser_presentation,
            present_device_authorization=_device_presentation,
            authorization_response_receiver=None,
        )

        assert isinstance(flow, DeviceAuthorizationFlow)
        assert isinstance(flow._provider, OpenAICodexOAuthProvider)

    def test_raises_value_error_for_unknown_provider(self) -> None:
        """Kimi remains API-key-only and has no OAuth provider mapping."""
        with pytest.raises(ValueError, match="No OAuth provider implemented"):
            OAuthFlowFactory()(
                provider=ProviderName.KIMI_FOR_CODING,
                login_method=OAuthLoginMethod.BROWSER_AUTHORIZATION,
                present_browser_authorization=_browser_presentation,
                present_device_authorization=_device_presentation,
                authorization_response_receiver=None,
            )
