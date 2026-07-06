"""UserPreferencesStore service — atomic reader/writer for user preferences."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from config.cfg import cfg as _cfg, SLO_HOME as _CFG_SLO_HOME

from src.agents.reasoning_capabilities import ReasoningLevel
from src.agents.slo_agent.preferences.dao import UserPreferencesDAO, UserPreferencesStoreCorruptError

__all__ = ["UserPreferencesStore"]


class UserPreferencesStore:
    """Atomic reader/writer for ``~/.slo/global/preferences.json``.

    This is the only class permitted to read or write the preferences file.
    All writes use temp-file-then-rename to guard against mid-write crashes.
    Directory permissions are ``0700``; file permissions are ``0600``.

    The ``SLO_PREFERENCES_FILE`` environment variable redirects the file
    path — use it in tests to avoid touching real user data.
    """

    _DIR_MODE: int = 0o700
    _FILE_MODE: int = 0o600
    _ENV_KEY: str = "SLO_PREFERENCES_FILE"

    @classmethod
    def _preferences_path(cls) -> Path:
        """Return the canonical preferences file path.

        Checks ``SLO_PREFERENCES_FILE`` first for test overrides, then
        falls back to ``~/.slo/global/preferences.json``.

        Returns:
            Path: Absolute path to the preferences file.
        """
        prefs_override: str | None = _cfg("SLO_PREFERENCES_FILE")
        if prefs_override:
            return Path(prefs_override)
        return _CFG_SLO_HOME / "global" / "preferences.json"

    @classmethod
    def load(cls) -> UserPreferencesDAO:
        """Return persisted preferences, or an empty DAO when the file is absent.

        Returns:
            UserPreferencesDAO: Parsed preferences, or all-``None`` defaults
                when the file does not exist.

        Raises:
            UserPreferencesStoreCorruptError: When the file exists but cannot
                be parsed as JSON or validated against the DAO schema.
        """
        path: Path = cls._preferences_path()
        if not path.exists():
            return UserPreferencesDAO()
        try:
            payload: dict = json.loads(path.read_text(encoding="utf-8"))
            return UserPreferencesDAO.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            raise UserPreferencesStoreCorruptError(path=path) from exc

    @classmethod
    def upsert(
        cls,
        *,
        model_name: Optional[str] = None,
        reasoning_level: Optional[ReasoningLevel] = None,
        model_pool: Optional[str] = None,
    ) -> UserPreferencesDAO:
        """Update one or more preference fields and persist atomically.

        Non-``None`` arguments overwrite their corresponding field.
        ``None`` arguments leave the existing persisted value unchanged.

        Args:
            model_name (Optional[str]): New preferred model name, or ``None``
                to leave the existing value unchanged.
            reasoning_level (Optional[ReasoningLevel]): New preferred reasoning
                level, or ``None`` to leave the existing value unchanged.
            model_pool (Optional[str]): New preferred comma-separated model pool
                (same format as ``SLO_MODEL_POOL``), or ``None`` to leave the
                existing value unchanged.

        Returns:
            UserPreferencesDAO: The updated preferences DAO after the write.
        """
        current: UserPreferencesDAO = cls.load()
        updated: UserPreferencesDAO = UserPreferencesDAO(
            schema_version=current.schema_version,
            default_model_name=(
                model_name if model_name is not None else current.default_model_name
            ),
            default_reasoning_level=(
                reasoning_level
                if reasoning_level is not None
                else current.default_reasoning_level
            ),
            default_model_pool=(
                model_pool if model_pool is not None else current.default_model_pool
            ),
        )
        cls._write(payload=updated)
        return updated

    @classmethod
    def clear(cls) -> bool:
        """Delete the preferences file so defaults apply on next boot.

        Returns:
            bool: ``True`` when the file was deleted, ``False`` when it
                did not exist.
        """
        path: Path = cls._preferences_path()
        if not path.exists():
            return False
        path.unlink()
        return True

    @classmethod
    def _write(cls, *, payload: UserPreferencesDAO) -> None:
        """Serialise ``payload`` and atomically move it into place.

        Creates the parent directory at ``0700`` if missing, writes to
        a ``.tmp`` sibling, ``chmod``s the file to ``0600``, then renames
        into place.

        Args:
            payload (UserPreferencesDAO): The preferences to persist.
        """
        path: Path = cls._preferences_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(cls._DIR_MODE)
        tmp: Path = path.with_suffix(".json.tmp")
        tmp.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        tmp.chmod(cls._FILE_MODE)
        tmp.replace(path)
