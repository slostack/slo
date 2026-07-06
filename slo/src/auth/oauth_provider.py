"""OAuth provider abstract interface and a test-only Faux (02.b.3).

Extended by 06.a (codex-oauth-redirect-uri-fix) with two opt-in hooks
— ``callback_bind`` and ``extra_authorization_params`` — plus the
``CallbackBind`` DAO. Providers that do not override either hook keep
their existing ephemeral-port, seven-standard-params behaviour.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, cast
from urllib.parse import urlencode

from aiohttp import ClientSession
from pydantic import BaseModel, ConfigDict

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.oauth_errors import OAuthTokenError
from src.auth.pkce import generate_state

__all__ = ["CallbackBind", "FauxOAuthProvider", "OAuthProvider"]


class CallbackBind(BaseModel):
    """Per-provider callback-server requirements.

    Providers whose OAuth app is registered against a specific localhost
    URI (for example the OpenAI Codex CLI app, which registers
    ``http://localhost:1455/auth/callback``) declare a ``CallbackBind``.
    The flow then binds a fixed socket and advertises a fixed
    ``redirect_uri`` string to the authorize endpoint. Providers whose
    OAuth app accepts any localhost callback (Anthropic, Faux) return
    ``None`` from ``OAuthProvider.callback_bind`` and keep the
    ephemeral-port default.

    Attributes:
        host (str): What to bind the local socket to. Almost always
            ``"127.0.0.1"`` — browsers resolve ``localhost`` to it.
        port (int): The exact local port. There is no fallback because
            the OAuth app's registered URI is exact-match validated
            server-side.
        path (str): The HTTP path the redirect lands on.
        public_host (str): Hostname embedded in the ``redirect_uri``
            string sent to the authorize endpoint. Usually
            ``"localhost"`` — that is what the registered URI says —
            even when the socket binds ``"127.0.0.1"``.
    """

    model_config = ConfigDict(frozen=True)

    host: str
    port: int
    path: str
    public_host: str

    @property
    def redirect_uri(self) -> str:
        """Return the redirect URI string to advertise to the authorize endpoint.

        Returns:
            str: ``http://{public_host}:{port}{path}``.
        """
        return f"http://{self.public_host}:{self.port}{self.path}"


class OAuthProvider(ABC):
    """Abstract interface implemented by every concrete provider.

    Concrete subclasses live in ``src/auth/providers/`` (added in 02.b.4).
    """

    @property
    @abstractmethod
    def provider_name(self) -> ProviderName:
        """Which ``ProviderName`` this concrete provider authorises.

        Returns:
            ProviderName: The provider identity this implementation owns.
        """

    @property
    @abstractmethod
    def authorization_endpoint(self) -> str:
        """The provider's authorisation URL (no query string).

        Returns:
            str: HTTPS URL the browser opens to start sign-in.
        """

    @property
    @abstractmethod
    def token_endpoint(self) -> str:
        """The provider's token endpoint URL.

        Returns:
            str: HTTPS URL the flow POSTs the auth code to.
        """

    @property
    @abstractmethod
    def client_id(self) -> str:
        """OAuth client id this provider expects.

        Returns:
            str: The provider's registered client identifier.
        """

    @property
    @abstractmethod
    def scopes(self) -> tuple[str, ...]:
        """Scopes requested in the authorisation URL.

        Returns:
            tuple[str, ...]: Ordered scope strings joined with spaces in
                the URL.
        """

    @property
    def callback_bind(self) -> Optional[CallbackBind]:
        """Return per-provider callback-server requirements; ``None`` for ephemeral.

        Override in providers whose OAuth app is registered against a
        specific localhost URI (for example Codex CLI). The base default
        returns ``None``, which keeps the existing ephemeral-port
        behaviour for Anthropic and Faux.

        Returns:
            Optional[CallbackBind]: A binding, or ``None`` to use an
                OS-picked port on ``127.0.0.1`` at ``/callback``.
        """
        return None

    def extra_authorization_params(self) -> dict[str, str]:
        """Return provider-specific extra query params for the authorize URL.

        Merged into the URL after the seven standard PKCE params.
        Override only when the provider requires extras (for example
        Codex's ``codex_cli_simplified_flow``).

        Returns:
            dict[str, str]: Extra ``key=value`` pairs. Empty by default.
        """
        return {}

    @abstractmethod
    def authorization_state(self, *, verifier: str) -> str:
        """Return the state value to send in the authorize request.

        Providers may use the standard random CSRF state behavior or a
        provider-specific value when parity requires it.

        Args:
            verifier (str): PKCE verifier generated for this flow.

        Returns:
            str: State value for the authorize request.
        """

    def authorization_url(
        self,
        *,
        code_challenge: str,
        state: str,
        redirect_uri: str,
    ) -> str:
        """Render the full authorisation URL for ``OAuthFlow`` to launch.

        Concrete providers override ``extra_authorization_params`` to
        add provider-specific keys; they do not need to override this
        method. The seven standard PKCE params are merged on top of any
        extras, so a buggy override that returns ``response_type``,
        ``client_id``, ``redirect_uri``, or any other standard key
        cannot clobber them.

        Args:
            code_challenge (str): S256 PKCE challenge.
            state (str): CSRF state value.
            redirect_uri (str): Callback URL the server is listening on
                — resolved from ``callback_bind.redirect_uri`` when set,
                otherwise the ephemeral ``_CallbackServer.redirect_uri``.

        Returns:
            str: Fully assembled HTTPS URL ready to hand to a browser.
        """
        # Build extras first, then write the standard keys on top so a
        # buggy override that returns ``client_id`` (or any other
        # standard key) cannot win the merge.
        params: dict[str, str] = dict(self.extra_authorization_params())
        params.update(
            {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(self.scopes),
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{self.authorization_endpoint}?{urlencode(params)}"

    @abstractmethod
    def parse_token_response(self, *, payload: dict[str, Any]) -> CredentialDAO:
        """Translate the token-endpoint JSON into a ``CredentialDAO``.

        Args:
            payload (dict[str, Any]): Raw JSON the provider returned.
                ``Any`` is required because provider token payloads are
                untyped JSON.

        Returns:
            CredentialDAO: Provider-tagged credential ready to persist.
        """

    async def exchange_code(
        self,
        *,
        code: str,
        verifier: str,
        state: str,
        redirect_uri: str,
    ) -> CredentialDAO:
        """Exchange one authorization code using the provider's default RFC shape.

        Standard providers use form-encoded POST bodies. Providers with
        non-standard semantics can override this method.

        Args:
            code (str): Authorization code from the callback.
            verifier (str): PKCE verifier generated at flow start.
            state (str): CSRF state validated by the callback server.
            redirect_uri (str): Redirect URI originally sent to the
                provider authorization endpoint.

        Returns:
            CredentialDAO: Provider-tagged credential ready to persist.

        Raises:
            OAuthTokenError: When the token endpoint returns a non-2xx
                response.
        """
        body: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
        }
        async with ClientSession() as http:
            async with http.post(url=self.token_endpoint, data=body) as resp:
                text: str = await resp.text()
                if resp.status >= 400:
                    raise OAuthTokenError(status=resp.status, body=text)
                payload: dict[str, Any] = cast(dict[str, Any], json.loads(text))
        return self.parse_token_response(payload=payload)

    async def refresh(self, *, refresh_token: str) -> CredentialDAO:
        """Exchange a refresh token for a fresh credential (feature 07 §3.1).

        Standard OAuth 2.0 refresh flow: POST ``token_endpoint`` with
        ``grant_type=refresh_token``, ``refresh_token=...``, ``client_id=...``
        and parse the response through ``parse_token_response`` so each
        provider's response idiosyncrasies (e.g. OpenAI Codex returning
        a fresh ``refresh_token`` on every exchange) are honoured.

        Concrete in the base class because the wire shape is the same
        for every provider Slo authenticates against. Subclasses with
        non-standard refresh semantics may override.

        Args:
            refresh_token (str): The persisted refresh token.

        Returns:
            CredentialDAO: Provider-tagged credential carrying the new
                ``access_token`` (and possibly a rotated ``refresh_token``).

        Raises:
            OAuthTokenError: When the token endpoint returns a non-2xx
                response.
        """
        body: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
        }
        async with ClientSession() as http:
            async with http.post(url=self.token_endpoint, data=body) as resp:
                text: str = await resp.text()
                if resp.status >= 400:
                    raise OAuthTokenError(status=resp.status, body=text)
                # ``Any`` is required because provider token payloads
                # are untyped JSON.
                payload: dict[str, Any] = cast(dict[str, Any], json.loads(text))
        return self.parse_token_response(payload=payload)


class FauxOAuthProvider(OAuthProvider):
    """Deterministic provider used by ``test_oauth_flow.py`` and 02.b.5.

    Returns fixed endpoints and a fixed credential shape.
    """

    def __init__(
        self,
        *,
        provider: ProviderName = ProviderName.OPENAI,
        access_token: str = "faux-access",
        refresh_token: Optional[str] = "faux-refresh",
        expires_in_seconds: int = 3600,
        subject: Optional[str] = "faux@example.com",
    ) -> None:
        """Capture the deterministic values this faux returns.

        Args:
            provider (ProviderName): Which provider this faux pretends
                to be. Defaults to OpenAI.
            access_token (str): The token returned by ``parse_token_response``.
            refresh_token (Optional[str]): Optional refresh token to embed.
            expires_in_seconds (int): Used to compute ``expires_at``.
            subject (Optional[str]): Subject embedded into the DAO.
        """
        self._provider: ProviderName = provider
        self._access_token: str = access_token
        self._refresh_token: Optional[str] = refresh_token
        self._expires_in_seconds: int = expires_in_seconds
        self._subject: Optional[str] = subject

    @property
    def provider_name(self) -> ProviderName:
        """Faux provider identity. Read-only."""
        return self._provider

    @property
    def authorization_endpoint(self) -> str:
        """Constant fake endpoint."""
        return "https://faux.example.com/oauth/authorize"

    @property
    def token_endpoint(self) -> str:
        """Constant fake token endpoint."""
        return "https://faux.example.com/oauth/token"

    @property
    def client_id(self) -> str:
        """Fixed test client id."""
        return "faux-client-id"

    @property
    def scopes(self) -> tuple[str, ...]:
        """Single deterministic scope for assertion shape."""
        return ("openid", "profile")

    def authorization_state(self, *, verifier: str) -> str:
        """Return the standard random CSRF state for Faux OAuth.

        Args:
            verifier (str): PKCE verifier generated for this flow.

        Returns:
            str: Random CSRF state.
        """
        return generate_state()

    def parse_token_response(self, *, payload: dict[str, Any]) -> CredentialDAO:
        """Return the deterministic ``CredentialDAO`` regardless of input.

        Args:
            payload (dict[str, Any]): Ignored; left for shape compatibility.
                ``Any`` matches the abstract base's signature.

        Returns:
            CredentialDAO: Built from the faux's constructor args.
        """
        return CredentialDAO(
            provider=self._provider,
            auth_type=AuthType.OAUTH,
            access_token=self._access_token,
            refresh_token=self._refresh_token,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self._expires_in_seconds),
            subject=self._subject,
            scope=" ".join(self.scopes),
        )
