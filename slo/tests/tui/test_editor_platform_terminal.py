"""Offline terminal contracts through mounted /code; never launch real terminals."""

import asyncio
import shlex
import subprocess
import threading

import pytest
from pathlib import Path
from typing import Optional

from src.tui.app import PromptInput, SloTUI
from src.tui.editor_launcher import EditorLauncher, SessionEditorTerminal
from tests.tui._scroll_settle import pump_until
from tests.tui.test_code_command import EditorLookup, transcript_lines
from tests.tui.test_path_suggestions_app import build_path_session


class RecordingTerminalProcess:
    """Record the process boundary and return a captured active tmux owner."""

    def __init__(self, *, replies: Optional[list[str]] = None) -> None:
        """Retain scripted stdout; all commands remain inert."""
        self.calls: list[tuple[str, ...]] = []
        self.replies = replies if replies is not None else ["$2 @7 %4", ""]

    def run(self, *, argv: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        """Return the next scripted successful command result."""
        self.calls.append(argv)
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=self.replies.pop(0), stderr="")


@pytest.mark.parametrize(argnames="platform", argvalues=["darwin", "linux"])
async def test_code_active_tmux_captures_owner_and_submits_literal_command(
    tmp_path: Path, platform: str
) -> None:
    """Keyboard /code reaches active validation then new-window, never a GUI fallback."""
    from src.tui.editor_platform_terminal import PlatformEditorTerminal

    target = tmp_path / "x';$(touch sentinel)`x` ü.py"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.touch()
    environment = {"TMUX": "/test-only/socket,123,0", "TMUX_PANE": "%4", "TERM_PROGRAM": "iTerm.app"}
    process = RecordingTerminalProcess()
    terminal = PlatformEditorTerminal(environment=environment, platform=platform, process=process)
    environment["TMUX_PANE"] = "%99"
    app = SloTUI(
        session=build_path_session(workdir=tmp_path),
        editor_launcher=EditorLauncher(
            terminal=SessionEditorTerminal(platform_terminal=terminal), executable_lookup=EditorLookup()
        ),
    )
    async with app.run_test() as pilot:
        app.query_one(PromptInput).load_text("/code " + shlex.quote(target.name))
        await pilot.press("enter")
        await pump_until(
            pilot=pilot,
            predicate=lambda: any("submitted to tmux" in text for text, _ in transcript_lines(app=app)),
        )
        assert any("readiness not confirmed" in text for text, _ in transcript_lines(app=app))
        assert not app._session.is_running
    assert process.calls == [
        (
            "tmux",
            "-S",
            "/test-only/socket",
            "display-message",
            "-p",
            "-t",
            "%4",
            "#{session_id} #{window_id} #{pane_id}",
        ),
        (
            "tmux",
            "-S",
            "/test-only/socket",
            "new-window",
            "-a",
            "-d",
            "-t",
            "$2:@7",
            shlex.join(("/test-only/nvim", "--", str(target))),
        ),
    ]
    assert not list(tmp_path.glob("sentinel*"))


@pytest.mark.parametrize(
    argnames=("platform", "environment"),
    argvalues=[
        ("darwin", {}),
        ("linux", {}),
        ("linux", {"TERM_PROGRAM": "iTerm.app", "ITERM_SESSION_ID": "owner-id"}),
        ("darwin", {"TERM_PROGRAM": "Apple_Terminal", "ITERM_SESSION_ID": "owner-id"}),
    ],
)
async def test_installed_tmux_is_not_active_and_unsupported_never_probes(
    platform: str, environment: dict[str, str]
) -> None:
    """No TMUX owner means no tmux invocation, regardless of installed executables."""
    from src.tui.editor_platform_terminal import PlatformEditorTerminal

    process = RecordingTerminalProcess(replies=[])
    notice = await PlatformEditorTerminal(environment=environment, platform=platform, process=process).submit(
        argv=("/nvim", "--", "/one.py")
    )
    assert "not possible" in notice
    assert process.calls == []


@pytest.mark.parametrize(
    argnames=("environment", "reply", "count"),
    argvalues=[
        ({"TMUX": "/socket,1,0"}, "", 0),
        ({"TMUX": "bad", "TMUX_PANE": "%4"}, "", 0),
        ({"TMUX": "/socket,1,0", "TMUX_PANE": "%4"}, "no server", 1),
        ({"TMUX": "/socket,1,0", "TMUX_PANE": "%4"}, "$2 @7 %99", 1),
    ],
)
async def test_tmux_invalid_or_inactive_owner_never_falls_back(
    environment: dict[str, str], reply: str, count: int
) -> None:
    """Selected stale tmux hints fail closed even when iTerm2 hints are present."""
    from src.tui.editor_platform_terminal import PlatformEditorTerminal

    environment.update(TERM_PROGRAM="iTerm.app", ITERM_SESSION_ID="w0t0p0:owner-id")
    process = RecordingTerminalProcess(replies=[reply])
    notice = await PlatformEditorTerminal(environment=environment, platform="darwin", process=process).submit(
        argv=("/nvim", "--", "/one.py")
    )
    assert "failed" in notice
    assert len(process.calls) == count
    assert all(call[0] == "tmux" for call in process.calls)


async def test_iterm_existing_owner_script_uses_argument_boundary_and_no_window_fallback() -> None:
    """Supported AppleScript contract targets owning session, not current/focused window."""
    from src.tui.editor_platform_terminal import PlatformEditorTerminal

    process = RecordingTerminalProcess(replies=["submitted"])
    environment = {"TERM_PROGRAM": "iTerm.app", "ITERM_SESSION_ID": "w0t0p0:owner-id"}
    terminal = PlatformEditorTerminal(environment=environment, platform="darwin", process=process)
    environment["ITERM_SESSION_ID"] = "w9t9p9:focus-drift"
    argv = ("/nvim", "--", "/x';$(touch sentinel)`x` ü.py")
    notice = await terminal.submit(argv=argv)
    assert "submitted to iTerm2 new tab" in notice and "readiness not confirmed" in notice
    command, flag, script, separator, identity, editor = process.calls[0]
    assert (command, flag, separator, identity) == ("/usr/bin/osascript", "-e", "--", "owner-id")
    assert shlex.split(s=editor) == list(argv)
    assert "unique ID of ownerSession is ownerID" in script
    assert "tell ownerWindow" in script and "create tab with default profile command editorCommand" in script
    assert "current window" not in script and "create window" not in script
    assert 'application id "com.googlecode.iterm2" is not running' in script
    assert argv[-1] not in script


class FailingTerminalProcess:
    """Return failure or raise without exposing private diagnostic text."""

    def __init__(self, *, raises: bool) -> None:
        """Choose the API failure shape."""
        self.raises = raises
        self.calls = 0

    def run(self, *, argv: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        """Fail exactly one request, never create a real process."""
        self.calls += 1
        if self.raises:
            raise OSError("private terminal details")
        return subprocess.CompletedProcess(args=argv, returncode=1, stdout="", stderr="private details")


@pytest.mark.parametrize(argnames="backend", argvalues=["tmux", "iterm"])
@pytest.mark.parametrize(argnames="raises", argvalues=[False, True])
async def test_selected_api_failure_has_no_retry_or_fallback(backend: str, raises: bool) -> None:
    """Failed validation/submission remains one attempt with fixed safe evidence."""
    from src.tui.editor_platform_terminal import PlatformEditorTerminal

    environment = {"TERM_PROGRAM": "iTerm.app", "ITERM_SESSION_ID": "w0t0p0:owner-id"}
    if backend == "tmux":
        environment.update(TMUX="/socket,1,0", TMUX_PANE="%4")
    process = FailingTerminalProcess(raises=raises)
    notice = await PlatformEditorTerminal(environment=environment, platform="darwin", process=process).submit(
        argv=("/nvim", "--", "/one.py")
    )
    assert "failed" in notice and "private" not in notice
    assert process.calls == 1


@pytest.mark.parametrize(argnames="identity", argvalues=["", 'bad"id', "bad\nidentity"])
async def test_iterm_requires_supported_owner_identity(identity: str) -> None:
    """Absent/invalid ownership never invokes AppleScript or targets ambient focus."""
    from src.tui.editor_platform_terminal import PlatformEditorTerminal

    process = RecordingTerminalProcess(replies=[])
    notice = await PlatformEditorTerminal(
        environment={"TERM_PROGRAM": "iTerm.app", "ITERM_SESSION_ID": identity},
        platform="darwin",
        process=process,
    ).submit(argv=("/nvim", "--", "/one.py"))
    assert "submitted" not in notice
    assert process.calls == []


class HeldTerminalProcess:
    """Hold one finite off-thread request for deterministic cancellation proof."""

    def __init__(self, *, replies: list[str], hold_call: int) -> None:
        """Retain the selected barrier and scripted results."""
        self.entered = threading.Event()
        self.release = threading.Event()
        self.replies = replies
        self.hold_call = hold_call
        self.calls = 0

    def run(self, *, argv: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        """Gate only the chosen call and record exactly how far submission proceeded."""
        self.calls += 1
        if self.calls == self.hold_call:
            self.entered.set()
            assert self.release.wait(timeout=5)
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=self.replies.pop(0), stderr="")


@pytest.mark.parametrize(argnames="stage", argvalues=["tmux-validation", "tmux-submission", "iterm"])
async def test_terminal_cancellation_joins_current_request_and_stops_next_step(stage: str) -> None:
    """Cancellation cannot orphan a thread or launch after cancelled active-owner validation."""
    from src.tui.editor_platform_terminal import PlatformEditorTerminal

    environment = {"TERM_PROGRAM": "iTerm.app", "ITERM_SESSION_ID": "w0t0p0:owner-id"}
    tmux = stage.startswith("tmux")
    if tmux:
        environment.update(TMUX="/socket,1,0", TMUX_PANE="%4")
    hold_call = 2 if stage == "tmux-submission" else 1
    process = HeldTerminalProcess(replies=["$2 @7 %4", ""] if tmux else ["submitted"], hold_call=hold_call)
    terminal = PlatformEditorTerminal(environment=environment, platform="darwin", process=process)
    task = asyncio.create_task(coro=terminal.submit(argv=("/nvim", "--", "/one.py")))
    try:
        async with asyncio.timeout(delay=2):
            while not process.entered.is_set():
                await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        process.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(fut=task, timeout=2)
        assert process.calls == hold_call
    finally:
        process.release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(argnames="control", argvalues=["\n", "\r", "\x00", "\x1b", "\t", "\x7f", "\x85"])
async def test_platform_control_paths_refused_before_api_calls(control: str) -> None:
    """Command strings must never feed terminal line controls even when shell quoted."""
    from src.tui.editor_platform_terminal import PlatformEditorTerminal

    process = RecordingTerminalProcess(replies=[])
    notice = await PlatformEditorTerminal(
        environment={"TMUX": "/socket,1,0", "TMUX_PANE": "%4"}, process=process
    ).submit(argv=("/nvim", "--", "/bad" + control + ".py"))
    assert "refused" in notice and process.calls == []


async def test_code_iterm_mounted_submission_uses_supported_existing_owner(tmp_path: Path) -> None:
    """Mounted /code reaches iTerm2 through the real selector and metadata validation."""
    from src.tui.editor_platform_terminal import PlatformEditorTerminal

    target = tmp_path / "space ü.py"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.touch()
    process = RecordingTerminalProcess(replies=["submitted"])
    app = SloTUI(
        session=build_path_session(workdir=tmp_path),
        editor_launcher=EditorLauncher(
            terminal=SessionEditorTerminal(
                platform_terminal=PlatformEditorTerminal(
                    environment={"TERM_PROGRAM": "iTerm.app", "ITERM_SESSION_ID": "w0t0p0:captured-id"},
                    platform="darwin",
                    process=process,
                )
            ),
            executable_lookup=EditorLookup(),
        ),
    )
    async with app.run_test() as pilot:
        app.query_one(PromptInput).load_text("/code " + shlex.quote(target.name))
        await pilot.press("enter")
        await pump_until(
            pilot=pilot,
            predicate=lambda: any("submitted to iTerm2" in text for text, _ in transcript_lines(app=app)),
        )
        assert any("readiness not confirmed" in text for text, _ in transcript_lines(app=app))
        assert not app._session.is_running
    assert len(process.calls) == 1
    assert process.calls[0][-2:] == ("captured-id", shlex.join(("/test-only/nvim", "--", str(target))))


class FailTmuxSubmission(RecordingTerminalProcess):
    """Validate successfully then reject creation; no other terminal is allowed."""

    def run(self, *, argv: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        """Return a nonzero submission outcome after active-owner validation."""
        if "new-window" in argv:
            self.calls.append(argv)
            return subprocess.CompletedProcess(args=argv, returncode=1, stdout="", stderr="private")
        return super().run(argv=argv)


async def test_tmux_creation_failure_does_not_retry_or_invoke_iterm() -> None:
    """A validated owner is not permission to redirect a failed new-window request."""
    from src.tui.editor_platform_terminal import PlatformEditorTerminal

    process = FailTmuxSubmission()
    notice = await PlatformEditorTerminal(
        environment={
            "TMUX": "/socket,1,0",
            "TMUX_PANE": "%4",
            "TERM_PROGRAM": "iTerm.app",
            "ITERM_SESSION_ID": "owner-id",
        },
        platform="darwin",
        process=process,
    ).submit(argv=("/nvim", "--", "/one.py"))
    assert "failed" in notice and "private" not in notice
    assert len(process.calls) == 2 and all(call[0] == "tmux" for call in process.calls)
