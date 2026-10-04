"""Filesystem cache and override persistence for the model catalog."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Optional

_fcntl: object | None
try:
    _fcntl = importlib.import_module("fcntl")
except ImportError:  # pragma: no cover - platform import behavior is exercised by subprocess tests.
    _fcntl = None

from config.cfg import SLO_HOME as _CFG_SLO_HOME, cfg as _cfg
from config.logger import log_error, log_info, log_warning

if TYPE_CHECKING:
    from src.agents.slo_agent.history.atomic_io import AtomicWriteOutcomeDAO

from src.agents.model_catalog.dao import (
    ModelCatalogCacheDAO,
    ModelCatalogOverrideDAO,
)

# Released Slo owns model_catalog_cache.json / model_catalog_cache.lock for schema "1".
# Never read, write, rename or delete those names. An incompatible future cache shape
# needs another file name; these provider slices retain schema "2" (86.b.2).
_CACHE_FILE_NAME: str = "model_catalog_cache.v2.json"
_OVERRIDES_FILE_NAME: str = "model_catalog_overrides.json"
_FILE_MODE: int = 0o600
_DIR_MODE: int = 0o700
_REFRESH_LEASE_FILE_NAME: str = "model_catalog_cache.v2.lock"
_REFRESH_LEASE_TIMEOUT_SECONDS: float = 30.0
_REFRESH_LEASE_POLL_SECONDS: float = 0.05


def _lock_path_for(*, cache_path: Path) -> Path:
    """Return a private sibling lock path after rejecting a symlinked parent.

    Args:
        cache_path: Raw catalog cache location selected by the caller.

    Returns:
        Path: Lexical lock-file sibling below the verified cache parent.

    Raises:
        ModelCatalogRefreshLeaseUnavailableError: The target parent is a symlink
            or cannot be prepared as a private directory.
    """
    parent: Path = cache_path.parent
    if parent.is_symlink():
        raise ModelCatalogRefreshLeaseUnavailableError("Model catalog refresh locking is unavailable.")
    try:
        parent.mkdir(parents=True, exist_ok=True)
        resolved_parent: Path = parent.resolve(strict=True)
    except OSError as exc:
        raise ModelCatalogRefreshLeaseUnavailableError(
            "Model catalog refresh locking is unavailable."
        ) from exc
    if resolved_parent != parent.absolute():
        raise ModelCatalogRefreshLeaseUnavailableError("Model catalog refresh locking is unavailable.")
    os.chmod(resolved_parent, _DIR_MODE)
    return resolved_parent / _REFRESH_LEASE_FILE_NAME


def _open_private_lock_file(*, cache_path: Path) -> int:
    """Create and open the refresh lock without following a lock-file symlink.

    Args:
        cache_path: Catalog cache location whose verified parent owns the lock.

    Returns:
        int: Open private lock-file descriptor.

    Raises:
        ModelCatalogRefreshLeaseUnavailableError: The lock path is unsafe or unusable.
    """
    lock_path: Path = _lock_path_for(cache_path=cache_path)
    if _fcntl is None:
        raise ModelCatalogRefreshLeaseUnavailableError("POSIX model catalog refresh locking is unavailable.")
    flags: int = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(lock_path, flags, _FILE_MODE)
        os.chmod(lock_path, _FILE_MODE)
        return descriptor
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise ModelCatalogRefreshLeaseUnavailableError(
            "Model catalog refresh locking is unavailable."
        ) from exc


class ModelCatalogRefreshLeaseUnavailableError(RuntimeError):
    """Signal that this host cannot provide the required POSIX refresh lease."""


def _global_dir() -> Path:
    """Return the private global artifacts directory under SLO_HOME.

    Returns:
        Path: Resolved ``~/.slo/global`` directory.
    """
    return (_CFG_SLO_HOME / "global").expanduser().resolve()


def _ensure_global_dir() -> Path:
    """Create the global artifacts directory with private permissions.

    Returns:
        Path: The created/existing directory.
    """
    global_dir: Path = _global_dir()
    global_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(global_dir, _DIR_MODE)
    return global_dir


class ModelCatalogStore:
    """Read raw provider catalog slices and operator overrides from private storage."""

    @classmethod
    @asynccontextmanager
    async def refresh_lease(
        cls,
        *,
        cache_path: Optional[Path] = None,
    ) -> AsyncIterator[None]:
        """Acquire the process-wide provider-cache refresh lease.

        Args:
            cache_path (Optional[Path]): Private cache path; tests inject a tmp-path target.

        Yields:
            None: Access while this process exclusively refreshes the cache.

        Raises:
            TimeoutError: If another process holds the lease for the full budget.
        """
        if _fcntl is None:
            raise ModelCatalogRefreshLeaseUnavailableError(
                "POSIX model catalog refresh locking is unavailable."
            )
        deadline: float = time.monotonic() + _REFRESH_LEASE_TIMEOUT_SECONDS
        target_path: Path = cache_path or (_ensure_global_dir() / _CACHE_FILE_NAME)
        descriptor: int = await cls._open_refresh_lock_descriptor(cache_path=target_path)
        lock_acquired: bool = False
        try:
            await cls._acquire_refresh_lock(descriptor=descriptor, deadline=deadline)
            lock_acquired = True
            yield
        finally:
            cls._release_refresh_lock(descriptor=descriptor, lock_acquired=lock_acquired)

    @staticmethod
    async def _open_refresh_lock_descriptor(*, cache_path: Path) -> int:
        """Open a lock descriptor and drain a late worker result on cancellation.

        WHAT: Transfers the descriptor returned by the off-loop private-file opener
            to this coroutine or closes it when task cancellation arrives first.
        WHO: ``refresh_lease`` calls this before attempting ``flock``.
        WHEN: Every refresh-lease acquisition, before any lock ownership exists.

        Args:
            cache_path (Path): Verified test-owned or application cache target.

        Returns:
            int: Open descriptor owned by the caller.

        Raises:
            asyncio.CancelledError: If cancellation arrives before descriptor transfer.
            ModelCatalogRefreshLeaseUnavailableError: If the private opener refuses the path.
        """
        open_task: asyncio.Task[int] = asyncio.create_task(
            asyncio.to_thread(_open_private_lock_file, cache_path=cache_path)
        )
        try:
            return await asyncio.shield(open_task)
        except asyncio.CancelledError:
            try:
                descriptor: int = await open_task
            except BaseException:
                raise
            os.close(descriptor)
            raise

    @staticmethod
    async def _acquire_refresh_lock(*, descriptor: int, deadline: float) -> None:
        """Poll a POSIX advisory lock without blocking the event loop.

        Args:
            descriptor (int): Open private lock-file descriptor.
            deadline (float): Monotonic deadline for acquiring the lock.

        Raises:
            TimeoutError: If the lock remains held after the configured budget.
        """
        if _fcntl is None:
            raise ModelCatalogRefreshLeaseUnavailableError(
                "POSIX model catalog refresh locking is unavailable."
            )
        while True:
            try:
                _fcntl.flock(descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)  # type: ignore[attr-defined]
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Model catalog refresh lease is unavailable.")
                await asyncio.sleep(_REFRESH_LEASE_POLL_SECONDS)
            except OSError as exc:
                raise ModelCatalogRefreshLeaseUnavailableError(
                    "POSIX model catalog refresh locking is unavailable."
                ) from exc

    @staticmethod
    def _release_refresh_lock(*, descriptor: int, lock_acquired: bool) -> None:
        """Release and close a refresh lock descriptor.

        Args:
            descriptor (int): Open private lock-file descriptor.
        """
        try:
            if lock_acquired and _fcntl is not None:
                _fcntl.flock(descriptor, _fcntl.LOCK_UN)  # type: ignore[attr-defined]
        except OSError:
            pass
        finally:
            os.close(descriptor)

    @classmethod
    def load_provider_cache(
        cls,
        *,
        override_path: Optional[Path] = None,
    ) -> Optional[ModelCatalogCacheDAO]:
        """Load the provider cache file model_catalog_cache.v2.json (schema "2").

        The catalog calls this during cold reads and refresh. A missing file is
        normal and logs nothing. Other versions log one info line; unreadable or
        invalid files log one warning without a traceback or file contents.
        When no valid cache is available, callers serve seed data until refresh
        rebuilds the provider cache file.

        Args:
            override_path (Optional[Path]): Explicit cache path used by tests.

        Returns:
            Optional[ModelCatalogCacheDAO]: Valid raw cache, or None for a missing,
                other-version, unreadable, or corrupt file.
        """
        cache_path: Path = override_path or (_global_dir() / _CACHE_FILE_NAME)
        if not cache_path.exists():
            return None
        try:
            raw_data: object = json.loads(cache_path.read_text(encoding="utf-8"))
            if not isinstance(raw_data, dict) or raw_data.get("schema_version") != "2":
                log_info(msg="model_catalog_cache_schema_ignored", path=str(cache_path))
                return None
            return ModelCatalogCacheDAO.model_validate(raw_data)
        except (json.JSONDecodeError, OSError, ValueError):
            log_warning(msg="model_catalog_cache_load_failed", path=str(cache_path))
            return None

    @classmethod
    def write_provider_cache(
        cls,
        *,
        cache: ModelCatalogCacheDAO,
        override_path: Optional[Path] = None,
    ) -> "AtomicWriteOutcomeDAO":
        """Persist raw provider slices before catalog publication.

        Args:
            cache (ModelCatalogCacheDAO): Raw schema-two provider-slice envelope.
            override_path (Optional[Path]): Explicit cache path used by tests.

        Returns:
            AtomicWriteOutcomeDAO: Commit state from the shared atomic writer.
        """
        cache_path: Path = override_path or (_global_dir() / _CACHE_FILE_NAME)
        from src.agents.slo_agent.history.atomic_io import AtomicFileWriter

        return AtomicFileWriter.write_text_with_outcome(
            path=cache_path,
            text=cache.model_dump_json(indent=2),
            private=True,
        )

    @classmethod
    def load_overrides(
        cls,
        *,
        override_path: Optional[Path] = None,
    ) -> list[ModelCatalogOverrideDAO]:
        """Load operator overrides from the configured file path.

        Args:
            override_path (Optional[Path]): Optional explicit overrides path for tests.

        Returns:
            list[ModelCatalogOverrideDAO]: Parsed overrides, or an empty list when the
                file is missing or invalid.
        """
        overrides_path: Path = override_path or cls.overrides_path()
        if not overrides_path.exists():
            return []
        try:
            raw_text: str = overrides_path.read_text(encoding="utf-8")
            raw_data: list = json.loads(raw_text)
            if not isinstance(raw_data, list):
                log_error(
                    msg="model_catalog_overrides_invalid_format",
                    path=str(overrides_path),
                )
                return []
            return [ModelCatalogOverrideDAO.model_validate(item) for item in raw_data]
        except (json.JSONDecodeError, OSError, ValueError):
            log_error(msg="model_catalog_overrides_load_failed", path=str(overrides_path))
            return []

    @classmethod
    def overrides_path(cls) -> Path:
        """Return the configured overrides file path.

        ``SLO_MODEL_CATALOG_OVERRIDES_FILE`` overrides the default location.

        Returns:
            Path: Resolved overrides path.
        """
        env_override: Optional[str] = _cfg("SLO_MODEL_CATALOG_OVERRIDES_FILE")
        if env_override:
            return Path(env_override).expanduser().resolve()
        return _global_dir() / _OVERRIDES_FILE_NAME
