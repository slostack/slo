"""Editor responsiveness, path completion, safe failure and session authority journeys."""

import asyncio
import gc
import json
import shlex
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from uuid import uuid4
from src.tui.app import PromptInput, SloTUI
from src.tui.editor_launcher import EditorLauncher, SessionEditorTerminal
from src.tui.editor_platform_terminal import PlatformEditorTerminal
from tests.tui.test_editor_platform_terminal import RecordingTerminalProcess
from tests.state_isolation import FakeHerdrFixture
from tests.tui.test_code_command import EditorLookup, RecordingEditorTerminal, transcript_lines
from tests.tui.test_path_suggestions_app import build_path_session
from tests.tui._scroll_settle import pump_until


class UnexpectedFailureEditorLauncher(EditorLauncher):
    """Inject supervisor failures while retaining real validation for later requests."""

    async def invoke(self, *, argument: str, session: SloAgentSession) -> str:
        """Fail inertly on designated requests, otherwise use the real launcher."""
        if argument == "fail":
            raise RuntimeError("private unexpected launcher failure")
        if argument == "fail-on-cancel":
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise RuntimeError("private unexpected launcher failure") from None
        return await super().invoke(argument=argument, session=session)


def local_file(*, root: Path, name: str) -> Path:
    """Create only new test-contained files, never link system executables."""
    path = root / name
    assert path.resolve().is_relative_to(root.resolve())
    path.write_text(data="private file content", encoding="utf-8")
    return path


@pytest.mark.parametrize(argnames="fail", argvalues=[False, True])
async def test_code_pending_submission_does_not_block_prompt_or_slash(tmp_path: Path, fail: bool) -> None:
    """A held terminal cannot block another local command; errors stay safe and usable."""
    local_file(root=tmp_path, name="one.py")
    terminal = RecordingEditorTerminal(fail=fail, hold=True)
    app = SloTUI(
        session=build_path_session(workdir=tmp_path),
        editor_launcher=EditorLauncher(
            terminal=terminal,
            executable_lookup=EditorLookup(),
        ),
    )
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.load_text("/code one.py")
        await pilot.press("enter")
        await asyncio.wait_for(fut=terminal.entered.wait(), timeout=2)
        prompt.load_text("/cwd")
        await pilot.press("enter")
        await pilot.pause()
        assert any(str(tmp_path) in text for text, _ in transcript_lines(app=app))
        assert not terminal.finished.is_set()
        workers = [worker for worker in app.workers if worker.group == "editor-launch"]
        assert len(workers) == 1 and workers[0].is_running
        prompt.load_text("next input")
        terminal.release.set()
        await pump_until(pilot=pilot, predicate=lambda: not app._editor_launch_tasks)
        assert prompt.text == "next input"
        assert not app._editor_launch_tasks
        assert not app._session.is_running
        expected = "Editor launch failed" if fail else "readiness not confirmed"
        assert any(expected in text for text, _ in transcript_lines(app=app))
        assert all("private terminal" not in text for text, _ in transcript_lines(app=app))


async def test_code_pending_editor_allows_real_prompt_history_journey(tmp_path: Path) -> None:
    """A held editor submission does not block the real agent/history prompt lifecycle."""
    local_file(root=tmp_path, name="one.py")
    history_root = tmp_path / "history"
    assert history_root.resolve().is_relative_to(tmp_path.resolve())
    history = FilesystemSessionHistoryStore(root=history_root)
    model = FauxChatModel(responses=[FauxChatModel.assistant_message(content="still usable")])
    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=str(uuid4()),
        history_store=history,
        enable_history=True,
    )
    terminal = RecordingEditorTerminal(hold=True)
    app = SloTUI(
        session=session,
        editor_launcher=EditorLauncher(
            terminal=terminal,
            executable_lookup=EditorLookup(),
        ),
    )
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.load_text("/code one.py")
        await pilot.press("enter")
        await asyncio.wait_for(fut=terminal.entered.wait(), timeout=2)
        prompt.load_text("ordinary prompt")
        await pilot.press("enter")
        await pump_until(
            pilot=pilot, predicate=lambda: any("still usable" in t for t, _ in transcript_lines(app=app))
        )
        events = await history.load_events(session_id=session.session_id)
        assert [event.payload.content for event in events if event.kind == "user_message"] == [
            "ordinary prompt"
        ]
        assert any(event.kind == "run_completed" for event in events)
        assert "private file content" not in str(events)
        assert not terminal.finished.is_set()
        terminal.release.set()
        await pump_until(pilot=pilot, predicate=lambda: not app._editor_launch_tasks)
        assert not app._editor_launch_tasks


async def test_code_uses_same_completion_then_expands_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quoted Unicode completion is accepted and launches the literal home-relative file."""
    target = local_file(root=tmp_path, name="space ü.py")
    monkeypatch.setenv(name="HOME", value=str(tmp_path))
    terminal = RecordingEditorTerminal()
    app = SloTUI(
        session=build_path_session(workdir=tmp_path),
        editor_launcher=EditorLauncher(
            terminal=terminal,
            executable_lookup=EditorLookup(),
        ),
    )
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.load_text('/code "~/sp')
        prompt.move_cursor(location=(0, len(prompt.text)))
        await pilot.press("tab")
        await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
        assert [row.label for row in app._slash_suggestion_state.rows] == ["space ü.py"]
        await pilot.press("tab", "enter")
        await pump_until(pilot=pilot, predicate=terminal.finished.is_set)
        assert terminal.calls == [("/test-only/nvim", "--", str(target))]


async def test_code_unmount_cancels_request_without_closing_editor(tmp_path: Path) -> None:
    """App shutdown joins owned request tasks and suppresses post-cutoff notices."""
    local_file(root=tmp_path, name="one.py")
    terminal = RecordingEditorTerminal(hold=True)
    app = SloTUI(
        session=build_path_session(workdir=tmp_path),
        editor_launcher=EditorLauncher(
            terminal=terminal,
            executable_lookup=EditorLookup(),
        ),
    )
    async with app.run_test() as pilot:
        app.query_one(PromptInput).load_text("/code one.py")
        await pilot.press("enter")
        await asyncio.wait_for(fut=terminal.entered.wait(), timeout=2)
    assert terminal.finished.is_set()
    assert not app._editor_launch_tasks
    assert not any("readiness" in text for text, _ in transcript_lines(app=app))


async def test_editor_cancel_before_worker_entry_retires_without_shutdown_join(tmp_path: Path) -> None:
    """Pending cancellation retires the App handle without validation, notice or drain."""
    target = local_file(root=tmp_path, name="one.py")
    lookups: list[str] = []

    def lookup(*, cmd: str) -> str:
        """Record whether pending cancellation ever enters executable discovery."""
        lookups.append(cmd)
        return "/test-only/nvim"

    terminal = RecordingEditorTerminal()
    app = SloTUI(
        session=build_path_session(workdir=tmp_path),
        editor_launcher=EditorLauncher(terminal=terminal, executable_lookup=lookup),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        before = transcript_lines(app=app)
        app._schedule_editor_launch(argument="one.py")
        worker = next(worker for worker in app.workers if worker.group == "editor-launch")
        worker.cancel()  # Cancel synchronously before the lazy launch callable enters.
        await pilot.pause()
        assert worker not in app.workers
        assert worker not in app._editor_launch_tasks
        assert lookups == []
        assert terminal.calls == []
        assert transcript_lines(app=app) == before

        app.query_one(PromptInput).load_text("/code one.py")
        await pilot.press("enter")
        await pump_until(pilot=pilot, predicate=terminal.finished.is_set)
        await pilot.pause()
        assert terminal.calls == [("/test-only/nvim", "--", str(target))]
        assert not app._editor_launch_tasks
        assert any("readiness not confirmed" in text for text, _ in transcript_lines(app=app))


async def test_editor_worker_failure_is_accounted_before_idle_retirement(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An idle failed worker leaves safe evidence, no unowned exception and a usable prompt."""
    target = local_file(root=tmp_path, name="one.py")
    terminal = RecordingEditorTerminal()
    app = SloTUI(
        session=build_path_session(workdir=tmp_path),
        editor_launcher=UnexpectedFailureEditorLauncher(terminal=terminal, executable_lookup=EditorLookup()),
    )
    loop = asyncio.get_running_loop()
    loop_errors: list[dict[str, object]] = []
    previous_handler = loop.get_exception_handler()

    def record_loop_error(loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
        """Observe unhandled wait-task failures without consuming any retained task result."""
        loop_errors.append(context)

    loop.set_exception_handler(handler=record_loop_error)
    try:
        async with app.run_test() as pilot:
            await pilot.pause()
            before = transcript_lines(app=app)
            app._schedule_editor_launch(argument="fail")
            worker = next(worker for worker in app.workers if worker.group == "editor-launch")
            await pump_until(pilot=pilot, predicate=lambda: not app._editor_launch_tasks)
            gc.collect()
            await pilot.pause()
            assert worker not in app.workers
            assert loop_errors == []
            failures = [
                record for record in caplog.records if record.message == "editor_launch_worker_failed"
            ]
            assert len(failures) == 1
            assert failures[0].exc_info is None and failures[0].stack_info is None
            assert "private unexpected" not in caplog.text
            assert transcript_lines(app=app) == before
            assert terminal.calls == []

            prompt = app.query_one(PromptInput)
            prompt.load_text("/cwd")
            await pilot.press("enter")
            assert any(str(tmp_path) in text for text, _ in transcript_lines(app=app))
            prompt.load_text("/code one.py")
            await pilot.press("enter")
            await pump_until(pilot=pilot, predicate=lambda: not app._editor_launch_tasks)
            assert terminal.calls == [("/test-only/nvim", "--", str(target))]
            assert any("readiness not confirmed" in text for text, _ in transcript_lines(app=app))
            await app._drain_editor_launches()
            await app._drain_editor_launches()
        gc.collect()
        await asyncio.sleep(0)
        assert loop_errors == []
    finally:
        loop.set_exception_handler(handler=previous_handler)


async def test_editor_failure_during_drain_does_not_abandon_other_validation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Failure accounting cannot cut off another request's OS join or emit late notices."""
    local_file(root=tmp_path, name="one.py")
    entered = threading.Event()
    release = threading.Event()

    def lookup(*, cmd: str) -> str:
        """Hold actual off-thread validation until the owner has accounted for failure."""
        entered.set()
        assert release.wait(timeout=5)
        return "/test-only/nvim"

    terminal = RecordingEditorTerminal()
    app = SloTUI(
        session=build_path_session(workdir=tmp_path),
        editor_launcher=UnexpectedFailureEditorLauncher(terminal=terminal, executable_lookup=lookup),
    )
    async with app.run_test() as pilot:
        drain: asyncio.Task[None] | None = None
        try:
            await pilot.pause()
            before = transcript_lines(app=app)
            app._schedule_editor_launch(argument="fail-on-cancel")
            app._schedule_editor_launch(argument="one.py")
            await pump_until(pilot=pilot, predicate=entered.is_set)
            assert len(app._editor_launch_tasks) == 2
            drain = asyncio.create_task(coro=app._drain_editor_launches())
            await pump_until(pilot=pilot, predicate=lambda: len(app._editor_launch_tasks) == 1)
            drain.cancel()
            await asyncio.sleep(0)
            drain.cancel()
            await pilot.pause()
            assert not drain.done()
            assert len(app._editor_launch_tasks) == 1
            assert [r.message for r in caplog.records].count("editor_launch_worker_failed") == 1
            release.set()
            await asyncio.wait_for(fut=drain, timeout=2)
            await app._drain_editor_launches()
            assert not app._editor_launch_tasks
            assert terminal.calls == []
            assert transcript_lines(app=app) == before
            assert "private unexpected" not in caplog.text
        finally:
            release.set()
            if drain is not None:
                await asyncio.wait_for(fut=drain, timeout=2)


async def test_editor_worker_repeated_cancel_joins_validation_without_notice(tmp_path: Path) -> None:
    """Framework cancellation retains uncancellable metadata work and never submits late."""
    local_file(root=tmp_path, name="one.py")
    entered = threading.Event()
    release = threading.Event()

    def lookup(*, cmd: str) -> str:
        """Hold real worker validation at an injected inert discovery boundary."""
        entered.set()
        assert release.wait(timeout=5)
        return "/test-only/nvim"

    terminal = RecordingEditorTerminal()
    app = SloTUI(
        session=build_path_session(workdir=tmp_path),
        editor_launcher=EditorLauncher(terminal=terminal, executable_lookup=lookup),
    )
    async with app.run_test() as pilot:
        try:
            app.query_one(PromptInput).load_text("/code one.py")
            await pilot.press("enter")
            await pump_until(pilot=pilot, predicate=entered.is_set)
            worker = next(worker for worker in app.workers if worker.group == "editor-launch")
            worker.cancel()
            await asyncio.sleep(0)
            worker.cancel()
            await pilot.pause()
            assert not worker.is_finished
            assert app._editor_launch_tasks
            release.set()
            await pump_until(pilot=pilot, predicate=lambda: not app._editor_launch_tasks)
            assert worker.is_cancelled and worker.is_finished
            assert terminal.calls == []
            assert not any("readiness" in text for text, _ in transcript_lines(app=app))
        finally:
            release.set()


async def test_code_platform_displays_impossibility_without_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unsupported adjacent tabs render an explicit notice, never windows/in-place editors."""
    monkeypatch.delenv(name="TMUX", raising=False)
    monkeypatch.delenv(name="ITERM_SESSION_ID", raising=False)
    local_file(root=tmp_path, name="one.py")
    app = SloTUI(
        session=build_path_session(workdir=tmp_path),
        editor_launcher=EditorLauncher(
            executable_lookup=EditorLookup(),
        ),
    )
    async with app.run_test() as pilot:
        app.query_one(PromptInput).load_text("/code one.py")
        await pilot.press("enter")
        await pump_until(
            pilot=pilot, predicate=lambda: any("not possible" in t for t, _ in transcript_lines(app=app))
        )
        assert any("adjacent terminal tab is not possible" in t for t, _ in transcript_lines(app=app))
        assert not app._session.is_running


async def test_code_native_session_uses_reporter_transport_and_captured_owner(
    tmp_path: Path, fake_herdr: FakeHerdrFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keyboard → real session/reporter/transport → guarded capture, never a real pane."""
    script = fake_herdr.executable
    assert script.resolve().is_relative_to(tmp_path.resolve()) and not script.is_symlink()
    with script.open(mode="a", encoding="utf-8") as stream:
        stream.write(
            "if sys.argv[1:3] == ['pane', 'split']: print(json.dumps({'result': {'pane': {'pane_id': 'editor-pane'}}}))\n"
        )
    fake_herdr.guard.require_registered(path=script)
    target = local_file(root=tmp_path, name="x';$(touch sentinel)`x` ü.py")
    with patch(
        target="src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[]),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
        platform_process = RecordingTerminalProcess(replies=[])
        platform_terminal = PlatformEditorTerminal(
            environment={"TMUX": "/test-only/socket,1,0", "TMUX_PANE": "%4"},
            process=platform_process,
        )
        app = SloTUI(
            session=session,
            editor_launcher=EditorLauncher(
                executable_lookup=EditorLookup(),
                terminal=SessionEditorTerminal(platform_terminal=platform_terminal),
            ),
        )
        async with app.run_test() as pilot:
            await pump_until(
                pilot=pilot, predicate=lambda: session.workflow_visualizer_destination == "herdr"
            )
            assert session.workflow_visualizer_destination == "herdr"
            # Ambient focus/settings drift after capture must not retarget the request.
            monkeypatch.setenv(name="HERDR_PANE_ID", value="focus-drift")
            app.query_one(PromptInput).load_text("/code " + shlex.quote(target.name))
            await pilot.press("enter")
            await pump_until(
                pilot=pilot,
                predicate=lambda: any("submitted to Herdr" in t for t, _ in transcript_lines(app=app)),
            )
            assert any("submitted to Herdr" in t for t, _ in transcript_lines(app=app))
            records = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
            panes = [row for row in records if row[:2] in [["pane", "split"], ["pane", "run"]]]
            assert panes == [
                ["pane", "split", "--pane", "synthetic-pane", "--direction", "right", "--no-focus"],
                ["pane", "run", "editor-pane", shlex.join(("/test-only/nvim", "--", str(target)))],
            ]
            session.begin_external_reporting_close()
            app.query_one(PromptInput).load_text("/code " + shlex.quote(target.name))
            await pilot.press("enter")
            await pump_until(
                pilot=pilot,
                predicate=lambda: any("authority unavailable" in t for t, _ in transcript_lines(app=app)),
            )
            assert any("authority unavailable" in t for t, _ in transcript_lines(app=app))
        records = [json.loads(line) for line in fake_herdr.capture.read_text().splitlines()]
        assert len([row for row in records if row[:2] == ["pane", "split"]]) == 1
        assert not any(row[:2] in [["pane", "close"], ["pane", "focus"]] for row in records)
        assert not list(tmp_path.glob("sentinel*"))
        assert not session._herdr_reporter.retains_external_resources
        assert platform_process.calls == []  # Herdr success AND revocation never redirect to tmux.
