"""Atomic read/write of ``~/.slo/global/authentication.json`` (02.b.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from config.cfg import cfg
from config.logger import log_info
from src.auth.credential_dao import (
    AuthenticationFileDAO,
    CredentialDAO,
    ProviderName,
)

__all__ = ["CredentialStore", "CredentialStoreCorruptError"]


class CredentialStoreCorruptError(RuntimeError):
    """Raised when the on-disk authentication file fails schema validation."""

    def __init__(self, *, path: Path) -> None:
        """Carry the path so callers can show it in the user message.

        Args:
            path (Path): The corrupt file.
        """
        super().__init__(f"Credentials file at {path} is not valid JSON or schema.")
        self.path: Path = path


class CredentialStore:
    """The only object permitted to read or write the credentials file.

    Owns directory creation, file mode (``0o600``), parent directory mode
    (``0o700``), atomic temp-and-rename writes, and schema validation
    via ``AuthenticationFileDAO``.

    Single in-process instance is expected; the file path is overridable
    via constructor or via ``SLO_AUTH_FILE``.
    """

    _DIR_MODE: int = 0o700
    _FILE_MODE: int = 0o600

    def __init__(self, *, path: Optional[Path] = None) -> None:
        """Default to ``cfg("SLO_AUTH_FILE")``; override for tests.

        Args:
            path (Optional[Path]): Override file location. ``None``
                resolves to ``cfg("SLO_AUTH_FILE")``.
        """
        resolved: Optional[str] = cfg(key="SLO_AUTH_FILE") if path is None else None
        self._path: Path = path or Path(resolved or "")

    @property
    def path(self) -> Path:
        """Return the resolved on-disk path. Read-only.

        Returns:
            Path: Absolute path to the credentials file.
        """
        return self._path

    def load(self) -> AuthenticationFileDAO:
        """Return the persisted envelope, or an empty one if absent.

        Used by ``CredentialResolver._from_store`` (02.b.2) on every
        agent build and by the modal's success screen (02.b.5).

        Returns:
            AuthenticationFileDAO: Parsed file contents; empty when the
                file does not exist.

        Raises:
            CredentialStoreCorruptError: When the file exists but does
                not parse or validate.
        """
        if not self._path.exists():
            return AuthenticationFileDAO()
        return self._parse_existing()

    def persist(self, *, cred: CredentialDAO) -> None:
        """Insert-or-replace the row for ``cred.provider`` atomically.

        Called by the modal (02.b.5) after a successful OAuth or paste
        flow.

        Args:
            cred (CredentialDAO): The credential to persist. The row key
                is ``cred.provider``.
        """
        current: AuthenticationFileDAO = self.load()
        current.providers[cred.provider] = cred
        self._atomic_write(payload=current)
        log_info(msg=f"CredentialStore.persist provider={cred.provider.value}")

    def remove(self, *, provider: ProviderName) -> bool:
        """Delete the row for ``provider`` and persist the result.

        Called by a future ``/auth`` sign-out action (surface needed by
        02.b.5 even if not exercised in v1).

        Args:
            provider (ProviderName): Which provider row to remove.

        Returns:
            bool: ``True`` when a row was removed, ``False`` when no row
                existed for ``provider``.
        """
        current: AuthenticationFileDAO = self.load()
        if provider not in current.providers:
            return False
        del current.providers[provider]
        self._atomic_write(payload=current)
        log_info(msg=f"CredentialStore.remove provider={provider.value}")
        return True

    def _parse_existing(self) -> AuthenticationFileDAO:
        """Read the file and validate it against the schema.

        Returns:
            AuthenticationFileDAO: Validated envelope.

        Raises:
            CredentialStoreCorruptError: When parsing or validation fails.
        """
        try:
            payload: dict = json.loads(self._path.read_text())
        except json.JSONDecodeError as exc:
            raise CredentialStoreCorruptError(path=self._path) from exc
        try:
            return AuthenticationFileDAO.model_validate(payload)
        except ValueError as exc:
            raise CredentialStoreCorruptError(path=self._path) from exc

    def _atomic_write(self, *, payload: AuthenticationFileDAO) -> None:
        """Serialise ``payload`` and atomically move it into place.

        Args:
            payload (AuthenticationFileDAO): Envelope to write.
        """
        self._ensure_dir()
        tmp: Path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(payload.model_dump_json(indent=2))
        tmp.chmod(self._FILE_MODE)
        tmp.replace(self._path)

    def _ensure_dir(self) -> None:
        """Create the parent directory with mode ``0o700`` if missing.

        Re-chmods the directory on every call so a hand-edited mode is
        corrected before the next write.
        """
        parent: Path = self._path.parent
        if not parent.exists():
            parent.mkdir(parents=True, mode=self._DIR_MODE)
            return
        parent.chmod(self._DIR_MODE)
