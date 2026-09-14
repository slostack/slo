"""Tests for ``AnthropicOAuthProvider`` (02.b.4)."""

from datetime import datetime, timezone
from unittest.mock import PropertyMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp import web

from src.auth.credential_dao import AuthType, ProviderName
from src.auth.providers import AnthropicOAuthProvider


class TestAnthropicAuthorizationUrl:
    """The Anthropic authorization URL matches the pi-parity contract."""

    def test_includes_real_client_id_scopes_and_fixed_redirect_uri(self) -> None:
        """URL uses the real client id, Claude Code scopes, and fixed callback URI."""
        provider: AnthropicOAuthProvider = AnthropicOAuthProvider()

        url: str = provider.authorization_url(
            code_challenge="ch",
            state="st",
            redirect_uri=provider.callback_bind.redirect_uri,
        )
        query: dict[str, list[str]] = parse_qs(urlsplit(url).query)

        assert url.startswith(provider.authorization_endpoint)
        assert query["client_id"] == ["9d1c250a-e61b-44d9-88ed-5944d1962f5e"]
        assert query["code"] == ["true"]
        assert query["redirect_uri"] == ["http://localhost:53692/callback"]
        assert query["scope"] == [
            "org:create_api_key user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"
        ]
        assert query["code_challenge_method"] == ["S256"]

    def test_callback_bind_uses_fixed_public_localhost_uri(self) -> None:
        """Anthropic uses a fixed callback bind rather than the ephemeral default."""
        provider: AnthropicOAuthProvider = AnthropicOAuthProvider()

        bind = provider.callback_bind

        assert bind.host == "127.0.0.1"
        assert bind.port == 53692
        assert bind.path == "/callback"
        assert bind.public_host == "localhost"
        assert bind.redirect_uri == "http://localhost:53692/callback"


class TestAnthropicTokenRequests:
    """Anthropic token exchange and refresh use JSON request bodies."""

    @pytest.mark.asyncio
    async def test_exchange_code_posts_json_body_with_state(self, free_port: int) -> None:
        """Authorization-code exchange sends the pi-parity JSON body including state."""
        captured_json: dict[str, object] = {}
        captured_content_type: str = ""

        async def _token_handler(request: web.Request) -> web.Response:
            nonlocal captured_json, captured_content_type
            captured_content_type = request.headers.get("Content-Type", "")
            captured_json = await request.json()
            return web.json_response(data={"access_token": "sk-ant-oat01-test"})

        app: web.Application = web.Application()
        app.router.add_post(path="/v1/oauth/token", handler=_token_handler)
        runner: web.AppRunner = web.AppRunner(app=app)
        await runner.setup()
        site: web.TCPSite = web.TCPSite(runner=runner, host="127.0.0.1", port=free_port)
        await site.start()
        try:
            provider: AnthropicOAuthProvider = AnthropicOAuthProvider()
            with patch.object(
                AnthropicOAuthProvider,
                "token_endpoint",
                new_callable=PropertyMock,
                return_value=f"http://127.0.0.1:{free_port}/v1/oauth/token",
            ):
                cred = await provider.exchange_code(
                    code="demo-code",
                    verifier="demo-verifier",
                    state="demo-state",
                    redirect_uri="http://localhost:53692/callback",
                )

            assert cred.access_token == "sk-ant-oat01-test"
            assert captured_json == {
                "grant_type": "authorization_code",
                "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
                "code": "demo-code",
                "state": "demo-state",
                "redirect_uri": "http://localhost:53692/callback",
                "code_verifier": "demo-verifier",
            }
            assert "application/json" in captured_content_type
        finally:
            await runner.cleanup()

    @pytest.mark.asyncio
    async def test_refresh_posts_json_body_without_scope(self, free_port: int) -> None:
        """Refresh sends JSON and does not include a scope key."""
        captured_json: dict[str, object] = {}

        async def _token_handler(request: web.Request) -> web.Response:
            nonlocal captured_json
            captured_json = await request.json()
            return web.json_response(data={"access_token": "sk-ant-oat01-refresh"})

        app: web.Application = web.Application()
        app.router.add_post(path="/v1/oauth/token", handler=_token_handler)
        runner: web.AppRunner = web.AppRunner(app=app)
        await runner.setup()
        site: web.TCPSite = web.TCPSite(runner=runner, host="127.0.0.1", port=free_port)
        await site.start()
        try:
            provider: AnthropicOAuthProvider = AnthropicOAuthProvider()
            with patch.object(
                AnthropicOAuthProvider,
                "token_endpoint",
                new_callable=PropertyMock,
                return_value=f"http://127.0.0.1:{free_port}/v1/oauth/token",
            ):
                cred = await provider.refresh(refresh_token="refresh-demo")

            assert cred.access_token == "sk-ant-oat01-refresh"
            assert captured_json == {
                "grant_type": "refresh_token",
                "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
                "refresh_token": "refresh-demo",
            }
            assert "scope" not in captured_json
        finally:
            await runner.cleanup()


class TestAnthropicParseTokenResponse:
    """Maps Anthropic's token JSON into a populated ``CredentialDAO``."""

    def test_parses_full_payload(self) -> None:
        """All optional fields populated → DAO with everything set."""
        provider: AnthropicOAuthProvider = AnthropicOAuthProvider()

        cred = provider.parse_token_response(
            payload={
                "access_token": "sk-ant-oat01-test",
                "refresh_token": "sk-ant-ort01-test",
                "expires_in": 3600,
                "sub": "alice@example.com",
            }
        )

        assert cred.provider is ProviderName.ANTHROPIC
        assert cred.auth_type is AuthType.OAUTH
        assert cred.access_token == "sk-ant-oat01-test"
        assert cred.refresh_token == "sk-ant-ort01-test"
        assert cred.subject == "alice@example.com"
        assert cred.expires_at is not None
        assert cred.expires_at > datetime.now(timezone.utc)

    def test_parses_minimal_payload_without_requiring_email(self) -> None:
        """``access_token`` only → DAO with no refresh / expiry / subject."""
        provider: AnthropicOAuthProvider = AnthropicOAuthProvider()

        cred = provider.parse_token_response(
            payload={
                "access_token": "sk-ant-oat01-minimal",
            }
        )

        assert cred.access_token == "sk-ant-oat01-minimal"
        assert cred.refresh_token is None
        assert cred.expires_at is None
        assert cred.subject is None
