"""Selection-aware ``Visual`` wrapper for Rich renderables (spec 72 follow-up).

Textual 8.2.8's ``RichVisual.render_strips`` silently drops the render-time
selection option, so any surface backed by a Rich renderable (padded markdown,
for example) never paints the mouse-selection highlight. The compositor also
cannot map pointer coordinates back to content offsets on those strips, so a
drag over such a surface falls back to a whole-widget ``SELECT_ALL`` entry in
``Screen.selections``. This module supplies the smallest app-side mitigation:
a ``Visual`` decorator that re-applies the selection span to the rendered
strips in content coordinates, so the highlight is baked into the widget's own
strips and therefore tracks the content exactly across parent scrolls.

The module also owns ``SelectableRawTextLeaf``, the single shared base for every
transcript surface that serves raw text to the selection machinery. Raw-text
storage, the ``SelectableRichVisual`` render wrap, and the raw-text
``Widget.get_selection`` seam are one implementation here rather than one copy
per surface: ``AnswerMarkdownPart``, ``AssistantThinkingBody``, and
``MermaidSourceSurface`` all inherit it. The base lives beside the visual it
wraps (and not in ``assistant_stream_block.py``) because ``mermaid_chart_block.py`` imports it
while ``assistant_stream_block.py`` imports ``MermaidChartBlock`` — housing the
base in the answer module would close an import cycle.
"""

from __future__ import annotations

from typing import Optional, cast

from rich.cells import cell_len
from rich.console import RenderableType
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.app import RenderResult
from textual.css.styles import RulesMap
from textual.selection import Selection
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, RichVisual, Visual, VisualType
from textual.widget import Widget
from textual.widgets import Static

__all__ = ["SelectableRawTextLeaf", "SelectableRichVisual"]


class SelectableRichVisual(Visual):
    """Paint the text-selection highlight over a Rich renderable's strips.

    WHAT: Delegates measurement and strip rendering to an inner
    ``RichVisual``, then applies ``options.selection`` with
    ``options.selection_style`` to the produced strips in content
    coordinates (strip index == content line), mirroring what
    ``Content.render_strips`` does natively. The highlight lives inside the
    widget's strips, so a parent ``VerticalScroll`` moves it together with
    the selected text instead of leaving stale paint behind.
    WHO: ``SelectableRawTextLeaf`` subclasses — ``AnswerMarkdownPart``,
    ``AssistantThinkingBody``, and ``MermaidSourceSurface`` — wrap their Rich
    renderables with it at every render boundary.
    WHEN: Active whenever ``Visual.to_strips`` renders the owning widget
    while ``Screen.selections`` holds a selection for it.
    """

    def __init__(self, *, widget: Widget, renderable: RenderableType) -> None:
        """Wrap one Rich renderable for selection-aware strip rendering.

        Args:
            widget (Widget): Owning widget, forwarded to the inner
                ``RichVisual`` for post-render processing.
            renderable (RenderableType): The Rich renderable to wrap.
        """
        self._rich_visual: RichVisual = RichVisual(widget=widget, renderable=renderable)

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        """Delegate width measurement to the wrapped Rich visual.

        WHAT: Returns the wrapped renderable's optimal width for the given
        container width.
        WHO: Textual's layout pipeline calls this through the ``Visual``
        protocol.
        WHEN: During layout recalculation when the owning widget's width is
        measured, before the widget's strips render.

        Args:
            rules (RulesMap): The widget's style rules.
            container_width (int): Width of the container in cells.

        Returns:
            int: Optimal width in cells, exactly as the inner visual reports.
        """
        return self._rich_visual.get_optimal_width(rules=rules, container_width=container_width)

    def get_height(self, rules: RulesMap, width: int) -> int:
        """Delegate height measurement to the wrapped Rich visual.

        WHAT: Returns the wrapped renderable's height at the requested width.
        WHO: Textual's layout pipeline calls this through the ``Visual``
        protocol.
        WHEN: During layout recalculation before the widget's strips render.

        Args:
            rules (RulesMap): The widget's style rules.
            width (int): Width of the visual in cells.

        Returns:
            int: Height in lines, exactly as the inner visual reports.
        """
        return self._rich_visual.get_height(rules=rules, width=width)

    def render_strips(
        self,
        width: int,
        height: Optional[int],
        style: Style,
        options: RenderOptions,
    ) -> list[Strip]:
        """Render the wrapped renderable, then paint any active selection.

        WHAT: Renders exactly as the inner ``RichVisual`` would, then
        overlays the selection span line-by-line in content coordinates.
        WHO: ``Visual.to_strips`` calls it from the widget's render pass.
        WHEN: At every widget re-render; the selection overlay is a no-op
        when no selection targets the owning widget.

        Args:
            width (int): Width of the desired render in cells.
            height (Optional[int]): Desired height in lines, or ``None`` for
                no limit.
            style (Style): The base visual style to render on top of.
            options (RenderOptions): Additional render options carrying the
                selection and its style.

        Returns:
            list[Strip]: The rendered strips, with the selection highlight
                baked into the selected content lines.
        """
        strips: list[Strip] = self._rich_visual.render_strips(
            width=width,
            height=height,
            style=style,
            options=options,
        )
        selection: Optional[Selection] = options.selection
        selection_style: Optional[Style] = options.selection_style
        if selection is None or selection_style is None:
            return strips
        rich_selection_style: RichStyle = selection_style.rich_style
        return [
            self._paint_selection(
                strip=strip,
                line_index=line_index,
                selection=selection,
                selection_style=rich_selection_style,
            )
            for line_index, strip in enumerate(strips)
        ]

    @classmethod
    def _paint_selection(
        cls,
        *,
        strip: Strip,
        line_index: int,
        selection: Selection,
        selection_style: RichStyle,
    ) -> Strip:
        """Paint the selection span for one content line onto its strip.

        Args:
            strip (Strip): The rendered strip for one content line.
            line_index (int): The strip's content line index.
            selection (Selection): The active selection in content
                coordinates.
            selection_style (RichStyle): The resolved selection style,
                applied on top of existing segment styles.

        Returns:
            Strip: The strip with the selection span highlighted, or the
                original strip when the line is outside the selection.
        """
        span: Optional[tuple[int, int]] = selection.get_span(line_index)
        if span is None:
            return strip
        start, end = span
        if end == -1:
            end = cell_len(strip.text.rstrip())
        start = max(0, start)
        end = min(end, strip.cell_length)
        if start >= end:
            return strip
        return cls._stylize_span(strip=strip, start=start, end=end, selection_style=selection_style)

    @staticmethod
    def _stylize_span(*, strip: Strip, start: int, end: int, selection_style: RichStyle) -> Strip:
        """Re-style the ``[start, end)`` cell range of a strip on top.

        Args:
            strip (Strip): The strip to re-style.
            start (int): First highlighted cell index.
            end (int): One past the last highlighted cell index.
            selection_style (RichStyle): Style layered over existing segment
                styles so the highlight wins.

        Returns:
            Strip: A new strip with the span carrying the selection style.
        """
        cell_length: int = strip.cell_length
        cuts: list[int] = sorted({cut for cut in (start, end, cell_length) if 0 < cut})
        parts: list[Strip] = list(strip.divide(cuts))
        styled_parts: list[Strip] = []
        lower: int = 0
        for part, upper in zip(parts, cuts):
            if lower >= start and upper <= end:
                part = SelectableRichVisual._apply_top_style(strip=part, selection_style=selection_style)
            styled_parts.append(part)
            lower = upper
        return Strip.join(styled_parts)

    @staticmethod
    def _apply_top_style(*, strip: Strip, selection_style: RichStyle) -> Strip:
        """Layer the selection style over every segment of a strip.

        Args:
            strip (Strip): The strip whose segments to re-style.
            selection_style (RichStyle): Style appended last so it overrides
                existing segment styles.

        Returns:
            Strip: A new strip carrying the selection style on top.
        """
        segments: list[Segment] = [
            Segment(
                text=segment.text,
                style=segment.style + selection_style if segment.style is not None else selection_style,
                control=segment.control,
            )
            for segment in strip
        ]
        return Strip(segments=segments, cell_length=strip.cell_length)


class SelectableRawTextLeaf(Static):
    """A childless transcript surface whose raw text stays selectable.

    WHAT: Holds one raw-text buffer beside a Rich renderable. It renders that
    renderable through ``SelectableRichVisual`` so a mouse drag paints the
    highlight into this widget's own strips, and it serves the raw text back
    through Textual's documented ``Widget.get_selection`` seam so the drag
    copies the text rather than nothing (the base ``Widget.get_selection``
    cannot extract text from a Rich renderable).
    WHO: ``AnswerMarkdownPart`` (one prose segment of an answer),
    ``AssistantThinkingBody`` (the thinking body), and ``MermaidSourceSurface``
    (the chart card's source region) extend it; ``Screen.get_selected_text``
    queries the seam after a mouse selection.
    WHEN: Whenever such a surface renders or the screen extracts selected text.

    The seam has to live on a leaf: Textual's
    ``SelectState._walk_selected_widgets`` skips any widget that has children,
    so a ``get_selection`` override on a container is never called.
    """

    def __init__(self, *, content: VisualType = "", classes: Optional[str] = None) -> None:
        """Initialise the leaf with its renderable and an empty raw-text buffer.

        Args:
            content (VisualType): Initial renderable to display. Defaults to
                the empty string.
            classes (Optional[str]): Space-separated CSS classes.
        """
        super().__init__(content, classes=classes)
        self._raw_text: str = ""

    def set_source_text(self, *, text: str) -> None:
        """Store the raw text used for selection extraction.

        WHAT: Records the unescaped text buffer so ``get_selection`` can serve
        it verbatim; performs no rendering itself.
        WHO: The owning block calls it alongside its ``update`` — for example
        ``AssistantStreamThinkingBlock._render_thinking``.
        WHEN: At every render boundary that changes the displayed text.

        Args:
            text (str): Raw text backing the rendered renderable.
        """
        self._raw_text = text

    def get_selection(self, selection: Selection) -> Optional[tuple[str, str]]:
        """Return the selected slice of the raw text.

        WHAT: Serves the raw (unescaped) text through Textual's documented
        custom-widget selection seam so a mouse drag over this surface yields
        the text itself.
        WHO: ``Screen.get_selected_text`` calls it for every widget captured by
        a mouse selection.
        WHEN: After a drag selection starts, moves, or completes.

        Args:
            selection (Selection): The selected range in content coordinates.

        Returns:
            Optional[tuple[str, str]]: Extracted text and its line ending, or
                ``None`` when this surface holds no raw text.
        """
        if not self._raw_text:
            return None
        return selection.extract(self._raw_text), "\n"

    def render(self) -> RenderResult:
        """Render the stored content through the selection-aware visual.

        WHAT: Wraps a Rich renderable in ``SelectableRichVisual`` so the
        mouse-selection highlight is baked into this surface's strips in
        content coordinates and tracks the text across parent scrolls; plain
        string content (the empty state) falls through unchanged.
        WHO: Textual's ``Widget._render`` calls it on every repaint.
        WHEN: At every render pass while the surface is mounted.

        Returns:
            RenderResult: The selection-aware visual wrapping the stored
                renderable, or the raw content when it is already a string or
                a ``Visual``.
        """
        content: VisualType = self.content
        if isinstance(content, (str, Visual)):
            return content
        return SelectableRichVisual(widget=self, renderable=cast(RenderableType, content))
