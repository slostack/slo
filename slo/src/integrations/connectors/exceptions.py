"""Typed exceptions for the connector credential subsystem (25.a.1)."""
from __future__ import annotations

from pathlib import Path

__all__ = [
    "ConnectorCredentialsRequiredError",
    "ConnectorCredentialStoreCorruptError",
]


class ConnectorCredentialStoreCorruptError(RuntimeError):
    """Raised when an on-disk connector credential file fails to parse.

    Attributes:
        path (Path): The corrupt file's location on disk.
    """

    def __init__(self, *, path: Path) -> None:
        """Carry the path so callers can include it in user-facing messages.

        Args:
            path (Path): The corrupt credential file.
        """
        super().__init__(f"Connector credential file at {path} is not valid JSON or schema.")
        self.path: Path = path


class ConnectorCredentialsRequiredError(RuntimeError):
    """Raised when a connector tool needs credentials that have not been provided.

    This exception is the signal that lets a TUI session open the interactive
    connector credential screen.  It carries enough context for the screen to
    pre-populate labels and know where the saved file will go.

    Attributes:
        provider (str): The connector provider name (e.g. ``"atlassian"``).
        required_fields (list[str]): The field names the operator needs to fill.
        credentials_path (Path): Where the credential will be persisted on save.
    """

    def __init__(
        self,
        *,
        provider: str,
        required_fields: list[str],
        credentials_path: Path,
    ) -> None:
        """Carry provider identity, field list, and target path.

        Args:
            provider (str): The connector provider name.
            required_fields (list[str]): Fields the operator must supply.
            credentials_path (Path): Filesystem path for the credential file.
        """
        super().__init__(
            f"Connector credentials required for provider '{provider}'. "
            f"Missing fields: {required_fields}."
        )
        self.provider: str = provider
        self.required_fields: list[str] = required_fields
        self.credentials_path: Path = credentials_path
