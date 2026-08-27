"""Pilot tests for the focused GitDiffScreen."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from src.tui.git_diff_content_service import GitDiffContentDAO
from src.tui.git_diff_screen import GitDiffScreen
from src.tui.slodiff.model import FileStateKind
from src.tui.slodiff.view import SloDiffView
from src.tui.widgets.literal_text_static import LiteralTextStatic


def _content() -> GitDiffContentDAO:
    """Build representative validated content for screen tests."""
    return GitDiffContentDAO(
        repository_relative_path="src/foo[bar].py",
        base_content="a\n",
        changed_content="b\n",
        file_state=FileStateKind.MODIFIED,
    )


class _HostApp(App[None]):
    """Push the target screen immediately for Pilot interaction tests."""

    def compose(self) -> ComposeResult:
        """Yield no base widgets below the pushed modal screen."""
        yield from ()

    async def on_mount(self) -> None:
        """Push the diff screen when the test host is ready."""
        self.push_screen(GitDiffScreen(content=_content()))


class TestGitDiffScreen:
    """Screen layout, controls, and dismissal coverage."""

    def test_build_summary_text_when_content_is_modified_formats_counts(self) -> None:
        """The summary uses canonical path, state, and count vocabulary."""
        assert (
            GitDiffScreen._build_summary_text(content=_content(), additions=1, removals=1)
            == "src/foo[bar].py — modified — +1 -1"
        )

    async def test_screen_when_mounted_uses_literal_summary_and_diff_view(self) -> None:
        """Paths with brackets remain literal and the core view is hosted."""
        app = _HostApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one(".git-diff-summary", LiteralTextStatic)
            assert app.screen.query_one("#git-diff-scroll", VerticalScroll)
            assert app.screen.query_one(SloDiffView).split is False

    async def test_screen_when_control_keys_pressed_toggles_view_reactives(self) -> None:
        """Screen-owned bindings delegate the three display controls to SloDiffView."""
        app = _HostApp()
        async with app.run_test(size=(160, 24)) as pilot:
            await pilot.pause()
            view = app.screen.query_one(SloDiffView)
            initial = (view.split, view.wrap, view.annotations)
            await pilot.press("s", "w", "a")
            assert (view.split, view.wrap, view.annotations) == tuple(not value for value in initial)
            assert view.split is True

    async def test_screen_when_escape_pressed_dismisses(self) -> None:
        """Escape returns the operator to the host transcript screen."""
        app = _HostApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            assert not isinstance(app.screen, GitDiffScreen)
