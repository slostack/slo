"""Attached spawn events cross the mounted app and real registered CLI boundary."""

import asyncio
from src.tui.components.chat_transcript.component import ChatTranscript
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.orchestrator.context_dao import OrchestratorContextDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.visualizer_launcher import VisualizerLauncher
from tests.state_isolation import FakeHerdrFixture
from tests.tui.test_herdr_activation_composed import commands, eventually, native_factory


@pytest.mark.parametrize("detached", [False, True])
@pytest.mark.parametrize("mode", ["enabled", "auto_off", "unavailable"])
async def test_attached_spawn_submits_real_parent_once(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: object,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    detached: bool,
) -> None:
    """Ordinary bootstrap preserves eligibility through real mounted launch and drain."""
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as stream:
        stream.write('if sys.argv[2] == "split": print(\'{"result":{"pane":{"pane_id":"viewer"}}}\')\n')
    monkeypatch.setenv(name="SLO_AUTO_VISUALIZE", value="1")
    monkeypatch.setenv(name="SLO_HOME", value=str(tmp_path))
    monkeypatch.setattr("src.agents.slo_agent.history.filesystem_store._CFG_SLO_HOME", tmp_path)
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="attached parent")
    assert session.history_root is not None
    context = session.history_root / session.session_id / "orchestrator_context.json"
    assert context.resolve().is_relative_to(tmp_path.resolve())
    context.write_text(
        OrchestratorContextDAO.build(
            system_prompt="PRIVATE",
            user_prompt="PRIVATE",
            model=None,
        ).model_dump_json(),
        encoding="utf-8",
    )
    parent_id = session.session_id
    if detached:
        parent = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
        await parent.rename_session(session_name="detached parent")
        parent_id = parent.session_id
        detached_context = session.history_root / parent_id / "orchestrator_context.json"
        assert detached_context.resolve().is_relative_to(tmp_path.resolve())
        detached_context.write_text(context.read_text(encoding="utf-8"), encoding="utf-8")
    app = SloTUI(session=session)
    with patch.object(VisualizerLauncher, "launch", side_effect=AssertionError("OS fallback")):
        async with app.run_test():
            assert session._standard_orchestrator_attachment is not None
            reporter = session._herdr_reporter
            assert isinstance(reporter, HerdrReporter)
            await eventually(predicate=lambda: reporter._display_ack_revision is not None)
            assert session._herdr_capture is not None
            assert not session._agent_is_injected
            assert session._herdr_visualizer is not None
            assert session._herdr_visualizer._transport is reporter._transport
            if mode == "auto_off":
                monkeypatch.setenv(name="SLO_AUTO_VISUALIZE", value="0")
            if mode == "unavailable":
                reporter.revoke_viewer_admission()
                assert session.workflow_visualizer_destination == "unavailable"
            event = AgentStreamEventDAO(
                kind="sub_agent_spawned", sub_agent_id="synthetic-child", task_id="task"
            )
            if detached:
                event = AgentStreamEventDAO(
                    kind="tool_result",
                    tool_name="launch_workflow",
                    tool_call_id="detached-call",
                    content='{"workflow_id":"wf-test","orchestrator_session_id":"' + parent_id + '"}',
                )
            await app._render_event(event=event)
            if mode == "auto_off":
                assert not app._visualizer_launch_tasks
            else:
                task = app._visualizer_launch_tasks[parent_id]
                await app._render_event(event=event)
                assert app._visualizer_launch_tasks[parent_id] is task
                await asyncio.wait_for(task, timeout=10)
                await eventually(predicate=lambda: not app._visualizer_launch_tasks)
            rows = [
                row
                for row in commands(fake_herdr)
                if row[:2] in [["pane", op] for op in ("split", "rename", "run")]
            ]
            if mode != "enabled":
                assert rows == []
                assert app._chat_transcript._adapter is not None
                assert not any(
                    "Submitted workflow viewer" in str(line) for line in app._chat_transcript._adapter.lines
                )
                return
            assert rows == [
                ["pane", "split", "--pane", "synthetic-pane", "--direction", "right", "--no-focus"],
                ["pane", "rename", "viewer", f"Slo workflow {parent_id[:8]}"],
                ["pane", "run", "viewer", f"slo visualize --session {parent_id} --follow"],
            ]
            await app._render_event(event=event)
            assert not app._visualizer_launch_tasks
            assert not any(
                row[:2] in [["pane", op] for op in ("focus", "get", "close")] for row in commands(fake_herdr)
            )
            assert app._chat_transcript._adapter is not None
            assert not any(
                "Opened workflow visualizer" in str(line) for line in app._chat_transcript._adapter.lines
            )
            assert (
                sum(
                    "Submitted workflow viewer command to Herdr pane (viewer)." in str(line)
                    for line in app._chat_transcript._adapter.lines
                )
                == 1
            )
    assert not app._visualizer_launch_tasks
    assert not reporter.retains_external_resources
