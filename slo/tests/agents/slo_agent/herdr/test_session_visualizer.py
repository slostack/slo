"""Session eligibility composes persisted parents with the owned viewer transport."""

import asyncio
import json
from unittest.mock import patch
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.history.dao import SessionHistoryMetadataDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.orchestrator.context_dao import OrchestratorContextDAO
from src.tui.visualizer_launcher import VisualizerLauncher
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.state_isolation import FakeHerdrFixture
from tests.tui.test_herdr_activation_composed import native_factory

PARENT = "a81d92fa-7a2e-4ccd-9975-445832a91d5e"


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "invalid",
        "closed",
        "missing",
        "corrupt",
        "ordinary",
        "workdir",
        "path",
        "ineligible",
        "metadata",
        "attached",
        "revoked",
        "default_changed",
        "selector_valid",
        "selector_skip",
        "metadata_wrong_id",
        "metadata_oserror",
        "standard",
        "replaced_tool",
        "reordered_tools",
        "changed_system",
        "changed_append",
        "injected",
    ],
)
async def test_saved_parent_submits_owned_viewer(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: object,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """A different saved parent uses the same reporter transport and exact parent argv."""
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as stream:
        stream.write('if sys.argv[2] == "split": print(\'{"result":{"pane":{"pane_id":"viewer"}}}\')\n')
    monkeypatch.setenv("SLO_HOME", str(tmp_path))
    monkeypatch.setattr("src.agents.slo_agent.history.filesystem_store._CFG_SLO_HOME", tmp_path)
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    if case == "injected":
        from langchain_core.messages import AIMessage
        from src.agents.providers.faux import FauxChatModel
        from src.agents.slo_agent.agent import SloAgent

        session = SloAgentSession(
            workdir=tmp_path,
            session_id=session.session_id,
            agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="offline")]), cwd=str(tmp_path)),
            enable_history=True,
        )
    parent = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", session_id=PARENT)
    )
    assert session._history_store is not None
    assert parent._history_store is not None
    await session.rename_session(session_name="owner")
    await parent.rename_session(session_name="parent")
    assert parent.history_root is not None
    context_path = parent.history_root / PARENT / "orchestrator_context.json"
    assert context_path.resolve().is_relative_to(tmp_path.resolve())
    context_path.write_text(
        OrchestratorContextDAO.build(
            system_prompt="PRIVATE", user_prompt="PRIVATE", model=None
        ).model_dump_json(),
        encoding="utf-8",
    )
    try:
        provenance_cases = (
            "standard",
            "replaced_tool",
            "reordered_tools",
            "changed_system",
            "changed_append",
        )
        if case in provenance_cases:
            from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap

            monkeypatch.setattr("config.cfg.DETACHED_WORKFLOWS", True)
            OrchestratorSessionBootstrap.attach(session=session)
            assert session._standard_orchestrator_attachment is not None
        await session.start_external_reporting(interactive=True)
        if case in provenance_cases:
            assert session._herdr_capture is not None and session._config is not None
            tools = session._config.extra_tools
            assert tools is not None and len(tools) > 1
            if case == "replaced_tool":
                tools[0] = tools[0].model_copy()
            elif case == "reordered_tools":
                tools.reverse()
            elif case == "changed_system":
                session._config.system_prompt = "PRIVATE"
            elif case == "changed_append":
                session._config.append_system_prompt = "PRIVATE"
        requested = PARENT
        if case == "invalid":
            requested = "../invalid"
        elif case == "closed":
            session.begin_external_reporting_close()
        elif case == "missing":
            requested = "b81d92fa-7a2e-4ccd-9975-445832a91d5e"
        elif case == "corrupt":
            context_path.write_text("PRIVATE-invalid", encoding="utf-8")
        elif case == "metadata":
            (context_path.parent / "session.json").write_text("PRIVATE-invalid", encoding="utf-8")
        elif case == "attached":
            context_path.unlink()
            from src.agents.slo_agent.history.dao import SessionHistoryEventDAO

            await parent._history_store.append_event(
                event=SessionHistoryEventDAO(
                    session_id=PARENT,
                    kind="sub_agent_spawned",
                    payload=SessionHistoryEventPayloadDAO(),
                )
            )
        elif case == "ordinary":
            context_path.unlink()
        elif case == "workdir":
            metadata_path = context_path.parent / "session.json"
            metadata = json.loads(metadata_path.read_text())
            metadata["workdir"] = str(tmp_path / "other")
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        elif case == "path":
            monkeypatch.setenv("PATH", str(tmp_path / "absent"))
        elif case == "ineligible":
            assert session._config is not None
            session._config.enable_history = False
        if case == "metadata_wrong_id":
            metadata_path = context_path.parent / "session.json"
            metadata = json.loads(metadata_path.read_text())
            metadata["session_id"] = session.session_id
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        if case == "selector_skip":
            context_path.unlink()
        if case == "default_changed":
            monkeypatch.setattr(
                "src.agents.slo_agent.history.filesystem_store._CFG_SLO_HOME", tmp_path / "changed"
            )
        if case == "revoked":
            entered, release = asyncio.Event(), asyncio.Event()
            original = session._history_store.read_metadata

            async def held_metadata(*, session_id: str) -> SessionHistoryMetadataDAO:
                """Hold the existing read boundary while reporter authority is revoked."""
                entered.set()
                await release.wait()
                return await original(session_id=session_id)

            with patch.object(session._history_store, "read_metadata", side_effect=held_metadata):
                task = asyncio.create_task(session.open_workflow_visualizer(parent_session_id=requested))
                try:
                    await asyncio.wait_for(entered.wait(), timeout=2)
                    session._herdr_reporter.revoke_viewer_admission()
                finally:
                    release.set()
                outcome = await asyncio.wait_for(task, timeout=2)
        elif case.startswith("selector_") or case in provenance_cases or case == "injected":
            monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
            with patch.object(VisualizerLauncher, "launch", side_effect=AssertionError("OS fallback")):
                outcome = await VisualizerLauncher.launch_async(parent_session_id=requested, session=session)
        elif case == "metadata_oserror":
            with patch.object(session._history_store, "read_metadata", side_effect=OSError("PRIVATE")):
                outcome = await session.open_workflow_visualizer(parent_session_id=requested)
            assert "PRIVATE" not in outcome.model_dump_json()
        else:
            outcome = await session.open_workflow_visualizer(parent_session_id=requested)
        if case not in ("valid", "attached", "selector_valid", "standard"):
            assert outcome.status == "skipped"
            commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
            assert not any("split" in command or "run" in command for command in commands)
            return
        assert outcome.status == "submitted"
        assert outcome.pane_id == "viewer"
        assert session._herdr_visualizer is not None
        assert isinstance(session._herdr_reporter, HerdrReporter)
        assert session._herdr_visualizer._transport is session._herdr_reporter._transport
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        pane_commands = [
            command
            for command in commands
            if command[:2] in [["pane", op] for op in ("split", "rename", "run")]
        ]
        assert pane_commands == [
            ["pane", "split", "--pane", "synthetic-pane", "--direction", "right", "--no-focus"],
            ["pane", "rename", "viewer", f"Slo workflow {PARENT[:8]}"],
            ["pane", "run", "viewer", f"slo visualize --session {PARENT} --follow"],
        ]
        assert not any(
            command[:2] in [["pane", "focus"], ["pane", "get"], ["pane", "close"]] for command in commands
        )
        assert str(tmp_path) not in json.dumps(pane_commands)
        assert "PRIVATE" not in outcome.model_dump_json()
    finally:
        await session.close_external_reporting()
        if session._sub_agent_pool is not None:
            await session._sub_agent_pool.abort_and_drain()
