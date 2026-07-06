"""Tests for ConnectorCredentialResolver (25.a.1)."""
from pathlib import Path
from typing import Optional

import pytest

from src.integrations.connectors.credentials import (
    ConnectorCredentialDAO,
    ConnectorCredentialResolver,
    ConnectorProviderName,
)
from src.integrations.connectors.exceptions import ConnectorCredentialsRequiredError
from src.integrations.connectors.store import ConnectorCredentialStore


def _clear_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all connector-related env vars so tests start from a clean state."""
    for var in (
        "SLO_ATLASSIAN_SITE_URL",
        "SLO_ATLASSIAN_EMAIL",
        "SLO_ATLASSIAN_API_TOKEN",
        "SLO_ATLASSIAN_TIMEOUT_SECONDS",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "SLO_GITHUB_TOKEN",
        "SLO_GITHUB_API_BASE_URL",
        "GITLAB_TOKEN",
        "GLAB_TOKEN",
        "SLO_GITLAB_TOKEN",
        "SLO_GITLAB_API_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)


class TestConnectorCredentialResolverEnv:
    """Env-variable resolution takes precedence over the store."""

    def test_atlassian_resolves_from_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", "https://acme.atlassian.net")
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "dev@acme.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok-abc")

        cred: Optional[ConnectorCredentialDAO] = ConnectorCredentialResolver.resolve(
            provider=ConnectorProviderName.ATLASSIAN,
        )

        assert cred is not None
        assert cred.provider is ConnectorProviderName.ATLASSIAN
        assert cred.base_url == "https://acme.atlassian.net"
        assert cred.username == "dev@acme.com"
        assert cred.token == "tok-abc"

    def test_atlassian_returns_none_when_any_required_var_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", "https://acme.atlassian.net")
        # email and token intentionally absent

        cred = ConnectorCredentialResolver.resolve(
            provider=ConnectorProviderName.ATLASSIAN,
        )

        assert cred is None

    def test_github_uses_github_token_first(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("GITHUB_TOKEN", "gh-a")
        monkeypatch.setenv("GH_TOKEN", "gh-b")
        monkeypatch.setenv("SLO_GITHUB_TOKEN", "gh-c")

        cred = ConnectorCredentialResolver.resolve(provider=ConnectorProviderName.GITHUB)

        assert cred is not None
        assert cred.token == "gh-a"

    def test_github_falls_back_to_gh_token(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("GH_TOKEN", "gh-b")
        monkeypatch.setenv("SLO_GITHUB_TOKEN", "gh-c")

        cred = ConnectorCredentialResolver.resolve(provider=ConnectorProviderName.GITHUB)

        assert cred is not None
        assert cred.token == "gh-b"

    def test_gitlab_uses_gitlab_token_first(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("GITLAB_TOKEN", "gl-a")
        monkeypatch.setenv("GLAB_TOKEN", "gl-b")
        monkeypatch.setenv("SLO_GITLAB_TOKEN", "gl-c")

        cred = ConnectorCredentialResolver.resolve(provider=ConnectorProviderName.GITLAB)

        assert cred is not None
        assert cred.token == "gl-a"

    def test_github_base_url_override_applied(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("SLO_GITHUB_API_BASE_URL", "https://github.enterprise.com/api/v3")

        cred = ConnectorCredentialResolver.resolve(provider=ConnectorProviderName.GITHUB)

        assert cred is not None
        assert cred.base_url == "https://github.enterprise.com/api/v3"


class TestConnectorCredentialResolverStore:
    """Store fallback when env vars are absent."""

    def test_resolves_from_store_when_env_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))

        stored = ConnectorCredentialDAO(
            provider=ConnectorProviderName.ATLASSIAN,
            base_url="https://stored.atlassian.net",
            token="stored-tok",
            username="user@stored.com",
        )
        ConnectorCredentialStore.upsert(credential=stored)

        cred = ConnectorCredentialResolver.resolve(
            provider=ConnectorProviderName.ATLASSIAN,
        )

        assert cred is not None
        assert cred.token == "stored-tok"

    def test_env_overrides_store(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))

        stored = ConnectorCredentialDAO(
            provider=ConnectorProviderName.ATLASSIAN,
            base_url="https://stored.atlassian.net",
            token="stored-tok",
            username="user@stored.com",
        )
        ConnectorCredentialStore.upsert(credential=stored)

        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", "https://env.atlassian.net")
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "env@example.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "env-tok")
        # Default is store-first: store wins over env.
        monkeypatch.delenv("SLO_CONNECTOR_PREFER_ENV", raising=False)

        cred = ConnectorCredentialResolver.resolve(
            provider=ConnectorProviderName.ATLASSIAN,
        )

        assert cred is not None
        assert cred.token == "stored-tok"  # store wins by default


class TestConnectorCredentialResolverRequire:
    """``require`` returns cred or raises ``ConnectorCredentialsRequiredError``."""

    def test_require_raises_when_not_configured(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))

        with pytest.raises(ConnectorCredentialsRequiredError) as exc_info:
            ConnectorCredentialResolver.require(
                provider=ConnectorProviderName.ATLASSIAN,
            )

        assert exc_info.value.provider == "atlassian"
        assert "base_url" in exc_info.value.required_fields

    def test_require_returns_credential_when_available(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", "https://ok.atlassian.net")
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "a@b.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        cred = ConnectorCredentialResolver.require(
            provider=ConnectorProviderName.ATLASSIAN,
        )

        assert cred.token == "tok"


class TestConnectorCredentialResolverIsConfigured:
    """``is_configured`` reflects ``resolve() is not None``."""

    def test_returns_false_when_no_credentials(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))

        assert ConnectorCredentialResolver.is_configured(
            provider=ConnectorProviderName.ATLASSIAN,
        ) is False

    def test_returns_true_when_env_present(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", "https://x.atlassian.net")
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "x@x.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "x-tok")

        assert ConnectorCredentialResolver.is_configured(
            provider=ConnectorProviderName.ATLASSIAN,
        ) is True


class TestConnectorCredentialResolverPrecedence:
    """Store-first precedence and SLO_CONNECTOR_PREFER_ENV=1 escape hatch."""

    def test_store_beats_env_by_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Default: store value wins over env vars."""
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.delenv("SLO_CONNECTOR_PREFER_ENV", raising=False)

        # Write a store credential
        stored = ConnectorCredentialDAO(
            provider=ConnectorProviderName.ATLASSIAN,
            base_url="https://store.atlassian.net",
            token="store-tok",
            username="store@example.com",
        )
        ConnectorCredentialStore.upsert(credential=stored)

        # Set env credentials with different token
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", "https://env.atlassian.net")
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "env@example.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "env-tok")

        cred = ConnectorCredentialResolver.resolve(provider=ConnectorProviderName.ATLASSIAN)

        assert cred is not None
        assert cred.token == "store-tok"

    def test_env_used_when_store_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When store is empty, env is used as fallback."""
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.delenv("SLO_CONNECTOR_PREFER_ENV", raising=False)

        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", "https://env.atlassian.net")
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "env@example.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "env-tok")

        cred = ConnectorCredentialResolver.resolve(provider=ConnectorProviderName.ATLASSIAN)

        assert cred is not None
        assert cred.token == "env-tok"

    def test_prefer_env_flag_restores_env_first(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When SLO_CONNECTOR_PREFER_ENV=1, env wins over store."""
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_CONNECTOR_PREFER_ENV", "1")

        stored = ConnectorCredentialDAO(
            provider=ConnectorProviderName.ATLASSIAN,
            base_url="https://store.atlassian.net",
            token="store-tok",
            username="store@example.com",
        )
        ConnectorCredentialStore.upsert(credential=stored)

        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", "https://env.atlassian.net")
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "env@example.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "env-tok")

        cred = ConnectorCredentialResolver.resolve(provider=ConnectorProviderName.ATLASSIAN)

        assert cred is not None
        assert cred.token == "env-tok"

    def test_prefer_env_only_activated_by_value_1(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Values other than '1' do not activate env-first mode."""
        _clear_env_vars(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_CONNECTOR_PREFER_ENV", "true")  # not "1"

        stored = ConnectorCredentialDAO(
            provider=ConnectorProviderName.ATLASSIAN,
            base_url="https://store.atlassian.net",
            token="store-tok",
            username="store@example.com",
        )
        ConnectorCredentialStore.upsert(credential=stored)

        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", "https://env.atlassian.net")
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "env@example.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "env-tok")

        cred = ConnectorCredentialResolver.resolve(provider=ConnectorProviderName.ATLASSIAN)

        # "true" != "1" so store still wins
        assert cred is not None
        assert cred.token == "store-tok"
