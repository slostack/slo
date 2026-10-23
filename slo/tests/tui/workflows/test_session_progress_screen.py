"""Mounted tests for the session progress screen and its viewport (feature 94 a.3).

Every test mounts real Textual widgets (``App.run_test``) because the claims are
about paint, scroll offsets and layout timing. No test reads files, runs a
provider, signals a process or opens a terminal.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Optional

from unittest.mock import patch

import pytest
from pydantic import ValidationError
from textual import events
from textual.app import App, ComposeResult
from textual.pilot import Pilot
from textual.screen import ModalScreen
from textual.scrollbar import ScrollTo
from textual.theme import Theme
from textual.widgets import Button, RichLog, Static

from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME
from src.tui.workflows.dao import (
    ChildAbortTargetDAO,
    ProgressViewportDAO,
    SessionProgressSnapshotDAO,
    WorkflowSessionKeyDAO,
)
from src.tui.workflows.session_progress_screen import (
    PROGRESS_RESET_VIEW_NOTICE,
    ProgressLog,
    SessionProgressScreen,
)

_LINE_COUNT: int = 200
"""Enough lines to make a 20-row log scroll in both directions."""

_WIDE_LINE: str = "x" * 400
"""A line wider than any test terminal so horizontal panning is possible."""


class _LogHost(App[None]):
    """Host one non-wrapping RichLog filled with scrollable content."""

    def compose(self) -> ComposeResult:
        """Yield the log under test."""
        yield RichLog(wrap=False, markup=False, auto_scroll=False)

    def fill(self) -> RichLog:
        """Write enough tall and wide content to scroll on both axes.

        Returns:
            RichLog: The filled log.
        """
        log: RichLog = self.query_one(RichLog)
        for index in range(_LINE_COUNT):
            log.write(f"{index:03d} {_WIDE_LINE}", scroll_end=False)
        return log


class TestProgressViewport:
    """The viewport value captures offsets and owns the follow decision."""

    async def test_capture_at_bottom_means_following(self) -> None:
        """A log scrolled to its end captures ``following=True``."""
        app: _LogHost = _LogHost()
        async with app.run_test(size=(80, 24)) as pilot:
            log: RichLog = app.fill()
            await pilot.pause()
            log.scroll_end(animate=False, immediate=True)
            await pilot.pause()

            viewport: ProgressViewportDAO = ProgressViewportDAO.capture(log=log)

            assert viewport.following is True
            assert viewport.y == log.max_scroll_y

    async def test_capture_in_the_middle_keeps_exact_offsets(self) -> None:
        """A reader above the tail is not following and keeps both offsets."""
        app: _LogHost = _LogHost()
        async with app.run_test(size=(80, 24)) as pilot:
            log: RichLog = app.fill()
            await pilot.pause()
            log.scroll_to(x=7, y=40, animate=False, immediate=True)
            await pilot.pause()

            viewport: ProgressViewportDAO = ProgressViewportDAO.capture(log=log)

            assert viewport == ProgressViewportDAO(x=7.0, y=40.0, following=False)

    async def test_empty_log_captures_following(self) -> None:
        """An empty log has ``scroll_y == max_scroll_y == 0`` and therefore follows."""
        app: _LogHost = _LogHost()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()

            viewport: ProgressViewportDAO = ProgressViewportDAO.capture(log=app.query_one(RichLog))

            assert viewport.following is True

    async def test_restore_following_goes_to_the_tail(self) -> None:
        """A following viewport restores to the new end, whatever its saved offsets."""
        app: _LogHost = _LogHost()
        async with app.run_test(size=(80, 24)) as pilot:
            log: RichLog = app.fill()
            await pilot.pause()

            ProgressViewportDAO(x=0.0, y=3.0, following=True).restore(log=log)

            assert log.scroll_y == log.max_scroll_y

    async def test_restore_nonfollowing_clamps_to_the_scrollable_range(self) -> None:
        """Saved offsets beyond the content are clamped, never forced to the tail."""
        app: _LogHost = _LogHost()
        async with app.run_test(size=(80, 24)) as pilot:
            log: RichLog = app.fill()
            await pilot.pause()

            ProgressViewportDAO(x=5.0, y=30.0, following=False).restore(log=log)
            assert (log.scroll_x, log.scroll_y) == (5.0, 30.0)

            ProgressViewportDAO(x=10_000.0, y=10_000.0, following=False).restore(log=log)
            assert (log.scroll_x, log.scroll_y) == (log.max_scroll_x, log.max_scroll_y)

    async def test_restore_waits_for_horizontal_scrolling_to_be_enabled(self) -> None:
        """A reachable saved pan is not restored before Textual enables its scrollbar."""
        app: _LogHost = _LogHost()
        async with app.run_test(size=(80, 24)) as pilot:
            log: RichLog = app.fill()
            await pilot.pause()
            viewport: ProgressViewportDAO = ProgressViewportDAO(x=4.0, y=5.0, following=False)
            assert log.max_scroll_x >= viewport.x

            # Content measurement can precede the scrollbar-visibility layout pass.
            log.show_horizontal_scrollbar = False
            assert viewport.restore(log=log) is False
            assert (log.scroll_x, log.scroll_y) == (0.0, 5.0)

            log.show_horizontal_scrollbar = True
            assert viewport.restore(log=log) is True
            assert (log.scroll_x, log.scroll_y) == (4.0, 5.0)

    def test_viewport_is_frozen_and_defaults_to_following(self) -> None:
        """A fresh viewport is the tail-following initial intent and cannot be mutated."""
        viewport: ProgressViewportDAO = ProgressViewportDAO()

        assert (viewport.x, viewport.y, viewport.following) == (0.0, 0.0, True)
        with pytest.raises(ValidationError, match="frozen"):
            viewport.y = 4.0  # type: ignore[misc]


_KEY: WorkflowSessionKeyDAO = WorkflowSessionKeyDAO(
    orchestrator_session_id="parent-1", session_id="child-[b]1[/b]"
)
_EXECUTION_ID: str = "11111111-1111-4111-8111-111111111111"
_RUN_ID: str = "33333333-3333-4333-8333-333333333333"


def _entries(*, count: int, prefix: str = "out", width: int = 300) -> tuple[TranscriptEntryDAO, ...]:
    """Build tool entries whose output lines are wider than the log.

    Args:
        count (int): Number of entries (each paints three lines).
        prefix (str, optional): Distinguishes entry sets. Defaults to ``"out"``.
        width (int, optional): Output width in cells. Defaults to 300.

    Returns:
        tuple[TranscriptEntryDAO, ...]: Entries in order.
    """
    return tuple(
        TranscriptEntryDAO(
            kind="tool", tool_name=f"tool-{index}", output=f"{prefix}-{index:03d} " + "x" * width
        )
        for index in range(count)
    )


def _snapshot(
    *,
    entries: tuple[TranscriptEntryDAO, ...] = (),
    revision: str = "r1",
    source_generation: str = "capture:1",
    availability: str = "available",
    notice: Optional[str] = None,
    status: str = "running",
    task_text: str = "Audit the [b]parser[/b]",
    abort_target: Optional[ChildAbortTargetDAO] = None,
) -> SessionProgressSnapshotDAO:
    """Build one progress snapshot for ``_KEY``.

    Args:
        entries (tuple[TranscriptEntryDAO, ...], optional): Content. Defaults to ().
        revision (str, optional): Content revision. Defaults to ``"r1"``.
        source_generation (str, optional): Source identity. Defaults to ``"capture:1"``.
        availability (str, optional): Readability. Defaults to ``"available"``.
        notice (Optional[str], optional): Fixed notice. Defaults to None.
        status (str, optional): Execution status. Defaults to ``"running"``.
        task_text (str, optional): Task text. Defaults to a markup-like string.
        abort_target (Optional[ChildAbortTargetDAO], optional): Target. Defaults to None.

    Returns:
        SessionProgressSnapshotDAO: Snapshot.
    """
    return SessionProgressSnapshotDAO(
        key=_KEY,
        execution_id=_EXECUTION_ID,
        entries=entries,
        revision=revision,
        source_generation=source_generation,
        availability=availability,  # type: ignore[arg-type]
        observed_at=datetime(2026, 10, 18, 12, 30, 5, tzinfo=timezone.utc).isoformat(),
        notice=notice,
        task_text=task_text,
        task_text_complete=True,
        status=status,
        abort_target=abort_target,
    )


class _ScreenHost(App[None]):
    """Push one progress screen and record the semantic messages it emits."""

    def __init__(self, *, viewport: ProgressViewportDAO = ProgressViewportDAO()) -> None:
        """Remember the saved viewport the screen opens with.

        Args:
            viewport (ProgressViewportDAO, optional): Saved position. Defaults to following.
        """
        super().__init__()
        self.register_theme(SLO_DEFAULT_THEME)
        self.register_theme(SLO_DARK_THEME)
        self.theme = SLO_DARK_THEME.name
        self.screen_under_test: SessionProgressScreen = SessionProgressScreen(key=_KEY, viewport=viewport)
        self.messages: list[object] = []

    def on_mount(self) -> None:
        """Push the screen like the app sink does."""
        self.push_screen(self.screen_under_test)

    def on_session_progress_screen_minimized(self, message: SessionProgressScreen.Minimized) -> None:
        """Record a minimize request.

        Args:
            message (SessionProgressScreen.Minimized): Message.
        """
        self.messages.append(message)

    def on_session_progress_screen_abort_requested(
        self, message: SessionProgressScreen.AbortRequested
    ) -> None:
        """Record an abort request.

        Args:
            message (SessionProgressScreen.AbortRequested): Message.
        """
        self.messages.append(message)


def _log(*, app: _ScreenHost) -> ProgressLog:
    """Return the screen's progress log.

    Args:
        app (_ScreenHost): Host.

    Returns:
        ProgressLog: Log.
    """
    return app.screen_under_test.query_one(ProgressLog)


def _state_text(*, app: _ScreenHost) -> str:
    """Return the status line's literal content.

    Args:
        app (_ScreenHost): Host.

    Returns:
        str: Status text.
    """
    return str(app.screen_under_test.query_one("#session-state", Static).render())


async def _paint(*, app: _ScreenHost, pilot: Pilot[None], snapshot: SessionProgressSnapshotDAO) -> None:
    """Apply a snapshot and let layout and restoration settle.

    Args:
        app (_ScreenHost): Host.
        pilot (Pilot[None]): Pilot.
        snapshot (SessionProgressSnapshotDAO): Snapshot to paint.
    """
    app.screen_under_test.apply_snapshot(snapshot=snapshot)
    await pilot.pause()
    await pilot.pause()


class _DeferredRestores:
    """Capture the screen's post-layout callbacks so a test decides when they run."""

    def __init__(self, *, screen: SessionProgressScreen) -> None:
        """Intercept ``call_after_refresh`` on one screen.

        Args:
            screen (SessionProgressScreen): Screen under test.
        """
        self.callbacks: list[tuple[Callable[..., Any], dict[str, Any]]] = []
        screen.call_after_refresh = self._capture  # type: ignore[method-assign]

    def _capture(self, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> bool:
        """Store a callback instead of scheduling it.

        Args:
            callback (Callable[..., Any]): Callback.
            *args (Any): Unused positional arguments.
            **kwargs (Any): Keyword arguments.

        Returns:
            bool: Always True, like Textual.
        """
        self.callbacks.append((callback, kwargs))
        return True

    def run_all(self) -> None:
        """Run every captured callback once, in order."""
        callbacks, self.callbacks = self.callbacks, []
        for callback, kwargs in callbacks:
            callback(**kwargs)


class TestThinkingFormatting:
    """Readable reasoning survives mounted refresh, replay projection and reopen."""

    @pytest.mark.parametrize("theme", [SLO_DARK_THEME, SLO_DEFAULT_THEME], ids=lambda theme: theme.name)
    @pytest.mark.parametrize("size", [(60, 20), (120, 40)])
    async def test_markdown_spacing_wrap_refresh_and_reopen(
        self, theme: Theme, size: tuple[int, int]
    ) -> None:
        """RichLog paints spaced wrapped prose, styled text and exact fenced indentation."""
        source = (
            "**Readable thinking** with spaces between every word " * 4
            + "\n\nSecond paragraph.  \nHard break.\n\n```text\n    x  =  1\n```"
        )
        thinking = TranscriptEntryDAO(kind="thinking", content=source)
        answer = TranscriptEntryDAO(kind="assistant", answer="Assistant keeps spaces.")
        app = _ScreenHost(viewport=ProgressViewportDAO(following=False))
        async with app.run_test(size=size) as pilot:
            app.theme = theme.name
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=(thinking, answer)))
            log = _log(app=app)
            painted = [line.text for line in log.lines]
            assert sum("Readable thinking" in line for line in painted) >= 2
            assert all(len(line.rstrip()) <= log.scrollable_content_region.width for line in painted), (
                log.scrollable_content_region.width,
                painted,
            )
            assert any("    x  =  1" in line for line in painted)
            assert any("Assistant keeps spaces." in line for line in painted)
            assert any(
                segment.style and segment.style.bold and "Readable" in segment.text
                for line in log.lines
                for segment in line
            )
            assert "**" not in "\n".join(painted)
            assert any(not line.strip() for line in painted)
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=(thinking, answer)))
            assert [line.text for line in log.lines] == painted
            # Canonical replay carries reasoning on an assistant entry rather than a thinking entry.
            replay = TranscriptEntryDAO(kind="assistant", reasoning=source, answer=answer.answer)
            await _paint(
                app=app,
                pilot=pilot,
                snapshot=_snapshot(entries=(replay,), revision="replay", source_generation="canonical:1"),
            )
            replay_lines = [line.text for line in log.lines]
            assert sum("x  =  1" in line for line in replay_lines) == 1
            assert sum("Assistant keeps spaces." in line for line in replay_lines) == 1
            app.screen_under_test.dismiss()
            await pilot.pause()
            app.screen_under_test = SessionProgressScreen(
                key=_KEY, viewport=ProgressViewportDAO(following=False)
            )
            await app.push_screen(app.screen_under_test)
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=(replay,), revision="reopen"))
            assert [line.text.rstrip() for line in _log(app=app).lines] == [
                line.rstrip() for line in replay_lines
            ]


class TestFirstPaint:
    """First paint honours the saved viewport; an empty first paint follows the first append."""

    async def test_new_screen_first_paint_lands_at_the_tail(self) -> None:
        """A newly opened screen defaults to following and shows the newest output."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=_entries(count=40)))

            log: ProgressLog = _log(app=app)
            assert log.max_scroll_y > 0
            assert log.scroll_y == log.max_scroll_y

    async def test_empty_first_paint_follows_first_append(self) -> None:
        """An empty first paint captures following, so the first real append lands at the tail."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(availability="empty", revision="r0"))
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=_entries(count=40)))

            log: ProgressLog = _log(app=app)
            assert log.max_scroll_y > 0
            assert log.scroll_y == log.max_scroll_y

    async def test_saved_nonfollowing_first_paint_does_not_follow(self) -> None:
        """Reopening with a saved reading position restores it, even after an empty first paint."""
        app: _ScreenHost = _ScreenHost(viewport=ProgressViewportDAO(x=4.0, y=12.0, following=False))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(availability="empty", revision="r0"))
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=_entries(count=40)))

            log: ProgressLog = _log(app=app)
            assert (log.scroll_x, log.scroll_y) == (4.0, 12.0)


class TestContentUpdates:
    """Identical revisions skip, exact prefixes append, everything else rebuilds with a notice."""

    async def test_identical_revision_writes_nothing(self) -> None:
        """A repeated revision neither clears nor writes."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            snapshot: SessionProgressSnapshotDAO = _snapshot(entries=_entries(count=5))
            await _paint(app=app, pilot=pilot, snapshot=snapshot)
            log: ProgressLog = _log(app=app)
            lines: int = len(log.lines)
            with patch.object(log, "write", wraps=log.write) as write, patch.object(log, "clear") as clear:
                await _paint(app=app, pilot=pilot, snapshot=snapshot)

            write.assert_not_called()
            clear.assert_not_called()
            assert len(log.lines) == lines

    @pytest.mark.parametrize("position", ["top", "middle"])
    async def test_prefix_append_preserves_a_reading_position(self, position: str) -> None:
        """Appending below a reader at the top or middle keeps both offsets exactly."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            first: tuple[TranscriptEntryDAO, ...] = _entries(count=40)
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=first))
            log: ProgressLog = _log(app=app)
            target_y: float = 0.0 if position == "top" else 30.0
            log.scroll_to(x=6, y=target_y, animate=False, immediate=True)
            await pilot.pause()

            await _paint(
                app=app,
                pilot=pilot,
                snapshot=_snapshot(entries=first + _entries(count=10, prefix="new"), revision="r2"),
            )

            assert (log.scroll_x, log.scroll_y) == (6.0, target_y)
            assert log.scroll_y < log.max_scroll_y
            assert PROGRESS_RESET_VIEW_NOTICE not in _state_text(app=app)

    async def test_prefix_append_follows_from_the_bottom(self) -> None:
        """A reader at the tail stays at the new tail after an append."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            first: tuple[TranscriptEntryDAO, ...] = _entries(count=40)
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=first))
            log: ProgressLog = _log(app=app)
            old_max: float = log.max_scroll_y

            await _paint(
                app=app,
                pilot=pilot,
                snapshot=_snapshot(entries=first + _entries(count=10, prefix="new"), revision="r2"),
            )

            assert log.max_scroll_y > old_max
            assert log.scroll_y == log.max_scroll_y

    @pytest.mark.parametrize(
        "change",
        ["changed_entry", "source_reset", "suffix_eviction", "authoritative_empty"],
    )
    async def test_non_prefix_update_rebuilds_with_reset_notice(self, change: str) -> None:
        """A changed entry, new source, evicted head or empty source rebuilds and shows the notice."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            first: tuple[TranscriptEntryDAO, ...] = _entries(count=40)
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=first))
            log: ProgressLog = _log(app=app)
            log.scroll_to(x=0, y=20, animate=False, immediate=True)
            await pilot.pause()
            updates: dict[str, SessionProgressSnapshotDAO] = {
                "changed_entry": _snapshot(
                    entries=_entries(count=1, prefix="edited") + first[1:], revision="r2"
                ),
                "source_reset": _snapshot(entries=first, revision="r2", source_generation="capture:2"),
                "suffix_eviction": _snapshot(
                    entries=first[5:] + _entries(count=5, prefix="new"), revision="r2"
                ),
                "authoritative_empty": _snapshot(availability="empty", revision="r2"),
            }

            await _paint(app=app, pilot=pilot, snapshot=updates[change])

            painted: int = len(updates[change].entries) * 3
            assert len(log.lines) == painted
            assert PROGRESS_RESET_VIEW_NOTICE in _state_text(app=app)
            assert log.scroll_y == min(20.0, log.max_scroll_y)

    async def test_growing_last_entry_rewrites_without_notice_and_keeps_position(self) -> None:
        """A streaming last entry (same source, earlier entries unchanged) is not a reset."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            first: tuple[TranscriptEntryDAO, ...] = _entries(count=40)
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=first))
            log: ProgressLog = _log(app=app)
            log.scroll_to(x=3, y=25, animate=False, immediate=True)
            await pilot.pause()
            grown: TranscriptEntryDAO = first[-1].model_copy(update={"output": "grown " + "y" * 400})

            await _paint(
                app=app,
                pilot=pilot,
                snapshot=_snapshot(
                    entries=first[:-1] + (grown,) + _entries(count=2, prefix="new"), revision="r2"
                ),
            )

            assert len(log.lines) == 42 * 3
            assert (log.scroll_x, log.scroll_y) == (3.0, 25.0)
            assert PROGRESS_RESET_VIEW_NOTICE not in _state_text(app=app)

    async def test_reset_notice_clears_on_the_next_user_navigation(self) -> None:
        """The reset notice stays beside the status until the reader navigates."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=_entries(count=40)))
            await _paint(
                app=app,
                pilot=pilot,
                snapshot=_snapshot(entries=_entries(count=40), revision="r2", source_generation="capture:2"),
            )
            assert PROGRESS_RESET_VIEW_NOTICE in _state_text(app=app)

            await pilot.press("up")
            await pilot.pause()

            assert PROGRESS_RESET_VIEW_NOTICE not in _state_text(app=app)

    @pytest.mark.parametrize("availability", ["stale", "unavailable"])
    async def test_stale_and_unavailable_keep_last_good_content(self, availability: str) -> None:
        """A failed read changes only the status line; content and position stay."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=_entries(count=40)))
            log: ProgressLog = _log(app=app)
            log.scroll_to(x=0, y=10, animate=False, immediate=True)
            await pilot.pause()
            lines: int = len(log.lines)

            await _paint(
                app=app,
                pilot=pilot,
                snapshot=_snapshot(
                    availability=availability,
                    revision="",
                    notice="Progress unavailable; retrying.",
                    status="unknown",
                ),
            )

            assert len(log.lines) == lines
            assert log.scroll_y == 10.0
            state: str = _state_text(app=app)
            assert "Progress unavailable; retrying." in state
            assert "running" in state
            assert "12:30:05" in state


class TestNavigationWins:
    """User navigation between delivery and layout cancels the scheduled restoration."""

    async def test_no_navigation_restores(self) -> None:
        """Without user input the captured position is restored after layout."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            first: tuple[TranscriptEntryDAO, ...] = _entries(count=40)
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=first))
            log: ProgressLog = _log(app=app)
            log.scroll_to(x=0, y=15, animate=False, immediate=True)
            await pilot.pause()
            deferred: _DeferredRestores = _DeferredRestores(screen=app.screen_under_test)

            app.screen_under_test.apply_snapshot(
                snapshot=_snapshot(entries=first + _entries(count=3), revision="r2")
            )
            log.scroll_to(x=0, y=0, animate=False, immediate=True)
            deferred.run_all()

            assert log.scroll_y == 15.0

    @pytest.mark.parametrize("navigation", ["key", "wheel", "drag"])
    async def test_navigation_between_delivery_and_layout_wins(self, navigation: str) -> None:
        """Key, wheel and scrollbar-drag input after delivery keeps the user's position."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            first: tuple[TranscriptEntryDAO, ...] = _entries(count=40)
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=first))
            log: ProgressLog = _log(app=app)
            log.scroll_to(x=0, y=15, animate=False, immediate=True)
            await pilot.pause()
            deferred: _DeferredRestores = _DeferredRestores(screen=app.screen_under_test)
            app.screen_under_test.apply_snapshot(
                snapshot=_snapshot(entries=first + _entries(count=3), revision="r2")
            )
            revision: int = log.navigation_revision

            if navigation == "key":
                await pilot.press("home")
            elif navigation == "wheel":
                log.post_message(
                    events.MouseScrollUp(
                        widget=log,
                        x=1,
                        y=1,
                        delta_x=0,
                        delta_y=-1,
                        button=0,
                        shift=False,
                        meta=False,
                        ctrl=False,
                    )
                )
            else:
                log.post_message(ScrollTo(y=2))
            await pilot.pause()
            user_y: float = log.scroll_y
            deferred.run_all()

            assert log.navigation_revision > revision
            assert log.scroll_y == user_y
            assert user_y != 15.0

    async def test_restore_after_unmount_is_harmless(self) -> None:
        """A restoration callback arriving after the screen left is ignored."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            deferred: _DeferredRestores = _DeferredRestores(screen=app.screen_under_test)
            app.screen_under_test.apply_snapshot(snapshot=_snapshot(entries=_entries(count=40)))
            log: ProgressLog = _log(app=app)
            app.screen_under_test.dismiss()
            await pilot.pause()
            assert not app.screen_under_test.is_attached
            offsets: tuple[float, float] = (log.scroll_x, log.scroll_y)

            deferred.run_all()

            assert (log.scroll_x, log.scroll_y) == offsets

    async def test_end_follows_and_horizontal_offset_persists(self) -> None:
        """End re-establishes following; a horizontal pan survives the next append."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            first: tuple[TranscriptEntryDAO, ...] = _entries(count=40)
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=first))
            await pilot.press("home", "pagedown", "right", "right", "right")
            await pilot.wait_for_scheduled_animations()
            await pilot.press("end")
            await pilot.wait_for_scheduled_animations()
            await pilot.pause()
            log: ProgressLog = _log(app=app)
            panned_x: float = log.scroll_x
            assert panned_x > 0

            await _paint(
                app=app,
                pilot=pilot,
                snapshot=_snapshot(entries=first + _entries(count=10, prefix="new"), revision="r2"),
            )

            assert log.scroll_y == log.max_scroll_y
            assert log.scroll_x == panned_x


class TestSubtleScrollbars:
    """Modal scrollbars remain usable at the minimum nonzero cell size."""

    @pytest.mark.parametrize("theme", [SLO_DARK_THEME, SLO_DEFAULT_THEME], ids=lambda theme: theme.name)
    @pytest.mark.parametrize("size", [(60, 20), (120, 40)])
    @pytest.mark.parametrize("status", ["running", "completed"])
    async def test_minimum_dimensions_and_both_scroll_axes(
        self, theme: Theme, size: tuple[int, int], status: str
    ) -> None:
        """Both themes keep subtle bars and real keyboard scrolling for all statuses."""
        app = _ScreenHost()
        async with app.run_test(size=size) as pilot:
            app.theme = theme.name
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=_entries(count=80), status=status))
            log = _log(app=app)
            task_scroll = app.screen_under_test.query_one("#task-scroll")
            for widget in (log, task_scroll):
                assert widget.styles.scrollbar_size_vertical == 1
                assert widget.styles.scrollbar_size_horizontal == 1
                assert 0 < widget.styles.scrollbar_color.a <= 0.25
                assert widget.styles.scrollbar_color_hover.a > widget.styles.scrollbar_color.a
            assert log.show_vertical_scrollbar and log.show_horizontal_scrollbar
            assert log.vertical_scrollbar.size.width == 1
            assert log.horizontal_scrollbar.size.height == 1
            await pilot.press("home", "pagedown", "right", "right")
            await pilot.wait_for_scheduled_animations()
            assert log.scroll_y > 0
            assert log.scroll_x > 0
            await pilot.press("end")
            await pilot.wait_for_scheduled_animations()
            assert log.scroll_y == log.max_scroll_y

    async def test_external_log_keeps_framework_scrollbar_dimensions(self) -> None:
        """The modal stylesheet must not change the external RichLog renderer."""
        app = _LogHost()
        async with app.run_test(size=(80, 24)) as pilot:
            log = app.fill()
            await pilot.pause()
            assert log.styles.scrollbar_size_vertical == 2
            assert log.styles.scrollbar_size_horizontal == 1
            assert log.styles.scrollbar_color.a > 0.25


class TestControls:
    """Escape/Minimize emit intent only; Abort follows the snapshot's target."""

    async def test_escape_and_minimize_button_post_minimized(self) -> None:
        """Escape and the Minimize button both ask the app to minimize, nothing else."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.click("#minimize")
            await pilot.pause()

            assert [type(message) for message in app.messages] == [
                SessionProgressScreen.Minimized,
                SessionProgressScreen.Minimized,
            ]
            assert app.screen is app.screen_under_test

    async def test_retire_closes_an_active_view_at_once(self) -> None:
        """A retired view on top of the stack leaves it immediately without posting intent."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.screen_under_test.retire()
            await pilot.pause()

            assert app.screen_under_test not in app.screen_stack
            assert app.messages == []

    async def test_retire_under_a_modal_waits_and_never_pops_the_modal(self) -> None:
        """A covered retired view keeps the modal on top, then leaves once the modal closes."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            modal: ModalScreen[None] = ModalScreen()
            await app.push_screen(modal)
            app.screen_under_test.retire()
            await pilot.pause()

            assert app.screen is modal
            assert app.screen_under_test in app.screen_stack
            modal.dismiss()
            await pilot.pause()
            await pilot.pause()

            assert app.screen_under_test not in app.screen_stack
            assert len(app.screen_stack) == 1
            assert app.messages == []

    async def test_retired_view_never_pops_a_modal_swapped_in_above_it(self) -> None:
        """A modal swap above a retired view keeps the new modal; the view leaves only once uncovered."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            first: ModalScreen[None] = ModalScreen()
            second: ModalScreen[None] = ModalScreen()
            await app.push_screen(first)
            app.screen_under_test.retire()
            await pilot.pause()

            first.dismiss()
            app.push_screen(second)
            await pilot.pause()
            await pilot.pause()

            assert app.screen is second
            assert app.screen_under_test in app.screen_stack
            second.dismiss()
            await pilot.pause()
            await pilot.pause()

            assert app.screen_under_test not in app.screen_stack
            assert len(app.screen_stack) == 1

    async def test_retire_before_the_first_resume_closes_once(self) -> None:
        """Retiring in the same block as the push leaves a base-only stack without a second pop."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.screen_under_test.retire()
            await pilot.pause()
            fresh: SessionProgressScreen = SessionProgressScreen(key=_KEY, viewport=ProgressViewportDAO())

            app.push_screen(fresh)
            fresh.retire()
            await pilot.pause()
            await pilot.pause()

            assert fresh not in app.screen_stack
            assert len(app.screen_stack) == 1
            assert app.return_code is None

    async def test_repeated_retire_closes_the_view_once(self) -> None:
        """Retiring twice pops only the view and never the base screen."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.screen_under_test.retire()
            app.screen_under_test.retire()
            await pilot.pause()
            await pilot.pause()

            assert app.screen_under_test not in app.screen_stack
            assert len(app.screen_stack) == 1
            assert app.return_code is None

    async def test_resume_without_retirement_keeps_the_view(self) -> None:
        """A view that was only covered stays open when the modal above it closes."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            modal: ModalScreen[None] = ModalScreen()
            await app.push_screen(modal)
            modal.dismiss()
            await pilot.pause()

            assert app.screen is app.screen_under_test

    async def test_abort_is_disabled_without_a_target(self) -> None:
        """Without an abort target the button is disabled and clicking emits nothing."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=_entries(count=2)))

            button: Button = app.screen_under_test.query_one("#abort-child", Button)
            assert button.disabled is True
            await pilot.click("#abort-child")
            assert app.messages == []

    async def test_abort_emits_the_displayed_target(self) -> None:
        """An eligible snapshot enables Abort, which carries that exact target."""
        app: _ScreenHost = _ScreenHost()
        target: ChildAbortTargetDAO = ChildAbortTargetDAO(
            key=_KEY, run_id=_RUN_ID, execution_id=_EXECUTION_ID
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await _paint(
                app=app, pilot=pilot, snapshot=_snapshot(entries=_entries(count=2), abort_target=target)
            )

            await pilot.click("#abort-child")
            await pilot.pause()

            assert len(app.messages) == 1
            message: object = app.messages[0]
            assert isinstance(message, SessionProgressScreen.AbortRequested)
            assert message.target == target

    async def test_withdrawn_target_disables_abort_and_shows_request_notice(self) -> None:
        """A later snapshot without a target (request pending) disables Abort and paints its notice."""
        app: _ScreenHost = _ScreenHost()
        target: ChildAbortTargetDAO = ChildAbortTargetDAO(
            key=_KEY, run_id=_RUN_ID, execution_id=_EXECUTION_ID
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await _paint(
                app=app, pilot=pilot, snapshot=_snapshot(entries=_entries(count=2), abort_target=target)
            )
            await _paint(
                app=app,
                pilot=pilot,
                snapshot=_snapshot(
                    entries=_entries(count=2),
                    notice="Abort requested; waiting for the orchestrator to confirm.",
                ),
            )

            button: Button = app.screen_under_test.query_one("#abort-child", Button)
            assert button.disabled is True
            assert "Abort requested; waiting for the orchestrator to confirm." in _state_text(app=app)
            assert "running" in _state_text(app=app)
            await pilot.click("#abort-child")
            assert app.messages == []

    async def test_stale_snapshot_disables_abort_but_keeps_content(self) -> None:
        """A status-only failure (stale) disables Abort while the last good content stays painted."""
        app: _ScreenHost = _ScreenHost()
        target: ChildAbortTargetDAO = ChildAbortTargetDAO(
            key=_KEY, run_id=_RUN_ID, execution_id=_EXECUTION_ID
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await _paint(
                app=app, pilot=pilot, snapshot=_snapshot(entries=_entries(count=2), abort_target=target)
            )
            painted: int = len(_log(app=app).lines)
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(availability="stale", revision=""))

            assert app.screen_under_test.query_one("#abort-child", Button).disabled is True
            assert len(_log(app=app).lines) == painted

    async def test_literal_identity_task_and_status(self) -> None:
        """Session id, task text and status paint literally, never as markup."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await _paint(
                app=app, pilot=pilot, snapshot=_snapshot(entries=_entries(count=2), status="[i]running[/i]")
            )

            screen: SessionProgressScreen = app.screen_under_test
            assert "child-[b]1[/b]" in str(screen.query_one("#progress-heading", Static).render())
            assert str(screen.query_one("#task-description", Static).render()) == "Audit the [b]parser[/b]"
            assert "[i]running[/i]" in _state_text(app=app)

    async def test_long_task_text_scrolls_independently_in_three_rows(self) -> None:
        """Full task text stays readable in a three-row scroll area above the log."""
        app: _ScreenHost = _ScreenHost()
        long_task: str = "\n".join(f"task line {index}" for index in range(12))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await _paint(
                app=app, pilot=pilot, snapshot=_snapshot(entries=_entries(count=2), task_text=long_task)
            )

            container = app.screen_under_test.query_one("#task-scroll")
            assert container.region.height == 3
            assert container.max_scroll_y > 0


class TestLayout:
    """Both themes at 60x20, 80x24 and 120x40 keep every control reachable."""

    @pytest.mark.parametrize("theme", [SLO_DARK_THEME, SLO_DEFAULT_THEME], ids=lambda theme: theme.name)
    @pytest.mark.parametrize(
        ("width", "height", "stacked"),
        [(60, 20, True), (80, 24, False), (120, 40, False)],
        ids=["60x20", "80x24", "120x40"],
    )
    async def test_buttons_reachable_and_log_visible(
        self, theme: Theme, width: int, height: int, stacked: bool
    ) -> None:
        """Buttons lie inside the screen, stack below 80 columns, and the log keeps rows."""
        app: _ScreenHost = _ScreenHost()
        async with app.run_test(size=(width, height)) as pilot:
            app.theme = theme.name
            await pilot.pause()
            await _paint(app=app, pilot=pilot, snapshot=_snapshot(entries=_entries(count=40)))

            screen: SessionProgressScreen = app.screen_under_test
            minimize: Button = screen.query_one("#minimize", Button)
            abort: Button = screen.query_one("#abort-child", Button)
            for button in (minimize, abort):
                assert button.region.height >= 1
                assert button.region.right <= width
                assert button.region.bottom <= height
            assert (minimize.region.y != abort.region.y) is stacked
            assert _log(app=app).region.height >= 3
            await pilot.click("#minimize")
            await pilot.pause()
            assert len(app.messages) == 1


class TestRestoreConvergence:
    """A restore clamped by unfinished layout retries until the saved offsets land."""

    async def test_restore_reports_whether_saved_offsets_landed(self) -> None:
        """Following and in-range restores land; out-of-range offsets are clamped."""
        app: _LogHost = _LogHost()
        async with app.run_test(size=(80, 24)) as pilot:
            log: RichLog = app.fill()
            await pilot.pause()

            assert ProgressViewportDAO(x=0.0, y=3.0, following=True).restore(log=log) is True
            assert ProgressViewportDAO(x=5.0, y=30.0, following=False).restore(log=log) is True
            assert ProgressViewportDAO(x=10_000.0, y=10_000.0, following=False).restore(log=log) is False

    async def test_saved_pan_retries_after_scrollbar_visibility_changes(self) -> None:
        """A reopened modal keeps its saved pan while scrollbar layout catches up."""
        saved: ProgressViewportDAO = ProgressViewportDAO(x=4.0, y=5.0, following=False)
        app: _ScreenHost = _ScreenHost(viewport=saved)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen: SessionProgressScreen = app.screen_under_test
            deferred: _DeferredRestores = _DeferredRestores(screen=screen)
            screen.apply_snapshot(snapshot=_snapshot(entries=_entries(count=40)))
            await pilot.pause()
            log: ProgressLog = _log(app=app)
            assert log.max_scroll_x >= saved.x

            log.show_horizontal_scrollbar = False
            deferred.run_all()
            assert (log.scroll_x, log.scroll_y) == (0.0, 5.0)
            log.show_horizontal_scrollbar = True
            await pilot.pause()

            assert (log.scroll_x, log.scroll_y) == (4.0, 5.0)

    async def test_clamped_restore_retries_when_the_log_is_laid_out(self) -> None:
        """Reopening before wide lines are laid out must not lose the saved pan."""
        app: _ScreenHost = _ScreenHost(viewport=ProgressViewportDAO(x=4.0, y=5.0, following=False))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            deferred: _DeferredRestores = _DeferredRestores(screen=app.screen_under_test)
            app.screen_under_test.apply_snapshot(snapshot=_snapshot(entries=_entries(count=40)))

            with patch.object(ProgressViewportDAO, "restore", side_effect=[False, True, True]) as restore:
                deferred.run_all()
                _log(app=app).post_message(ProgressLog.LayoutChanged())
                await pilot.pause()
                _log(app=app).post_message(ProgressLog.LayoutChanged())
                await pilot.pause()

            assert restore.call_count == 2

    async def test_pending_saved_position_survives_a_new_paint(self) -> None:
        """A newer paint restores the still-unmet saved position, not the clamped one."""
        saved: ProgressViewportDAO = ProgressViewportDAO(x=4.0, y=5.0, following=False)
        app: _ScreenHost = _ScreenHost(viewport=saved)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            deferred: _DeferredRestores = _DeferredRestores(screen=app.screen_under_test)
            first: tuple[TranscriptEntryDAO, ...] = _entries(count=40)
            app.screen_under_test.apply_snapshot(snapshot=_snapshot(entries=first))

            with patch.object(ProgressViewportDAO, "restore", return_value=False):
                deferred.run_all()
            app.screen_under_test.apply_snapshot(
                snapshot=_snapshot(entries=first + _entries(count=3), revision="r2")
            )
            [(_callback, kwargs)] = deferred.callbacks

            assert kwargs["viewport"] == saved

    async def test_navigation_cancels_a_pending_restore(self) -> None:
        """Reader input after a clamped restore wins over the pending retry."""
        app: _ScreenHost = _ScreenHost(viewport=ProgressViewportDAO(x=4.0, y=5.0, following=False))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            deferred: _DeferredRestores = _DeferredRestores(screen=app.screen_under_test)
            app.screen_under_test.apply_snapshot(snapshot=_snapshot(entries=_entries(count=40)))

            with patch.object(ProgressViewportDAO, "restore", return_value=False) as restore:
                deferred.run_all()
                _log(app=app).post_message(ScrollTo(y=2))
                await pilot.pause()
                _log(app=app).post_message(ProgressLog.LayoutChanged())
                await pilot.pause()

            assert restore.call_count == 1
