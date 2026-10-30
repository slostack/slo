"""Local editor journeys: real keyboard, registry, validation and launch boundary."""

import asyncio
import shlex
from pathlib import Path
from typing import Optional

import pytest

from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import PromptInput, SloTUI
from tests.tui.test_path_suggestions_app import build_path_session
from tests.tui._scroll_settle import pump_until


class RecordingEditorTerminal:
    """Record argv without touching a terminal; optionally hold or fail submission."""

    def __init__(self, *, fail: bool = False, hold: bool = False) -> None:
        """Configure a deterministic submission boundary."""
        self.calls: list[tuple[str, ...]] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()
        self.fail = fail
        if not hold:
            self.release.set()

    async def submit(self, *, argv: tuple[str, ...], session: SloAgentSession) -> str:
        """Capture the resolved argv and wait only at this injected boundary."""
        del session
        self.calls.append(argv)
        self.entered.set()
        try:
            await self.release.wait()
            if self.fail:
                raise RuntimeError("private terminal secret")
            return "Editor command submitted; readiness not confirmed."
        finally:
            self.finished.set()


@pytest.mark.parametrize(argnames="prefix", argvalues=["", "RE"])
async def test_code_tab_discovers_argument_then_accepts_and_submits_file(tmp_path: Path, prefix: str) -> None:
    """Tab after the command token completes a real file, never the command again.

    Drive the mounted input through the actual slash router and file validation;
    only executable discovery and terminal submission are injected. All writes
    stay in the test directory and the empty Faux model must remain unused.

    Args:
        tmp_path (Path): Disposable session cwd and filesystem root.
        prefix (str): Empty argument or slash-free literal basename prefix.
    """
    from src.tui.editor_launcher import EditorLauncher

    target: Path = tmp_path / "README.md"
    directory: Path = tmp_path / "assets"
    for path in (target, directory):
        assert path.resolve().is_relative_to(tmp_path.resolve())
    target.write_text(data="PRIVATE COMPLETION CONTENT", encoding="utf-8")
    directory.mkdir()
    terminal = RecordingEditorTerminal()
    app = SloTUI(
        session=build_path_session(workdir=tmp_path),
        editor_launcher=EditorLauncher(terminal=terminal, executable_lookup=EditorLookup()),
    )

    async with app.run_test() as pilot:
        prompt: PromptInput = app.query_one(PromptInput)
        entered: str = "/code " + prefix
        for key in entered:
            await pilot.press(key)
        await pilot.pause()
        assert not app._slash_suggestion_state.visible

        await pilot.press("tab")
        await pump_until(
            pilot=pilot,
            predicate=lambda: app._slash_suggestion_state.visible,
        )
        assert prompt.text == entered
        assert app._slash_suggestion_state.kind == "path"
        assert [row.label for row in app._slash_suggestion_state.rows] == (
            ["assets/", "README.md"] if not prefix else ["README.md"]
        )
        if not prefix:
            await pilot.press("down")
        await pilot.press("tab")
        await pilot.pause()
        assert prompt.text == "/code README.md"
        assert prompt.cursor_location == (0, len(prompt.text))
        assert not app._slash_suggestion_state.visible

        await pilot.press("enter")
        await pump_until(pilot=pilot, predicate=terminal.finished.is_set)
        assert terminal.calls == [("/test-only/nvim", "--", str(target.resolve()))]
        assert prompt.text == ""
        assert not app._session.is_running
        assert any("readiness not confirmed" in text for text, _ in transcript_lines(app=app))
        assert all("PRIVATE COMPLETION CONTENT" not in text for text, _ in transcript_lines(app=app))

    assert app._path_suggestions._task is None


@pytest.mark.parametrize(argnames="name", argvalues=[".", "space ü", "-c;$(touch sentinel)`x`'\""])
async def test_code_keyboard_submits_literal_existing_directory(tmp_path: Path, name: str) -> None:
    """Directories, including session cwd, cross the same literal editor boundary."""
    from src.tui.editor_launcher import EditorLauncher

    target = tmp_path / name
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.mkdir(exist_ok=True)
    terminal = RecordingEditorTerminal()
    app = SloTUI(
        session=build_path_session(workdir=tmp_path),
        editor_launcher=EditorLauncher(terminal=terminal, executable_lookup=EditorLookup()),
    )
    async with app.run_test() as pilot:
        app.query_one(PromptInput).load_text("/code " + shlex.quote(name))
        await pilot.press("enter")
        await pump_until(
            pilot=pilot,
            predicate=lambda: bool(transcript_lines(app=app)),
        )
        await pump_until(pilot=pilot, predicate=lambda: not app._editor_launch_tasks)
        assert terminal.calls == [("/test-only/nvim", "--", str(target.resolve()))]
        assert not app._session.is_running


class EditorLookup:
    """Return a fixed executable identity rather than invoking host tools."""

    def __init__(self, *, available: bool = True) -> None:
        """Retain the requested availability."""
        self.available = available

    def __call__(self, *, cmd: str) -> Optional[str]:
        """Model executable discovery without starting a process."""
        assert cmd == "nvim"
        return "/test-only/nvim" if self.available else None


@pytest.mark.parametrize(argnames="name", argvalues=["one.py", "space ü.py", "-c;$(touch sentinel)`x`'\".py"])
async def test_code_keyboard_resolves_literal_file_without_model(tmp_path: Path, name: str) -> None:
    """Enter routes locally through validation and sends exactly one safe argv."""
    from src.tui.editor_launcher import EditorLauncher

    target = tmp_path / name
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.write_text(data="PRIVATE CONTENT MUST NOT BE ATTACHED", encoding="utf-8")
    terminal = RecordingEditorTerminal()
    app = SloTUI(
        session=build_path_session(workdir=tmp_path),
        editor_launcher=EditorLauncher(terminal=terminal, executable_lookup=EditorLookup()),
    )
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.load_text("/code " + shlex.quote(name))
        await pilot.press("enter")
        await pump_until(pilot=pilot, predicate=terminal.finished.is_set)
        assert terminal.calls == [("/test-only/nvim", "--", str(target.resolve()))]
        assert not app._session.is_running
        assert prompt.text == ""
        assert any("readiness not confirmed" in text for text, _ in transcript_lines(app=app))
        assert all("PRIVATE CONTENT" not in text for text, _ in transcript_lines(app=app))
        assert not list(tmp_path.glob("sentinel*"))


@pytest.mark.parametrize(
    argnames=("argument", "available", "message"),
    argvalues=[
        ("", True, "Usage: /code"),
        ("missing.py", True, "existing file"),
        ("'unterminated", True, "Usage: /code"),
        ("one.py two.py", True, "Usage: /code"),
        ("one.py", False, "nvim is unavailable"),
    ],
)
async def test_code_rejects_invalid_request_without_launch(
    tmp_path: Path, argument: str, available: bool, message: str
) -> None:
    """Rejected paths/executable availability render safely and keep slash input usable."""
    from src.tui.editor_launcher import EditorLauncher

    target = tmp_path / "one.py"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.touch()
    terminal = RecordingEditorTerminal()
    app = SloTUI(
        session=build_path_session(workdir=tmp_path),
        editor_launcher=EditorLauncher(
            terminal=terminal, executable_lookup=EditorLookup(available=available)
        ),
    )
    async with app.run_test() as pilot:
        app.query_one(PromptInput).load_text("/code " + argument)
        await pilot.press("enter")
        await pump_until(
            pilot=pilot, predicate=lambda: any(message in text for text, _ in transcript_lines(app=app))
        )
        assert any(message in text for text, _ in transcript_lines(app=app))
        assert terminal.calls == []
        app.query_one(PromptInput).load_text("/cwd")
        await pilot.press("enter")
        await pilot.pause()
        assert any(str(tmp_path) in text for text, _ in transcript_lines(app=app))
        assert not app._session.is_running


def transcript_lines(*, app: SloTUI) -> list[tuple[str, str]]:
    """Read the mounted semantic transcript seam with explicit lifetime validation."""
    assert app._adapter is not None
    return app._adapter.lines
