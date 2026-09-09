"""Atomic per-provider connector credential store (25.a.1).

Each connector provider gets its own file under ``~/.slo/connectors/``.
No provider's credentials touch another provider's file.  All writes are
atomic (temp-file + rename) to guard against mid-write crashes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from config.cfg import cfg as _cfg, SLO_HOME as _CFG_SLO_HOME
from src.integrations.connectors.exceptions import ConnectorCredentialStoreCorruptError

if TYPE_CHECKING:
    from src.integrations.connectors.credentials import (
        ConnectorCredentialDAO,
        ConnectorProviderName,
    )

__all__ = ["ConnectorCredentialStore"]


class ConnectorCredentialStore:
    """Atomic per-provider credential store under ``~/.slo/connectors/``.

    This is the only class permitted to read or write connector credential
    files.  Callers should not construct filesystem paths directly.

    Class attributes:
        _ROOT (Path): Root directory for all connector credential files.
            Overridable via the ``SLO_CONNECTORS_DIR`` environment variable
            for tests.
        _DIR_MODE (int): Octal mode for credential directories (``0o700``).
        _FILE_MODE (int): Octal mode for credential files (``0o600``).
    """

    _DIR_MODE: int = 0o700
    _FILE_MODE: int = 0o600

    @classmethod
    def _root(cls) -> Path:
        """Return the root directory for connector credentials.

        Checks ``SLO_CONNECTORS_DIR`` first so tests can redirect writes.

        Returns:
            Path: Absolute path to the connectors root directory.
        """
        connectors_dir: str | None = _cfg("SLO_CONNECTORS_DIR")
        if connectors_dir:
            return Path(connectors_dir)
        return _CFG_SLO_HOME / "connectors"

    @classmethod
    def credentials_path(
        cls,
        *,
        provider: "ConnectorProviderName",
    ) -> Path:
        """Return the canonical credentials file path for one provider.

        Args:
            provider (ConnectorProviderName): The connector provider.

        Returns:
            Path: Full filesystem path to ``credentials.json`` for the provider.
        """
        return cls._root() / provider.value / "credentials.json"

    @classmethod
    def load(
        cls,
        *,
        provider: "ConnectorProviderName",
    ) -> Optional["ConnectorCredentialDAO"]:
        """Load one provider's stored credentials when the file is present.

        Returns ``None`` when no credential file exists for the provider.
        Raises ``ConnectorCredentialStoreCorruptError`` when the file exists
        but cannot be parsed.

        Args:
            provider (ConnectorProviderName): Provider whose credentials to load.

        Returns:
            Optional[ConnectorCredentialDAO]: The stored credentials, or ``None``.

        Raises:
            ConnectorCredentialStoreCorruptError: When the file is malformed.
        """
        path: Path = cls.credentials_path(provider=provider)
        if not path.exists():
            return None

        # Deferred import avoids the circular dependency between store.py
        # and credentials.py (which imports store.py).
        from src.integrations.connectors.credentials import ConnectorCredentialDAO  # noqa: PLC0415

        try:
            payload: dict = json.loads(path.read_text(encoding="utf-8"))
            return ConnectorCredentialDAO.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorCredentialStoreCorruptError(path=path) from exc

    @classmethod
    def upsert(
        cls,
        *,
        credential: "ConnectorCredentialDAO",
    ) -> None:
        """Atomically insert or replace one provider's credential file.

        Writes to a ``.tmp`` sibling first, then renames so a crash during
        the write never leaves a partially-written credential file.

        Args:
            credential (ConnectorCredentialDAO): The credential to persist.
        """
        path: Path = cls.credentials_path(provider=credential.provider)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(cls._DIR_MODE)

        tmp: Path = path.with_suffix(".json.tmp")
        tmp.write_text(credential.model_dump_json(indent=2), encoding="utf-8")
        tmp.chmod(cls._FILE_MODE)
        tmp.replace(path)
