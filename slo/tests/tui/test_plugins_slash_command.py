"""Tests for the ``/plugins`` slash command surface (75.a.3).

``/plugins`` renders health lines from ``PluginRegistry.health_reports()``;
``/plugins trust`` records the current project and triggers a reload;
``/plugins reload`` reconciles registrations — a dropped plugin's
registrations vanish.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.slash_router import SlashRouter

_OBSERVER_PLUGIN: str = (
    "def register(slo):\n"
    "    slo.on(event_kind='run_completed', handler=lambda event: None)\n"
    "    slo.set_status(key='alpha:status', text='ready')\n"
)


def _write_plugin(*, directory: Path, name: str, body: str) -> Path:
    """Write one plugin file.

    Args:
        directory (Path): Existing directory.
        name (str): File name including ``.py``.
        body (str): Plugin source.

    Returns:
        Path: The written file.
    """
    path: Path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def _build_session(*, workdir: Path, plugin_paths: list[Path], trust_store_path: Path) -> SloAgentSession:
    """Build a history-disabled session with plugin wiring under test control.

    Args:
        workdir (Path): Session workdir.
        plugin_paths (list[Path]): Explicit CLI-tier plugin paths.
        trust_store_path (Path): Trust-store override path.

    Returns:
        SloAgentSession: The wired session.
    """
    faux: FauxChatModel = FauxChatModel(responses=[AIMessage(content="done")])
    agent: SloAgent = SloAgent(llm=faux, cwd=str(workdir))
    return SloAgentSession(
        agent=agent,
        workdir=workdir,
        session_id="plugins-slash",
        plugin_paths=plugin_paths,
        plugin_loader_kwargs={
            "managed_root": workdir / "absent-managed",
            "trust_store_path": trust_store_path,
        },
    )


@pytest.mark.asyncio
async def test_plugins_lists_health_lines(tmp_path: Path) -> None:
    """``/plugins`` renders one health line per loaded plugin."""
    plugin_path: Path = _write_plugin(directory=tmp_path, name="alpha.py", body=_OBSERVER_PLUGIN)
    session: SloAgentSession = _build_session(
        workdir=tmp_path,
        plugin_paths=[plugin_path],
        trust_store_path=tmp_path / "trust.json",
    )

    result = await SlashRouter.dispatch(line="/plugins", session=session)
    assert result.rendered is not None

    assert "alpha" in result.rendered
    assert "loaded" in result.rendered


@pytest.mark.asyncio
async def test_plugins_reports_empty_when_none_loaded(tmp_path: Path) -> None:
    """``/plugins`` says so when no plugins are loaded."""
    session: SloAgentSession = _build_session(
        workdir=tmp_path,
        plugin_paths=[],
        trust_store_path=tmp_path / "trust.json",
    )

    result = await SlashRouter.dispatch(line="/plugins", session=session)
    assert result.rendered is not None

    assert "no plugins" in result.rendered.lower()


@pytest.mark.asyncio
async def test_plugins_reload_drops_registrations_of_removed_plugin(tmp_path: Path) -> None:
    """After the plugin file is deleted, reload drops its registrations."""
    plugin_path: Path = _write_plugin(directory=tmp_path, name="alpha.py", body=_OBSERVER_PLUGIN)
    session: SloAgentSession = _build_session(
        workdir=tmp_path,
        plugin_paths=[plugin_path],
        trust_store_path=tmp_path / "trust.json",
    )
    assert len(session.plugin_health_reports()) == 1

    plugin_path.unlink()
    result = await SlashRouter.dispatch(line="/plugins reload", session=session)
    assert result.rendered is not None

    reports = session.plugin_health_reports()
    assert [report.status.value for report in reports] == ["load_failed"]
    assert "load_failed" in result.rendered


@pytest.mark.asyncio
async def test_plugins_trust_records_project_and_reloads(tmp_path: Path) -> None:
    """``/plugins trust`` trusts the workdir; reload then loads project plugins."""
    project_plugins: Path = tmp_path / ".slo" / "plugins"
    project_plugins.mkdir(parents=True)
    _write_plugin(directory=project_plugins, name="proj.py", body=_OBSERVER_PLUGIN)
    trust_store_path: Path = tmp_path / "trust.json"
    session: SloAgentSession = _build_session(
        workdir=tmp_path,
        plugin_paths=[],
        trust_store_path=trust_store_path,
    )
    assert session.plugin_health_reports() == []

    result = await SlashRouter.dispatch(line="/plugins trust", session=session)
    assert result.rendered is not None

    assert "trust" in result.rendered.lower()
    assert "proj" in result.rendered
    assert [report.plugin_id for report in session.plugin_health_reports()] == ["proj"]
