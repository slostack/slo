"""Tests for ``CredentialStore`` (02.b.1)."""

import json
import stat
from pathlib import Path

import pytest

from src.auth.credential_dao import (
    AuthType,
    AuthenticationFileDAO,
    CredentialDAO,
    ProviderName,
)
from src.auth.credential_store import CredentialStore, CredentialStoreCorruptError


def _build_openai_credential() -> CredentialDAO:
    """Build a known-good OpenAI API-key row for tests.

    Returns:
        CredentialDAO: Deterministic row used across the test class.
    """
    return CredentialDAO(
        provider=ProviderName.OPENAI,
        auth_type=AuthType.API_KEY,
        access_token="sk-test-fixture",
    )


def _build_anthropic_credential() -> CredentialDAO:
    """Build a known-good Anthropic OAuth row for tests.

    Returns:
        CredentialDAO: Deterministic row used across the test class.
    """
    return CredentialDAO(
        provider=ProviderName.ANTHROPIC,
        auth_type=AuthType.OAUTH,
        access_token="sk-ant-oat01-fixture",
        refresh_token="sk-ant-ort01-fixture",
        subject="user@example.com",
    )


class TestCredentialStoreLoad:
    """``CredentialStore.load`` — file-absent and parse paths."""

    def test_load_returns_empty_envelope_when_file_absent(self, tmp_path: Path) -> None:
        """Missing file → empty envelope, no error."""
        store: CredentialStore = CredentialStore(
            path=tmp_path / "global" / "authentication.json",
        )

        envelope: AuthenticationFileDAO = store.load()

        assert envelope == AuthenticationFileDAO()

    def test_load_returns_parsed_envelope_when_file_present(self, tmp_path: Path) -> None:
        """Valid file → envelope parsed via the DAO."""
        path: Path = tmp_path / "global" / "authentication.json"
        store: CredentialStore = CredentialStore(path=path)
        store.persist(cred=_build_openai_credential())

        envelope: AuthenticationFileDAO = store.load()

        assert ProviderName.OPENAI in envelope.providers
        assert envelope.providers[ProviderName.OPENAI].access_token == "sk-test-fixture"

    def test_load_raises_corrupt_error_on_invalid_json(self, tmp_path: Path) -> None:
        """Garbage on disk → ``CredentialStoreCorruptError``."""
        path: Path = tmp_path / "global" / "authentication.json"
        path.parent.mkdir(parents=True)
        path.write_text("{this is not json")

        store: CredentialStore = CredentialStore(path=path)
        with pytest.raises(CredentialStoreCorruptError):
            store.load()

    def test_load_raises_corrupt_error_on_schema_violation(self, tmp_path: Path) -> None:
        """Wrong shape → ``CredentialStoreCorruptError``."""
        path: Path = tmp_path / "global" / "authentication.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema_version": 1, "providers": "not-a-dict"}))

        store: CredentialStore = CredentialStore(path=path)
        with pytest.raises(CredentialStoreCorruptError):
            store.load()


class TestCredentialStorePersist:
    """``CredentialStore.persist`` — write semantics + mode bits."""

    def test_persist_creates_parent_dir_with_mode_700(self, tmp_path: Path) -> None:
        """Parent dir gets ``0o700`` on first write."""
        path: Path = tmp_path / "global" / "authentication.json"
        store: CredentialStore = CredentialStore(path=path)

        store.persist(cred=_build_openai_credential())

        parent_mode: int = stat.S_IMODE(path.parent.stat().st_mode)
        assert parent_mode == 0o700

    def test_persist_writes_file_with_mode_600(self, tmp_path: Path) -> None:
        """Resulting file is owner-read/write only."""
        path: Path = tmp_path / "global" / "authentication.json"
        store: CredentialStore = CredentialStore(path=path)

        store.persist(cred=_build_openai_credential())

        file_mode: int = stat.S_IMODE(path.stat().st_mode)
        assert file_mode == 0o600

    def test_persist_overwrites_existing_provider_row(self, tmp_path: Path) -> None:
        """Writing twice for the same provider replaces, never appends."""
        path: Path = tmp_path / "global" / "authentication.json"
        store: CredentialStore = CredentialStore(path=path)
        store.persist(cred=_build_openai_credential())
        store.persist(
            cred=CredentialDAO(
                provider=ProviderName.OPENAI,
                auth_type=AuthType.API_KEY,
                access_token="sk-replacement",
            )
        )

        envelope: AuthenticationFileDAO = store.load()

        assert len(envelope.providers) == 1
        assert envelope.providers[ProviderName.OPENAI].access_token == "sk-replacement"

    def test_persist_preserves_other_provider_rows(self, tmp_path: Path) -> None:
        """Adding a second provider does not stomp the first."""
        path: Path = tmp_path / "global" / "authentication.json"
        store: CredentialStore = CredentialStore(path=path)
        store.persist(cred=_build_openai_credential())
        store.persist(cred=_build_anthropic_credential())

        envelope: AuthenticationFileDAO = store.load()

        assert ProviderName.OPENAI in envelope.providers
        assert ProviderName.ANTHROPIC in envelope.providers

    def test_persist_corrects_directory_mode_on_subsequent_write(self, tmp_path: Path) -> None:
        """Re-chmod runs every write so hand-edited modes are corrected."""
        path: Path = tmp_path / "global" / "authentication.json"
        store: CredentialStore = CredentialStore(path=path)
        store.persist(cred=_build_openai_credential())
        path.parent.chmod(0o755)

        store.persist(cred=_build_anthropic_credential())

        parent_mode: int = stat.S_IMODE(path.parent.stat().st_mode)
        assert parent_mode == 0o700


class TestCredentialStoreInit:
    """``CredentialStore.__init__`` — three branches across the path argument."""

    def test_init_uses_explicit_path_when_passed(self, tmp_path: Path) -> None:
        """Explicit ``path=`` argument wins, regardless of cfg."""
        explicit: Path = tmp_path / "explicit" / "authentication.json"
        store: CredentialStore = CredentialStore(path=explicit)

        assert store.path == explicit

    def test_init_uses_cfg_path_when_none_passed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No path argument → ``cfg('SLO_AUTH_FILE')`` is consulted."""
        configured: Path = tmp_path / "from-cfg" / "authentication.json"
        monkeypatch.setattr(
            "src.auth.credential_store.cfg",
            lambda *, key: str(configured) if key == "SLO_AUTH_FILE" else None,
        )

        store: CredentialStore = CredentialStore()

        assert store.path == configured

    def test_init_falls_back_to_empty_path_when_cfg_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When cfg returns ``None``, the store stores ``Path('')``."""
        monkeypatch.setattr(
            "src.auth.credential_store.cfg",
            lambda *, key: None,
        )

        store: CredentialStore = CredentialStore()

        assert store.path == Path("")


class TestCredentialStoreRemove:
    """``CredentialStore.remove`` — present and absent branches."""

    def test_remove_returns_true_when_row_existed(self, tmp_path: Path) -> None:
        """Existing row → removed, returns True."""
        path: Path = tmp_path / "global" / "authentication.json"
        store: CredentialStore = CredentialStore(path=path)
        store.persist(cred=_build_openai_credential())

        result: bool = store.remove(provider=ProviderName.OPENAI)

        assert result is True
        envelope: AuthenticationFileDAO = store.load()
        assert ProviderName.OPENAI not in envelope.providers

    def test_remove_returns_false_when_row_absent(self, tmp_path: Path) -> None:
        """No row → no-op, returns False."""
        path: Path = tmp_path / "global" / "authentication.json"
        store: CredentialStore = CredentialStore(path=path)

        result: bool = store.remove(provider=ProviderName.OPENAI)

        assert result is False
