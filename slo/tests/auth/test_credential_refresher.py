"""Tests for ``refresh_if_stale`` (feature 07 §4.2)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.auth.credential_dao import (
    AuthType,
    AuthenticationFileDAO,
    CredentialDAO,
    ProviderName,
)
from src.auth.credential_refresher import refresh_if_stale
from src.auth.credential_store import CredentialStore


def _fresh_oauth_cred(
    *,
    ttl_seconds: int,
    provider: ProviderName = ProviderName.OPENAI,
) -> CredentialDAO:
    """Build an OAuth credential whose ``expires_at`` is ``ttl_seconds`` from now.

    Args:
        ttl_seconds (int): Seconds until the credential expires. Negative
            values represent already-expired credentials.
        provider (ProviderName): Provider to attach to the credential.

    Returns:
        CredentialDAO: A fully-populated OAuth credential ready for the
            refresher under test.
    """
    return CredentialDAO(
        provider=provider,
        auth_type=AuthType.OAUTH,
        access_token="stale-access",
        refresh_token="stale-refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        scope="openid profile email offline_access",
    )


def _refreshed_oauth_cred(
    *,
    provider: ProviderName = ProviderName.OPENAI,
) -> CredentialDAO:
    """Build the credential the provider's ``refresh`` mock returns.

    Args:
        provider (ProviderName): Provider to attach to the credential.

    Returns:
        CredentialDAO: Refreshed OAuth credential.
    """
    return CredentialDAO(
        provider=provider,
        auth_type=AuthType.OAUTH,
        access_token="refreshed-access",
        refresh_token="refreshed-refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="openid profile email offline_access",
    )


def _api_key_cred() -> CredentialDAO:
    """Build a non-OAuth credential used to assert the early-return."""
    return CredentialDAO(
        provider=ProviderName.OPENAI,
        auth_type=AuthType.API_KEY,
        access_token="sk-test",
    )


def _build_store(*, tmp_path: Path) -> CredentialStore:
    """Build a ``CredentialStore`` rooted under ``tmp_path``."""
    return CredentialStore(path=tmp_path / "global" / "authentication.json")


class TestRefreshIfStaleEarlyReturns:
    """Branches where ``refresh_if_stale`` short-circuits without refreshing."""

    async def test_returns_cred_when_not_expiring_soon(self, tmp_path: Path) -> None:
        """``expires_at`` more than the buffer away → unchanged."""
        store: CredentialStore = _build_store(tmp_path=tmp_path)
        cred: CredentialDAO = _fresh_oauth_cred(ttl_seconds=3600)

        result: CredentialDAO = await refresh_if_stale(cred=cred, store=store)

        assert result is cred

    async def test_skips_api_key_credentials(self, tmp_path: Path) -> None:
        """``auth_type=API_KEY`` is returned untouched (no refresh path)."""
        store: CredentialStore = _build_store(tmp_path=tmp_path)
        cred: CredentialDAO = _api_key_cred()

        result: CredentialDAO = await refresh_if_stale(cred=cred, store=store)

        assert result is cred

    async def test_skips_oauth_creds_without_expires_at(self, tmp_path: Path) -> None:
        """OAuth credentials that never declared a TTL are returned unchanged."""
        store: CredentialStore = _build_store(tmp_path=tmp_path)
        cred: CredentialDAO = _fresh_oauth_cred(ttl_seconds=3600).model_copy(
            update={"expires_at": None},
        )

        result: CredentialDAO = await refresh_if_stale(cred=cred, store=store)

        assert result is cred


class TestRefreshIfStaleRefreshes:
    """Branches where ``refresh_if_stale`` actually calls the provider."""

    async def test_refreshes_and_persists_when_within_buffer(self, tmp_path: Path) -> None:
        """``expires_at`` < buffer → provider.refresh called once, store.persist invoked."""
        store: CredentialStore = _build_store(tmp_path=tmp_path)
        stale: CredentialDAO = _fresh_oauth_cred(ttl_seconds=10)
        refreshed: CredentialDAO = _refreshed_oauth_cred()

        with patch("src.auth.credential_refresher.OpenAICodexOAuthProvider") as provider_cls:
            provider_cls.return_value.refresh = AsyncMock(return_value=refreshed)

            result: CredentialDAO = await refresh_if_stale(
                cred=stale,
                store=store,
            )

        assert result is refreshed
        provider_cls.return_value.refresh.assert_awaited_once_with(
            refresh_token="stale-refresh",
        )
        persisted: AuthenticationFileDAO = store.load()
        assert persisted.providers[ProviderName.OPENAI].access_token == "refreshed-access"

    async def test_refresh_already_done_by_concurrent_caller_is_skipped(self, tmp_path: Path) -> None:
        """If the store already has a fresh credential, we do not refresh again."""
        store: CredentialStore = _build_store(tmp_path=tmp_path)
        # Seed the store with an already-fresh credential. The caller
        # still sees a stale snapshot in memory, but the lock-guarded
        # re-read picks up the fresh row and short-circuits.
        already_fresh: CredentialDAO = _refreshed_oauth_cred()
        store.persist(cred=already_fresh)
        stale_in_memory: CredentialDAO = _fresh_oauth_cred(ttl_seconds=10)

        with patch("src.auth.credential_refresher.OpenAICodexOAuthProvider") as provider_cls:
            provider_cls.return_value.refresh = AsyncMock(
                return_value=_refreshed_oauth_cred(),
            )

            result: CredentialDAO = await refresh_if_stale(
                cred=stale_in_memory,
                store=store,
            )

        provider_cls.return_value.refresh.assert_not_awaited()
        assert result.access_token == already_fresh.access_token


class TestRefreshIfStaleAnthropic:
    """Anthropic-specific refresh coverage."""

    async def test_refreshes_and_persists_anthropic_within_buffer(self, tmp_path: Path) -> None:
        """Within-buffer Anthropic OAuth credentials refresh and persist."""
        store: CredentialStore = _build_store(tmp_path=tmp_path)
        stale: CredentialDAO = _fresh_oauth_cred(
            ttl_seconds=10,
            provider=ProviderName.ANTHROPIC,
        )
        refreshed: CredentialDAO = _refreshed_oauth_cred(
            provider=ProviderName.ANTHROPIC,
        )

        with patch("src.auth.credential_refresher.AnthropicOAuthProvider") as provider_cls:
            provider_cls.return_value.refresh = AsyncMock(return_value=refreshed)

            result: CredentialDAO = await refresh_if_stale(cred=stale, store=store)

        assert result is refreshed
        provider_cls.return_value.refresh.assert_awaited_once_with(
            refresh_token="stale-refresh",
        )
        persisted: AuthenticationFileDAO = store.load()
        assert persisted.providers[ProviderName.ANTHROPIC].access_token == "refreshed-access"

    async def test_anthropic_without_refresh_token_short_circuits(self, tmp_path: Path) -> None:
        """Legacy Anthropic fallback credentials without refresh metadata no-op."""
        store: CredentialStore = _build_store(tmp_path=tmp_path)
        cred: CredentialDAO = _fresh_oauth_cred(
            ttl_seconds=10,
            provider=ProviderName.ANTHROPIC,
        ).model_copy(update={"refresh_token": None})

        result: CredentialDAO = await refresh_if_stale(cred=cred, store=store)

        assert result is cred

    async def test_concurrent_anthropic_refreshes_share_one_provider_call(self, tmp_path: Path) -> None:
        """Concurrent Anthropic refreshes coalesce under the shared lock."""
        store: CredentialStore = _build_store(tmp_path=tmp_path)
        stale: CredentialDAO = _fresh_oauth_cred(
            ttl_seconds=10,
            provider=ProviderName.ANTHROPIC,
        )
        refreshed: CredentialDAO = _refreshed_oauth_cred(
            provider=ProviderName.ANTHROPIC,
        )
        call_count: int = 0

        async def _slow_refresh(*, refresh_token: str) -> CredentialDAO:
            """Track Anthropic refresh invocation count."""
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0)
            return refreshed

        with (
            patch("src.auth.credential_refresher.AnthropicOAuthProvider") as provider_cls,
            patch(
                "src.auth.credential_refresher._REFRESH_LOCK",
                new=asyncio.Lock(),
            ),
        ):
            provider_cls.return_value.refresh = _slow_refresh

            results: list[CredentialDAO] = await asyncio.gather(
                *[refresh_if_stale(cred=stale, store=store) for _ in range(4)]
            )

        assert call_count == 1
        for result in results:
            assert result.provider is ProviderName.ANTHROPIC
            assert result.access_token == "refreshed-access"


class TestRefreshIfStaleConcurrency:
    """Concurrent refresh requests coalesce into one provider call."""

    async def test_concurrent_callers_share_one_refresh(self, tmp_path: Path) -> None:
        """Five concurrent stale callers → exactly one ``provider.refresh`` invocation."""
        store: CredentialStore = _build_store(tmp_path=tmp_path)
        stale: CredentialDAO = _fresh_oauth_cred(ttl_seconds=10)
        refreshed: CredentialDAO = _refreshed_oauth_cred()

        call_count: int = 0

        async def _slow_refresh(*, refresh_token: str) -> CredentialDAO:
            """Track how many times the provider's refresh is invoked."""
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0)
            return refreshed

        with (
            patch("src.auth.credential_refresher.OpenAICodexOAuthProvider") as provider_cls,
            patch(
                "src.auth.credential_refresher._REFRESH_LOCK",
                new=asyncio.Lock(),
            ),
        ):
            provider_cls.return_value.refresh = _slow_refresh

            results: list[CredentialDAO] = await asyncio.gather(
                *[refresh_if_stale(cred=stale, store=store) for _ in range(5)]
            )

        assert call_count == 1
        # All callers observe the refreshed credential (the first
        # invocation refreshes; subsequent invocations read the freshly
        # persisted row inside the lock).
        for result in results:
            assert result.access_token == "refreshed-access"


class TestCredentialFileLock:
    """Cross-process ``fcntl.flock`` advisory lock (sub-spec 01-sub-agents 01.g)."""

    async def test_lock_file_created_when_absent(self, tmp_path: Path) -> None:
        """The lock sentinel file is created automatically on first use."""
        from unittest.mock import patch as _patch

        from src.auth.credential_refresher import (
            _file_locked_refresh,
            _CREDENTIALS_LOCK_FILE,
        )

        lock_path: Path = tmp_path / ".credentials.lock"
        with _patch("src.auth.credential_refresher._CREDENTIALS_LOCK_FILE", lock_path):
            with _patch(
                "src.auth.credential_refresher._refresh_body",
                new=AsyncMock(return_value=AsyncMock()),
            ):
                await _file_locked_refresh(
                    cred=AsyncMock(),
                    store=AsyncMock(),
                    provider_cls=AsyncMock(),
                )

        assert lock_path.exists()

    async def test_concurrent_callers_serialise(self, tmp_path: Path) -> None:
        """Two concurrent callers do not overlap inside ``_refresh_body``."""
        import time
        from unittest.mock import patch as _patch

        from src.auth.credential_refresher import _file_locked_refresh

        lock_path: Path = tmp_path / ".credentials.lock"
        call_order: list[str] = []

        async def _fake_body(**kwargs: object) -> object:
            call_order.append("enter")
            await asyncio.sleep(0.02)
            call_order.append("exit")
            return AsyncMock()

        with _patch("src.auth.credential_refresher._CREDENTIALS_LOCK_FILE", lock_path):
            with _patch(
                "src.auth.credential_refresher._refresh_body",
                new=_fake_body,
            ):
                await asyncio.gather(
                    _file_locked_refresh(cred=AsyncMock(), store=AsyncMock(), provider_cls=AsyncMock()),
                    _file_locked_refresh(cred=AsyncMock(), store=AsyncMock(), provider_cls=AsyncMock()),
                )

        # Serialised: enter, exit, enter, exit (never enter, enter, exit, exit)
        assert call_order == ["enter", "exit", "enter", "exit"]

    async def test_lock_released_on_exception(self, tmp_path: Path) -> None:
        """The file lock is released even when ``_refresh_body`` raises."""
        from unittest.mock import patch as _patch

        from src.auth.credential_refresher import _file_locked_refresh

        lock_path: Path = tmp_path / ".credentials.lock"

        with _patch("src.auth.credential_refresher._CREDENTIALS_LOCK_FILE", lock_path):
            with _patch(
                "src.auth.credential_refresher._refresh_body",
                side_effect=RuntimeError("refresh exploded"),
            ):
                with pytest.raises(RuntimeError, match="refresh exploded"):
                    await _file_locked_refresh(cred=AsyncMock(), store=AsyncMock(), provider_cls=AsyncMock())

        # A subsequent call must succeed — proving the lock was released.
        with _patch("src.auth.credential_refresher._CREDENTIALS_LOCK_FILE", lock_path):
            with _patch(
                "src.auth.credential_refresher._refresh_body",
                new=AsyncMock(return_value=AsyncMock()),
            ):
                # Must not raise or hang — the lock was properly released.
                result = await _file_locked_refresh(
                    cred=AsyncMock(), store=AsyncMock(), provider_cls=AsyncMock()
                )
        assert result is not None
