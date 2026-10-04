"""Atomic ownership of released and additional-provider credentials (86.b.3).

Released Slo reads only authentication.json. Keep its frozen provider set there;
additional providers use authentication.additional-providers.json beside it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from config.cfg import cfg
from config.logger import log_info, log_warning
from src.auth.credential_dao import (
    RELEASED_CREDENTIAL_PROVIDERS,
    AuthenticationFileDAO,
    CredentialDAO,
    ProviderName,
)

__all__ = ["CredentialStore", "CredentialStoreCorruptError"]


class CredentialStoreCorruptError(RuntimeError):
    """Raised when a credential file is unreadable or fails JSON/schema validation."""

    def __init__(self, *, path: Path) -> None:
        """Carry the path so callers can show it in the user message.

        Args:
            path (Path): The corrupt file.
        """
        super().__init__(f"Credentials file at {path} is not valid JSON or schema.")
        self.path: Path = path


class CredentialStore:
    """The sole owner of both credential files, using the same AuthenticationFileDAO.

    Released providers stay in ``path``; others use ``additional_providers_path``.
    Reads merge owned rows and warn about misfiled rows on every lookup. Writes
    update only the owning file, preserving all other rows, including misfiled ones.
    No automatic cleanup or migration occurs.

    Owns parent mode 0700, file mode 0600 and atomic temp-and-rename writes.
    Constructor or SLO_AUTH_FILE overrides move both files together.

    Both files validate a closed provider enum. Later versions must put providers
    unknown to this version in another sibling file, or rollback breaks lookups
    and fail-closed history redaction. Never widen the released provider set.
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
        """Return the released credential file path. Read-only.

        Returns:
            Path: authentication.json or its constructor/configuration override.
        """
        return self._path

    @property
    def additional_providers_path(self) -> Path:
        """Return the sibling file for providers released Slo does not know.

        Store reads and writes derive this on access so constructor and
        SLO_AUTH_FILE overrides move both files together.

        Returns:
            Path: The released path with .additional-providers before its suffix.
        """
        return self._path.with_name(f"{self._path.stem}.additional-providers{self._path.suffix}")

    def _path_for(self, *, provider: ProviderName) -> Path:
        """Choose the owning file before a provider read or write.

        Args:
            provider (ProviderName): Provider whose row the store is handling.

        Returns:
            Path: Released file for the frozen set, otherwise its sibling.
        """
        if provider in RELEASED_CREDENTIAL_PROVIDERS:
            return self._path
        return self.additional_providers_path

    def load(self) -> AuthenticationFileDAO:
        """Merge owned rows for credential lookups and the authentication screen.

        The resolver also calls this on every protected history write. Misfiled
        rows are ignored with warnings, not moved; move pre-fix OpenRouter rows
        manually before running new Slo so their keys remain known to redaction.

        Returns:
            AuthenticationFileDAO: Owned rows from both files, empty if absent.

        Raises:
            CredentialStoreCorruptError: Either file is unreadable or invalid.
        """
        merged: AuthenticationFileDAO = self._load_owned(path=self._path)
        merged.providers.update(self._load_owned(path=self.additional_providers_path).providers)
        return merged

    def _load_owned(self, *, path: Path) -> AuthenticationFileDAO:
        """Project only owned rows for load, never for an owning-file rewrite.

        Every lookup warns about pre-fix misfiled rows without modifying them.

        Args:
            path (Path): File whose owned rows load needs.

        Returns:
            AuthenticationFileDAO: The envelope restricted to its owned rows.

        Raises:
            CredentialStoreCorruptError: Existing content fails validation.
        """
        envelope: AuthenticationFileDAO = self._read_envelope(path=path)
        owned: dict[ProviderName, CredentialDAO] = {
            provider: cred
            for provider, cred in envelope.providers.items()
            if self._path_for(provider=provider) == path
        }
        self._warn_misfiled(path=path, misfiled=set(envelope.providers) - set(owned))
        return envelope.model_copy(update={"providers": owned})

    @staticmethod
    def _warn_misfiled(*, path: Path, misfiled: set[ProviderName]) -> None:
        """Warn once per misfiled row on every load until manual cleanup.

        The read projection calls this with provider names only, never secrets.

        Args:
            path (Path): File containing the misplaced rows.
            misfiled (set[ProviderName]): Rows excluded from this lookup.
        """
        for provider in sorted(misfiled, key=lambda item: item.value):
            log_warning(msg="credential_store_misfiled_row_ignored", path=str(path), provider=provider.value)

    def _read_envelope(self, *, path: Path) -> AuthenticationFileDAO:
        """Read the full envelope before lookup or an owning-file update.

        Writers retain every row; filtering belongs only to the read projection.

        Args:
            path (Path): Credential file to read.

        Returns:
            AuthenticationFileDAO: Validated envelope, or empty when absent.

        Raises:
            CredentialStoreCorruptError: Existing content fails validation.
        """
        try:
            if not path.exists():
                return AuthenticationFileDAO()
        except OSError as exc:
            raise CredentialStoreCorruptError(path=path) from exc
        return self._parse_existing(path=path)

    def persist(self, *, cred: CredentialDAO) -> None:
        """Insert or replace one row in its owning file after authentication or refresh.

        The auth modal, OpenRouter verification and OAuth refresh use this path.
        It never reads or writes the sibling file; misfiled rows are kept unchanged.

        Args:
            cred (CredentialDAO): The credential to persist. The row key
                is ``cred.provider``.

        Raises:
            CredentialStoreCorruptError: The owning file is unreadable or invalid.
            OSError: The atomic write fails.
        """
        path: Path = self._path_for(provider=cred.provider)
        current: AuthenticationFileDAO = self._read_envelope(path=path)
        current.providers[cred.provider] = cred
        self._atomic_write(path=path, payload=current)
        log_info(msg=f"CredentialStore.persist provider={cred.provider.value}")

    def remove(self, *, provider: ProviderName) -> bool:
        """Delete one owning-file row for a future authentication sign-out action.

        Other rows, including misfiled rows, survive the rewrite unchanged.
        The sibling file is neither read nor written.

        Args:
            provider (ProviderName): Which provider row to remove.

        Returns:
            bool: ``True`` when a row was removed, ``False`` when no row
                existed for ``provider``.

        Raises:
            CredentialStoreCorruptError: The owning file is unreadable or invalid.
            OSError: The atomic write fails.
        """
        path: Path = self._path_for(provider=provider)
        current: AuthenticationFileDAO = self._read_envelope(path=path)
        if provider not in current.providers:
            return False
        del current.providers[provider]
        self._atomic_write(path=path, payload=current)
        log_info(msg=f"CredentialStore.remove provider={provider.value}")
        return True

    @staticmethod
    def _parse_existing(*, path: Path) -> AuthenticationFileDAO:
        """Validate existing content for the full-envelope reader before lookup or update.

        Args:
            path (Path): Credential file to read.

        Returns:
            AuthenticationFileDAO: Validated envelope.

        Raises:
            CredentialStoreCorruptError: When reading, decoding or validation fails.
        """
        try:
            payload: object = json.loads(path.read_text())
            return AuthenticationFileDAO.model_validate(payload)
        except (OSError, ValueError) as exc:
            raise CredentialStoreCorruptError(path=path) from exc

    def _atomic_write(self, *, path: Path, payload: AuthenticationFileDAO) -> None:
        """Activate one private envelope when persist or remove commits an update.

        Args:
            path (Path): Owning credential file to replace.
            payload (AuthenticationFileDAO): Full envelope, including misfiled rows.

        Raises:
            OSError: Directory preparation, staging or replacement fails.
        """
        self._ensure_dir(path=path)
        tmp: Path = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(payload.model_dump_json(indent=2))
        tmp.chmod(self._FILE_MODE)
        tmp.replace(path)

    def _ensure_dir(self, *, path: Path) -> None:
        """Create the parent directory with mode ``0o700`` if missing.

        The atomic writer calls this before staging each update, correcting
        a hand-edited parent mode before the write.

        Args:
            path (Path): Owning credential file about to be written.

        Raises:
            OSError: Directory creation or permission correction fails.
        """
        parent: Path = path.parent
        if not parent.exists():
            parent.mkdir(parents=True, mode=self._DIR_MODE)
            return
        parent.chmod(self._DIR_MODE)
