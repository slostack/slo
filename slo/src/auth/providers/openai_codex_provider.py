"""OpenAI ChatGPT-subscription OAuth provider (Codex grant, 02.b.4).

Extended by 06.a (codex-oauth-redirect-uri-fix) with a fixed
``CallbackBind`` and three Codex-specific authorize-URL parameters
required by ORY Hydra. Without them OpenAI rejects the authorize
request with ``authorize_hydra_invalid_request``.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, cast

from aiohttp import ClientSession, ClientTimeout

from config.cfg import cfg as _cfg
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.oauth_errors import (
    OAuthDeviceAuthorizationDeniedError,
    OAuthDeviceAuthorizationExpiredError,
    OAuthDeviceAuthorizationProtocolError,
    OAuthDeviceAuthorizationUnsupportedError,
)
from src.auth.oauth_provider import (
    CallbackBind,
    DeviceAuthorizationDAO,
    DeviceAuthorizationPollResultDAO,
    DeviceAuthorizationPollStatus,
    OAuthLoginMethod,
    OAuthProvider,
)
from src.auth.pkce import generate_state

__all__ = ["OpenAICodexOAuthProvider"]


# OAuth endpoints and client id match the official OpenAI Codex CLI app.
# Reusing the Codex CLI client id is what lets Slo authenticate users against
# their ChatGPT subscription quota (rather than API-key billing). The same
# value is used by Pi at packages/ai/src/auth/oauth/openai-codex.ts.
_AUTHORIZATION_ENDPOINT: str = "https://auth.openai.com/oauth/authorize"
_TOKEN_ENDPOINT: str = "https://auth.openai.com/oauth/token"
_CLIENT_ID: str = "app_EMoamEEZ73f0CkXaXp7hrann"
_SCOPES: tuple[str, ...] = (
    "openid",
    "profile",
    "email",
    "offline_access",
)

# Codex CLI's OAuth app is registered with exactly one redirect URI:
# http://localhost:1455/auth/callback. ORY Hydra exact-match validates
# this string at the authorize step, so the host must read "localhost"
# (not "127.0.0.1") even though the local socket binds 127.0.0.1.
_CODEX_REDIRECT_PORT: int = 1455
_CODEX_REDIRECT_PATH: str = "/auth/callback"
_CODEX_PUBLIC_HOST: str = "localhost"
_CODEX_ORIGINATOR: str = "slo"
_DEVICE_AUTHORIZATION_START_ENDPOINT: str = "https://auth.openai.com/api/accounts/deviceauth/usercode"
_DEVICE_AUTHORIZATION_TOKEN_ENDPOINT: str = "https://auth.openai.com/api/accounts/deviceauth/token"
_DEVICE_AUTHORIZATION_VERIFICATION_URI: str = "https://auth.openai.com/codex/device"
_DEVICE_START_TIMEOUT_SECONDS: int = 30
_DEVICE_POLL_HOLD_SECONDS: int = 30
_DEVICE_POLL_CLIENT_MARGIN_SECONDS: int = 5
_DEVICE_EXCHANGE_REDIRECT_URI: str = "https://auth.openai.com/deviceauth/callback"


class OpenAICodexOAuthProvider(OAuthProvider):
    """PKCE OAuth provider tied to the user's ChatGPT subscription."""

    @property
    def provider_name(self) -> ProviderName:
        """``ProviderName.OPENAI``."""
        return ProviderName.OPENAI

    @property
    def authorization_endpoint(self) -> str:
        """Codex authorisation endpoint."""
        return _AUTHORIZATION_ENDPOINT

    @property
    def token_endpoint(self) -> str:
        """Codex token endpoint."""
        return _TOKEN_ENDPOINT

    @property
    def client_id(self) -> str:
        """Codex CLI's registered client id."""
        return _CLIENT_ID

    @property
    def scopes(self) -> tuple[str, ...]:
        """Scopes Slo requests (``offline_access`` enables refresh tokens)."""
        return _SCOPES

    def supported_login_methods(self) -> frozenset[OAuthLoginMethod]:
        """Return the browser and device interactions verified for Codex."""
        return frozenset(
            {
                OAuthLoginMethod.BROWSER_AUTHORIZATION,
                OAuthLoginMethod.DEVICE_AUTHORIZATION,
            }
        )

    async def start_device_authorization(self) -> DeviceAuthorizationDAO:
        """Request one OpenAI device session with its endpoint-scoped timeout.

        WHO: DeviceAuthorizationFlow calls this once before it presents safe instructions.
        WHEN: At the beginning of a selected OpenAI device sign-in attempt.
        """
        status, payload = await self._post_device_json_with_status(
            endpoint=_DEVICE_AUTHORIZATION_START_ENDPOINT,
            payload={"client_id": self.client_id},
            timeout_seconds=_DEVICE_START_TIMEOUT_SECONDS,
        )
        if status == 404:
            raise OAuthDeviceAuthorizationUnsupportedError(provider=self.provider_name)
        if status < 200 or status >= 300:
            raise OAuthDeviceAuthorizationProtocolError(provider=self.provider_name)
        return self._build_device_authorization(payload=payload)

    async def poll_device_authorization(
        self,
        *,
        device_authorization: DeviceAuthorizationDAO,
    ) -> DeviceAuthorizationPollResultDAO:
        """Perform one OpenAI long-poll and classify the vendor result.

        WHO: DeviceAuthorizationFlow calls this immediately and after its own waits.
        WHEN: Until the provider returns a credential or a typed terminal error.
        """
        status, payload = await self._post_device_json_with_status(
            endpoint=_DEVICE_AUTHORIZATION_TOKEN_ENDPOINT,
            payload={
                "device_auth_id": device_authorization.device_code,
                "user_code": device_authorization.user_code,
            },
            timeout_seconds=_DEVICE_POLL_HOLD_SECONDS + _DEVICE_POLL_CLIENT_MARGIN_SECONDS,
        )
        return await self._classify_device_poll(
            status=status,
            payload=payload,
            device_authorization=device_authorization,
        )

    async def _post_device_json_with_status(
        self,
        *,
        endpoint: str,
        payload: dict[str, str],
        timeout_seconds: int,
    ) -> tuple[int, dict[str, Any]]:
        """Post one JSON request without retrying and preserve its status for callers."""
        timeout: ClientTimeout = ClientTimeout(total=timeout_seconds)
        async with ClientSession(timeout=timeout) as http:
            async with http.post(url=endpoint, json=payload) as response:
                try:
                    body: dict[str, Any] = cast(dict[str, Any], await response.json(content_type=None))
                except (ValueError, TypeError):
                    body = {}
                return response.status, body

    def _build_device_authorization(self, *, payload: dict[str, Any]) -> DeviceAuthorizationDAO:
        """Validate OpenAI's start payload and synthesize Slo's product deadline."""
        device_auth_id: Any = payload.get("device_auth_id")
        user_code: Any = payload.get("user_code")
        interval: Any = payload.get("interval")
        if not isinstance(device_auth_id, str) or not isinstance(user_code, str):
            raise OAuthDeviceAuthorizationProtocolError(provider=self.provider_name)
        if not isinstance(interval, int) or interval < 0:
            raise OAuthDeviceAuthorizationProtocolError(provider=self.provider_name)
        return DeviceAuthorizationDAO(
            device_code=device_auth_id,
            user_code=user_code,
            verification_uri=_DEVICE_AUTHORIZATION_VERIFICATION_URI,
            expires_in_seconds=int(_cfg("SLO_OAUTH_DEVICE_TIMEOUT_SECONDS") or 900),
            interval_seconds=interval,
        )

    async def _classify_device_poll(
        self,
        *,
        status: int,
        payload: dict[str, Any],
        device_authorization: DeviceAuthorizationDAO,
    ) -> DeviceAuthorizationPollResultDAO:
        """Translate endpoint status and body code into one typed poll result."""
        if status in {403, 404}:
            return DeviceAuthorizationPollResultDAO(status=DeviceAuthorizationPollStatus.PENDING)
        if status < 200 or status >= 300:
            raise OAuthDeviceAuthorizationProtocolError(provider=self.provider_name)
        error_code: Any = payload.get("error")
        if error_code == "deviceauth_authorization_pending":
            return DeviceAuthorizationPollResultDAO(status=DeviceAuthorizationPollStatus.PENDING)
        if error_code == "slow_down":
            return DeviceAuthorizationPollResultDAO(status=DeviceAuthorizationPollStatus.SLOW_DOWN)
        if error_code in {"access_denied", "deviceauth_access_denied"}:
            raise OAuthDeviceAuthorizationDeniedError(provider=self.provider_name)
        if error_code in {"expired_token", "deviceauth_expired"}:
            raise OAuthDeviceAuthorizationExpiredError(provider=self.provider_name)
        return await self._complete_device_poll(
            payload=payload,
            device_authorization=device_authorization,
        )

    async def _complete_device_poll(
        self,
        *,
        payload: dict[str, Any],
        device_authorization: DeviceAuthorizationDAO,
    ) -> DeviceAuthorizationPollResultDAO:
        """Exchange validated completion fields through the existing token parser path."""
        authorization_code: Any = payload.get("authorization_code")
        code_verifier: Any = payload.get("code_verifier")
        if not isinstance(authorization_code, str) or not isinstance(code_verifier, str):
            raise OAuthDeviceAuthorizationProtocolError(provider=self.provider_name)
        credential: CredentialDAO = await self.exchange_code(
            code=authorization_code,
            verifier=code_verifier,
            state="",
            redirect_uri=_DEVICE_EXCHANGE_REDIRECT_URI,
        )
        return DeviceAuthorizationPollResultDAO(
            status=DeviceAuthorizationPollStatus.COMPLETE,
            credential=credential,
        )

    def authorization_state(self, *, verifier: str) -> str:
        """Return the standard random CSRF state for OpenAI OAuth.

        Args:
            verifier (str): PKCE verifier generated for this flow.

        Returns:
            str: Random CSRF state.
        """
        return generate_state()

    @property
    def callback_bind(self) -> CallbackBind:
        """Return the fixed Codex callback bind required by Hydra.

        ``host`` is overridable via the ``SLO_OAUTH_CALLBACK_HOST``
        environment variable for WSL or devcontainer setups where
        ``127.0.0.1`` is not the right loopback interface. ``public_host``
        stays ``"localhost"`` regardless, so the ``redirect_uri`` string
        sent to Hydra matches the OAuth app's exact registration.

        Returns:
            CallbackBind: ``localhost:1455/auth/callback``, with the
                socket bound to ``host`` (default ``127.0.0.1``).
        """
        return CallbackBind(
            host=_cfg("SLO_OAUTH_CALLBACK_HOST") or "127.0.0.1",
            port=_CODEX_REDIRECT_PORT,
            path=_CODEX_REDIRECT_PATH,
            public_host=_CODEX_PUBLIC_HOST,
        )

    def extra_authorization_params(self) -> dict[str, str]:
        """Return the three Codex-specific authorize-URL extras.

        ``id_token_add_organizations`` and ``codex_cli_simplified_flow``
        are required by Codex's authorize flow; missing either of them
        produces ``authorize_hydra_invalid_request``. ``originator`` is
        a telemetry tag — the value is not auth-validated, so Slo sends
        its own brand string rather than impersonating the CLI any
        further than ``client_id`` already does.

        Returns:
            dict[str, str]: The three Codex-specific params.
        """
        return {
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": _CODEX_ORIGINATOR,
        }

    def parse_token_response(self, *, payload: dict[str, Any]) -> CredentialDAO:
        """Translate Codex's token JSON into a ``CredentialDAO``.

        Codex returns standard OAuth fields plus a JWT ``access_token``.
        ``subject`` is best-effort: decode the JWT body unverified and
        read the ``sub`` claim. Tests assert both the populated and
        absent paths.

        Args:
            payload (dict[str, Any]): Decoded JSON from the token endpoint.
                ``Any`` is required because provider token payloads are
                untyped JSON.

        Returns:
            CredentialDAO: ``provider=OPENAI``, ``auth_type=OAUTH``.
        """
        access_token: str = str(payload["access_token"])
        expires_in: Optional[int] = payload.get("expires_in")
        expires_at: Optional[datetime] = None
        if expires_in is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        return CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.OAUTH,
            access_token=access_token,
            refresh_token=payload.get("refresh_token"),
            expires_at=expires_at,
            subject=_extract_jwt_subject(token=access_token),
            scope=payload.get("scope") or " ".join(_SCOPES),
        )


def _extract_jwt_subject(*, token: str) -> Optional[str]:
    """Decode the JWT body and return the ``sub`` claim, best-effort.

    Does NOT verify the signature — the subject is only used for the
    success screen banner, never for auth decisions.

    Args:
        token (str): JWT-shaped access token.

    Returns:
        Optional[str]: The ``sub`` claim, or ``None`` if the token is
            not a parseable JWT.
    """
    parts: list[str] = token.split(".")
    if len(parts) != 3:
        return None
    payload_segment: str = parts[1]
    padding: str = "=" * (-len(payload_segment) % 4)
    try:
        decoded: bytes = base64.urlsafe_b64decode(payload_segment + padding)
        # Any: JWT bodies are untyped JSON.
        body: dict[str, Any] = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return None
    # Any: ``sub`` is a free-form JWT claim.
    sub: Optional[Any] = body.get("sub")
    if sub is None:
        return None
    return str(sub)
