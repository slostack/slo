"""Mounted paint tests for the two horizontal prompt rules (spec 94.a.1).

The prompt frame is styling only: ``src/tui/app.tcss`` paints a top and bottom
rule around the native ``PromptInput`` editor, with no side edges or corners.
Widget model state cannot prove a painted frame, so every assertion reads the
compositor cells inside the editor's own region through the shared
authentication capture helpers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Callable, Optional
from unittest.mock import patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from rich.color import Color
from rich.color_triplet import ColorTriplet
from textual.pilot import Pilot
from textual.strip import Strip
from textual.theme import Theme

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import PromptInput, SloTUI
from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME
from src.tui.widgets.queued_prompt_block import QueuedPromptBlock
from tests.tui._scroll_settle import pump_until
from tests.tui.authentication._painted_output import painted_widget_strips

HORIZONTAL_RULE_GLYPH: str = "─"
"""Glyph Textual paints for a ``solid`` top or bottom edge."""

FRAME_SIDE_AND_CORNER_GLYPHS: frozenset[str] = frozenset("│┃║╭╮╰╯┌┐└┘┏┓┗┛╔╗╚╝▊▎▌▐█")
"""Vertical-edge and corner glyphs of every Textual border style; none may frame the editor."""


@dataclass(frozen=True)
class PaintedPromptFrame:
    """Compositor rows painted inside the mounted ``PromptInput`` region.

    Attributes:
        rows (list[Strip]): Painted rows, top rule first and bottom rule last.
    """

    rows: list[Strip]

    @classmethod
    def capture(cls, *, app: SloTUI) -> PaintedPromptFrame:
        """Read the editor's painted rows from the running compositor.

        WHO: Every prompt-rule test after its paint barrier.
        WHEN: After a pilot pause so the latest layout has rendered.

        Args:
            app (SloTUI): Mounted application whose prompt editor is read.

        Returns:
            PaintedPromptFrame: The painted rows of the editor region.
        """
        assert app._input is not None
        return cls(rows=painted_widget_strips(app=app, widget=app._input))

    @property
    def top_rule(self) -> str:
        """str: Painted text of the first editor row."""
        return self.rows[0].text

    @property
    def bottom_rule(self) -> str:
        """str: Painted text of the last editor row."""
        return self.rows[-1].text

    @property
    def content_rows(self) -> list[str]:
        """list[str]: Painted text of every row between the two rules."""
        return [row.text for row in self.rows[1:-1]]

    def assert_horizontal_rules(self, *, width: int) -> None:
        """Assert two full-width horizontal rules and no side edge or corner.

        Args:
            width (int): Expected painted width of the editor region in cells.

        Raises:
            AssertionError: A rule is partial, or a side edge or corner glyph is painted.
        """
        expected_rule: str = HORIZONTAL_RULE_GLYPH * width
        assert self.top_rule == expected_rule, f"top rule painted {self.top_rule!r}"
        assert self.bottom_rule == expected_rule, f"bottom rule painted {self.bottom_rule!r}"
        assert self.content_rows, "the rules must enclose at least one content row"
        edge_cells: set[str] = {row[0] for row in self.content_rows} | {row[-1] for row in self.content_rows}
        assert not edge_cells & FRAME_SIDE_AND_CORNER_GLYPHS, f"side/corner glyphs painted: {edge_cells!r}"

    def assert_rules_coloured(self, *, accent_hex: str) -> None:
        """Assert both rules paint in the active theme's accent colour.

        Args:
            accent_hex (str): ``#rrggbb`` accent token of the active theme.

        Raises:
            AssertionError: A rule cell is painted in a different foreground colour.
        """
        expected_triplet: ColorTriplet = Color.parse(accent_hex).get_truecolor()
        rule_colours: set[Optional[ColorTriplet]] = {
            segment.style.color.get_truecolor() if segment.style and segment.style.color else None
            for row in (self.rows[0], self.rows[-1])
            for segment in row
            if segment.text.strip()
        }
        assert rule_colours == {expected_triplet}, f"rule colours {rule_colours!r} != {expected_triplet!r}"


def _build_session(*, workdir: Path) -> SloAgentSession:
    """Build a real session driven by a Faux model; no provider is contacted.

    Args:
        workdir (Path): Test-owned working directory.

    Returns:
        SloAgentSession: Session ready to drive a mounted ``SloTUI``.
    """
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="ok")])),
        workdir=workdir,
        session_id=str(uuid4()),
    )


def _recording_invoke(
    *, invoke_log: list[str], release: asyncio.Event
) -> Callable[..., AsyncIterator[AgentStreamEventDAO]]:
    """Build a faux ``session.invoke`` that records each prompt and holds the turn open.

    WHO: The queue and submission tests, patched over the real session's ``invoke``.
    WHEN: Each prompt submission; the turn stays active until ``release`` is set.

    Args:
        invoke_log (list[str]): Receives every submitted prompt text, in order.
        release (asyncio.Event): Completes every held turn once set.

    Returns:
        Callable[..., AsyncIterator[AgentStreamEventDAO]]: Async generator compatible with
            ``SloAgentSession.invoke``.
    """

    async def _invoke(*, text: str) -> AsyncIterator[AgentStreamEventDAO]:
        invoke_log.append(text)
        await release.wait()
        yield AgentStreamEventDAO(kind="text_delta", delta="ok")

    return _invoke


async def _submit_prompt(*, app: SloTUI, pilot: Pilot, text: str) -> None:
    """Load a prompt into the editor and submit it with a bare Enter.

    Args:
        app (SloTUI): Mounted application.
        pilot (Pilot): Pilot driving the application.
        text (str): Prompt text to submit.
    """
    _require_prompt_input(app=app).load_text(text)
    await pilot.press("enter")
    await pilot.pause()


def _require_prompt_input(*, app: SloTUI) -> PromptInput:
    """Return the mounted prompt editor.

    Args:
        app (SloTUI): Mounted application.

    Returns:
        PromptInput: The mounted prompt editor.
    """
    assert app._input is not None
    return app._input


class TestPromptInputRulesPaint:
    """The prompt editor paints exactly two horizontal rules in every state."""

    @pytest.mark.parametrize("theme", [SLO_DARK_THEME, SLO_DEFAULT_THEME], ids=lambda theme: theme.name)
    @pytest.mark.usefixtures("theme_colors")
    async def test_rules_when_focused_and_unfocused(self, tmp_path: Path, theme: Theme) -> None:
        """Focused and unfocused editors both paint accent-coloured top/bottom rules only."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            app.theme = theme.name
            prompt_input: PromptInput = _require_prompt_input(app=app)
            assert theme.accent is not None
            accent_hex: str = theme.accent

            prompt_input.focus()
            await pilot.pause()
            assert prompt_input.has_focus
            focused: PaintedPromptFrame = PaintedPromptFrame.capture(app=app)
            focused.assert_horizontal_rules(width=prompt_input.region.width)
            focused.assert_rules_coloured(accent_hex=accent_hex)

            assert app._transcript_scroll is not None
            app._transcript_scroll.focus()
            await pilot.pause()
            assert not prompt_input.has_focus
            unfocused: PaintedPromptFrame = PaintedPromptFrame.capture(app=app)
            unfocused.assert_horizontal_rules(width=prompt_input.region.width)
            unfocused.assert_rules_coloured(accent_hex=accent_hex)

    async def test_rules_when_resized(self, tmp_path: Path) -> None:
        """The rules follow the region width across resizes and leave no stale corner cells."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(60, 24)) as pilot:
            await pilot.pause()
            prompt_input: PromptInput = _require_prompt_input(app=app)
            narrow_width: int = prompt_input.region.width
            PaintedPromptFrame.capture(app=app).assert_horizontal_rules(width=narrow_width)

            await pilot.resize_terminal(width=120, height=40)
            await pilot.pause()
            wide_width: int = prompt_input.region.width
            assert wide_width > narrow_width
            PaintedPromptFrame.capture(app=app).assert_horizontal_rules(width=wide_width)

            await pilot.resize_terminal(width=60, height=24)
            await pilot.pause()
            assert prompt_input.region.width == narrow_width
            PaintedPromptFrame.capture(app=app).assert_horizontal_rules(width=narrow_width)


class TestPromptInputRulesGeometry:
    """The rules sit outside the buffer and keep the editor's existing geometry."""

    LONG_LINE: str = "wrap this prompt so the editor grows " * 12
    TALL_PROMPT: str = "\n".join(f"line {index}" for index in range(30))

    async def test_rules_when_multiline_and_wrapped(self, tmp_path: Path) -> None:
        """Min/max heights hold, content scrolls at the cap, and the rules never enter the buffer."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            prompt_input: PromptInput = _require_prompt_input(app=app)
            empty: PaintedPromptFrame = PaintedPromptFrame.capture(app=app)
            assert prompt_input.outer_size.height == 3
            assert len(empty.content_rows) == 1
            empty.assert_horizontal_rules(width=prompt_input.region.width)
            # The recovered side cells widen the content area; padding 0 1 is not compensated.
            assert prompt_input.content_region.width == prompt_input.region.width - 2

            prompt_input.load_text(f"first\n{self.LONG_LINE}")
            await pilot.pause()
            wrapped: PaintedPromptFrame = PaintedPromptFrame.capture(app=app)
            assert 3 < prompt_input.outer_size.height < 17
            assert len(wrapped.content_rows) == prompt_input.outer_size.height - 2
            assert "first" in wrapped.content_rows[0]
            wrapped.assert_horizontal_rules(width=prompt_input.region.width)

            prompt_input.load_text(self.TALL_PROMPT)
            await pilot.pause()
            capped: PaintedPromptFrame = PaintedPromptFrame.capture(app=app)
            assert prompt_input.outer_size.height == 17
            assert len(capped.content_rows) == 15
            assert prompt_input.max_scroll_y > 0
            capped.assert_horizontal_rules(width=prompt_input.region.width)

            prompt_input.move_cursor(location=(29, 0))
            await pilot.pause()
            scrolled: PaintedPromptFrame = PaintedPromptFrame.capture(app=app)
            assert prompt_input.scroll_y > 0
            assert "line 29" in scrolled.content_rows[-1]
            scrolled.assert_horizontal_rules(width=prompt_input.region.width)
            assert HORIZONTAL_RULE_GLYPH not in prompt_input.text


class TestPromptInputRulesNeighbours:
    """The rules change no neighbour placement and never become editor text."""

    async def test_rules_when_queue_and_suggestions_visible(self, tmp_path: Path) -> None:
        """Queue stays above the editor; suggestions and status bar stay visible and nonoverlapping."""
        session: SloAgentSession = _build_session(workdir=tmp_path)
        app: SloTUI = SloTUI(session=session)
        invoke_log: list[str] = []
        release: asyncio.Event = asyncio.Event()

        with patch.object(
            target=session, attribute="invoke", new=_recording_invoke(invoke_log=invoke_log, release=release)
        ):
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                prompt_input: PromptInput = _require_prompt_input(app=app)
                await _submit_prompt(app=app, pilot=pilot, text="first")
                await _submit_prompt(app=app, pilot=pilot, text="queued second")
                # A narrowed query keeps the menu short. A bare "/" sizes the menu from the screen
                # height alone and overflows the viewport with or without these rules (pre-existing
                # SlashSuggestionMenu capacity defect, recorded in the T01 evidence; not a frame concern).
                prompt_input.load_text("/he")
                await pilot.pause()

                queued_blocks: list[QueuedPromptBlock] = list(app.query(QueuedPromptBlock))
                assert app._in_flight_task is not None
                assert invoke_log == ["first"]
                assert len(queued_blocks) == 1
                assert app._slash_suggestion_state.visible is True
                assert app._suggestion_menu is not None and app._usage_status_bar is not None
                queue_region = queued_blocks[0].region
                menu_region = app._suggestion_menu.region
                status_region = app._usage_status_bar.region
                editor_region = prompt_input.region

                assert queue_region.bottom <= editor_region.y
                assert menu_region.bottom <= queue_region.y
                assert editor_region.bottom <= status_region.y
                assert status_region.height >= 1 and status_region.bottom <= app.screen.region.bottom
                assert menu_region.height >= 1
                PaintedPromptFrame.capture(app=app).assert_horizontal_rules(width=editor_region.width)

                prompt_input.load_text("")
                release.set()
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: app._in_flight_task is None and app._queued_prompt_text is None,
                )
                assert invoke_log == ["first", "queued second"]

    async def test_editor_text_excludes_rules(self, tmp_path: Path) -> None:
        """Typed, copied, submitted and recalled prompt text contains no rule or corner glyph."""
        session: SloAgentSession = _build_session(workdir=tmp_path)
        app: SloTUI = SloTUI(session=session)
        invoke_log: list[str] = []
        release: asyncio.Event = asyncio.Event()
        release.set()
        clipboard: list[str] = []
        frame_glyphs: frozenset[str] = FRAME_SIDE_AND_CORNER_GLYPHS | {HORIZONTAL_RULE_GLYPH}

        with (
            patch.object(
                target=session,
                attribute="invoke",
                new=_recording_invoke(invoke_log=invoke_log, release=release),
            ),
            patch.object(target=app, attribute="copy_to_clipboard", new=clipboard.append),
        ):
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                prompt_input: PromptInput = _require_prompt_input(app=app)
                prompt_input.focus()
                await pilot.press("h", "i", "shift+enter", "y", "o")
                await pilot.pause()
                assert prompt_input.text == "hi\nyo"

                prompt_input.select_all()
                await app.action_copy_visible_text()
                await pilot.press("enter")
                await pump_until(pilot=pilot, predicate=lambda: app._in_flight_task is None)
                await pilot.press("up")
                await pilot.pause()

                assert clipboard == ["hi\nyo"]
                assert invoke_log == ["hi\nyo"]
                assert prompt_input.text == "hi\nyo"
                observed_text: str = "".join([*clipboard, *invoke_log, prompt_input.text])
                assert not set(observed_text) & frame_glyphs
