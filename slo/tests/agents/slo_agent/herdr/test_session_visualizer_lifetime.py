"""Real saved-parent reads retain ownership through gateway cancellation."""

import asyncio
import json
import shutil
import threading
from pathlib import Path
from typing import Optional

import pytest

from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.context_dao import OrchestratorContextDAO
from src.agents.slo_agent.orchestrator.context_reader import OrchestratorContextReader
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.state_isolation import FakeHerdrFixture
from tests.tui.test_herdr_activation_composed import native_factory

PARENT = "a81d92fa-7a2e-4ccd-9975-445832a91d5e"


@pytest.mark.parametrize("boundary", ["metadata", "events", "context", "path"])
@pytest.mark.parametrize(
    "action",
    [
        "cancel",
        "cancel_error",
        "close",
        "revoke",
        "default",
        "config_root",
        "store_root",
        "workdir",
        "viewer",
        "success",
        "error",
        "unexpected_error",
    ],
)
async def test_gateway_read_lifetime(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    native_factory: object,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    action: str,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Block real reader/discovery off-loop, mutate authority, then inspect exact effects."""
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    with fake_herdr.executable.open(mode="a", encoding="utf-8") as stream:
        stream.write('if sys.argv[2] == "split": print(\'{"result":{"pane":{"pane_id":"viewer"}}}\')\n')
    monkeypatch.setattr("src.agents.slo_agent.history.filesystem_store._CFG_SLO_HOME", tmp_path)
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    parent = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", session_id=PARENT)
    )
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
    if boundary == "events":
        context_path.unlink()
        assert parent._history_store is not None
        await parent._history_store.append_event(
            event=SessionHistoryEventDAO(
                session_id=PARENT, kind="sub_agent_spawned", payload=SessionHistoryEventPayloadDAO()
            )
        )
    await session.start_external_reporting(interactive=True)
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    entered, finished = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    original_reader, original_which = OrchestratorContextReader.load, shutil.which
    original_read_text = Path.read_text

    def fail_if_requested() -> None:
        """Exercise ordinary private exceptions without exposing their text."""
        if action in ("error", "cancel_error"):
            raise OSError("PRIVATE boundary failure")
        if action == "unexpected_error":
            raise RuntimeError("PRIVATE unexpected failure")

    def read_text(path: Path, encoding: Optional[str] = None, errors: Optional[str] = None) -> str:
        """Hold only the requested parent's actual metadata or event file read."""
        filename = "session.json" if boundary == "metadata" else "events.jsonl"
        if path != context_path.parent / filename:
            return original_read_text(path, encoding=encoding, errors=errors)
        hold()
        try:
            result = original_read_text(path, encoding=encoding, errors=errors)
            fail_if_requested()
            return result
        finally:
            loop.call_soon_threadsafe(finished.set)

    def hold() -> None:
        """Prove thread identity before blocking; never block the event loop on regression."""
        assert threading.get_ident() != loop_thread
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=10), "test barrier not released"

    def reader(*, history_root: Path, parent_session_id: str) -> Optional[OrchestratorContextDAO]:
        """Read actual private bytes after the deterministic barrier."""
        hold()
        try:
            result = original_reader(history_root=history_root, parent_session_id=parent_session_id)
            fail_if_requested()
            return result
        finally:
            loop.call_soon_threadsafe(finished.set)

    def which(cmd: str, mode: int = 1, path: Optional[str] = None) -> Optional[str]:
        """Perform actual PATH discovery after the deterministic barrier."""
        hold()
        try:
            result = original_which(cmd=cmd, mode=mode, path=path)
            assert result == str(tmp_path / "slo")
            fail_if_requested()
            return result
        finally:
            loop.call_soon_threadsafe(finished.set)

    if boundary == "context":
        monkeypatch.setattr(OrchestratorContextReader, "load", reader)
    elif boundary == "path":
        monkeypatch.setattr("src.agents.slo_agent.sessions.service.shutil.which", which)
    else:
        monkeypatch.setattr(Path, "read_text", read_text)
    original_viewer = session._herdr_visualizer
    task = asyncio.create_task(coro=session.open_workflow_visualizer(parent_session_id=PARENT))
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        assert session._config is not None
        assert isinstance(session._herdr_reporter, HerdrReporter)
        if action.startswith("cancel"):
            for _ in range(2):
                task.cancel()
                checkpoint = asyncio.Event()
                loop.call_soon(checkpoint.set)
                await checkpoint.wait()
            assert not task.done(), "gateway abandoned its running file/discovery thread"
        elif action == "close":
            await session.close_external_reporting()
        elif action == "revoke":
            session._herdr_reporter.revoke_viewer_admission()
        elif action == "default":
            monkeypatch.setattr(
                "src.agents.slo_agent.history.filesystem_store._CFG_SLO_HOME", tmp_path / "changed"
            )
        elif action == "config_root":
            session._config.history_root = tmp_path / "changed"
        elif action == "store_root":
            session._history_store = FilesystemSessionHistoryStore(root=tmp_path / "changed")
        elif action == "workdir":
            session._config.workdir = tmp_path / "changed"
        elif action == "viewer":
            session._herdr_visualizer = session._herdr_reporter.build_visualizer()
        release.set()
        if action.startswith("cancel"):
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=3)
        else:
            outcome = await asyncio.wait_for(task, timeout=3)
            assert outcome.status == ("submitted" if action == "success" else "skipped")
            assert "PRIVATE" not in outcome.model_dump_json()
        assert finished.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.wait_for(finished.wait(), timeout=3)
        await session.close_external_reporting()
        if original_viewer is not None:
            await original_viewer.close()
    rows = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
    viewer_rows = [row for row in rows if row[:2] in [["pane", op] for op in ("split", "rename", "run")]]
    assert [row[1] for row in viewer_rows] == (["split", "rename", "run"] if action == "success" else [])
    assert "PRIVATE" not in json.dumps(rows)
    captured = capsys.readouterr()
    assert "PRIVATE" not in captured.out + captured.err + caplog.text
