"""In-process wire-contract tests for OpenAI Codex device authorization."""

from __future__ import annotations

import json
from typing import Any

import pytest
from aiohttp import web

from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.oauth_errors import (
    OAuthDeviceAuthorizationProtocolError,
    OAuthDeviceAuthorizationUnsupportedError,
)
from src.auth.oauth_provider import DeviceAuthorizationDAO, DeviceAuthorizationPollStatus, OAuthLoginMethod
from src.auth.providers.openai_codex_provider import OpenAICodexOAuthProvider


async def _start_server(handler: Any) -> tuple[str, web.AppRunner]:
    """Start a local aiohttp endpoint and return its origin plus cleanup runner."""
    app: web.Application = web.Application()
    app.router.add_post("/device", handler)
    runner: web.AppRunner = web.AppRunner(app=app)
    await runner.setup()
    site: web.TCPSite = web.TCPSite(runner=runner, host="127.0.0.1", port=0)
    await site.start()
    server = site._server  # type: ignore[attr-defined]
    assert server is not None and server.sockets
    port: int = server.sockets[0].getsockname()[1]
    return f"http://127.0.0.1:{port}/device", runner


def _live_shaped_start_payload(*, interval: Any) -> dict[str, Any]:
    """Return OpenAI's observed device start body with one interval value under test.

    WHAT: Mirrors the live 2026-09-14 usercode response field types (string interval
        and expires_at) with dummy-only identifiers.
    WHO: TestOpenAICodexDeviceStartIntervalParsing builds each payload through it.
    WHEN: Once per parse case, before calling the provider's payload builder.

    Args:
        interval (Any): The JSON interval value under test; ``Any`` mirrors untyped vendor JSON.

    Returns:
        dict[str, Any]: A start payload with dummy device id and user code.
    """
    return {
        "device_auth_id": "dummy-device-auth-id",
        "user_code": "DUMMY-CODE",
        "interval": interval,
        "expires_at": "2026-09-14T12:15:00.000000+00:00",
    }


class TestOpenAICodexDeviceStartIntervalParsing:
    """The start payload interval accepts OpenAI's live string shape and rejects unusable values."""

    @pytest.mark.parametrize(
        ("interval", "expected_seconds"),
        [(5, 5), (0, 0), ("5", 5), (" 5 ", 5), ("0", 0)],
        ids=["int", "int-zero", "decimal-text", "padded-decimal-text", "zero-text"],
    )
    def test_build_accepts_integer_or_trimmed_decimal_text_interval(
        self, interval: Any, expected_seconds: int
    ) -> None:
        """An int or trimmed decimal-text interval becomes the integer poll cadence."""
        session: DeviceAuthorizationDAO = OpenAICodexOAuthProvider()._build_device_authorization(
            payload=_live_shaped_start_payload(interval=interval)
        )

        assert session.interval_seconds == expected_seconds
        assert session.user_code == "DUMMY-CODE"

    @pytest.mark.parametrize(
        "interval",
        [True, False, -1, "-1", "abc", "", "5.5", 5.5, None],
        ids=[
            "bool-true",
            "bool-false",
            "negative",
            "negative-text",
            "non-numeric",
            "empty",
            "float-text",
            "float",
            "null",
        ],
    )
    def test_build_rejects_unusable_interval(self, interval: Any) -> None:
        """Booleans, negatives, non-decimal text, floats, and null are protocol failures."""
        with pytest.raises(OAuthDeviceAuthorizationProtocolError):
            OpenAICodexOAuthProvider()._build_device_authorization(
                payload=_live_shaped_start_payload(interval=interval)
            )

    async def test_start_accepts_live_shaped_string_interval(self) -> None:
        """The exact live usercode response shape yields a device session through the endpoint seam."""

        async def handler(request: web.Request) -> web.Response:
            """Return OpenAI's observed 200 body with string interval and expires_at."""
            return web.json_response(data=_live_shaped_start_payload(interval="5"))

        endpoint, runner = await _start_server(handler=handler)

        class _LocalStartProvider(OpenAICodexOAuthProvider):
            """Provider whose device start endpoint is the local live-shaped server."""

            @property
            def device_authorization_start_endpoint(self) -> str:
                """Return the local start endpoint."""
                return endpoint

        try:
            session: DeviceAuthorizationDAO = await _LocalStartProvider().start_device_authorization()
        finally:
            await runner.cleanup()

        assert session.interval_seconds == 5
        assert session.user_code == "DUMMY-CODE"
        assert session.verification_uri == "https://auth.openai.com/codex/device"

    def test_build_rejects_missing_interval(self) -> None:
        """A start payload without any interval is a protocol failure."""
        payload: dict[str, Any] = _live_shaped_start_payload(interval=None)
        del payload["interval"]

        with pytest.raises(OAuthDeviceAuthorizationProtocolError):
            OpenAICodexOAuthProvider()._build_device_authorization(payload=payload)


class TestOpenAICodexDeviceAuthorization:
    """Provider-local request bodies and endpoint-status semantics."""

    async def test_start_posts_exact_json_and_uses_config_deadline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Start uses the exact Codex client JSON and a Slo-owned expiry deadline."""
        captured: dict[str, Any] = {}

        async def handler(request: web.Request) -> web.Response:
            """Capture JSON without emitting the secret device authorization ID."""
            captured["json"] = await request.json()
            return web.json_response(
                data={"device_auth_id": "secret", "user_code": "USER-CODE", "interval": 0}
            )

        endpoint, runner = await _start_server(handler=handler)
        monkeypatch.setattr(
            "src.auth.providers.openai_codex_provider._DEVICE_AUTHORIZATION_START_ENDPOINT", endpoint
        )
        monkeypatch.setattr("src.auth.providers.openai_codex_provider._cfg", lambda key: "77")
        try:
            session: DeviceAuthorizationDAO = await OpenAICodexOAuthProvider().start_device_authorization()
        finally:
            await runner.cleanup()

        assert captured["json"] == {"client_id": "app_EMoamEEZ73f0CkXaXp7hrann"}
        assert session.user_code == "USER-CODE"
        assert session.expires_in_seconds == 77
        assert session.interval_seconds == 0

    async def test_start_404_raises_unsupported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only the start endpoint maps its 404 to unsupported capability."""

        async def handler(request: web.Request) -> web.Response:
            """Return an endpoint-scoped absence result."""
            return web.Response(status=404)

        endpoint, runner = await _start_server(handler=handler)
        monkeypatch.setattr(
            "src.auth.providers.openai_codex_provider._DEVICE_AUTHORIZATION_START_ENDPOINT", endpoint
        )
        try:
            with pytest.raises(OAuthDeviceAuthorizationUnsupportedError):
                await OpenAICodexOAuthProvider().start_device_authorization()
        finally:
            await runner.cleanup()

    async def test_start_non_404_failure_raises_protocol_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Other start failure statuses remain a safe protocol failure."""

        async def handler(request: web.Request) -> web.Response:
            """Return a generic rejected start request."""
            return web.Response(status=500)

        endpoint, runner = await _start_server(handler=handler)
        monkeypatch.setattr(
            "src.auth.providers.openai_codex_provider._DEVICE_AUTHORIZATION_START_ENDPOINT", endpoint
        )
        try:
            with pytest.raises(OAuthDeviceAuthorizationProtocolError):
                await OpenAICodexOAuthProvider().start_device_authorization()
        finally:
            await runner.cleanup()

    @pytest.mark.parametrize("status", [403, 404])
    async def test_poll_status_is_pending_for_403_or_404(
        self, monkeypatch: pytest.MonkeyPatch, status: int
    ) -> None:
        """Poll 403/404 is an in-progress authorization state, never unsupported."""

        async def handler(request: web.Request) -> web.Response:
            """Return one transient polling status."""
            return web.Response(status=status)

        endpoint, runner = await _start_server(handler=handler)
        monkeypatch.setattr(
            "src.auth.providers.openai_codex_provider._DEVICE_AUTHORIZATION_TOKEN_ENDPOINT", endpoint
        )
        try:
            result = await OpenAICodexOAuthProvider().poll_device_authorization(
                device_authorization=DeviceAuthorizationDAO(
                    device_code="device-secret",
                    user_code="USER-CODE",
                    verification_uri="https://example.test",
                    expires_in_seconds=30,
                )
            )
        finally:
            await runner.cleanup()

        assert result.status is DeviceAuthorizationPollStatus.PENDING

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            ("deviceauth_authorization_pending", DeviceAuthorizationPollStatus.PENDING),
            ("slow_down", DeviceAuthorizationPollStatus.SLOW_DOWN),
        ],
    )
    async def test_poll_classifies_2xx_error_body(
        self, monkeypatch: pytest.MonkeyPatch, error: str, expected: DeviceAuthorizationPollStatus
    ) -> None:
        """OpenAI conveys pending and slow-down inside successful JSON responses."""

        async def handler(request: web.Request) -> web.Response:
            """Return a 2xx error-code body."""
            return web.json_response(data={"error": error})

        endpoint, runner = await _start_server(handler=handler)
        monkeypatch.setattr(
            "src.auth.providers.openai_codex_provider._DEVICE_AUTHORIZATION_TOKEN_ENDPOINT", endpoint
        )
        try:
            result = await OpenAICodexOAuthProvider().poll_device_authorization(
                device_authorization=DeviceAuthorizationDAO(
                    device_code="device-secret",
                    user_code="USER-CODE",
                    verification_uri="https://example.test",
                    expires_in_seconds=30,
                )
            )
        finally:
            await runner.cleanup()

        assert result.status is expected

    async def test_completion_exchange_form_body_is_exactly_five_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Device completion reuses exchange_code with Pi's exact five-field body."""
        captured: dict[str, bytes] = {}

        async def handler(request: web.Request) -> web.Response:
            """Capture raw bytes for exact form comparison and return minimal token JSON."""
            captured["body"] = await request.read()
            return web.json_response(data={"access_token": "not-a-jwt"})

        endpoint, runner = await _start_server(handler=handler)
        provider: OpenAICodexOAuthProvider = OpenAICodexOAuthProvider()

        class _Provider(OpenAICodexOAuthProvider):
            """Test provider that directs only its token endpoint to the local server."""

            @property
            def token_endpoint(self) -> str:
                """Return the local capture endpoint."""
                return endpoint

        provider = _Provider()
        try:
            result = await provider._complete_device_poll(
                payload={"authorization_code": "code", "code_verifier": "verifier"},
                device_authorization=DeviceAuthorizationDAO(
                    device_code="device-secret",
                    user_code="USER-CODE",
                    verification_uri="https://example.test",
                    expires_in_seconds=30,
                ),
            )
        finally:
            await runner.cleanup()

        assert result.status is DeviceAuthorizationPollStatus.COMPLETE
        assert captured["body"] == (
            b"grant_type=authorization_code&client_id=app_EMoamEEZ73f0CkXaXp7hrann&"
            b"code=code&code_verifier=verifier&"
            b"redirect_uri=https%3A%2F%2Fauth.openai.com%2Fdeviceauth%2Fcallback"
        )
        assert b"state" not in captured["body"]

    def test_capabilities_include_browser_and_device(self) -> None:
        """Codex declares exactly its implemented UI interactions."""
        assert OpenAICodexOAuthProvider().supported_login_methods() == frozenset(
            {OAuthLoginMethod.BROWSER_AUTHORIZATION, OAuthLoginMethod.DEVICE_AUTHORIZATION}
        )
