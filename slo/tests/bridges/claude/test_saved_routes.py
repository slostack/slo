"""Saved bridge routes must fail closed at the real CLI configuration boundary."""

from pathlib import Path

import pytest

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.preferences.service import UserPreferencesStore
from src.cli.typer_dispatch import TyperDispatch


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("route", ["claude-bridge:claude-haiku-5-5", "claude-bridge:unknown"])
async def test_saved_bridge_route_resumes_like_any_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool, route: str
) -> None:
    """A saved bridge route is kept on resume and never replaced by the default route."""
    monkeypatch.setenv(name="SLO_HOME", value=str(tmp_path))
    monkeypatch.setenv(name="SLO_PREFERENCES_FILE", value=str(tmp_path / "preferences.json"))
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1" if enabled else "0")
    UserPreferencesStore.upsert(model_name="gpt-5.4")
    store = FilesystemSessionHistoryStore(root=tmp_path / "history")
    await store.ensure_session(session_id="saved", workdir=tmp_path, model_name=route)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    metadata = await store.read_metadata(session_id="saved")
    assert metadata is not None
    config = TyperDispatch._build_session_config(
        workdir=tmp_path, resume_session_id="saved", resumed_model_name=metadata.model_name
    )
    assert config.model_name == route
    assert config.session_id == "saved"
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("enabled", [False, True])
def test_explicit_bridge_route_may_resume_an_existing_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    """Explicit bridge selection resumes any host conversation through shared history."""
    monkeypatch.setenv(name="SLO_PREFERENCES_FILE", value=str(tmp_path / "preferences.json"))
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1" if enabled else "0")
    config = TyperDispatch._build_session_config(
        workdir=tmp_path, resume_session_id="saved", model="claude-bridge:claude-opus-4-8"
    )
    assert config.model_name == "claude-bridge:claude-opus-4-8"
    assert config.session_id == "saved"
