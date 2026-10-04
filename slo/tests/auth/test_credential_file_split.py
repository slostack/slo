"""Real-file credential ownership contracts for released and additional providers (86.b.3)."""

import json
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from src.auth.credential_dao import (
    RELEASED_CREDENTIAL_PROVIDERS,
    AuthType,
    AuthenticationFileDAO,
    CredentialDAO,
    ProviderName,
)
from src.auth.credential_store import CredentialStore, CredentialStoreCorruptError


def _credential(*, provider: ProviderName) -> CredentialDAO:
    """Build a synthetic row for store tests, never a usable provider credential."""
    return CredentialDAO(
        provider=provider, auth_type=AuthType.API_KEY, access_token=f"{provider.value}-synthetic"
    )


@pytest.fixture
def store(tmp_path: Path) -> CredentialStore:
    """Build the real store after proving its complete write namespace is test-owned."""
    directory = tmp_path / "global"
    for name in ("authentication.json", "authentication.additional-providers.json"):
        path = directory / name
        assert path.resolve().is_relative_to(tmp_path.resolve())
        assert path.with_suffix(".json.tmp").resolve().is_relative_to(tmp_path.resolve())
    return CredentialStore(path=directory / "authentication.json")


def test_persist_when_openrouter_leaves_released_file_absent(store: CredentialStore) -> None:
    """Saving OpenRouter creates only a private sibling with the same envelope shape."""
    store.persist(cred=_credential(provider=ProviderName.OPENROUTER))

    assert not store.path.exists()
    additional = store.path.parent / "authentication.additional-providers.json"
    envelope = AuthenticationFileDAO.model_validate_json(additional.read_text())
    assert envelope.schema_version == 1
    assert set(envelope.providers) == {ProviderName.OPENROUTER}
    assert stat.S_IMODE(additional.stat().st_mode) == 0o600
    assert stat.S_IMODE(additional.parent.stat().st_mode) == 0o700


@pytest.mark.parametrize(argnames="provider", argvalues=list(ProviderName)[:3])
def test_persist_when_released_provider_keeps_other_file_absent(
    store: CredentialStore, provider: ProviderName
) -> None:
    """Each released provider stays readable by the old closed-enum reader."""
    store.persist(cred=_credential(provider=provider))

    assert set(json.loads(store.path.read_text())["providers"]) == {provider.value}
    assert not (store.path.parent / "authentication.additional-providers.json").exists()


def test_persist_when_openrouter_leaves_released_bytes_and_mtime_unchanged(store: CredentialStore) -> None:
    """Adding an additional provider does not rewrite the released envelope."""
    store.persist(cred=_credential(provider=ProviderName.ANTHROPIC))
    before = (store.path.read_bytes(), store.path.stat().st_mtime_ns)

    store.persist(cred=_credential(provider=ProviderName.OPENROUTER))

    assert (store.path.read_bytes(), store.path.stat().st_mtime_ns) == before


def _write_envelope(*, path: Path, root: Path, envelope: AuthenticationFileDAO) -> None:
    """Seed a pre-fix envelope only after checking its resolved test-root boundary."""
    assert path.resolve().is_relative_to(root.resolve())
    assert path.parent.resolve().is_relative_to(root.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data=envelope.model_dump_json(indent=2), encoding="utf-8")


def test_load_when_both_files_hold_owned_rows_merges_them(store: CredentialStore) -> None:
    """Released and additional credentials remain available to one store lookup."""
    credentials = {provider: _credential(provider=provider) for provider in ProviderName}
    for credential in credentials.values():
        store.persist(cred=credential)

    assert store.load().providers == credentials


@pytest.mark.parametrize(argnames="additional", argvalues=[False, True])
def test_load_when_rows_are_misfiled_ignores_and_warns_on_every_lookup(
    store: CredentialStore, tmp_path: Path, caplog: pytest.LogCaptureFixture, additional: bool
) -> None:
    """Read projection never repairs pre-fix rows or logs their credential values."""
    path = store.additional_providers_path if additional else store.path
    misplaced = list(ProviderName)[:3] if additional else [ProviderName.OPENROUTER]
    envelope = AuthenticationFileDAO(providers={p: _credential(provider=p) for p in misplaced})
    _write_envelope(path=path, root=tmp_path, envelope=envelope)
    before = (path.read_bytes(), path.stat().st_mtime_ns)

    for _ in range(2):
        assert store.load().providers == {}

    warnings = [r for r in caplog.records if r.message == "credential_store_misfiled_row_ignored"]
    assert len(warnings) == 2 * len(misplaced)
    assert [r.__dict__["provider"] for r in warnings] == sorted(p.value for p in misplaced) * 2
    assert all(
        r.__dict__["path"] == str(path) and r.levelname == "WARNING" and r.exc_info is None for r in warnings
    )
    assert "synthetic" not in caplog.text
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    other = store.path if additional else store.additional_providers_path
    assert not other.exists()


def test_load_when_neither_file_exists_returns_empty_without_creating_files(store: CredentialStore) -> None:
    """An unconfigured store has no read-side filesystem effects."""
    assert store.load() == AuthenticationFileDAO()
    assert not store.path.parent.exists()


@pytest.mark.parametrize(argnames="additional", argvalues=[False, True])
@pytest.mark.parametrize(argnames="operation", argvalues=["persist", "remove"])
def test_write_when_misfiled_rows_exist_preserves_them_and_the_sibling(
    store: CredentialStore, tmp_path: Path, additional: bool, operation: str
) -> None:
    """Owning-file updates retain all other values and never read a corrupt sibling."""
    path = store.additional_providers_path if additional else store.path
    other = store.path if additional else store.additional_providers_path
    owner = ProviderName.OPENROUTER if additional else ProviderName.ANTHROPIC
    misplaced = ProviderName.OPENAI if additional else ProviderName.OPENROUTER
    envelope = AuthenticationFileDAO(
        schema_version=7,
        providers={p: _credential(provider=p) for p in (owner, misplaced)},
    )
    _write_envelope(path=path, root=tmp_path, envelope=envelope)
    assert other.resolve().is_relative_to(tmp_path.resolve())
    other.write_text(data="{synthetic-corrupt-sibling", encoding="utf-8")
    before = (other.read_bytes(), other.stat().st_mtime_ns)
    replacement = _credential(provider=owner).model_copy(update={"access_token": "replacement-synthetic"})

    if operation == "persist":
        store.persist(cred=replacement)
    else:
        assert store.remove(provider=owner) is True

    written = AuthenticationFileDAO.model_validate_json(path.read_text())
    expected = {misplaced: envelope.providers[misplaced]}
    if operation == "persist":
        expected[owner] = replacement
    assert written.providers == expected
    assert written.schema_version == 7
    assert (other.read_bytes(), other.stat().st_mtime_ns) == before
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(argnames="provider", argvalues=list(ProviderName))
def test_remove_when_owned_row_exists_changes_only_owning_file(
    store: CredentialStore, provider: ProviderName
) -> None:
    """Removing each provider leaves all remaining rows available through merged load."""
    for item in ProviderName:
        store.persist(cred=_credential(provider=item))
    other = store.path if provider == ProviderName.OPENROUTER else store.additional_providers_path
    before = (other.read_bytes(), other.stat().st_mtime_ns)

    assert store.remove(provider=provider) is True

    assert set(store.load().providers) == set(ProviderName) - {provider}
    assert (other.read_bytes(), other.stat().st_mtime_ns) == before


@pytest.mark.parametrize(argnames="provider", argvalues=list(ProviderName))
def test_remove_when_owning_file_absent_never_removes_misfiled_row(
    store: CredentialStore, tmp_path: Path, provider: ProviderName
) -> None:
    """A misplaced row is not a removal target and cannot cause creation of an owning file."""
    other = store.path if provider == ProviderName.OPENROUTER else store.additional_providers_path
    own = store.additional_providers_path if provider == ProviderName.OPENROUTER else store.path
    _write_envelope(
        path=other,
        root=tmp_path,
        envelope=AuthenticationFileDAO(providers={provider: _credential(provider=provider)}),
    )
    before = (other.read_bytes(), other.stat().st_mtime_ns)

    assert store.remove(provider=provider) is False

    assert (other.read_bytes(), other.stat().st_mtime_ns) == before
    assert not own.exists()


@pytest.mark.parametrize(argnames="additional", argvalues=[False, True])
@pytest.mark.parametrize(
    argnames="content",
    argvalues=[
        b"{not-json",
        b'{"providers": "wrong-shape"}',
        b"\xff",
        b'{"providers":{"future_provider":{"provider":"future_provider",'
        b'"auth_type":"api_key","access_token":"future-synthetic"}}}',
    ],
    ids=["invalid-json", "invalid-schema", "invalid-encoding", "future-provider"],
)
@pytest.mark.parametrize(argnames="operation", argvalues=["load", "persist", "remove"])
def test_operation_when_owning_file_invalid_fails_closed_without_rewrite(
    store: CredentialStore, tmp_path: Path, additional: bool, content: bytes, operation: str
) -> None:
    """Both closed-enum files reject corruption and unknown future providers identically."""
    path = store.additional_providers_path if additional else store.path
    provider = ProviderName.OPENROUTER if additional else ProviderName.OPENAI
    assert path.resolve().is_relative_to(tmp_path.resolve())
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    before = (path.read_bytes(), path.stat().st_mtime_ns)

    with pytest.raises(CredentialStoreCorruptError) as raised:
        if operation == "load":
            store.load()
        elif operation == "persist":
            store.persist(cred=_credential(provider=provider))
        else:
            store.remove(provider=provider)

    assert raised.value.path == path
    assert "synthetic" not in str(raised.value)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize(argnames="additional", argvalues=[False, True])
@pytest.mark.parametrize(argnames="operation", argvalues=["load", "persist", "remove"])
def test_operation_when_file_read_is_denied_raises_corrupt_error(
    store: CredentialStore, tmp_path: Path, additional: bool, operation: str
) -> None:
    """An OS read refusal is not credential absence, including when tests run as root."""
    path = store.additional_providers_path if additional else store.path
    provider = ProviderName.OPENROUTER if additional else ProviderName.OPENAI
    _write_envelope(path=path, root=tmp_path, envelope=AuthenticationFileDAO())
    before = path.read_bytes()

    with patch.object(target=Path, attribute="read_text", side_effect=PermissionError("synthetic-denial")):
        with pytest.raises(CredentialStoreCorruptError) as raised:
            if operation == "load":
                store.load()
            elif operation == "persist":
                store.persist(cred=_credential(provider=provider))
            else:
                store.remove(provider=provider)

    assert raised.value.path == path
    assert "synthetic-denial" not in str(raised.value)
    assert path.read_bytes() == before


@pytest.mark.parametrize(argnames="additional", argvalues=[False, True])
def test_load_when_file_stat_is_denied_raises_corrupt_error(store: CredentialStore, additional: bool) -> None:
    """An inaccessible parent directory cannot be treated as an absent credentials file."""
    path = store.additional_providers_path if additional else store.path
    with patch.object(
        target=Path,
        attribute="exists",
        side_effect=(
            [False, PermissionError("synthetic-stat-denial")]
            if additional
            else PermissionError("synthetic-stat-denial")
        ),
    ):
        with pytest.raises(CredentialStoreCorruptError) as raised:
            store.load()
    assert raised.value.path == path


def test_released_credential_providers_when_compared_to_release_are_frozen() -> None:
    """The compatibility routing set never grows with the current provider enum."""
    assert isinstance(RELEASED_CREDENTIAL_PROVIDERS, frozenset)
    assert {provider.value for provider in RELEASED_CREDENTIAL_PROVIDERS} == {
        "anthropic",
        "openai",
        "kimi_for_coding",
    }


@pytest.mark.parametrize(argnames="filename", argvalues=["authentication.json", "custom.data", "no-suffix"])
def test_additional_providers_path_when_env_overridden_is_a_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str
) -> None:
    """An SLO_AUTH_FILE override moves both credential files without creating either."""
    path = tmp_path / filename
    monkeypatch.setenv(name="SLO_AUTH_FILE", value=str(path))
    configured = CredentialStore()
    assert configured.path == path
    assert configured.additional_providers_path == path.with_name(
        f"{path.stem}.additional-providers{path.suffix}"
    )
    assert list(tmp_path.iterdir()) == []


def test_persist_when_additional_file_mode_changed_restores_private_modes(
    store: CredentialStore, tmp_path: Path
) -> None:
    """An overwrite corrects permissions and round-trips the replacement credential."""
    store.persist(cred=_credential(provider=ProviderName.OPENROUTER))
    path = store.additional_providers_path
    assert path.resolve().is_relative_to(tmp_path.resolve())
    path.chmod(0o644)
    path.parent.chmod(0o755)
    replacement = _credential(provider=ProviderName.OPENROUTER)
    store.persist(cred=replacement)
    assert store.load().providers == {ProviderName.OPENROUTER: replacement}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


@pytest.mark.parametrize(argnames="broken", argvalues=["json", "future-provider"])
async def test_history_write_when_additional_file_corrupt_refuses_unchecked_text(
    store: CredentialStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, broken: str
) -> None:
    """Real store-to-resolver-to-history serialization stays redacted and fails closed."""
    from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
    from src.auth.credential_resolver import CredentialResolver

    monkeypatch.setenv(name="SLO_AUTH_FILE", value=str(store.path))
    monkeypatch.delenv(name="SLO_OPENROUTER_API_KEY", raising=False)
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    credential = _credential(provider=ProviderName.OPENROUTER)
    store.persist(cred=credential)
    history = FilesystemSessionHistoryStore(root=root)
    await history.ensure_session(session_id="split", workdir=tmp_path, model_name="gpt-5.4")
    event = SessionHistoryEventDAO(
        session_id="split",
        kind="assistant_message",
        payload=SessionHistoryEventPayloadDAO(content=credential.access_token),
    )
    with CredentialResolver.bind_operation_credential(credential=None):
        await history.append_event(event=event)
        loaded = await history.load_events(session_id="split")
        assert loaded[-1].payload.content == "[REDACTED]"
        before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
        assert all(credential.access_token.encode() not in value for value in before.values())
        path = store.additional_providers_path
        assert path.resolve().is_relative_to(tmp_path.resolve())
        path.write_text(
            data="{invalid" if broken == "json" else '{"providers":{"future_provider":{}}}',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="serialization refused") as raised:
            await history.append_event(event=event)
    assert raised.value.__suppress_context__
    assert credential.access_token not in str(raised.value)
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize(argnames="provider", argvalues=list(ProviderName))
def test_load_when_both_files_contain_same_provider_uses_only_owned_row(
    store: CredentialStore, tmp_path: Path, provider: ProviderName
) -> None:
    """A misplaced duplicate never shadows the owning file, regardless of merge order."""
    owned = _credential(provider=provider)
    misplaced = owned.model_copy(update={"access_token": "misplaced-synthetic"})
    other = store.path if provider == ProviderName.OPENROUTER else store.additional_providers_path
    _write_envelope(
        path=other, root=tmp_path, envelope=AuthenticationFileDAO(providers={provider: misplaced})
    )
    store.persist(cred=owned)
    assert store.load().providers == {provider: owned}


@pytest.mark.parametrize(argnames="additional", argvalues=[False, True])
def test_remove_when_row_absent_in_existing_file_does_not_rewrite(
    store: CredentialStore, tmp_path: Path, additional: bool
) -> None:
    """A no-op remove leaves the existing envelope and timestamp untouched."""
    path = store.additional_providers_path if additional else store.path
    provider = ProviderName.OPENROUTER if additional else ProviderName.OPENAI
    _write_envelope(path=path, root=tmp_path, envelope=AuthenticationFileDAO())
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    assert store.remove(provider=provider) is False
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize(argnames="provider", argvalues=list(ProviderName))
def test_persist_when_atomic_replace_fails_keeps_original_file(
    store: CredentialStore, provider: ProviderName
) -> None:
    """A failed activation cannot corrupt the previously committed owning envelope."""
    store.persist(cred=_credential(provider=provider))
    path = store.additional_providers_path if provider == ProviderName.OPENROUTER else store.path
    before = path.read_bytes()
    with patch.object(target=Path, attribute="replace", side_effect=OSError("synthetic-write-refusal")):
        with pytest.raises(OSError, match="synthetic-write-refusal"):
            store.persist(cred=_credential(provider=provider))
    assert path.read_bytes() == before
    assert stat.S_IMODE(path.with_suffix(".json.tmp").stat().st_mode) == 0o600
