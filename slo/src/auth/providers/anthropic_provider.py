"""Anthropic Claude-subscription OAuth provider (02.b.4).

The Anthropic OAuth grant is the same grant ``claude /login`` runs.
Token responses are bearer tokens of the same shape that
``CredentialResolver._read_legacy_claude_oauth`` understands from
``~/.claude/.credentials.json``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, cast

from aiohttp import ClientSession

from config.cfg import cfg as _cfg
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.oauth_errors import OAuthTokenError
from src.auth.oauth_provider import CallbackBind, OAuthProvider


__all__ = ["AnthropicOAuthProvider"]


_AUTHORIZATION_ENDPOINT: str = "https://claude.ai/oauth/authorize"
_TOKEN_ENDPOINT: str = "https://platform.claude.com/v1/oauth/token"
_CLIENT_ID: str = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_SCOPES: tuple[str, ...] = (
    "org:create_api_key",
    "user:profile",
    "user:inference",
    "user:sessions:claude_code",
    "user:mcp_servers",
    "user:file_upload",
)
_CALLBACK_PUBLIC_HOST: str = "localhost"
_CALLBACK_PORT: int = 53692
_CALLBACK_PATH: str = "/callback"


class AnthropicOAuthProvider(OAuthProvider):
    """PKCE OAuth provider for the Claude subscription grant.

    Endpoints are top-of-module constants so updates are one edit each.
    """

    @property
    def provider_name(self) -> ProviderName:
        """``ProviderName.ANTHROPIC``."""
        return ProviderName.ANTHROPIC

    @property
    def authorization_endpoint(self) -> str:
        """Authorisation URL the browser visits."""
        return _AUTHORIZATION_ENDPOINT

    @property
    def token_endpoint(self) -> str:
        """Token endpoint the flow POSTs the auth code to."""
        return _TOKEN_ENDPOINT

    @property
    def client_id(self) -> str:
        """OAuth client identifier."""
        return _CLIENT_ID

    @property
    def scopes(self) -> tuple[str, ...]:
        """Scopes Slo requests on the user's behalf."""
        return _SCOPES

    @property
    def callback_bind(self) -> CallbackBind:
        """Return Anthropic's fixed localhost callback contract.

        Returns:
            CallbackBind: Fixed host / port / path configuration.
        """
        return CallbackBind(
            host=_cfg("SLO_OAUTH_CALLBACK_HOST") or "127.0.0.1",
            port=_CALLBACK_PORT,
            path=_CALLBACK_PATH,
            public_host=_CALLBACK_PUBLIC_HOST,
        )

    def extra_authorization_params(self) -> dict[str, str]:
        """Return Anthropic's provider-specific authorize query params.

        Returns:
            dict[str, str]: Extra authorize query params required by
                the Claude Code OAuth flow.
        """
        return {"code": "true"}

    def authorization_state(self, *, verifier: str) -> str:
        """Return Anthropic's authorize ``state`` value.

        Pi's Claude Code flow uses the PKCE verifier itself as the
        ``state`` value. Slo mirrors that behavior here for parity.

        Args:
            verifier (str): PKCE verifier generated for this flow.

        Returns:
            str: The verifier, reused as the authorize ``state``.
        """
        return verifier

    async def exchange_code(
        self,
        *,
        code: str,
        verifier: str,
        state: str,
        redirect_uri: str,
    ) -> CredentialDAO:
        """Exchange Anthropic authorization codes using pi's JSON wire shape.

        Args:
            code (str): Authorization code from the callback.
            verifier (str): PKCE verifier generated at flow start.
            state (str): CSRF state originally sent to the authorize URL.
            redirect_uri (str): Fixed localhost callback URI.

        Returns:
            CredentialDAO: Parsed Anthropic OAuth credential.

        Raises:
            OAuthTokenError: When the token endpoint returns a non-2xx
                response.
        """
        body: dict[str, str] = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "code": code,
            "state": state,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
        async with ClientSession() as http:
            async with http.post(url=self.token_endpoint, json=body) as resp:
                text: str = await resp.text()
                if resp.status >= 400:
                    raise OAuthTokenError(status=resp.status, body=text)
                payload: dict[str, Any] = cast(dict[str, Any], json.loads(text))
        return self.parse_token_response(payload=payload)

    async def refresh(self, *, refresh_token: str) -> CredentialDAO:
        """Refresh Anthropic OAuth credentials using JSON request bodies.

        Args:
            refresh_token (str): Persisted refresh token.

        Returns:
            CredentialDAO: Parsed Anthropic OAuth credential.

        Raises:
            OAuthTokenError: When the token endpoint returns a non-2xx
                response.
        """
        body: dict[str, str] = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token,
        }
        async with ClientSession() as http:
            async with http.post(url=self.token_endpoint, json=body) as resp:
                text: str = await resp.text()
                if resp.status >= 400:
                    raise OAuthTokenError(status=resp.status, body=text)
                payload: dict[str, Any] = cast(dict[str, Any], json.loads(text))
        return self.parse_token_response(payload=payload)

    def parse_token_response(self, *, payload: dict[str, Any]) -> CredentialDAO:
        """Translate Anthropic's token JSON into a ``CredentialDAO``.

        Anthropic returns the token as ``access_token`` / ``refresh_token``
        / ``expires_in`` (seconds). Email is best-effort.

        Args:
            payload (dict[str, Any]): Decoded JSON from the token endpoint.
                ``Any`` is required because provider token payloads are
                untyped JSON.

        Returns:
            CredentialDAO: ``provider=ANTHROPIC``, ``auth_type=OAUTH``.
        """
        expires_at: Optional[datetime] = None
        expires_in_raw: Any = payload.get("expires_in")
        if expires_in_raw is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in_raw))
        return CredentialDAO(
            provider=ProviderName.ANTHROPIC,
            auth_type=AuthType.OAUTH,
            access_token=str(payload["access_token"]),
            refresh_token=cast(Optional[str], payload.get("refresh_token")),
            expires_at=expires_at,
            subject=cast(Optional[str], payload.get("sub")),
            scope=cast(Optional[str], payload.get("scope")) or " ".join(_SCOPES),
        )
