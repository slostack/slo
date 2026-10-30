"""The shared context reader preserves private schema and ordinary slug support."""

from pathlib import Path

import pytest

from src.agents.slo_agent.orchestrator.context_dao import OrchestratorContextDAO
from src.agents.slo_agent.orchestrator.context_reader import OrchestratorContextReader


@pytest.mark.parametrize(
    argnames="parent", argvalues=["ordinary-parent", "a81d92fa-7a2e-4ccd-9975-445832a91d5e"]
)
def test_context_roundtrip(tmp_path: Path, parent: str, caplog: pytest.LogCaptureFixture) -> None:
    """Read the existing file verbatim without exposing its private contents."""
    path = tmp_path / parent / "orchestrator_context.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    path.parent.mkdir()
    context = OrchestratorContextDAO.build(
        system_prompt="PRIVATE-SYSTEM", user_prompt="PRIVATE-USER", model=None
    )
    path.write_text(context.model_dump_json(), encoding="utf-8")
    assert OrchestratorContextReader.load(history_root=tmp_path, parent_session_id=parent) == context
    assert caplog.text == ""


@pytest.mark.parametrize(argnames="contents", argvalues=[None, "{", "{}", "[]", "PRIVATE-INVALID"])
def test_unavailable_context(tmp_path: Path, contents: str | None, caplog: pytest.LogCaptureFixture) -> None:
    """Missing or invalid private captures yield absence without diagnostics."""
    path = tmp_path / "ordinary" / "orchestrator_context.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    if contents is not None:
        path.parent.mkdir()
        path.write_text(contents, encoding="utf-8")
    assert OrchestratorContextReader.load(history_root=tmp_path, parent_session_id="ordinary") is None
    assert caplog.text == ""


@pytest.mark.parametrize(argnames="parent", argvalues=["../outside", "/outside", "", "bad/name", "bad\\name"])
def test_invalid_identity(tmp_path: Path, parent: str) -> None:
    """Reject path-like identifiers before filesystem access."""
    assert OrchestratorContextReader.load(history_root=tmp_path, parent_session_id=parent) is None
    assert list(tmp_path.iterdir()) == []


def test_os_error(tmp_path: Path) -> None:
    """A directory at the capture filename degrades like other read errors."""
    path = tmp_path / "ordinary" / "orchestrator_context.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    path.mkdir(parents=True)
    assert OrchestratorContextReader.load(history_root=tmp_path, parent_session_id="ordinary") is None
