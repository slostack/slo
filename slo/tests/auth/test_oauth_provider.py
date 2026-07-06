"""Tests for ``OAuthProvider`` base behavior and ``FauxOAuthProvider`` (02.b.3).

Extended by 06.a with coverage for the two new hooks
(``callback_bind``, ``extra_authorization_params``) and the
``CallbackBind`` DAO.
"""

import pytest
from pydantic import ValidationError

from src.auth.credential_dao import AuthType, ProviderName
from src.auth.oauth_provider import CallbackBind, FauxOAuthProvider


class TestAuthorizationUrl:
    """Default ``authorization_url`` includes every required query param."""

    def test_includes_all_required_params(self) -> None:
        """response_type, client_id, redirect_uri, scope, state, challenge, method."""
        provider: FauxOAuthProvider = FauxOAuthProvider()

        url: str = provider.authorization_url(
            code_challenge="challenge-xyz",
            state="state-abc",
            redirect_uri="http://127.0.0.1:54321/callback",
        )

        for required in (
            "response_type=code",
            "client_id=faux-client-id",
            "code_challenge=challenge-xyz",
            "code_challenge_method=S256",
            "state=state-abc",
        ):
            assert required in url


class _ExtrasProvider(FauxOAuthProvider):
    """Faux variant whose ``extra_authorization_params`` returns one key.

    Used by ``TestAuthorizationUrlExtras`` to assert the merge contract
    without leaning on any real provider.
    """

    def __init__(self, *, extras: dict[str, str]) -> None:
        """Capture the extras dict for the override to return.

        Args:
            extras (dict[str, str]): The dict ``extra_authorization_params``
                should return.
        """
        super().__init__()
        self._extras: dict[str, str] = extras

    def extra_authorization_params(self) -> dict[str, str]:
        """Return the captured extras dict.

        Returns:
            dict[str, str]: The dict supplied at construction time.
        """
        return self._extras


class TestDefaultHookValues:
    """Default values of the 06.a hooks on every provider that does not override."""

    def test_callback_bind_defaults_to_none(self) -> None:
        """``OAuthProvider.callback_bind`` default is ``None``."""
        provider: FauxOAuthProvider = FauxOAuthProvider()

        assert provider.callback_bind is None

    def test_extra_authorization_params_defaults_to_empty(self) -> None:
        """``OAuthProvider.extra_authorization_params()`` default is ``{}``."""
        provider: FauxOAuthProvider = FauxOAuthProvider()

        assert provider.extra_authorization_params() == {}


class TestAuthorizationUrlExtras:
    """``authorization_url`` merges ``extra_authorization_params`` correctly."""

    def test_includes_extras_when_provider_overrides(self) -> None:
        """Override returns ``{'foo': 'bar'}`` → URL contains ``foo=bar``."""
        provider: _ExtrasProvider = _ExtrasProvider(extras={"foo": "bar"})

        url: str = provider.authorization_url(
            code_challenge="ch",
            state="st",
            redirect_uri="http://127.0.0.1:1/cb",
        )

        assert "foo=bar" in url

    def test_extras_cannot_clobber_standard_keys(self) -> None:
        """Override returning ``client_id`` does not overwrite the standard one."""
        provider: _ExtrasProvider = _ExtrasProvider(extras={"client_id": "evil"})

        url: str = provider.authorization_url(
            code_challenge="ch",
            state="st",
            redirect_uri="http://127.0.0.1:1/cb",
        )

        assert "client_id=faux-client-id" in url
        assert "client_id=evil" not in url

    def test_no_extras_means_only_seven_standard_params(self) -> None:
        """Default provider with empty extras emits exactly seven params."""
        provider: FauxOAuthProvider = FauxOAuthProvider()

        url: str = provider.authorization_url(
            code_challenge="ch",
            state="st",
            redirect_uri="http://127.0.0.1:1/cb",
        )

        query: str = url.split("?", 1)[1]
        params: list[str] = query.split("&")
        assert len(params) == 7


class TestCallbackBindModel:
    """``CallbackBind`` Pydantic model: redirect URI assembly and immutability."""

    def test_redirect_uri_uses_public_host(self) -> None:
        """``redirect_uri`` reads from ``public_host``, not ``host``."""
        bind: CallbackBind = CallbackBind(
            host="127.0.0.1",
            port=1455,
            path="/auth/callback",
            public_host="localhost",
        )

        assert bind.redirect_uri == "http://localhost:1455/auth/callback"

    def test_redirect_uri_matches_socket_host_when_public_host_same(self) -> None:
        """When ``public_host == host``, the redirect URI uses that host."""
        bind: CallbackBind = CallbackBind(
            host="127.0.0.1",
            port=9000,
            path="/callback",
            public_host="127.0.0.1",
        )

        assert bind.redirect_uri == "http://127.0.0.1:9000/callback"

    def test_callback_bind_raises_validation_error_on_mutation(self) -> None:
        """Mutating a field after construction raises a Pydantic validation error."""
        bind: CallbackBind = CallbackBind(
            host="127.0.0.1",
            port=1455,
            path="/auth/callback",
            public_host="localhost",
        )

        with pytest.raises(ValidationError):
            bind.port = 9999  # type: ignore[misc]


class TestFauxParseTokenResponse:
    """Faux returns the deterministic DAO regardless of input."""

    def test_returns_oauth_credential_with_constructor_values(self) -> None:
        """Output matches the constructor args."""
        provider: FauxOAuthProvider = FauxOAuthProvider(
            access_token="real-access",
            refresh_token="real-refresh",
            subject="alice@example.com",
        )

        cred = provider.parse_token_response(payload={"anything": "ignored"})

        assert cred.auth_type is AuthType.OAUTH
        assert cred.access_token == "real-access"
        assert cred.refresh_token == "real-refresh"
        assert cred.subject == "alice@example.com"

    def test_provider_field_matches_constructor(self) -> None:
        """``provider`` defaults to OpenAI; overridable."""
        provider: FauxOAuthProvider = FauxOAuthProvider(
            provider=ProviderName.ANTHROPIC,
        )

        cred = provider.parse_token_response(payload={})

        assert cred.provider is ProviderName.ANTHROPIC
