"""Real prompt/file journeys for the bounded path-completion slice."""

import asyncio
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from textual.widgets import Static

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import PromptInput, SloTUI
from src.tui.path_suggestion_engine import PathSuggestionEngine, PathSuggestionQueryDAO
from src.tui.slash_suggestion_engine import SlashSuggestionStateDAO
from src.tui.widgets.slash_suggestion_menu import SlashSuggestionMenu
from tests.tui._scroll_settle import pump_until


def build_path_session(*, workdir: Path) -> SloAgentSession:
    """Inject only a scripted third-party LLM; filesystem and session stay real.

    Args:
        workdir: Test-owned directory used as the session cwd.

    Returns:
        Resource-owned session that must never call its unused model here.
    """
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[]), cwd=str(workdir), tools=[]),
        workdir=workdir,
        session_id=str(uuid4()),
    )


class TestPathSuggestionJourney:
    """Keyboard entry reaches real directory enumeration and menu acceptance."""

    async def test_prefix_menu_and_file_acceptance_preserve_cursor_text(self, tmp_path: Path) -> None:
        """Slash lists immediate children; narrowing and Tab edit only the path span."""
        source = tmp_path / "src"
        assert source.resolve().is_relative_to(tmp_path.resolve())
        source.mkdir()
        for name in ("alpha", "zeta"):
            directory = source / name
            assert directory.resolve().is_relative_to(tmp_path.resolve())
            directory.mkdir()
        for name in ("abc.py", "readme.md"):
            target = source / name
            assert target.resolve().is_relative_to(tmp_path.resolve())
            target.write_text(data="not attached", encoding="utf-8")
        nested = source / "alpha" / "not-immediate.txt"
        assert nested.resolve().is_relative_to(tmp_path.resolve())
        nested.write_text(data="not indexed", encoding="utf-8")
        app = SloTUI(session=build_path_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            prompt = app.query_one(PromptInput)
            menu = app.query_one(SlashSuggestionMenu)
            prompt.load_text("Review\nuse src later")
            prompt.move_cursor(location=(1, 7))
            await pilot.press("/")
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
            assert [row.label for row in app._slash_suggestion_state.rows] == [
                "alpha/",
                "zeta/",
                "abc.py",
                "readme.md",
            ]
            assert str(menu.query_one(Static).content).splitlines() == [
                "› alpha/",
                "  zeta/",
                "  abc.py",
                "  readme.md",
                "Showing 4 of 4 — type to narrow",
            ]
            assert "not-immediate" not in str(menu.query_one(Static).content)

            await pilot.press("a")
            await pump_until(
                pilot=pilot,
                predicate=lambda: len(app._slash_suggestion_state.rows) == 2,
            )
            assert [row.label for row in app._slash_suggestion_state.rows] == ["alpha/", "abc.py"]
            await pilot.press("down")
            await pilot.press("tab")
            await pilot.pause()
            assert prompt.text == "Review\nuse src/abc.py later"
            assert prompt.cursor_location == (1, 14)
            assert menu.has_class("-hidden")
            prompt.action_undo()
            await pilot.pause()
            assert prompt.text == "Review\nuse src/a later"
            assert not app._session.is_running

    async def test_single_line_path_window_scrolls_and_preserves_command_details(
        self, tmp_path: Path
    ) -> None:
        """Path capacity uses one line per row; slash commands retain their descriptions."""
        for index in range(30):
            target = tmp_path / f"file-{index:02}.py"
            assert target.resolve().is_relative_to(tmp_path.resolve())
            target.touch()
        app = SloTUI(session=build_path_session(workdir=tmp_path))
        async with app.run_test(size=(120, 40)) as pilot:
            prompt = app.query_one(PromptInput)
            menu = app.query_one(SlashSuggestionMenu)
            await pilot.press(".", "/")
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
            lines = str(menu.query_one(Static).content).splitlines()
            assert lines[0] == "› file-00.py"
            assert lines[-2:] == ["  file-24.py", "Showing 25 of 30 — type to narrow"]
            assert len(lines) == 26
            await pilot.press("up")
            await pilot.pause()
            lines = str(menu.query_one(Static).content).splitlines()
            assert lines[-2] == "› file-29.py"
            await pilot.press("tab")
            await pilot.pause()
            assert prompt.text == "./file-29.py"
            assert not app._slash_suggestion_state.visible

            prompt.load_text("/he")
            prompt.move_cursor(location=(0, 3))
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
            row = app._slash_suggestion_state.rows[0]
            assert row.label == "/help" and row.detail
            assert str(menu.query_one(Static).content).splitlines()[:2] == [
                "› /help",
                f"  {row.detail}",
            ]
            assert not app._session.is_running

    @pytest.mark.parametrize(
        argnames=("separator", "display_separator"),
        argvalues=[
            ("\n", r"\n"),
            ("\r", r"\r"),
            ("\r\n", r"\r\n"),
            ("\v", r"\v"),
            ("\f", r"\f"),
            ("\x1c", r"\x1c"),
            ("\x1d", r"\x1d"),
            ("\x1e", r"\x1e"),
            ("\x85", r"\x85"),
            ("\u2028", r"\u2028"),
            ("\u2029", r"\u2029"),
        ],
    )
    async def test_newline_label_is_one_row_in_short_layout_and_inserts_literal_path(
        self, tmp_path: Path, separator: str, display_separator: str
    ) -> None:
        """Display escaped line breaks without changing the accepted filesystem token."""
        import shlex

        filename = f"line{separator}break.py"
        target = tmp_path / filename
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.touch()
        app = SloTUI(session=build_path_session(workdir=tmp_path))
        async with app.run_test(size=(60, 16)) as pilot:
            prompt = app.query_one(PromptInput)
            await pilot.press(".", "/")
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
            menu = app.query_one(SlashSuggestionMenu)
            assert str(menu.query_one(Static).content).splitlines() == [
                f"› line{display_separator}break.py",
                "Showing 1 of 1 — type to narrow",
            ]
            assert menu.region.bottom <= prompt.region.y
            insert_text = app._slash_suggestion_state.rows[0].insert_text
            await pilot.press("tab")
            await pilot.pause()
            assert shlex.split(prompt.text) == [f"./{filename}"]
            assert prompt.text == insert_text
            assert prompt.cursor_location == prompt.document.end
            prompt.action_undo()
            await pilot.pause()
            assert prompt.text == "./"
            assert prompt.cursor_location == (0, 2)
            prompt.action_redo()
            await pilot.pause()
            assert prompt.text == insert_text
            assert prompt.cursor_location == prompt.document.end

    @pytest.mark.parametrize("separator", ["\r", "\r\n", "\n", "\u2028"])
    @pytest.mark.parametrize("quote", ["", "'", '"'])
    async def test_separator_directory_navigation_preserves_quotes_cursor_and_undo(
        self, tmp_path: Path, separator: str, quote: str
    ) -> None:
        """Complete a literal directory then its child without losing suffix or undo history."""
        import shlex

        directory = tmp_path / f"line{separator}quote'and\"dir"
        assert directory.resolve().is_relative_to(tmp_path.resolve())
        directory.mkdir()
        target = directory / "child.py"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.touch()
        app = SloTUI(session=build_path_session(workdir=tmp_path))
        async with app.run_test() as pilot:
            prompt = app.query_one(PromptInput)
            original = f"before\nuse {quote}./li{quote} later"
            prompt.load_text(original)
            prompt.move_cursor(location=(1, len(f"use {quote}./li")))
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
            await pilot.press("tab")
            await pump_until(
                pilot=pilot,
                predicate=lambda: [row.label for row in app._slash_suggestion_state.rows] == ["child.py"],
            )
            directory_text = prompt.text
            directory_cursor = prompt.cursor_location
            assert shlex.split(directory_text) == ["before", "use", f"./{directory.name}/", "later"]
            assert (
                prompt.document.get_text_range(prompt.cursor_location, prompt.document.end)
                == quote + " later"
            )
            await pilot.press("tab")
            await pilot.pause()
            accepted = prompt.text
            assert shlex.split(accepted) == ["before", "use", f"./{directory.name}/child.py", "later"]
            assert prompt.document.get_text_range(prompt.cursor_location, prompt.document.end) == " later"
            await pilot.press("left", "right")
            assert prompt.document.get_text_range(prompt.cursor_location, prompt.document.end) == " later"
            prompt.action_undo()
            await pilot.pause()
            assert prompt.text == directory_text
            assert prompt.cursor_location == directory_cursor
            prompt.action_undo()
            await pilot.pause()
            assert prompt.text == original
            prompt.action_redo()
            prompt.action_redo()
            await pilot.pause()
            assert prompt.text == accepted

    async def test_directory_acceptance_lists_contents_and_escape_keeps_text(self, tmp_path: Path) -> None:
        """Tab navigates directories; Escape dismisses without modifying the prompt.

        Args:
            tmp_path: Test-owned filesystem root.
        """
        directory = tmp_path / "src" / "alpha"
        assert directory.resolve().is_relative_to(tmp_path.resolve())
        directory.mkdir(parents=True)
        target = directory / "one.py"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.write_text(data="never attached", encoding="utf-8")
        app = SloTUI(session=build_path_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            prompt = app.query_one(PromptInput)
            menu = app.query_one(SlashSuggestionMenu)
            await pilot.press("s", "r", "c", "/")
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
            assert [row.label for row in app._slash_suggestion_state.rows] == ["alpha/"]
            await pilot.press("tab")
            await pump_until(
                pilot=pilot,
                predicate=lambda: [row.label for row in app._slash_suggestion_state.rows] == ["one.py"],
            )
            assert prompt.text == "src/alpha/"
            assert prompt.cursor_location == (0, 10)
            assert "one.py" in str(menu.query_one(Static).content)
            await pilot.press("escape")
            await pilot.pause()
            assert prompt.text == "src/alpha/"
            assert menu.has_class("-hidden")
            assert app._path_suggestions._query is None
            assert not app._session.is_running

        assert app._path_suggestions._task is None

    @pytest.mark.parametrize(
        argnames=("entered", "expected"),
        argvalues=[
            ('use "src dir/é', 'use "src dir/écho.py" later'),
            ("use 'src dir/é", "use 'src dir/écho.py' later"),
            (r"use src\ dir/é", r"use src\ dir/écho.py later"),
            ("use plain", "use plain.py later"),
        ],
    )
    async def test_quoted_or_tab_prefix_accepts_whole_token(
        self, tmp_path: Path, entered: str, expected: str
    ) -> None:
        """Tab discovers plain prefixes and safely replaces quoted mid-token paths."""
        directory = tmp_path / "src dir"
        assert directory.resolve().is_relative_to(tmp_path.resolve())
        directory.mkdir()
        for target in (directory / "écho.py", tmp_path / "plain.py"):
            assert target.resolve().is_relative_to(tmp_path.resolve())
            target.write_text(data="private contents", encoding="utf-8")
        app = SloTUI(session=build_path_session(workdir=tmp_path))
        async with app.run_test(size=(120, 40)) as pilot:
            prompt = app.query_one(PromptInput)
            prompt.load_text(
                entered + ('junk"' if '"' in entered else "junk'" if "'" in entered else "junk") + " later"
            )
            prompt.move_cursor(location=(0, len(entered)))
            await pilot.pause()
            if "/" not in entered:
                await pilot.press("tab")
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
            assert app._slash_suggestion_state.kind == "path"
            await pilot.press("tab")
            await pilot.pause()
            assert prompt.text == expected
            assert prompt.cursor_location == (0, len(expected) - len(" later"))
            assert not app._slash_suggestion_state.visible
            prompt.action_undo()
            await pilot.pause()
            assert prompt.text.endswith(" later") and "junk" in prompt.text


class ControlledPathReader:
    """Gate one off-thread evaluation, then delegate to real directory enumeration."""

    def __init__(self, *, fail: bool = False) -> None:
        """Record worker identity and gate the first call; optional failure tests containment."""
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls: list[PathSuggestionQueryDAO] = []
        self.threads: list[int] = []
        self.fail = fail

    def evaluate(self, *, query: PathSuggestionQueryDAO) -> SlashSuggestionStateDAO:
        """Wait with a safety bound, then evaluate real files or inject a collaborator failure."""
        self.calls.append(query)
        self.threads.append(threading.get_ident())
        if len(self.calls) == 1:
            self.entered.set()
            if not self.release.wait(timeout=5):
                raise TimeoutError("test reader not released")
            if self.fail:
                raise RuntimeError("synthetic private filesystem failure")
        return PathSuggestionEngine.evaluate(query=query)


class TestPathReaderLifetime:
    """Controlled scheduling proves stale rejection and failure-safe owned shutdown."""

    @pytest.mark.parametrize(
        argnames="cutoff", argvalues=["edit", "cursor", "selection", "escape", "shutdown"]
    )
    async def test_pending_read_never_publishes_after_revocation(self, tmp_path: Path, cutoff: str) -> None:
        """One slow read never blocks keyboard input, spawns a parallel read or paints stale rows."""
        for name in ("old", "new"):
            directory = tmp_path / name
            assert directory.resolve().is_relative_to(tmp_path.resolve())
            directory.mkdir()
            target = directory / f"{name}.py"
            assert target.resolve().is_relative_to(tmp_path.resolve())
            target.touch()
        reader = ControlledPathReader()
        session = build_path_session(workdir=tmp_path)
        app = SloTUI(session=session, path_reader=reader)
        shutdown: asyncio.Task[None] | None = None
        async with app.run_test(size=(120, 40)) as pilot:
            try:
                prompt = app.query_one(PromptInput)
                await pilot.press(*"old/")
                await pump_until(pilot=pilot, predicate=reader.entered.is_set)
                assert reader.entered.is_set()
                workers = [worker for worker in app.workers if worker.group == "path-suggestions"]
                assert len(workers) == 1 and workers[0].is_running
                assert reader.threads == [reader.threads[0]]
                assert reader.threads[0] != threading.get_ident()
                if cutoff == "edit":
                    prompt.load_text("new/")
                    prompt.move_cursor(location=(0, 4))
                elif cutoff == "cursor":
                    await pilot.press("left")
                elif cutoff == "selection":
                    await pilot.press("shift+left")
                elif cutoff == "escape":
                    await pilot.press("escape")
                else:
                    shutdown = asyncio.create_task(coro=app.on_unmount())
                await pilot.pause()
                if cutoff == "shutdown":
                    await pump_until(
                        pilot=pilot, predicate=lambda: app._render_event not in session._subscribers
                    )
                    assert app._render_event not in session._subscribers
                    assert shutdown is not None and not shutdown.done()
                assert len(reader.calls) == 1
                assert not app._slash_suggestion_state.visible
                reader.release.set()
                await pump_until(pilot=pilot, predicate=lambda: app._path_suggestions._task is None)
                assert app._path_suggestions._task is None
                if cutoff == "edit":
                    assert [row.label for row in app._slash_suggestion_state.rows] == ["new.py"]
                    assert len(reader.calls) == 2
                else:
                    assert not app._slash_suggestion_state.visible
                    assert len(reader.calls) == 1
                if shutdown is not None:
                    await asyncio.wait_for(fut=shutdown, timeout=3)
                    assert app._render_event not in session._subscribers
            finally:
                reader.release.set()
        assert app._path_suggestions._task is None

    async def test_reader_failure_does_not_skip_other_shutdown_cleanup(self, tmp_path: Path) -> None:
        """An unexpected reader error is consumed without bypassing session unsubscribe."""
        reader = ControlledPathReader(fail=True)
        session = build_path_session(workdir=tmp_path)
        app = SloTUI(session=session, path_reader=reader)
        async with app.run_test() as pilot:
            try:
                await pilot.press(*"src/")
                await pump_until(pilot=pilot, predicate=reader.entered.is_set)
                shutdown = asyncio.create_task(coro=app.on_unmount())
                await pilot.pause()
                reader.release.set()
                await asyncio.wait_for(fut=shutdown, timeout=3)
                assert app._render_event not in session._subscribers
                assert not app._slash_suggestion_state.visible
            finally:
                reader.release.set()
        assert app._path_suggestions._task is None


async def test_path_worker_repeated_cancel_blocks_parallel_read_until_join(tmp_path: Path) -> None:
    """Cancelling supervision cannot release a live reader or publish its stale output."""
    target = tmp_path / "one.py"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.touch()
    reader = ControlledPathReader()
    app = SloTUI(session=build_path_session(workdir=tmp_path), path_reader=reader)
    async with app.run_test() as pilot:
        try:
            await pilot.press(".", "/")
            await pump_until(pilot=pilot, predicate=reader.entered.is_set)
            worker = next(worker for worker in app.workers if worker.group == "path-suggestions")
            worker.cancel()
            await asyncio.sleep(0)
            worker.cancel()
            await pilot.pause()
            await pilot.press("o")
            assert len(reader.calls) == 1
            assert not worker.is_finished
            assert app._path_suggestions._task is not None
            reader.release.set()
            await pump_until(pilot=pilot, predicate=lambda: worker.is_finished)
            assert not app._slash_suggestion_state.visible
            assert len(reader.calls) == 1
            await pilot.press("tab")
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
            assert [row.label for row in app._slash_suggestion_state.rows] == ["one.py"]
        finally:
            reader.release.set()


class TestPathContextJourneys:
    """Representative path forms cross the real mounted entry, not just parser methods."""

    @pytest.mark.parametrize(
        argnames="form", argvalues=["dot", "parent", "home", "absolute", "code", "quote-directory"]
    )
    async def test_path_forms_navigate_real_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str
    ) -> None:
        """Relative, tilde, absolute and future command arguments keep their literal spelling."""
        directory = tmp_path / "src"
        assert directory.resolve().is_relative_to(tmp_path.resolve())
        directory.mkdir()
        target = directory / "one.py"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.touch()
        monkeypatch.setenv(name="HOME", value=str(tmp_path))
        workdir = directory if form == "parent" else tmp_path
        prefixes = {
            "dot": "./src/",
            "parent": "../src/",
            "home": "~/src/",
            "absolute": f"use {directory}/",
            "code": "/code src/",
            "quote-directory": 'use "./s',
        }
        prefix = prefixes[form]
        app = SloTUI(session=build_path_session(workdir=workdir))
        async with app.run_test(size=(120, 40)) as pilot:
            prompt = app.query_one(PromptInput)
            await pilot.press(*prefix)
            await pump_until(
                pilot=pilot,
                predicate=lambda: app._slash_suggestion_state.visible
                and app._slash_suggestion_state.kind == "path",
            )
            if form == "quote-directory":
                assert [row.label for row in app._slash_suggestion_state.rows] == ["src/"]
                await pilot.press("tab")
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: [row.label for row in app._slash_suggestion_state.rows] == ["one.py"],
                )
                prefix = 'use "./src/'
                assert prompt.text == prefix + '"'
            await pilot.press("up", "tab")
            await pilot.pause()
            assert prompt.text == prefix + "one.py" + ('"' if form == "quote-directory" else "")
            assert not app._slash_suggestion_state.visible
            assert not app._session.is_running

    async def test_tab_discovery_stays_live_while_narrowing_and_can_reopen(self, tmp_path: Path) -> None:
        """Explicit discovery remains active through plain basename edits and Escape/Tab reopening."""
        for name in ("alpha.py", "alpine.py", "beta.py"):
            target = tmp_path / name
            assert target.resolve().is_relative_to(tmp_path.resolve())
            target.touch()
        app = SloTUI(session=build_path_session(workdir=tmp_path))
        async with app.run_test() as pilot:
            prompt = app.query_one(PromptInput)
            await pilot.press("a", "tab")
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
            await pilot.press("l", "p", "h")
            await pump_until(
                pilot=pilot,
                predicate=lambda: [row.label for row in app._slash_suggestion_state.rows] == ["alpha.py"],
            )
            assert [row.label for row in app._slash_suggestion_state.rows] == ["alpha.py"]
            await pilot.press("escape")
            await pilot.pause()
            assert prompt.text == "alph" and not app._slash_suggestion_state.visible
            await pilot.press("tab")
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
            await pilot.press("tab")
            await pilot.pause()
            assert prompt.text == "alpha.py"

    async def test_explicit_discovery_ends_at_token_boundary(self, tmp_path: Path) -> None:
        """Tab completion must not keep enumerating cwd while the user resumes prose."""
        target = tmp_path / "alpha.py"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.touch()
        reader = ControlledPathReader()
        reader.release.set()
        app = SloTUI(session=build_path_session(workdir=tmp_path), path_reader=reader)
        async with app.run_test() as pilot:
            await pilot.press("a", "tab")
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
            assert app._slash_suggestion_state.visible
            count = len(reader.calls)
            await pilot.press(" ", "p", "r", "o", "s", "e")
            await pilot.pause()
            assert not app._slash_suggestion_state.visible
            assert len(reader.calls) == count

    async def test_path_enter_submits_literal_prompt_to_real_history(self, tmp_path: Path) -> None:
        """Enter submits rather than completing or attaching the highlighted file contents."""
        from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore

        directory = tmp_path / "src"
        assert directory.resolve().is_relative_to(tmp_path.resolve())
        directory.mkdir()
        target = directory / "one.py"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.write_text(data="SECRET_NEVER_ATTACHED", encoding="utf-8")
        history_root = tmp_path / "history"
        assert history_root.resolve().is_relative_to(tmp_path.resolve())
        store = FilesystemSessionHistoryStore(root=history_root)
        session = SloAgentSession(
            agent=SloAgent(
                llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="done")]),
                cwd=str(tmp_path),
                tools=[],
            ),
            workdir=tmp_path,
            session_id=str(uuid4()),
            history_store=store,
            enable_history=True,
        )
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.press(*"use src/")
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
            await pilot.press("enter")
            await pump_until(
                pilot=pilot,
                predicate=lambda: app._in_flight_task is None and app.query_one(PromptInput).text == "",
            )
            assert not app._slash_suggestion_state.visible
        events = await store.load_events(session_id=session.session_id)
        assert [event.payload.content for event in events if event.kind == "user_message"] == ["use src/"]
        assert "SECRET_NEVER_ATTACHED" not in "".join(event.model_dump_json() for event in events)
        assert any(event.kind == "run_completed" for event in events)


async def test_quoted_directory_navigation_preserves_following_prose(tmp_path: Path) -> None:
    """A directory completion inside closed quotes keeps the next argument outside the path."""
    directory = tmp_path / "src dir"
    assert directory.resolve().is_relative_to(tmp_path.resolve())
    directory.mkdir()
    target = directory / "one.py"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.touch()
    app = SloTUI(session=build_path_session(workdir=tmp_path))
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.load_text('use "./s" later')
        prompt.move_cursor(location=(0, len('use "./s')))
        await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
        assert app._slash_suggestion_state.rows[0].label == "src dir/"
        await pilot.press("tab")
        await pump_until(
            pilot=pilot,
            predicate=lambda: [row.label for row in app._slash_suggestion_state.rows] == ["one.py"],
        )
        assert [row.label for row in app._slash_suggestion_state.rows] == ["one.py"]
        assert prompt.text == 'use "./src dir/" later'
        assert prompt.cursor_location == (0, len('use "./src dir/'))
        await pilot.press("tab")
        await pilot.pause()
        assert prompt.text == 'use "./src dir/one.py" later'


class TestPathFailureJourneys:
    """Real symlinks/errors and stale keyboard acceptance through mounted UI entry points."""

    @pytest.mark.parametrize(
        argnames="prefix", argvalues=["missing/", "empty/", "plain.py/", "~slo_nonexistent_user_934817/"]
    )
    async def test_bad_or_empty_parent_keeps_prompt_usable(self, tmp_path: Path, prefix: str) -> None:
        """Predictable filesystem failures hide completion and leave ordinary keyboard input intact."""
        empty = tmp_path / "empty"
        assert empty.resolve().is_relative_to(tmp_path.resolve())
        empty.mkdir()
        target = tmp_path / "plain.py"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.touch()
        app = SloTUI(session=build_path_session(workdir=tmp_path))
        async with app.run_test() as pilot:
            prompt = app.query_one(PromptInput)
            await pilot.press(*prefix)
            await pump_until(pilot=pilot, predicate=lambda: app._path_suggestions._task is None)
            assert app._path_suggestions._task is None
            assert not app._slash_suggestion_state.visible
            await pilot.press("x")
            assert prompt.text == prefix + "x"

    async def test_symlinks_are_literal_immediate_entries_and_navigable(self, tmp_path: Path) -> None:
        """Directory links navigate, file/broken links close, and no recursive search happens."""
        root = tmp_path / "src"
        assert root.resolve().is_relative_to(tmp_path.resolve())
        root.mkdir()
        directory = tmp_path / "target"
        assert directory.resolve().is_relative_to(tmp_path.resolve())
        directory.mkdir()
        file = directory / "one.py"
        assert file.resolve().is_relative_to(tmp_path.resolve())
        file.touch()
        for name, destination in (
            ("dir-link", directory),
            ("file-link", file),
            ("broken", tmp_path / "absent"),
        ):
            link = root / name
            assert link.resolve().is_relative_to(tmp_path.resolve())
            assert destination.resolve().is_relative_to(tmp_path.resolve())
            link.symlink_to(destination)
        app = SloTUI(session=build_path_session(workdir=tmp_path))
        async with app.run_test() as pilot:
            prompt = app.query_one(PromptInput)
            await pilot.press(*"src/")
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
            assert [row.label for row in app._slash_suggestion_state.rows] == [
                "dir-link/",
                "broken",
                "file-link",
            ]
            await pilot.press("up", "tab")
            await pilot.pause()
            assert prompt.text == "src/file-link" and not app._slash_suggestion_state.visible
            prompt.load_text("src/")
            prompt.move_cursor(location=(0, 4))
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
            await pilot.press("tab")
            await pump_until(
                pilot=pilot,
                predicate=lambda: [row.label for row in app._slash_suggestion_state.rows] == ["one.py"],
            )
            assert prompt.text == "src/dir-link/"
            await pilot.press("tab")
            await pilot.pause()
            assert prompt.text == "src/dir-link/one.py"
            prompt.load_text("src/b")
            prompt.move_cursor(location=(0, 5))
            await pump_until(
                pilot=pilot,
                predicate=lambda: [row.label for row in app._slash_suggestion_state.rows] == ["broken"],
            )
            await pilot.press("tab")
            await pilot.pause()
            assert prompt.text == "src/broken" and not app._slash_suggestion_state.visible

    @pytest.mark.parametrize(argnames="change", argvalues=["text", "cursor", "selection"])
    async def test_stale_acceptance_is_rejected_before_change_message(
        self, tmp_path: Path, change: str
    ) -> None:
        """A queued Tab can never apply an old span after synchronous prompt edits."""
        from textual.document._document import Selection

        directory = tmp_path / "src"
        assert directory.resolve().is_relative_to(tmp_path.resolve())
        directory.mkdir()
        target = directory / "one.py"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.touch()
        app = SloTUI(session=build_path_session(workdir=tmp_path))
        async with app.run_test() as pilot:
            prompt = app.query_one(PromptInput)
            await pilot.press(*"src/")
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
            if change == "text":
                prompt.load_text("do not replace")
            elif change == "cursor":
                prompt.move_cursor(location=(0, 1))
            else:
                prompt.selection = Selection(start=(0, 0), end=(0, 2))
            expected = (prompt.text, prompt.selection)
            app.on_prompt_input_suggestion_accepted(PromptInput.SuggestionAccepted())
            assert (prompt.text, prompt.selection) == expected
            await pilot.pause()


class DeniedPathReader:
    """Inject an OS permission failure at the off-thread filesystem boundary."""

    def evaluate(self, *, query: PathSuggestionQueryDAO) -> SlashSuggestionStateDAO:
        """Raise as an inaccessible filesystem would, without relying on root mode bits."""
        raise PermissionError("synthetic inaccessible parent")


async def test_permission_failure_is_hidden_and_typing_recovers(tmp_path: Path) -> None:
    """Permission errors under elevated tests use a controlled collaborator, not chmod fiction."""
    app = SloTUI(session=build_path_session(workdir=tmp_path), path_reader=DeniedPathReader())
    async with app.run_test() as pilot:
        await pilot.press(*"src/")
        await pump_until(pilot=pilot, predicate=lambda: app._path_suggestions._task is None)
        assert app._path_suggestions._task is None
        assert not app._slash_suggestion_state.visible
        await pilot.press("escape", "x")
        assert app.query_one(PromptInput).text == "src/x"


async def test_unchanged_refresh_does_no_read_or_menu_replacement(tmp_path: Path) -> None:
    """The reused menu guard and captured-query guard skip unchanged prompt events."""
    target = tmp_path / "one.py"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.touch()
    reader = ControlledPathReader()
    reader.release.set()
    app = SloTUI(session=build_path_session(workdir=tmp_path), path_reader=reader)
    async with app.run_test() as pilot:
        await pilot.press(".", "/")
        await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
        assert app._slash_suggestion_state.visible
        menu = app.query_one(SlashSuggestionMenu)
        original_state = menu._state
        app._refresh_slash_suggestions()
        app._refresh_slash_suggestions()
        menu.update_state(state=original_state.model_copy())
        await pilot.pause()
        assert len(reader.calls) == 1
        assert menu._state is original_state
        await pilot.press("escape")
        await pilot.pause()
        app._refresh_slash_suggestions()
        await pilot.pause()
        assert len(reader.calls) == 1
        assert not app._slash_suggestion_state.visible
