"""E2E tests for session plugin wiring (75.a.3 step-level e2e + M3 seam).

A session built with a real plugin file loads it at construction: the plugin's
tool reaches the agent bundle, its event handler fires in a ``FauxChatModel``
run, injected ``before_agent_turn`` messages reach the next LLM call, and a
second raising plugin never fails the session.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from src.agents.base import LLMFactory
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.sessions.service import SloAgentSession

_PLUGIN_WITH_TOOL_AND_HANDLER: str = '''
from langchain_core.tools import tool

OBSERVED = []


@tool
def alpha_tools__deploy(target: str) -> str:
    """Deploy one target (test plugin tool).

    Args:
        target (str): Deployment target.

    Returns:
        str: Deployment acknowledgement.
    """
    return f"deployed {target}"


def register(slo):
    """Register one tool and one run_completed observer."""

    def on_completed(event):
        OBSERVED.append(event.kind)

    slo.on(event_kind="run_completed", handler=on_completed)
    slo.register_tool(tool=alpha_tools__deploy)
'''

_RAISING_PLUGIN: str = "def register(slo):\n    raise RuntimeError('boom')\n"

_INTERCEPTING_PLUGIN: str = '''
def register(slo):
    """Block one tool call and patch another terminal result."""

    from src.agents.slo_agent.plugins.dao import (
        AfterToolResultPatchDAO,
        BeforeToolCallDecisionDAO,
    )

    def block(decision, tool_input):
        return BeforeToolCallDecisionDAO(block=True, reason="plugin blocked stream")

    def patch(content, is_error):
        return AfterToolResultPatchDAO(content=content + " [plugin patch]")

    slo.on_before_tool_call(handler=block)
    slo.on_after_tool_result(handler=patch)
'''

_INJECTING_PLUGIN: str = '''
from langchain_core.messages import HumanMessage


def register(slo):
    """Inject one context message before every agent turn."""

    def inject(iteration):
        from src.agents.slo_agent.plugins.dao import BeforeAgentTurnDecisionDAO

        return BeforeAgentTurnDecisionDAO(
            inject_messages=[HumanMessage(content="plugin-injected-context")]
        )

    slo.on_before_agent_turn(handler=inject)
'''


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


def _build_session(
    *,
    workdir: Path,
    responses: list[AIMessage],
    plugin_path: Path,
    extra_plugin_paths: list[Path] | None = None,
) -> SloAgentSession:
    """Build a history-disabled session loading the given CLI-tier plugins.

    Args:
        workdir (Path): Session workdir.
        responses (list[AIMessage]): Scripted FauxChatModel responses.
        plugin_path (Path): First explicit plugin path.
        extra_plugin_paths (list[Path] | None): Additional plugin paths.

    Returns:
        SloAgentSession: The wired session.
    """
    faux: FauxChatModel = FauxChatModel(responses=responses)
    agent: SloAgent = SloAgent(llm=faux, cwd=str(workdir))
    return SloAgentSession(
        agent=agent,
        workdir=workdir,
        session_id="plugin-wiring-e2e",
        plugin_paths=[plugin_path, *(extra_plugin_paths or [])],
        plugin_loader_kwargs={
            "managed_root": workdir / "absent-managed",
            "trust_store_path": workdir / "absent-trust.json",
        },
    )


@pytest.mark.asyncio
async def test_session_loads_real_plugin_tool_and_fires_handler(tmp_path: Path) -> None:
    """A real plugin file's tool reaches the bundle and its handler fires."""
    plugin_path: Path = _write_plugin(
        directory=tmp_path,
        name="alpha_tools.py",
        body=_PLUGIN_WITH_TOOL_AND_HANDLER,
    )
    session: SloAgentSession = _build_session(
        workdir=tmp_path,
        responses=[AIMessage(content="done")],
        plugin_path=plugin_path,
    )

    async for _ in session.invoke(text="hello"):
        pass

    import sys

    module = sys.modules["slo_plugin_alpha_tools"]
    assert "run_completed" in module.OBSERVED
    health = session.plugin_health_reports()[0]
    assert health.status.value == "loaded"
    tool_names: list[str] = session._runtime_tool_names()
    assert "alpha_tools__deploy" in tool_names


@pytest.mark.asyncio
async def test_second_raising_plugin_does_not_fail_session(tmp_path: Path) -> None:
    """A raising plugin records LOAD_FAILED; the session still completes."""
    good_path: Path = _write_plugin(
        directory=tmp_path,
        name="good_plugin.py",
        body=_PLUGIN_WITH_TOOL_AND_HANDLER,
    )
    bad_path: Path = _write_plugin(directory=tmp_path, name="bad_plugin.py", body=_RAISING_PLUGIN)
    session: SloAgentSession = _build_session(
        workdir=tmp_path,
        responses=[AIMessage(content="fine")],
        plugin_path=good_path,
        extra_plugin_paths=[bad_path],
    )

    final: str = ""
    async for event in session.invoke(text="hello"):
        if event.kind == "run_completed":
            final = event.content or ""

    assert final == "fine"
    reports = session.plugin_health_reports()
    by_id: dict[str, Any] = {report.plugin_id: report for report in reports}
    assert by_id["good_plugin"].status.value == "loaded"
    assert by_id["bad_plugin"].status.value == "load_failed"
    assert "boom" in (by_id["bad_plugin"].load_error or "")


@pytest.mark.asyncio
async def test_injected_before_agent_turn_messages_reach_next_llm_call(tmp_path: Path) -> None:
    """M3: injected messages land in the LLM's next request messages."""
    plugin_path: Path = _write_plugin(
        directory=tmp_path,
        name="injector.py",
        body=_INJECTING_PLUGIN,
    )
    faux: FauxChatModel = FauxChatModel(responses=[AIMessage(content="done")])
    agent: SloAgent = SloAgent(llm=faux, cwd=str(tmp_path))
    session: SloAgentSession = SloAgentSession(
        agent=agent,
        workdir=tmp_path,
        session_id="m3-seam",
        plugin_paths=[plugin_path],
        plugin_loader_kwargs={
            "managed_root": tmp_path / "absent-managed",
            "trust_store_path": tmp_path / "absent-trust.json",
        },
    )
    captured: list[list[BaseMessage]] = []
    original_astream = FauxChatModel._astream

    async def capturing_astream(self: FauxChatModel, messages: list[BaseMessage], **kwargs: Any) -> Any:
        """Record the request messages then delegate to the scripted stream.

        Args:
            self (FauxChatModel): The (possibly tool-bound clone) model.
            messages (list[BaseMessage]): The request messages.
            **kwargs (Any): Passthrough kwargs.

        Yields:
            Any: The scripted chunks.
        """
        captured.append(list(messages))
        async for chunk in original_astream(self, messages, **kwargs):
            yield chunk

    with patch.object(FauxChatModel, "_astream", capturing_astream):
        async for _ in session.invoke(text="hello"):
            pass

    assert any(
        str(message.content) == "plugin-injected-context" for request in captured for message in request
    )


def test_kill_switch_env_disables_session_plugin_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SLO_PLUGINS_DISABLED=1 leaves the session with an empty registry."""
    monkeypatch.setenv("SLO_PLUGINS_DISABLED", "1")
    plugin_path: Path = _write_plugin(
        directory=tmp_path,
        name="alpha_tools.py",
        body=_PLUGIN_WITH_TOOL_AND_HANDLER,
    )
    session: SloAgentSession = _build_session(
        workdir=tmp_path,
        responses=[AIMessage(content="done")],
        plugin_path=plugin_path,
    )

    assert session.plugin_health_reports() == []
    assert "alpha_tools__deploy" not in session._runtime_tool_names()
