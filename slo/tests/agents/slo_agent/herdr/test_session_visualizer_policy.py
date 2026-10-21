"""Gateway policy through real config-backed sessions and registered CLI transport."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.orchestrator.context_dao import OrchestratorContextDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.visualizer_launcher import VisualizerLauncher
from tests.state_isolation import FakeHerdrFixture
from tests.tui.test_herdr_activation_composed import native_factory

PARENT = "a81d92fa-7a2e-4ccd-9975-445832a91d5e"
PRIVATE = "synthetic-private-context-secret-99"


@pytest.mark.parametrize(
    "case", ["headless", "custom_root", "owner_slug", "no_history", "custom_prompt", "custom_append"]
)
async def test_unsupported_owner_never_reads_parent_or_falls_back(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: object,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """Unsupported native owners cannot launch a viewer even for a canonical parent."""
    monkeypatch.setattr("src.agents.slo_agent.history.filesystem_store._CFG_SLO_HOME", tmp_path)
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="gpt-5.4",
        history_root=tmp_path / "custom" if case == "custom_root" else None,
        session_id="ordinary-slug" if case == "owner_slug" else None,
        enable_history=case != "no_history",
        system_prompt=PRIVATE if case == "custom_prompt" else None,
        append_system_prompt=PRIVATE if case == "custom_append" else None,
    )
    session = SloAgentSession.build(config=config)
    if config.enable_history:
        await session.rename_session(session_name="owner")
    try:
        await session.start_external_reporting(interactive=case != "headless")
        assert session._herdr_capture is None
        monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
        with (
            patch.object(session, "_workflow_parent_is_persisted", side_effect=AssertionError("parent read")),
            patch.object(VisualizerLauncher, "launch", side_effect=AssertionError("platform fallback")),
        ):
            result = await VisualizerLauncher.launch_async(parent_session_id=PARENT, session=session)
        # Noncanonical owner identity refuses reporter activation itself.
        assert result.status == ("failed" if case == "owner_slug" else "skipped")
        assert (await session.open_workflow_visualizer(parent_session_id=PARENT)).status == "skipped"
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        assert not any(
            row[:2] in [["pane", op] for op in ("split", "rename", "run", "focus", "get")] for row in commands
        )
        assert PRIVATE not in result.model_dump_json() + json.dumps(commands)
    finally:
        await session.close_external_reporting()


@pytest.mark.parametrize(
    "case",
    [
        "context",
        "private_paths",
        "context_directory",
        "wrong_event",
        "mixed_events",
        "history_error",
        "workdir_error",
        "metadata_workdir_error",
        "path_error",
    ],
)
async def test_parent_evidence_and_private_diagnostics(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    """Real persisted evidence admits only the requested parent and never publishes context."""
    monkeypatch.setattr("src.agents.slo_agent.history.filesystem_store._CFG_SLO_HOME", tmp_path)
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as stream:
        stream.write('if sys.argv[2] == "split": print(\'{"result":{"pane":{"pane_id":"viewer"}}}\')\n')
    workspace = tmp_path / "private-workspace-100.code-workspace"
    plugin = tmp_path / "private-plugin-100.py"
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            workspace_file=workspace if case == "private_paths" else None,
            plugin_paths=[plugin] if case == "private_paths" else [],
        )
    )
    parent = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", session_id=PARENT)
    )
    await session.rename_session(session_name="owner")
    await parent.rename_session(session_name="parent")
    assert parent.history_root is not None and session._history_store is not None
    context = parent.history_root / PARENT / "orchestrator_context.json"
    assert context.resolve().is_relative_to(tmp_path.resolve())
    if case in ("context", "private_paths"):
        context.write_text(
            OrchestratorContextDAO.build(
                system_prompt=PRIVATE, user_prompt=PRIVATE, model=None
            ).model_dump_json(),
            encoding="utf-8",
        )
    elif case == "context_directory":
        context.mkdir()
    if case in ("wrong_event", "mixed_events"):
        events = parent.history_root / PARENT / "events.jsonl"
        assert events.resolve().is_relative_to(tmp_path.resolve())
        wrong = SessionHistoryEventDAO(
            session_id=session.session_id, kind="sub_agent_spawned", payload=SessionHistoryEventPayloadDAO()
        )
        ordinary = SessionHistoryEventDAO(
            session_id=PARENT, kind="run_started", payload=SessionHistoryEventPayloadDAO()
        )
        rows = [wrong, ordinary]
        if case == "mixed_events":
            rows.append(
                SessionHistoryEventDAO(
                    session_id=PARENT, kind="sub_agent_spawned", payload=SessionHistoryEventPayloadDAO()
                )
            )
        events.write_text("\n".join(row.model_dump_json() for row in rows) + "\n", encoding="utf-8")
    try:
        await session.start_external_reporting(interactive=True)
        assert session._herdr_capture is not None
        if case == "private_paths":
            assert session._herdr_capture.config.workspace_file == workspace
            assert session._herdr_capture.config.plugin_paths == (plugin,)
        events_seen: list[str] = []

        async def observe(event: AgentStreamEventDAO) -> None:
            """Capture public subscriber bytes, never the private publication."""
            events_seen.append(event.model_dump_json())

        session.subscribe(handler=observe)
        capsys.readouterr()
        caplog.clear()  # Construction logs own cwd; this assertion covers gateway diagnostics only.
        monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
        from contextlib import ExitStack

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(VisualizerLauncher, "launch", side_effect=AssertionError("OS fallback"))
            )
            if case == "history_error":
                stack.enter_context(
                    patch.object(session._history_store, "load_events", side_effect=OSError(PRIVATE))
                )
            elif case == "workdir_error":
                stack.enter_context(patch.object(Path, "resolve", side_effect=OSError(PRIVATE)))
            elif case == "metadata_workdir_error":
                original_resolve = Path.resolve
                resolved: list[Path] = []

                def resolve_metadata(path: Path, strict: bool = False) -> Path:
                    """Fail only the metadata workdir, after the real root check."""
                    resolved.append(path)
                    if path == tmp_path:
                        raise OSError(PRIVATE)
                    return original_resolve(path, strict=strict)

                stack.enter_context(patch.object(Path, "resolve", new=resolve_metadata))
            elif case == "path_error":
                stack.enter_context(
                    patch("src.agents.slo_agent.sessions.service.shutil.which", side_effect=OSError(PRIVATE))
                )
            outcome = await VisualizerLauncher.launch_async(parent_session_id=PARENT, session=session)
        if case == "metadata_workdir_error":
            assert parent.history_root in resolved
            assert resolved[-1] == tmp_path
        assert outcome.status == (
            "submitted" if case in ("context", "private_paths", "mixed_events") else "skipped"
        )
        commands = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        pane_commands = [
            row
            for row in commands
            if row[:2] in [["pane", op] for op in ("split", "rename", "run", "focus", "get", "close")]
        ]
        if outcome.status == "skipped":
            assert pane_commands == []
        captured = capsys.readouterr()
        public = (
            outcome.model_dump_json()
            + json.dumps(commands)
            + caplog.text
            + captured.out
            + captured.err
            + "".join(events_seen)
        )
        if case == "private_paths":
            from src.agents.slo_agent.herdr.reporter import HerdrReporter

            assert isinstance(session._herdr_reporter, HerdrReporter)
            state_root = session._herdr_reporter._config.state_root
            assert session._herdr_reporter._latest is not None
            public += session._herdr_reporter._latest.snapshot.model_dump_json()
            sequence_files = list(state_root.glob("sequence-v1/*.json"))
            assert sequence_files
            public += "".join(path.read_text() for path in sequence_files)
            assert str(workspace) not in public
            assert str(plugin) not in public
        assert PRIVATE not in public
        assert str(context) not in public
        assert str(parent.history_root) not in public
    finally:
        await session.close_external_reporting()
