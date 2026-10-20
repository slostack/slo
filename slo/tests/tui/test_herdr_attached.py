"""Attached viewer scheduling contracts; no real windows or providers."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.herdr.dao import VisualizerLaunchOutcomeDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.visualizer_launcher import VisualizerLauncher


async def test_attached_event_schedules_captured_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Actual mounted routing schedules once and never calls the synchronous launcher."""
    monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]), supports_explicit_caching=False
        ),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
        )
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            with patch.object(VisualizerLauncher, "launch_async", new_callable=AsyncMock) as launch:
                launch.return_value = VisualizerLaunchOutcomeDAO(status="submitted", pane_id="viewer")
                event = AgentStreamEventDAO(kind="sub_agent_spawned", sub_agent_id="child", task_id="task")
                await app._route_sub_agent_event(event=event)
                await app._route_sub_agent_event(event=event)
                await asyncio.gather(*app._visualizer_launch_tasks.values())
                launch.assert_awaited_once_with(parent_session_id=session.session_id, session=session)


@pytest.mark.parametrize("status", ["opened", "submitted", "reused", "failed", "skipped"])
async def test_worker_renders_typed_outcome_once(status: str, tmp_path: Path) -> None:
    """Completion renders distinct truthful outcomes and releases failed request guards."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
    )
    app = SloTUI(session=session)
    app._adapter = Mock()
    app._visualizer_launched_for_run = True
    outcome = VisualizerLaunchOutcomeDAO.model_validate({"status": status, "pane_id": "viewer"})
    with patch.object(VisualizerLauncher, "launch_async", new_callable=AsyncMock, return_value=outcome):
        await app._run_visualizer_launch(parent_session_id="parent", session=session)
    app._adapter.write.assert_called_once()
    text = app._adapter.write.call_args.kwargs["content"]
    expected = {
        "opened": "Opened",
        "submitted": "Submitted",
        "reused": "Select",
        "failed": "failed",
        "skipped": "skipped",
    }
    assert expected[status] in text
    if status == "reused":
        assert "if still present" in text
        assert "Previously attempted" in text
        assert "slo visualize --session parent --follow" in text
        assert session.session_id not in text
        assert str(tmp_path) not in text
    if status != "opened":
        assert "Opened" not in text and "running" not in text
    assert app._visualizer_launched_for_run is (status != "failed")


@pytest.mark.parametrize("cutoff", ["replacement", "closing", "quiescing", "notice_error", "gateway_error"])
async def test_completion_lifetime_and_failure_isolation(cutoff: str, tmp_path: Path) -> None:
    """Late completions stay silent; optional failures release guards without leaking errors."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
    )
    app = SloTUI(session=session)
    sink = Mock()
    app._adapter = sink
    app._visualizer_launched_for_run = True

    async def launch(**kwargs: object) -> VisualizerLaunchOutcomeDAO:
        """Apply a lifetime cutoff at the awaited boundary."""
        if cutoff == "replacement":
            app._session = SloAgentSession.build(
                config=SessionConfigDAO(
                    workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4"
                )
            )
        if cutoff == "closing":
            app._app_closing = True
        if cutoff == "quiescing":
            app._delivery_quiescing = True
        if cutoff == "gateway_error":
            raise RuntimeError("private-sentinel")
        return VisualizerLaunchOutcomeDAO(status="failed", pane_id="known-pane")

    if cutoff == "notice_error":
        sink.write.side_effect = RuntimeError("private-sentinel")
    with patch.object(VisualizerLauncher, "launch_async", side_effect=launch):
        await app._run_visualizer_launch(parent_session_id="parent", session=session)
    late = cutoff in ("replacement", "closing", "quiescing")
    assert sink.write.call_count == (0 if late else 1)
    assert app._visualizer_launched_for_run is late
    assert "private-sentinel" not in str(sink.write.call_args)
