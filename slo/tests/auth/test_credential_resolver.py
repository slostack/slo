"""Tests for ``CredentialResolver`` (02.b.2)."""

import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import config.cfg as cfg_module
from src.auth.credential_dao import (
    AuthType,
    CredentialDAO,
    ProviderName,
)
from src.auth.credential_resolver import CredentialResolver
from src.auth.credential_store import CredentialStore


def _reload_cfg() -> None:
    """Re-import ``config.cfg`` so module-level env captures pick up changes.

    ``config.cfg`` reads ``SLO_*`` env vars at import time and caches the
    resulting values in its ``__cfg__`` dict. Tests that ``monkeypatch.setenv``
    or ``monkeypatch.delenv`` must reload the module to flush the cache —
    the same pattern used by ``tests/agents/test_base.py``.
    """
    importlib.reload(cfg_module)


def _patch_store_path(*, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Re-root ``CredentialStore`` at ``tmp_path`` for the test.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest's monkeypatch fixture.
        tmp_path (Path): The test's temp dir.

    Returns:
        Path: The redirected credentials file path.
    """
    store_path: Path = tmp_path / "global" / "authentication.json"
    monkeypatch.setattr(
        "src.auth.credential_resolver.CredentialStore",
        lambda: CredentialStore(path=store_path),
    )
    return store_path


class TestResolveEnvPath:
    """Env var always wins."""

    def test_returns_env_credential_when_set(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Env var for the provider produces an API-key DAO."""
        _patch_store_path(monkeypatch=monkeypatch, tmp_path=tmp_path)
        monkeypatch.setenv("SLO_OPENAI_API_KEY", "sk-from-env")
        _reload_cfg()

        cred = CredentialResolver.resolve(provider=ProviderName.OPENAI)

        assert cred is not None
        assert cred.auth_type is AuthType.API_KEY
        assert cred.access_token == "sk-from-env"

    def test_env_wins_over_store(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Env value beats a stored row."""
        store_path: Path = _patch_store_path(monkeypatch=monkeypatch, tmp_path=tmp_path)
        CredentialStore(path=store_path).persist(
            cred=CredentialDAO(
                provider=ProviderName.OPENAI,
                auth_type=AuthType.API_KEY,
                access_token="sk-from-store",
            )
        )
        monkeypatch.setenv("SLO_OPENAI_API_KEY", "sk-from-env")
        _reload_cfg()

        cred = CredentialResolver.resolve(provider=ProviderName.OPENAI)

        assert cred is not None
        assert cred.access_token == "sk-from-env"


class TestResolveStorePath:
    """Store wins when env is empty."""

    def test_returns_store_credential_when_env_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No env, populated store → store row."""
        store_path: Path = _patch_store_path(monkeypatch=monkeypatch, tmp_path=tmp_path)
        monkeypatch.delenv("SLO_OPENAI_API_KEY", raising=False)
        _reload_cfg()
        CredentialStore(path=store_path).persist(
            cred=CredentialDAO(
                provider=ProviderName.OPENAI,
                auth_type=AuthType.API_KEY,
                access_token="sk-from-store",
            )
        )

        cred = CredentialResolver.resolve(provider=ProviderName.OPENAI)

        assert cred is not None
        assert cred.access_token == "sk-from-store"

    def test_skips_expired_store_row(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Expired OAuth row falls through to next source."""
        store_path: Path = _patch_store_path(monkeypatch=monkeypatch, tmp_path=tmp_path)
        monkeypatch.delenv("SLO_OPENAI_API_KEY", raising=False)
        _reload_cfg()
        CredentialStore(path=store_path).persist(
            cred=CredentialDAO(
                provider=ProviderName.OPENAI,
                auth_type=AuthType.OAUTH,
                access_token="expired",
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
        )

        cred = CredentialResolver.resolve(provider=ProviderName.OPENAI)

        # OpenAI has no legacy fallback, so expired-skip → None.
        assert cred is None


class TestResolveLegacyClaudePath:
    """Legacy ``~/.claude/.credentials.json`` is Anthropic-only."""

    def test_legacy_used_when_env_and_store_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Anthropic provider falls through to the legacy file."""
        _patch_store_path(monkeypatch=monkeypatch, tmp_path=tmp_path)
        monkeypatch.delenv("SLO_ANTHROPIC_API_KEY", raising=False)
        _reload_cfg()

        legacy_path: Path = tmp_path / "credentials.json"
        legacy_path.write_text(
            json.dumps(
                {
                    "claudeAiOauth": {"accessToken": "sk-ant-legacy"},
                }
            )
        )
        monkeypatch.setattr(
            CredentialResolver,
            "_CLAUDE_CREDENTIALS_PATH",
            legacy_path,
        )

        cred = CredentialResolver.resolve(provider=ProviderName.ANTHROPIC)

        assert cred is not None
        assert cred.access_token == "sk-ant-legacy"
        assert cred.auth_type is AuthType.OAUTH

    def test_legacy_ignored_for_openai(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Even with a populated legacy file, OpenAI never reads it."""
        _patch_store_path(monkeypatch=monkeypatch, tmp_path=tmp_path)
        monkeypatch.delenv("SLO_OPENAI_API_KEY", raising=False)
        _reload_cfg()

        legacy_path: Path = tmp_path / "credentials.json"
        legacy_path.write_text(
            json.dumps(
                {
                    "claudeAiOauth": {"accessToken": "sk-ant-legacy"},
                }
            )
        )
        monkeypatch.setattr(
            CredentialResolver,
            "_CLAUDE_CREDENTIALS_PATH",
            legacy_path,
        )

        cred = CredentialResolver.resolve(provider=ProviderName.OPENAI)

        assert cred is None

    def test_legacy_swallowed_when_malformed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Garbage legacy file does not raise."""
        _patch_store_path(monkeypatch=monkeypatch, tmp_path=tmp_path)
        monkeypatch.delenv("SLO_ANTHROPIC_API_KEY", raising=False)
        _reload_cfg()

        legacy_path: Path = tmp_path / "credentials.json"
        legacy_path.write_text("{ bad json")
        monkeypatch.setattr(
            CredentialResolver,
            "_CLAUDE_CREDENTIALS_PATH",
            legacy_path,
        )

        cred = CredentialResolver.resolve(provider=ProviderName.ANTHROPIC)

        assert cred is None


class TestRequire:
    """``require`` raises with provider-specific messages."""

    def test_require_returns_resolved_credential(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When ``resolve`` returns a credential, ``require`` returns the same."""
        _patch_store_path(monkeypatch=monkeypatch, tmp_path=tmp_path)
        monkeypatch.setenv("SLO_OPENAI_API_KEY", "sk-from-env")
        _reload_cfg()

        cred = CredentialResolver.require(provider=ProviderName.OPENAI)

        assert cred.access_token == "sk-from-env"

    def test_require_raises_for_anthropic_when_nothing_resolves(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Anthropic-specific message names SLO_ANTHROPIC_API_KEY."""
        _patch_store_path(monkeypatch=monkeypatch, tmp_path=tmp_path)
        monkeypatch.delenv("SLO_ANTHROPIC_API_KEY", raising=False)
        _reload_cfg()
        monkeypatch.setattr(
            CredentialResolver,
            "_CLAUDE_CREDENTIALS_PATH",
            tmp_path / "does-not-exist.json",
        )

        with pytest.raises(ValueError, match="SLO_ANTHROPIC_API_KEY"):
            CredentialResolver.require(provider=ProviderName.ANTHROPIC)

    def test_require_raises_for_openai_when_nothing_resolves(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """OpenAI-specific message names SLO_OPENAI_API_KEY."""
        _patch_store_path(monkeypatch=monkeypatch, tmp_path=tmp_path)
        monkeypatch.delenv("SLO_OPENAI_API_KEY", raising=False)
        _reload_cfg()

        with pytest.raises(ValueError, match="SLO_OPENAI_API_KEY"):
            CredentialResolver.require(provider=ProviderName.OPENAI)


class TestNothingResolves:
    """All sources empty → ``resolve`` returns ``None``."""

    def test_returns_none_when_no_sources_have_credentials(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Clean slate, OpenAI provider → None."""
        _patch_store_path(monkeypatch=monkeypatch, tmp_path=tmp_path)
        monkeypatch.delenv("SLO_OPENAI_API_KEY", raising=False)
        _reload_cfg()

        cred = CredentialResolver.resolve(provider=ProviderName.OPENAI)

        assert cred is None
