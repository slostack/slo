"""Filesystem cache and override persistence for the model catalog."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.cfg import SLO_HOME as _CFG_SLO_HOME, cfg as _cfg
from config.logger import log_error, log_info
from src.agents.model_catalog.dao import (
    ModelCatalogOverrideDAO,
    ModelCatalogSnapshotDAO,
)

_CACHE_FILE_NAME: str = "model_catalog_cache.json"
_OVERRIDES_FILE_NAME: str = "model_catalog_overrides.json"
_FILE_MODE: int = 0o600
_DIR_MODE: int = 0o700
_CACHE_TTL_SECONDS: int = 3_600


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
    """Read and write the merged model catalog snapshot and operator overrides."""

    @classmethod
    def load_cache(
        cls,
        *,
        override_path: Optional[Path] = None,
    ) -> Optional[ModelCatalogSnapshotDAO]:
        """Load the cached snapshot if it exists and is valid.

        Args:
            override_path (Optional[Path]): Optional explicit cache path for tests.

        Returns:
            Optional[ModelCatalogSnapshotDAO]: Validated snapshot, or ``None`` when
                the cache is missing, stale, or invalid.
        """
        cache_path: Path = override_path or (_ensure_global_dir() / _CACHE_FILE_NAME)
        if not cache_path.exists():
            return None
        try:
            raw_text: str = cache_path.read_text(encoding="utf-8")
            raw_data: dict = json.loads(raw_text)
            snapshot: ModelCatalogSnapshotDAO = ModelCatalogSnapshotDAO.model_validate(raw_data)
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            log_error(
                msg="model_catalog_cache_load_failed",
                path=str(cache_path),
                error=str(exc),
            )
            return None
        if snapshot.schema_version != "1":
            log_info(
                msg="model_catalog_cache_schema_mismatch",
                schema_version=snapshot.schema_version,
            )
            return None
        return snapshot

    @classmethod
    def write_cache(
        cls,
        *,
        snapshot: ModelCatalogSnapshotDAO,
        override_path: Optional[Path] = None,
    ) -> None:
        """Persist a snapshot atomically with private permissions.

        Args:
            snapshot (ModelCatalogSnapshotDAO): Snapshot to persist.
            override_path (Optional[Path]): Optional explicit destination path for tests.
        """
        cache_path: Path = override_path or (_ensure_global_dir() / _CACHE_FILE_NAME)
        temp_path: Path = cache_path.with_suffix(f".{os.getpid()}.tmp")
        raw_text: str = snapshot.model_dump_json(indent=2)
        try:
            temp_path.write_text(raw_text, encoding="utf-8")
            os.chmod(temp_path, _FILE_MODE)
            os.replace(temp_path, cache_path)
            log_info(msg="model_catalog_cache_written", path=str(cache_path))
        except OSError as exc:
            log_error(
                msg="model_catalog_cache_write_failed",
                path=str(cache_path),
                error=str(exc),
            )
            raise

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
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            log_error(
                msg="model_catalog_overrides_load_failed",
                path=str(overrides_path),
                error=str(exc),
            )
            return []

    @classmethod
    def is_cache_fresh(
        cls,
        *,
        snapshot: ModelCatalogSnapshotDAO,
    ) -> bool:
        """Return True when the snapshot was generated within the cache TTL.

        Args:
            snapshot (ModelCatalogSnapshotDAO): Loaded snapshot to evaluate.

        Returns:
            bool: True when the snapshot is fresh, False when stale or undated.
        """
        try:
            generated_at: datetime = datetime.fromisoformat(snapshot.generated_at)
        except ValueError:
            return False
        age_seconds: float = (datetime.now(tz=timezone.utc) - generated_at).total_seconds()
        return age_seconds <= _CACHE_TTL_SECONDS

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
        return _ensure_global_dir() / _OVERRIDES_FILE_NAME
