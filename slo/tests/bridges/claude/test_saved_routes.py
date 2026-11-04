"""Saved bridge routes must fail closed at the real CLI configuration boundary."""

from pathlib import Path

import pytest

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.preferences.service import UserPreferencesStore
from src.cli.typer_dispatch import TyperDispatch


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("route", ["claude-bridge:claude-haiku-5-5", "claude-bridge:unknown"])
async def test_saved_bridge_resume_never_becomes_direct_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool, route: str
) -> None:
    """Reject saved native resume before constructing or mutating a host session."""
    monkeypatch.setenv(name="SLO_HOME", value=str(tmp_path))
    monkeypatch.setenv(name="SLO_PREFERENCES_FILE", value=str(tmp_path / "preferences.json"))
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1" if enabled else "0")
    UserPreferencesStore.upsert(model_name="gpt-5.4")
    store = FilesystemSessionHistoryStore(root=tmp_path / "history")
    await store.ensure_session(session_id="saved", workdir=tmp_path, model_name=route)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    metadata = await store.read_metadata(session_id="saved")
    assert metadata is not None
    with pytest.raises(ValueError, match="fresh|resume"):
        TyperDispatch._build_session_config(
            workdir=tmp_path, resume_session_id="saved", resumed_model_name=metadata.model_name
        )
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("enabled", [False, True])
def test_explicit_bridge_cannot_override_resume_restriction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    """Explicit bridge selection cannot silently import an existing host conversation."""
    monkeypatch.setenv(name="SLO_PREFERENCES_FILE", value=str(tmp_path / "preferences.json"))
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1" if enabled else "0")
    with pytest.raises(ValueError, match="fresh|resume"):
        TyperDispatch._build_session_config(
            workdir=tmp_path, resume_session_id="saved", model="claude-bridge:claude-opus-4-8"
        )
