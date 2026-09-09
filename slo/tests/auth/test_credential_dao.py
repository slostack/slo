"""Tests for ``CredentialDAO`` and ``AuthenticationFileDAO`` (02.b.1)."""

from datetime import datetime, timedelta, timezone

from src.auth.credential_dao import (
    AuthType,
    AuthenticationFileDAO,
    CredentialDAO,
    ProviderName,
)


class TestCredentialDAOIsExpired:
    """``CredentialDAO.is_expired`` — the only branch with logic."""

    def test_is_expired_false_when_expires_at_is_none(self) -> None:
        """No declared expiry → never expired (API keys, perpetual OAuth)."""
        cred: CredentialDAO = CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.API_KEY,
            access_token="sk-test",
        )
        assert cred.is_expired is False

    def test_is_expired_false_when_expires_at_is_future(self) -> None:
        """Future ``expires_at`` → not expired."""
        cred: CredentialDAO = CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.OAUTH,
            access_token="sk-test",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        assert cred.is_expired is False

    def test_is_expired_true_when_expires_at_is_past(self) -> None:
        """Past ``expires_at`` → expired."""
        cred: CredentialDAO = CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.OAUTH,
            access_token="sk-test",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        assert cred.is_expired is True


class TestAuthenticationFileDAODefaults:
    """The envelope's defaults are load-bearing for first-launch."""

    def test_empty_envelope_has_schema_version_one(self) -> None:
        """Schema version stays at 1 for first-launch."""
        envelope: AuthenticationFileDAO = AuthenticationFileDAO()
        assert envelope.schema_version == 1

    def test_empty_envelope_has_no_providers(self) -> None:
        """Default ``providers`` is empty, not None."""
        envelope: AuthenticationFileDAO = AuthenticationFileDAO()
        assert envelope.providers == {}


class TestEnumSerialisation:
    """Enums round-trip as their string values in JSON."""

    def test_provider_name_json_roundtrip(self) -> None:
        """ProviderName serialises as ``anthropic`` / ``openai``."""
        envelope: AuthenticationFileDAO = AuthenticationFileDAO(
            providers={
                ProviderName.ANTHROPIC: CredentialDAO(
                    provider=ProviderName.ANTHROPIC,
                    auth_type=AuthType.OAUTH,
                    access_token="sk-ant-oat01-x",
                ),
            },
        )
        data: dict = envelope.model_dump(mode="json")
        assert data["providers"]["anthropic"]["provider"] == "anthropic"
        assert data["providers"]["anthropic"]["auth_type"] == "oauth"
