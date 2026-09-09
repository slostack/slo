"""Runtime integration coverage for validated plugin slash commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.slash_router import SlashRouter


def _session(*, workdir: Path, plugin_path: Path) -> SloAgentSession:
    """Build a session with one explicit trusted plugin file."""
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="done")]), cwd=str(workdir)),
        workdir=workdir,
        session_id="plugin-command",
        plugin_paths=[plugin_path],
        plugin_loader_kwargs={
            "managed_root": workdir / "missing",
            "trust_store_path": workdir / "trust.json",
        },
    )


@pytest.mark.asyncio
async def test_plugin_command_is_registered_and_invokes_its_handler(tmp_path: Path) -> None:
    """A plugin command becomes discoverable and returns its handler output."""
    plugin: Path = tmp_path / "release.py"
    plugin.write_text(
        "def register(slo):\n"
        "    slo.register_command(name='release:notes', handler=lambda rest, session: f'notes:{rest}')\n",
        encoding="utf-8",
    )
    session: SloAgentSession = _session(workdir=tmp_path, plugin_path=plugin)

    result = await SlashRouter.dispatch(line="/release:notes v1", session=session)

    assert SlashRouter.registry().resolve(token="release:notes") is not None
    assert result.rendered == "notes:v1"


@pytest.mark.asyncio
async def test_plugin_command_colliding_with_builtin_is_refused_and_plugins_still_work(
    tmp_path: Path,
) -> None:
    """Built-ins retain ownership when a plugin attempts to register their token."""
    plugin: Path = tmp_path / "collision.py"
    plugin.write_text(
        "def register(slo):\n"
        "    slo.register_command(name='plugins', handler=lambda rest, session: 'shadowed')\n",
        encoding="utf-8",
    )
    session: SloAgentSession = _session(workdir=tmp_path, plugin_path=plugin)

    result = await SlashRouter.dispatch(line="/plugins", session=session)

    assert "shadowed" not in (result.rendered or "")
    assert "duplicate slash command" in (session.plugin_health_reports()[0].load_error or "").lower()
