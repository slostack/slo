"""Tests for connector credential exceptions (25.a.1)."""

from pathlib import Path

from src.integrations.connectors.exceptions import (
    ConnectorCredentialStoreCorruptError,
    ConnectorCredentialsRequiredError,
)


class TestConnectorCredentialStoreCorruptError:
    """``ConnectorCredentialStoreCorruptError`` carries the corrupt path."""

    def test_message_contains_path(self) -> None:
        path: Path = Path("/tmp/test/credentials.json")
        exc = ConnectorCredentialStoreCorruptError(path=path)
        assert str(path) in str(exc)

    def test_path_attribute_is_set(self) -> None:
        path: Path = Path("/tmp/test/credentials.json")
        exc = ConnectorCredentialStoreCorruptError(path=path)
        assert exc.path == path


class TestConnectorCredentialsRequiredError:
    """``ConnectorCredentialsRequiredError`` carries provider, fields, and path."""

    def test_attributes_match_constructor_args(self) -> None:
        path: Path = Path("/tmp/atlassian/credentials.json")
        exc = ConnectorCredentialsRequiredError(
            provider="atlassian",
            required_fields=["base_url", "username", "token"],
            credentials_path=path,
        )
        assert exc.provider == "atlassian"
        assert exc.required_fields == ["base_url", "username", "token"]
        assert exc.credentials_path == path

    def test_message_mentions_provider(self) -> None:
        exc = ConnectorCredentialsRequiredError(
            provider="atlassian",
            required_fields=["token"],
            credentials_path=Path("/tmp/credentials.json"),
        )
        assert "atlassian" in str(exc).lower()
