"""Tests for ConnectorCredentialStore (25.a.1)."""

import json
import stat
from pathlib import Path

import pytest

from src.integrations.connectors.credentials import (
    ConnectorCredentialDAO,
    ConnectorProviderName,
)
from src.integrations.connectors.exceptions import ConnectorCredentialStoreCorruptError
from src.integrations.connectors.store import ConnectorCredentialStore


def _atlassian_cred(
    *,
    base: str = "https://example.atlassian.net",
    token: str = "tok-123",
    username: str = "dev@example.com",
) -> ConnectorCredentialDAO:
    """Build a deterministic Atlassian credential for tests."""
    return ConnectorCredentialDAO(
        provider=ConnectorProviderName.ATLASSIAN,
        base_url=base,
        token=token,
        username=username,
    )


def _github_cred(*, token: str = "gh-tok") -> ConnectorCredentialDAO:
    """Build a deterministic GitHub credential for tests."""
    return ConnectorCredentialDAO(
        provider=ConnectorProviderName.GITHUB,
        base_url="https://api.github.com",
        token=token,
    )


class TestConnectorCredentialStorePaths:
    """``credentials_path`` returns the correct location per provider."""

    def test_atlassian_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        path: Path = ConnectorCredentialStore.credentials_path(
            provider=ConnectorProviderName.ATLASSIAN,
        )
        assert path == tmp_path / "atlassian" / "credentials.json"

    def test_github_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        path: Path = ConnectorCredentialStore.credentials_path(
            provider=ConnectorProviderName.GITHUB,
        )
        assert path == tmp_path / "github" / "credentials.json"

    def test_gitlab_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        path: Path = ConnectorCredentialStore.credentials_path(
            provider=ConnectorProviderName.GITLAB,
        )
        assert path == tmp_path / "gitlab" / "credentials.json"


class TestConnectorCredentialStoreLoad:
    """``load`` — file-absent, valid, and corrupt paths."""

    def test_returns_none_when_file_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        result = ConnectorCredentialStore.load(provider=ConnectorProviderName.ATLASSIAN)
        assert result is None

    def test_returns_dao_when_file_present(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        cred = _atlassian_cred()
        ConnectorCredentialStore.upsert(credential=cred)

        loaded = ConnectorCredentialStore.load(provider=ConnectorProviderName.ATLASSIAN)

        assert loaded is not None
        assert loaded.token == "tok-123"
        assert loaded.username == "dev@example.com"

    def test_raises_corrupt_error_on_invalid_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        path = tmp_path / "atlassian" / "credentials.json"
        path.parent.mkdir(parents=True)
        path.write_text("{invalid json", encoding="utf-8")

        with pytest.raises(ConnectorCredentialStoreCorruptError):
            ConnectorCredentialStore.load(provider=ConnectorProviderName.ATLASSIAN)


class TestConnectorCredentialStoreUpsert:
    """``upsert`` — write semantics, permissions, isolation."""

    def test_creates_dir_with_mode_700(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        ConnectorCredentialStore.upsert(credential=_atlassian_cred())

        parent = ConnectorCredentialStore.credentials_path(
            provider=ConnectorProviderName.ATLASSIAN,
        ).parent
        assert stat.S_IMODE(parent.stat().st_mode) == 0o700

    def test_creates_file_with_mode_600(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        ConnectorCredentialStore.upsert(credential=_atlassian_cred())

        path = ConnectorCredentialStore.credentials_path(
            provider=ConnectorProviderName.ATLASSIAN,
        )
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_replaces_existing_credential(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        ConnectorCredentialStore.upsert(credential=_atlassian_cred(token="old"))
        ConnectorCredentialStore.upsert(credential=_atlassian_cred(token="new"))

        loaded = ConnectorCredentialStore.load(provider=ConnectorProviderName.ATLASSIAN)

        assert loaded is not None
        assert loaded.token == "new"

    def test_does_not_touch_other_provider_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        ConnectorCredentialStore.upsert(credential=_atlassian_cred())
        ConnectorCredentialStore.upsert(credential=_github_cred(token="gh-tok-2"))

        atlassian = ConnectorCredentialStore.load(provider=ConnectorProviderName.ATLASSIAN)
        github = ConnectorCredentialStore.load(provider=ConnectorProviderName.GITHUB)

        assert atlassian is not None
        assert atlassian.token == "tok-123"
        assert github is not None
        assert github.token == "gh-tok-2"

    def test_corrects_dir_mode_on_subsequent_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        ConnectorCredentialStore.upsert(credential=_atlassian_cred())
        parent = ConnectorCredentialStore.credentials_path(
            provider=ConnectorProviderName.ATLASSIAN,
        ).parent
        parent.chmod(0o755)

        ConnectorCredentialStore.upsert(credential=_atlassian_cred(token="v2"))

        assert stat.S_IMODE(parent.stat().st_mode) == 0o700
