"""Proactive OAuth refresh helper (feature 07 §4.2).

Called from ``LLMFactory._build_openai`` (and any future component that
constructs an OAuth-backed client) before the credential is handed to
the chat model. Refreshes the persisted credential when ``expires_at``
is within ``_EXPIRY_BUFFER_SECONDS`` of now and persists the result;
returns the latest credential otherwise.

In-process serialisation uses the module-level ``asyncio.Lock``
(``_REFRESH_LOCK``) as the fast path. Cross-process serialisation (needed
when multiple ``slo run --json`` child processes share the same
``~/.slo/.credentials.json``) uses an advisory ``fcntl.flock`` exclusive
lock on ``~/.slo/.credentials.lock``. The file lock is acquired in a
thread via ``asyncio.to_thread`` so the event loop stays responsive while
a child waits for another child to finish refreshing.

Sub-spec 01-sub-agents 01.g adds the cross-process file lock.
"""

from __future__ import annotations

import asyncio
import fcntl
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Optional

from config.cfg import SLO_HOME as _CFG_SLO_HOME
from config.logger import log_info
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore
from src.auth.oauth_provider import OAuthProvider
from src.auth.providers.anthropic_provider import AnthropicOAuthProvider
from src.auth.providers.openai_codex_provider import OpenAICodexOAuthProvider

__all__ = ["refresh_if_stale"]


_EXPIRY_BUFFER_SECONDS: int = 60
"""How close to ``expires_at`` we consider the credential stale.

Sixty seconds is the working budget for the request to hit the wire
before the access token rolls over. Smaller buffers race the clock;
larger buffers refresh more often than necessary.
"""

_REFRESH_LOCK: asyncio.Lock = asyncio.Lock()
"""Module-level in-process lock so concurrent refreshes coalesce into one IdP call."""

_CREDENTIALS_LOCK_FILE: Path = _CFG_SLO_HOME / ".credentials.lock"
"""Cross-process advisory lock file.

Used by ``fcntl.flock`` to serialise OAuth credential refresh across
concurrent ``slo run --json`` child processes. The file is created
automatically on first use and is never deleted — its presence has no
semantic meaning beyond providing a stable descriptor for ``flock``.

**NFS caveat:** ``fcntl.flock`` is unreliable on NFS-mounted home
directories. If ``~/.slo`` is NFS-mounted, set ``SLO_HOME`` to a local
path.
"""


def _oauth_provider_class_for(
    *,
    name: ProviderName,
) -> type[OAuthProvider] | None:
    """Resolve the concrete ``OAuthProvider`` class for one provider name.

    Resolved at call time (not import time) so tests can patch the
    module-level ``OpenAICodexOAuthProvider`` symbol and have the
    override picked up by the next refresh attempt.

    Args:
        name (ProviderName): The provider whose OAuth class we need.

    Returns:
        type[OAuthProvider] | None: The class, or ``None`` for providers
            that do not support OAuth refresh in v1.
    """
    if name == ProviderName.OPENAI:
        return OpenAICodexOAuthProvider
    if name == ProviderName.ANTHROPIC:
        return AnthropicOAuthProvider
    return None


async def refresh_if_stale(
    *,
    cred: CredentialDAO,
    store: CredentialStore,
) -> CredentialDAO:
    """Refresh ``cred`` if it expires within ``_EXPIRY_BUFFER_SECONDS``.

    Tell-don't-ask: callers hand us a credential and a store, we either
    return the same credential (still fresh, or not OAuth-backed) or
    swap it for a freshly refreshed one and persist that swap atomically.

    Acquires the in-process ``_REFRESH_LOCK`` first (fast path for
    same-process callers), then acquires the cross-process
    ``fcntl.flock`` advisory lock before reading or writing credentials,
    so concurrent ``slo run --json`` children cannot interleave token
    refreshes and corrupt ``~/.slo/.credentials.json``.

    Args:
        cred (CredentialDAO): The credential about to be used.
        store (CredentialStore): The persistence layer to read latest
            state from and write the refresh back to.

    Returns:
        CredentialDAO: ``cred`` if still fresh, otherwise the refreshed
            credential after it has been persisted.
    """
    if cred.auth_type != AuthType.OAUTH or cred.expires_at is None:
        return cred
    if not _is_within_expiry_buffer(expires_at=cred.expires_at):
        return cred
    provider_cls: type[OAuthProvider] | None = _oauth_provider_class_for(
        name=cred.provider,
    )
    if provider_cls is None or cred.refresh_token is None:
        return cred

    async with _REFRESH_LOCK:
        return await _file_locked_refresh(
            cred=cred,
            store=store,
            provider_cls=provider_cls,
        )


async def _file_locked_refresh(
    *,
    cred: CredentialDAO,
    store: CredentialStore,
    provider_cls: type[OAuthProvider],
) -> CredentialDAO:
    """Run the credential refresh under a cross-process ``fcntl.flock`` advisory lock.

    Acquires ``_CREDENTIALS_LOCK_FILE`` exclusively in a thread (so the
    event loop is not blocked while waiting), then performs the
    re-check-and-refresh body while the lock is held, and releases on
    exit regardless of whether an exception was raised.

    Args:
        cred (CredentialDAO): The stale credential that triggered the refresh.
        store (CredentialStore): Persistence layer for reading and writing.
        provider_cls (type[OAuthProvider]): Resolved OAuth provider class.

    Returns:
        CredentialDAO: Freshly refreshed credential, or the latest persisted
            credential when another process refreshed first.
    """
    lock_path: Path = _CREDENTIALS_LOCK_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd: IO[str] = open(str(lock_path), "w")  # noqa: WPS515
    try:
        await asyncio.to_thread(fcntl.flock, fd, fcntl.LOCK_EX)
        return await _refresh_body(
            cred=cred,
            store=store,
            provider_cls=provider_cls,
        )
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


async def _refresh_body(
    *,
    cred: CredentialDAO,
    store: CredentialStore,
    provider_cls: type[OAuthProvider],
) -> CredentialDAO:
    """Perform the re-check and conditional refresh while the file lock is held.

    Re-reads the persisted credential after acquiring the lock so concurrent
    processes that observed the same stale credential share one refresh
    round-trip instead of stampeding the IdP.

    Args:
        cred (CredentialDAO): The original stale credential.
        store (CredentialStore): Persistence layer for reading and writing.
        provider_cls (type[OAuthProvider]): Resolved OAuth provider class.

    Returns:
        CredentialDAO: The refreshed credential (and persisted), or the
            already-fresh latest credential when another process refreshed first.
    """
    latest: CredentialDAO = store.load().providers.get(cred.provider, cred)
    if latest.expires_at is not None and not _is_within_expiry_buffer(
        expires_at=latest.expires_at,
    ):
        return latest
    if latest.refresh_token is None:
        return latest
    refreshed: CredentialDAO = await provider_cls().refresh(
        refresh_token=latest.refresh_token,
    )
    store.persist(cred=refreshed)
    log_info(msg=f"refresh_if_stale provider={cred.provider.value} refreshed=true")
    return refreshed


def _is_within_expiry_buffer(*, expires_at: datetime) -> bool:
    """Return True when ``expires_at`` is at or before now+``_EXPIRY_BUFFER_SECONDS``.

    Args:
        expires_at (datetime): UTC expiry timestamp.

    Returns:
        bool: ``True`` if the credential should be refreshed now.
    """
    threshold: datetime = datetime.now(timezone.utc) + timedelta(
        seconds=_EXPIRY_BUFFER_SECONDS,
    )
    return expires_at <= threshold
