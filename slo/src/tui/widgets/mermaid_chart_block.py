"""First-class transcript widget for one mermaid chart fence."""

from __future__ import annotations

from typing import ClassVar

from rich.console import Group, RenderableType
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message

from src.tui.mermaid_graph_renderer import MermaidDrawingDAO, MermaidGraphRenderer
from src.tui.mermaid_lexer import MermaidLexer
from src.tui.widgets.literal_text_static import LiteralTextStatic
from src.tui.widgets.selectable_rich_visual import SelectableRawTextLeaf

__all__ = ["MermaidChartBlock", "MermaidChartChrome", "MermaidChartSurface"]

_UNDRAWN_HINT: str = "showing the source instead"
"""What the card tells the reader when a diagram could not be drawn."""

_MERMAID_PREVIEW_LINE_CAP: int = 150
"""Undrawn fences longer than this show a truncated source (rung 2)."""

_MERMAID_PREVIEW_HEAD_LINES: int = 40
"""How many leading source lines the truncated preview keeps."""


class MermaidChartChrome(LiteralTextStatic):
    """A card label region that Textual's selection walk skips.

    WHAT: A literal-text ``Static`` with Textual's ``ALLOW_SELECT`` turned
    off, so a drag across the answer copies the prose and the mermaid source
    but never the card's own label text. Without it the caption is a
    childless leaf holding a plain string, which the base
    ``Widget.get_selection`` happily extracts onto the clipboard.
    WHO: ``MermaidChartBlock.compose`` yields one for the header rule and one
    for the caption line.
    WHEN: Once per card mount; read by Textual's
    ``SelectState._walk_selected_widgets`` on every drag.
    """

    ALLOW_SELECT: ClassVar[bool] = False


class MermaidChartSurface(SelectableRawTextLeaf):
    """Leaf surface showing one chart's drawing, selectable as its source.

    WHAT: Renders whatever the card decided to show — the drawn diagram, or
    a note saying why it could not be drawn — while serving the verbatim
    mermaid SOURCE through the inherited ``get_selection``. What a reader
    sees and what a drag copies are deliberately different: the picture is
    for reading, the source is what anyone actually wants on the clipboard.
    WHO: ``MermaidChartBlock.compose`` yields exactly one.
    WHEN: Built once at card mount; never updated.

    It extends ``SelectableRawTextLeaf`` rather than re-implementing the
    seam: the block is a ``Vertical``, and Textual skips containers in
    ``SelectState._walk_selected_widgets``, so the selection seam has to
    live on a widget with no children.
    """

    def __init__(self, *, source: str, visual: RenderableType) -> None:
        """Seed the surface with what to show and what to copy.

        Args:
            source (str): Verbatim, untruncated mermaid source — the text a
                drag or a copy chord lands on the clipboard.
            visual (RenderableType): What the reader sees: the drawn diagram,
                or the note explaining its absence.
        """
        super().__init__(content=visual, classes="mermaid-chart-body")
        self.set_source_text(text=source)


class MermaidChartBlock(Vertical):
    """Render one mermaid fence as a titled, explorable chart card.

    WHAT: Three regions — a ``Rule`` header naming the directive line, a
    ``MermaidChartSurface`` body, and a caption with the chart-type summary
    and the full-screen hint. Settled at mount.
    WHO: ``AssistantAnswerBody`` mounts one per mermaid segment; ``SloTUI``
    handles its ``FullScreenRequested`` message.
    WHEN: Created at an answer render boundary for each closed mermaid fence.
    """

    can_focus: bool = True

    DEFAULT_CSS = """
    MermaidChartBlock {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1;
        background: $mermaid-chart-bg;
        border-left: thick $accent;
    }
    MermaidChartBlock .mermaid-chart-caption {
        color: $text-muted;
        text-style: italic;
    }
    """

    BINDINGS = [
        Binding(key="ctrl+f", action="mermaid_full_screen", description="full screen"),
    ]
    """``ctrl+f``, never ``f``: ``SloTUI.on_key`` swallows every printable key
    and replays it into the prompt input, so a plain-letter binding on a
    focused transcript widget never fires (§3, executed proof)."""

    class FullScreenRequested(Message):
        """Posted when the user presses ``ctrl+f`` on the focused chart block.

        Attributes:
            source (str): Verbatim mermaid source (never escaped).
            directive (str): The fence's directive line, e.g. ``graph TD``.
        """

        def __init__(self, *, source: str, directive: str) -> None:
            """Initialise the request with the chart's source and directive.

            Args:
                source (str): Verbatim mermaid source.
                directive (str): Directive line for the screen title.
            """
            super().__init__()
            self.source: str = source
            self.directive: str = directive

    def __init__(self, *, source: str) -> None:
        """Seed the block with verbatim mermaid source.

        The drawing is settled here, once, because the card never re-renders
        after mount — so both the body and the caption read one decision
        rather than each asking the renderer again.

        Args:
            source (str): Fence body, unescaped, without the fence lines.
        """
        super().__init__()
        self._source: str = source
        self._directive: str = self._directive_line(source=source)
        self._drawing: MermaidDrawingDAO = MermaidGraphRenderer.render(source=source)

    def compose(self) -> ComposeResult:
        """Build the header, body, and caption regions once.

        WHAT: Yields the card's three settled-at-mount regions from the
        constructor arguments; nothing re-renders afterward.
        WHO: Textual calls it during mount.
        WHEN: Once per card mount.

        Yields:
            ComposeResult: Two ``MermaidChartChrome`` label regions a drag
                never copies — the titled rule and the caption line — around
                the selectable ``MermaidChartSurface``.
        """
        yield MermaidChartChrome(
            Rule(title=f"📊 Mermaid chart — {self._directive}"),
            classes="mermaid-chart-header",
        )
        yield MermaidChartSurface(source=self._source, visual=self._body_visual())
        yield MermaidChartChrome(self._caption_text(), classes="mermaid-chart-caption")

    @property
    def source(self) -> str:
        """Return the verbatim mermaid source.

        WHAT: Exposes the full fence body the card was built from — the
        untruncated text, even when the body renders a preview. It is the
        card's domain accessor; ``get_copyable_text`` is the separate
        clipboard contract every focusable transcript block implements, and
        the two coincide in value today by design, not by accident.
        WHO: The card's tests read it; no production code does. ``SloTUI``
        reads ``message.source`` off ``FullScreenRequested``, never this
        property. Spec ``77.a.2`` names it in acceptance criteria 4 and 8.
        WHEN: Any time after construction.

        Returns:
            str: The full fence body (never the truncated preview).
        """
        return self._source

    def action_mermaid_full_screen(self) -> None:
        """Post the full-screen request consumed by ``SloTUI``.

        WHAT: Sends ``FullScreenRequested`` carrying this card's source and
        directive. The block posts a message rather than pushing a screen
        itself so screen routing stays on the app, mirroring the copy funnel
        (spec 72.a.3) and keeping this widget free of app coupling.
        WHO: Textual invokes it for the card's ``ctrl+f`` binding while the
        card holds focus.
        WHEN: The operator presses ``ctrl+f`` on a focused chart card.
        """
        self.post_message(
            MermaidChartBlock.FullScreenRequested(source=self._source, directive=self._directive)
        )

    def get_copyable_text(self) -> str:
        """Return the verbatim mermaid source for the focused-copy action.

        WHAT: Hands the clipboard tier this card's source and nothing else.
        WHO: ``SloTUI.action_copy_visible_text`` calls it when this block
        holds focus and the user presses the copy chord — the same contract
        every focusable transcript block honors.
        WHEN: The operator invokes the copy-visible-text binding.

        Returns:
            str: The full, unescaped, untruncated mermaid source.
        """
        return self._source

    def _body_visual(self) -> RenderableType:
        """Build what the card's body shows.

        WHAT: Shows the drawing when the fence could be drawn; otherwise
        shows the renderer's own plain-language reason above the highlighted
        source, so an undrawable diagram is never less useful than a plain
        code block. Exactly one decision.
        WHO: ``compose`` calls it once while building the body region.
        WHEN: Once per card mount.

        Returns:
            RenderableType: The drawn diagram, or the note standing in for it.
        """
        if self._drawing.drawing:
            return Text(self._drawing.drawing)
        return Group(
            Text(f"⚠ {self._drawing.note} — {_UNDRAWN_HINT}", style="italic"),
            Syntax(
                code=self._preview_source(),
                lexer=MermaidLexer(),
                background_color="default",
            ),
        )

    def _caption_text(self) -> str:
        """Build the caption line with directive summary and hints.

        WHAT: Names the chart type, its source line count, and the
        full-screen chord; an undrawn oversized fence also says how much of
        its source is on screen.
        WHO: ``compose`` calls it when building the caption region.
        WHEN: Once per card mount.

        Returns:
            str: One-line caption naming the chart type, its source size, and
                the chord that opens the full source.
        """
        if self._shows_truncated_source():
            return (
                f"mermaid · {self._directive} · showing {_MERMAID_PREVIEW_HEAD_LINES}"
                f" of {self._source_line_count()} lines — ctrl+f for full source"
            )
        return f"mermaid · {self._directive} · {self._source_line_count()}" " lines · ctrl+f for full screen"

    def _shows_truncated_source(self) -> bool:
        """Return True when the body shows a shortened source, not a drawing.

        WHAT: The one condition under which the caption has to account for
        missing lines — an undrawn fence longer than the preview cap.
        WHO: ``_caption_text`` asks before wording the caption.
        WHEN: Once per card mount.

        Returns:
            bool: True when the body is a truncated source preview.
        """
        return not self._drawing.drawing and self._source_line_count() > _MERMAID_PREVIEW_LINE_CAP

    def _source_line_count(self) -> int:
        """Return how many lines the verbatim fence body has.

        WHO: ``_caption_text`` and ``_shows_truncated_source`` read it.
        WHEN: Once per card mount.

        Returns:
            int: Line count of the untruncated source.
        """
        return len(self._source.splitlines())

    def _preview_source(self) -> str:
        """Return the source to display, truncated for oversized fences.

        WHAT: Applies degradation rung 2 — the full source at or under the
        line cap, otherwise its leading lines only. Only ever reached when
        the fence could not be drawn.
        WHO: ``_body_visual`` calls it when building the fallback source.
        WHEN: Once per undrawn card mount.

        Returns:
            str: Full source at or under the line cap; otherwise the first
                ``_MERMAID_PREVIEW_HEAD_LINES`` lines.
        """
        lines: list[str] = self._source.splitlines()
        if len(lines) <= _MERMAID_PREVIEW_LINE_CAP:
            return self._source
        return "\n".join(lines[:_MERMAID_PREVIEW_HEAD_LINES])

    @staticmethod
    def _directive_line(*, source: str) -> str:
        """Extract the directive (first non-blank source line).

        WHAT: Returns the fence's chart-type line for the header and title.
        WHO: ``__init__`` calls it once.
        WHEN: At card construction, before mount.

        Args:
            source (str): Verbatim mermaid source.

        Returns:
            str: The directive line, or ``"chart"`` when the body is blank.
        """
        for line in source.splitlines():
            if line.strip():
                return line.strip()
        return "chart"
