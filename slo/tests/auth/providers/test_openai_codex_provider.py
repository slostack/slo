"""Tests for ``OpenAICodexOAuthProvider`` (02.b.4, extended by 06.a)."""

import base64
import json

import pytest

from src.auth.credential_dao import AuthType, ProviderName
from src.auth.oauth_provider import CallbackBind
from src.auth.providers import OpenAICodexOAuthProvider


def _build_jwt(*, claims: dict) -> str:
    """Build a minimal unsigned JWT carrying ``claims`` in the body.

    Args:
        claims (dict): Claims to embed (subject, etc.).

    Returns:
        str: ``header.body.signature``-shaped string. Signature is empty.
    """

    def _b64(payload: dict) -> str:
        raw: bytes = json.dumps(payload).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{_b64({'alg': 'RS256'})}.{_b64(claims)}."


class TestCodexAuthorizationUrl:
    """The default ``authorization_url`` shape works against Codex constants."""

    def test_includes_offline_access_scope(self) -> None:
        """Refresh tokens require ``offline_access`` in the scope list."""
        provider: OpenAICodexOAuthProvider = OpenAICodexOAuthProvider()

        url: str = provider.authorization_url(
            code_challenge="ch",
            state="st",
            redirect_uri="http://127.0.0.1:1/cb",
        )

        assert "offline_access" in url


class TestCodexParseTokenResponse:
    """``parse_token_response`` extracts every field including the JWT subject."""

    def test_extracts_subject_from_jwt(self) -> None:
        """``sub`` claim from JWT body → ``cred.subject``."""
        provider: OpenAICodexOAuthProvider = OpenAICodexOAuthProvider()
        jwt: str = _build_jwt(claims={"sub": "user-abc-123"})

        cred = provider.parse_token_response(
            payload={
                "access_token": jwt,
                "refresh_token": "rt-1",
                "expires_in": 60,
            }
        )

        assert cred.provider is ProviderName.OPENAI
        assert cred.auth_type is AuthType.OAUTH
        assert cred.subject == "user-abc-123"

    def test_subject_is_none_when_token_not_jwt(self) -> None:
        """Non-JWT access token → ``subject is None``, no raise."""
        provider: OpenAICodexOAuthProvider = OpenAICodexOAuthProvider()

        cred = provider.parse_token_response(
            payload={
                "access_token": "not-a-jwt",
            }
        )

        assert cred.subject is None

    def test_subject_is_none_when_jwt_has_no_sub(self) -> None:
        """JWT without ``sub`` → ``subject is None``."""
        provider: OpenAICodexOAuthProvider = OpenAICodexOAuthProvider()
        jwt: str = _build_jwt(claims={"aud": "codex"})

        cred = provider.parse_token_response(payload={"access_token": jwt})

        assert cred.subject is None

    def test_subject_is_none_when_jwt_body_not_json(self) -> None:
        """Malformed JWT body → ``subject is None``, no raise."""
        provider: OpenAICodexOAuthProvider = OpenAICodexOAuthProvider()
        bad_jwt: str = "header.this-is-not-b64-or-json.signature"

        cred = provider.parse_token_response(payload={"access_token": bad_jwt})

        assert cred.subject is None


class TestCodexCallbackBind:
    """``callback_bind`` pins the values the Codex OAuth app is registered with."""

    def test_default_matches_codex_app_registration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without ``SLO_OAUTH_CALLBACK_HOST``, the bind matches the Codex CLI registration."""
        monkeypatch.delenv(name="SLO_OAUTH_CALLBACK_HOST", raising=False)
        provider: OpenAICodexOAuthProvider = OpenAICodexOAuthProvider()

        bind: CallbackBind = provider.callback_bind

        assert bind == CallbackBind(
            host="127.0.0.1",
            port=1455,
            path="/auth/callback",
            public_host="localhost",
        )

    def test_redirect_uri_uses_localhost_string_not_127_0_0_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``redirect_uri`` advertises ``localhost`` so Hydra's exact match succeeds."""
        monkeypatch.delenv(name="SLO_OAUTH_CALLBACK_HOST", raising=False)
        provider: OpenAICodexOAuthProvider = OpenAICodexOAuthProvider()

        assert provider.callback_bind.redirect_uri == "http://localhost:1455/auth/callback"

    def test_env_override_changes_socket_host_but_not_public_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``SLO_OAUTH_CALLBACK_HOST`` rewrites ``host``; ``public_host`` stays ``localhost``."""
        monkeypatch.setenv(name="SLO_OAUTH_CALLBACK_HOST", value="0.0.0.0")
        provider: OpenAICodexOAuthProvider = OpenAICodexOAuthProvider()

        bind: CallbackBind = provider.callback_bind

        assert bind.host == "0.0.0.0"
        assert bind.public_host == "localhost"
        assert bind.redirect_uri == "http://localhost:1455/auth/callback"


class TestCodexExtraAuthorizationParams:
    """The three Hydra-required extras are present with the documented values."""

    def test_returns_three_codex_specific_keys(self) -> None:
        """``extra_authorization_params`` returns exactly the three documented keys."""
        provider: OpenAICodexOAuthProvider = OpenAICodexOAuthProvider()

        extras: dict[str, str] = provider.extra_authorization_params()

        assert extras == {
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": "slo",
        }

    def test_authorization_url_contains_all_codex_extras(self) -> None:
        """The assembled URL carries all three extras alongside the standard params."""
        provider: OpenAICodexOAuthProvider = OpenAICodexOAuthProvider()

        url: str = provider.authorization_url(
            code_challenge="ch",
            state="st",
            redirect_uri="http://localhost:1455/auth/callback",
        )

        assert "codex_cli_simplified_flow=true" in url
        assert "id_token_add_organizations=true" in url
        assert "originator=slo" in url

    def test_authorization_url_preserves_provided_redirect_uri_string(self) -> None:
        """Caller-supplied ``redirect_uri`` is URL-encoded into the query untouched."""
        provider: OpenAICodexOAuthProvider = OpenAICodexOAuthProvider()

        url: str = provider.authorization_url(
            code_challenge="ch",
            state="st",
            redirect_uri="http://localhost:1455/auth/callback",
        )

        assert "redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback" in url
