"""Dense metadata validation decisions not duplicated across mounted journeys."""

import asyncio
import threading
import shutil
from pathlib import Path

import pytest

from src.tui.editor_launcher import EditorLauncher
from tests.tui.test_code_command import EditorLookup, RecordingEditorTerminal
from tests.tui.test_path_suggestions_app import build_path_session


@pytest.mark.parametrize(argnames="form", argvalues=["absolute", "parent", "symlink", "escaped"])
async def test_code_path_forms_resolve_against_session(tmp_path: Path, form: str) -> None:
    """Existing files resolve literally without consulting process cwd or opening content."""
    target = tmp_path / "space ü.py"
    nested = tmp_path / "project"
    link = tmp_path / "link.py"
    for path in (target, nested, link):
        assert path.resolve().is_relative_to(tmp_path.resolve())
    target.touch()
    nested.mkdir()
    link.symlink_to(target)
    argument = {
        "absolute": f'"{target}"',
        "parent": '"../space ü.py"',
        "symlink": "../link.py",
        "escaped": "../space\\ ü.py",
    }[form]
    terminal = RecordingEditorTerminal()
    notice = await EditorLauncher(terminal=terminal, executable_lookup=EditorLookup()).invoke(
        argument=argument,
        session=build_path_session(workdir=nested),
    )
    assert "submitted" in notice
    assert terminal.calls == [("/test-only/nvim", "--", str(target))]


@pytest.mark.parametrize(
    argnames="argument", argvalues=["'\x00'", "~no_such_slo_user_987654/file", "broken.py"]
)
async def test_code_path_resolution_errors_remain_safe(tmp_path: Path, argument: str) -> None:
    """NUL, unknown homes and broken symlinks never submit a launch."""
    broken = tmp_path / "broken.py"
    assert broken.resolve().is_relative_to(tmp_path.resolve())
    broken.symlink_to(tmp_path / "absent.py")
    terminal = RecordingEditorTerminal()
    notice = await EditorLauncher(terminal=terminal, executable_lookup=EditorLookup()).invoke(
        argument=argument,
        session=build_path_session(workdir=tmp_path),
    )
    assert terminal.calls == []
    assert "Traceback" not in notice


@pytest.mark.parametrize(argnames="path_entry", argvalues=["bin", ":"])
async def test_discovered_editor_keeps_process_cwd_and_symlink_spelling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path_entry: str
) -> None:
    """Real relative/empty PATH lookup freezes invocation identity before crossing cwd."""
    discovery = tmp_path / "discovery"
    session_dir = tmp_path / "session"
    bin_dir = discovery / "bin" if path_entry == "bin" else discovery
    for directory in (discovery, session_dir, bin_dir):
        assert directory.resolve().is_relative_to(tmp_path.resolve())
        directory.mkdir(exist_ok=True)
    executable = bin_dir / "editor-wrapper"
    link = bin_dir / "nvim"
    target = session_dir / "one.py"
    for path in (executable, link, target):
        assert path.resolve().is_relative_to(tmp_path.resolve())
    executable.write_text(data="never executed", encoding="utf-8")
    executable.chmod(mode=0o700)
    link.symlink_to(executable.name)
    target.touch()
    monkeypatch.chdir(discovery)
    monkeypatch.setenv(name="PATH", value=path_entry)
    assert shutil.which(cmd="nvim") == ("bin/nvim" if path_entry == "bin" else "nvim")
    terminal = RecordingEditorTerminal()
    session = build_path_session(workdir=session_dir)
    assert Path.cwd() == discovery

    notice = await EditorLauncher(terminal=terminal).invoke(argument="one.py", session=session)

    assert "submitted" in notice
    assert terminal.calls == [(str(link), "--", str(target))]
    assert Path(terminal.calls[0][0]).is_absolute()
    assert Path(terminal.calls[0][0]).is_symlink()
    assert Path(terminal.calls[0][0]).resolve() == executable


async def test_code_validation_runs_off_loop_and_cancellation_joins(tmp_path: Path) -> None:
    """A blocked lookup remains owned until released; cancellation never submits."""
    target = tmp_path / "one.py"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.touch()
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    thread_ids: list[int] = []

    def lookup(*, cmd: str) -> str:
        """Hold the off-thread validation collaborator with a finite barrier."""
        assert cmd == "nvim"
        thread_ids.append(threading.get_ident())
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=5)
        return "/nvim"

    terminal = RecordingEditorTerminal()
    task = asyncio.create_task(
        coro=EditorLauncher(terminal=terminal, executable_lookup=lookup).invoke(
            argument="one.py",
            session=build_path_session(workdir=tmp_path),
        )
    )
    try:
        await asyncio.wait_for(fut=entered.wait(), timeout=2)
        assert thread_ids != [threading.get_ident()]
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(fut=task, timeout=2)
        assert terminal.calls == []
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
