"""Drawing of an arranged mermaid flowchart as box-drawing text.

This module owns *glyphs and geometry* — box outlines, connector routing, and
the finished character canvas. It makes no graph decisions: layering, cycle
rejection, and ordering all happened in ``MermaidGraphLayout``, and grammar in
``MermaidGraphParser``.

``MermaidGraphRenderer.render`` is the gateway the chart card calls. It draws
a whole diagram or returns ``None``; it never returns a partial drawing,
because a partial diagram misleads more than an honest note.
"""

from __future__ import annotations

from typing import NamedTuple, Optional, Union

from pydantic import BaseModel

from src.tui.mermaid_graph_layout import (
    MAXIMUM_NODES,
    LayeredGraphDAO,
    MermaidGraphLayout,
    PlacedEdgeDAO,
    PlacedNodeDAO,
)
from src.tui.mermaid_graph_parser import MermaidGraphDAO, MermaidGraphParser, NodeShape

__all__ = ["MermaidDrawingDAO", "MermaidGraphRenderer"]

_MAXIMUM_CANVAS_WIDTH: int = 100
"""Widest drawing a transcript pane can show without wrapping into nonsense."""

_MAXIMUM_CANVAS_HEIGHT: int = 80
"""Tallest drawing worth inlining in a transcript."""

_BOX_HEIGHT: int = 3
"""Every node box is a top border, a label line, and a bottom border."""

_LABEL_PADDING: int = 4
"""Two side glyphs plus one space either side of the label."""

_SIBLING_GAP: int = 3
"""Blank cells between two boxes in the same layer."""

_UP: str = "up"
_DOWN: str = "down"
_LEFT: str = "left"
_RIGHT: str = "right"

_LINE_GLYPHS: dict[frozenset[str], str] = {
    frozenset({_UP}): "│",
    frozenset({_DOWN}): "│",
    frozenset({_LEFT}): "─",
    frozenset({_RIGHT}): "─",
    frozenset({_UP, _DOWN}): "│",
    frozenset({_LEFT, _RIGHT}): "─",
    frozenset({_DOWN, _RIGHT}): "┌",
    frozenset({_DOWN, _LEFT}): "┐",
    frozenset({_UP, _RIGHT}): "└",
    frozenset({_UP, _LEFT}): "┘",
    frozenset({_UP, _DOWN, _RIGHT}): "├",
    frozenset({_UP, _DOWN, _LEFT}): "┤",
    frozenset({_DOWN, _LEFT, _RIGHT}): "┬",
    frozenset({_UP, _LEFT, _RIGHT}): "┴",
    frozenset({_UP, _DOWN, _LEFT, _RIGHT}): "┼",
}
"""Which box-drawing character joins a given set of directions."""


class MermaidDrawingDAO(BaseModel):
    """The outcome of trying to draw one mermaid fence.

    Exactly one field is ever non-empty: a drawing when the source could be
    drawn, otherwise a note saying plainly why it could not.

    Attributes:
        drawing (str): The finished box-drawing text, empty when undrawn.
        note (str): Why the diagram was not drawn, empty when it was.
    """

    drawing: str = ""
    note: str = ""


class _BoxStyle(NamedTuple):
    """The six glyphs that outline one node shape.

    Attributes:
        top_left (str): Upper-left corner.
        top_right (str): Upper-right corner.
        bottom_left (str): Lower-left corner.
        bottom_right (str): Lower-right corner.
        left_side (str): Left wall of the label line.
        right_side (str): Right wall of the label line.
    """

    top_left: str
    top_right: str
    bottom_left: str
    bottom_right: str
    left_side: str
    right_side: str


_BOX_STYLES: dict[NodeShape, _BoxStyle] = {
    "rectangle": _BoxStyle("┌", "┐", "└", "┘", "│", "│"),
    "rounded": _BoxStyle("╭", "╮", "╰", "╯", "│", "│"),
    "decision": _BoxStyle("╱", "╲", "╲", "╱", "│", "│"),
    "circle": _BoxStyle("╭", "╮", "╰", "╯", "(", ")"),
}
"""How each parsed node shape is outlined, so shapes stay visually distinct."""


class _Canvas:
    """A growable character grid that merges box-drawing lines.

    WHAT: Holds the drawing as rows of characters. Writing text overwrites;
    connecting a cell merges its directions with whatever already passes
    through it, so two crossing edges produce a junction glyph rather than
    one clobbering the other.
    WHO: The two painters write into one; ``MermaidGraphRenderer.render``
    reads the finished text out.
    WHEN: For the lifetime of a single render.
    """

    def __init__(self) -> None:
        """Start an empty canvas with no rows."""
        self._rows: list[list[str]] = []
        self._directions: dict[tuple[int, int], set[str]] = {}

    def write(self, *, row: int, column: int, text: str) -> None:
        """Write text with its upper-left corner at one cell.

        WHO: The painters call it for every box glyph and every label.
        WHEN: Throughout a render.

        Args:
            row (int): Zero-based row.
            column (int): Zero-based column of the first character.
            text (str): The characters to place.
        """
        for offset, character in enumerate(text):
            self._put(row=row, column=column + offset, character=character)

    def connect(self, *, row: int, column: int, directions: set[str]) -> None:
        """Route a line through one cell, merging with any line already there.

        WHO: The painters call it for every connector cell.
        WHEN: Throughout a render.

        Args:
            row (int): Zero-based row.
            column (int): Zero-based column.
            directions (set[str]): Which sides the line leaves this cell by.
        """
        merged: set[str] = self._directions.setdefault((row, column), set())
        merged.update(directions)
        self._put(row=row, column=column, character=_LINE_GLYPHS[frozenset(merged)])

    def is_blank(self, *, row: int, column: int, width: int) -> bool:
        """Return True when a horizontal span holds nothing but spaces.

        WHO: ``_TopDownPainter._draw_edge_labels`` asks before placing a label.
        WHEN: Once per candidate label position.

        Args:
            row (int): Zero-based row.
            column (int): Leftmost column of the span.
            width (int): How many cells the span covers.

        Returns:
            bool: True when every cell in the span is empty.
        """
        if column < 0:
            return False
        if row >= len(self._rows):
            return True
        return all(
            index >= len(self._rows[row]) or self._rows[row][index] == " "
            for index in range(column, column + width)
        )

    def to_text(self) -> str:
        """Return the canvas as one padded, rectangular block of text.

        WHO: ``MermaidGraphRenderer.render`` calls it last.
        WHEN: Once per render.

        Returns:
            str: Every row padded to the widest row, newline separated.
        """
        width: int = max((len(row) for row in self._rows), default=0)
        return "\n".join("".join(row).ljust(width) for row in self._rows)

    def size(self) -> tuple[int, int]:
        """Return the drawn height and width.

        WHO: ``MermaidGraphRenderer.render`` checks it against the caps.
        WHEN: Once per render, before handing the drawing back.

        Returns:
            tuple[int, int]: Row count and the widest row's length.
        """
        return len(self._rows), max((len(row) for row in self._rows), default=0)

    def _put(self, *, row: int, column: int, character: str) -> None:
        """Place one character, growing the grid to reach it.

        Args:
            row (int): Zero-based row.
            column (int): Zero-based column.
            character (str): The character to place.
        """
        while len(self._rows) <= row:
            self._rows.append([])
        line: list[str] = self._rows[row]
        while len(line) <= column:
            line.append(" ")
        line[column] = character


def _box_width(*, node: PlacedNodeDAO) -> int:
    """Return how many columns one node occupies.

    WHAT: A drawn box is its label plus walls and padding, rounded up to an
    odd width; a pass-through node is a single column of line. Odd widths
    matter because a box's centre is ``left + width // 2``, and only odd
    widths put every single-node layer on the same centre column.
    WHO: Both painters call it while measuring layers.
    WHEN: Once per node per render.

    Args:
        node (PlacedNodeDAO): The node being measured.

    Returns:
        int: Column count.
    """
    if node.is_virtual:
        return 1
    width: int = len(node.label) + _LABEL_PADDING
    return width + 1 - width % 2


def _draw_box(*, canvas: _Canvas, node: PlacedNodeDAO, top: int, left: int) -> None:
    """Draw one real node's outline and label.

    WHAT: Renders the three lines of a node's box, centring the label inside
    the odd width ``_box_width`` reserved for it.
    WHO: Both painters call it once per drawn node. Pass-through nodes are
    not drawn here — each painter strokes those along its own axis.
    WHEN: While drawing a layer.

    Args:
        canvas (_Canvas): The canvas being drawn into.
        node (PlacedNodeDAO): The node to draw.
        top (int): Row of the box's top border.
        left (int): Column of the box's left wall.
    """
    style: _BoxStyle = _BOX_STYLES[node.shape]
    inner: int = _box_width(node=node) - 2
    canvas.write(row=top, column=left, text=style.top_left + "─" * inner + style.top_right)
    canvas.write(
        row=top + 1,
        column=left,
        text=f"{style.left_side}{node.label.center(inner)}{style.right_side}",
    )
    canvas.write(row=top + 2, column=left, text=style.bottom_left + "─" * inner + style.bottom_right)


def _draw_horizontal_run(*, canvas: _Canvas, row: int, start: int, end: int) -> None:
    """Join two columns on one row with a horizontal line.

    WHAT: Draws the corner at each end and the run between them, merging
    with any line already crossing those cells.
    WHO: ``_TopDownPainter._draw_band`` calls it per jogging edge.
    WHEN: Once per edge whose source and target are not aligned.

    Args:
        canvas (_Canvas): The canvas being drawn into.
        row (int): Row the run sits on.
        start (int): Column the line arrives from above.
        end (int): Column the line leaves downward.
    """
    if start == end:
        canvas.connect(row=row, column=start, directions={_UP, _DOWN})
        return
    step: str = _RIGHT if end > start else _LEFT
    back: str = _LEFT if end > start else _RIGHT
    canvas.connect(row=row, column=start, directions={_UP, step})
    canvas.connect(row=row, column=end, directions={_DOWN, back})
    for column in range(min(start, end) + 1, max(start, end)):
        canvas.connect(row=row, column=column, directions={_LEFT, _RIGHT})


def _draw_vertical_run(*, canvas: _Canvas, column: int, start: int, end: int) -> None:
    """Join two rows in one column with a vertical line.

    WHAT: The left-to-right mirror of ``_draw_horizontal_run``.
    WHO: ``_LeftToRightPainter._draw_band`` calls it per jogging edge.
    WHEN: Once per edge whose source and target rows differ.

    Args:
        canvas (_Canvas): The canvas being drawn into.
        column (int): Column the run sits on.
        start (int): Row the line arrives from the left.
        end (int): Row the line leaves rightward.
    """
    if start == end:
        canvas.connect(row=start, column=column, directions={_LEFT, _RIGHT})
        return
    step: str = _DOWN if end > start else _UP
    back: str = _UP if end > start else _DOWN
    canvas.connect(row=start, column=column, directions={_LEFT, step})
    canvas.connect(row=end, column=column, directions={_RIGHT, back})
    for row in range(min(start, end) + 1, max(start, end)):
        canvas.connect(row=row, column=column, directions={_UP, _DOWN})


class _TopDownPainter:
    """Draws a layered graph with layers as rows.

    WHAT: Places each layer's boxes centred on one band of rows, then draws
    a connector band between consecutive layers.
    WHO: ``MermaidGraphRenderer.render`` builds one for a ``TD`` layout.
    WHEN: For the lifetime of a single render.
    """

    def __init__(self, *, layout: LayeredGraphDAO) -> None:
        """Measure the layout and seed an empty canvas.

        Args:
            layout (LayeredGraphDAO): The arranged graph to draw.
        """
        self._layout: LayeredGraphDAO = layout
        self._canvas: _Canvas = _Canvas()
        self._centers: dict[str, int] = {}
        self._tops: dict[str, int] = {}

    def paint(self) -> _Canvas:
        """Draw the whole diagram and return the canvas.

        WHO: ``MermaidGraphRenderer.render`` calls it once.
        WHEN: After the layout has been arranged.

        Returns:
            _Canvas: The finished canvas.
        """
        self._place_layers()
        self._draw_boxes()
        self._draw_bands()
        return self._canvas

    def _place_layers(self) -> None:
        """Assign every node a centre column and a top row."""
        widths: list[int] = [self._layer_width(layer=layer) for layer in self._layout.layers]
        canvas_width: int = max(widths, default=0)
        row: int = 0
        for index, layer in enumerate(self._layout.layers):
            column: int = (canvas_width - widths[index]) // 2
            for node in layer:
                self._tops[node.key] = row
                self._centers[node.key] = column + _box_width(node=node) // 2
                column += _box_width(node=node) + _SIBLING_GAP
            row += _BOX_HEIGHT + self._band_height(layer_index=index)

    def _draw_boxes(self) -> None:
        """Draw every node at its placed position."""
        for layer in self._layout.layers:
            for node in layer:
                self._draw_node(node=node)

    def _draw_node(self, *, node: PlacedNodeDAO) -> None:
        """Draw one node as a box, or stroke it as a pass-through.

        Args:
            node (PlacedNodeDAO): The node to draw.
        """
        if node.is_virtual:
            self._stroke_pass_through(node=node)
            return
        _draw_box(
            canvas=self._canvas,
            node=node,
            top=self._tops[node.key],
            left=self._centers[node.key] - _box_width(node=node) // 2,
        )

    def _stroke_pass_through(self, *, node: PlacedNodeDAO) -> None:
        """Carry a routed edge straight down through one layer's rows.

        Args:
            node (PlacedNodeDAO): The pass-through node.
        """
        for offset in range(_BOX_HEIGHT):
            self._canvas.connect(
                row=self._tops[node.key] + offset,
                column=self._centers[node.key],
                directions={_UP, _DOWN},
            )

    def _draw_bands(self) -> None:
        """Draw a connector band under every layer but the last."""
        for index in range(len(self._layout.layers) - 1):
            self._draw_band(layer_index=index)

    def _draw_band(self, *, layer_index: int) -> None:
        """Draw one layer's outgoing connectors.

        Args:
            layer_index (int): Index of the upper layer.
        """
        edges: list[PlacedEdgeDAO] = self._edges_leaving(layer_index=layer_index)
        stub_row: int = self._tops[self._layout.layers[layer_index][0].key] + _BOX_HEIGHT
        arrow_row: int = self._tops[self._layout.layers[layer_index + 1][0].key] - 1
        for edge in edges:
            self._draw_edge(edge=edge, stub_row=stub_row, arrow_row=arrow_row)
        self._draw_edge_labels(edges=edges, row=arrow_row - 1)

    def _draw_edge(self, *, edge: PlacedEdgeDAO, stub_row: int, arrow_row: int) -> None:
        """Draw one edge from its source's underside to its target's top.

        Args:
            edge (PlacedEdgeDAO): The edge to draw.
            stub_row (int): First row below the upper layer's boxes.
            arrow_row (int): Row carrying the arrowhead.
        """
        source_column: int = self._centers[edge.source_key]
        target_column: int = self._centers[edge.target_key]
        self._canvas.connect(row=stub_row, column=source_column, directions={_UP, _DOWN})
        _draw_horizontal_run(canvas=self._canvas, row=stub_row + 1, start=source_column, end=target_column)
        for row in range(stub_row + 2, arrow_row):
            self._canvas.connect(row=row, column=target_column, directions={_UP, _DOWN})
        self._canvas.write(row=arrow_row, column=target_column, text="▼")

    def _draw_edge_labels(self, *, edges: list[PlacedEdgeDAO], row: int) -> None:
        """Write each labelled edge's text beside its arrow.

        Args:
            edges (list[PlacedEdgeDAO]): The band's edges.
            row (int): Row just above the arrowheads.
        """
        for edge in edges:
            if not edge.label:
                continue
            self._write_label(label=edge.label, row=row, column=self._centers[edge.target_key])

    def _write_label(self, *, label: str, row: int, column: int) -> None:
        """Place one edge label to the right of a column, else to its left.

        Args:
            label (str): The edge's text.
            row (int): Row to write on.
            column (int): The target's centre column.
        """
        if self._canvas.is_blank(row=row, column=column + 2, width=len(label)):
            self._canvas.write(row=row, column=column + 2, text=label)
            return
        self._canvas.write(row=row, column=column - 1 - len(label), text=label)

    def _edges_leaving(self, *, layer_index: int) -> list[PlacedEdgeDAO]:
        """Return the edges whose source sits in one layer.

        Args:
            layer_index (int): Index of the upper layer.

        Returns:
            list[PlacedEdgeDAO]: That layer's outgoing edges.
        """
        keys: set[str] = {node.key for node in self._layout.layers[layer_index]}
        return [edge for edge in self._layout.edges if edge.source_key in keys]

    def _layer_width(self, *, layer: list[PlacedNodeDAO]) -> int:
        """Return how many columns one layer of boxes occupies.

        Args:
            layer (list[PlacedNodeDAO]): The layer to measure.

        Returns:
            int: Total width including the gaps between boxes.
        """
        boxes: int = sum(_box_width(node=node) for node in layer)
        return boxes + _SIBLING_GAP * max(len(layer) - 1, 0)

    def _band_height(self, *, layer_index: int) -> int:
        """Return how many rows the connector band under a layer needs.

        Args:
            layer_index (int): Index of the upper layer.

        Returns:
            int: Row count: a stub row, a routing row, an arrow row, and a
                label row when any of the band's edges carries text.
        """
        if layer_index >= len(self._layout.layers) - 1:
            return 0
        labelled: bool = any(edge.label for edge in self._edges_leaving(layer_index=layer_index))
        return 4 if labelled else 3


class _LeftToRightPainter:
    """Draws a layered graph with layers as columns.

    WHAT: The mirror of ``_TopDownPainter`` — each layer is a column of
    boxes, and connector bands run horizontally between them.
    WHO: ``MermaidGraphRenderer.render`` builds one for an ``LR`` layout.
    WHEN: For the lifetime of a single render.
    """

    def __init__(self, *, layout: LayeredGraphDAO) -> None:
        """Measure the layout and seed an empty canvas.

        Args:
            layout (LayeredGraphDAO): The arranged graph to draw.
        """
        self._layout: LayeredGraphDAO = layout
        self._canvas: _Canvas = _Canvas()
        self._middles: dict[str, int] = {}
        self._lefts: dict[str, int] = {}

    def paint(self) -> _Canvas:
        """Draw the whole diagram and return the canvas.

        WHO: ``MermaidGraphRenderer.render`` calls it once.
        WHEN: After the layout has been arranged.

        Returns:
            _Canvas: The finished canvas.
        """
        self._place_layers()
        self._draw_boxes()
        self._draw_bands()
        return self._canvas

    def _place_layers(self) -> None:
        """Assign every node a middle row and a left column."""
        heights: list[int] = [self._layer_height(layer=layer) for layer in self._layout.layers]
        canvas_height: int = max(heights, default=0)
        column: int = 0
        for index, layer in enumerate(self._layout.layers):
            row: int = (canvas_height - heights[index]) // 2
            for node in layer:
                self._lefts[node.key] = column
                self._middles[node.key] = row + self._node_height(node=node) // 2
                row += self._node_height(node=node) + 1
            column += self._layer_column_width(layer=layer) + self._band_width(layer_index=index)

    def _draw_boxes(self) -> None:
        """Draw every node at its placed position."""
        for layer in self._layout.layers:
            for node in layer:
                self._draw_node(node=node, layer=layer)

    def _draw_node(self, *, node: PlacedNodeDAO, layer: list[PlacedNodeDAO]) -> None:
        """Draw one node as a box, or stroke it as a pass-through.

        Args:
            node (PlacedNodeDAO): The node to draw.
            layer (list[PlacedNodeDAO]): The column the node belongs to.
        """
        if node.is_virtual:
            self._stroke_pass_through(node=node, layer=layer)
            return
        _draw_box(
            canvas=self._canvas,
            node=node,
            top=self._middles[node.key] - self._node_height(node=node) // 2,
            left=self._lefts[node.key],
        )

    def _stroke_pass_through(self, *, node: PlacedNodeDAO, layer: list[PlacedNodeDAO]) -> None:
        """Carry a routed edge straight across one layer's columns.

        Args:
            node (PlacedNodeDAO): The pass-through node.
            layer (list[PlacedNodeDAO]): The column it belongs to, whose full
                width the stroke spans so the line never breaks.
        """
        left: int = self._lefts[node.key]
        for offset in range(self._layer_column_width(layer=layer)):
            self._canvas.connect(
                row=self._middles[node.key], column=left + offset, directions={_LEFT, _RIGHT}
            )

    def _draw_bands(self) -> None:
        """Draw a connector band right of every layer but the last."""
        for index in range(len(self._layout.layers) - 1):
            self._draw_band(layer_index=index)

    def _draw_band(self, *, layer_index: int) -> None:
        """Draw one layer's outgoing connectors.

        Args:
            layer_index (int): Index of the left-hand layer.
        """
        layer: list[PlacedNodeDAO] = self._layout.layers[layer_index]
        stub_column: int = self._lefts[layer[0].key] + self._layer_column_width(layer=layer)
        arrow_column: int = self._lefts[self._layout.layers[layer_index + 1][0].key] - 1
        for edge in self._edges_leaving(layer_index=layer_index):
            self._draw_edge(edge=edge, stub_column=stub_column, arrow_column=arrow_column)

    def _draw_edge(self, *, edge: PlacedEdgeDAO, stub_column: int, arrow_column: int) -> None:
        """Draw one edge from its source's right side to its target's left.

        Args:
            edge (PlacedEdgeDAO): The edge to draw.
            stub_column (int): First column right of the left-hand boxes.
            arrow_column (int): Column carrying the arrowhead.
        """
        source_row: int = self._middles[edge.source_key]
        target_row: int = self._middles[edge.target_key]
        self._canvas.connect(row=source_row, column=stub_column, directions={_LEFT, _RIGHT})
        _draw_vertical_run(canvas=self._canvas, column=stub_column + 1, start=source_row, end=target_row)
        for column in range(stub_column + 2, arrow_column):
            self._canvas.connect(row=target_row, column=column, directions={_LEFT, _RIGHT})
        self._canvas.write(row=target_row, column=arrow_column, text="▶")
        self._write_label(edge=edge, row=target_row, column=stub_column + 2)

    def _write_label(self, *, edge: PlacedEdgeDAO, row: int, column: int) -> None:
        """Write an edge's label into the gap its band reserved.

        Args:
            edge (PlacedEdgeDAO): The edge whose label is written.
            row (int): The target's middle row.
            column (int): First column of the band's label gap.
        """
        if not edge.label:
            return
        self._canvas.write(row=row, column=column, text=edge.label)

    def _edges_leaving(self, *, layer_index: int) -> list[PlacedEdgeDAO]:
        """Return the edges whose source sits in one layer.

        Args:
            layer_index (int): Index of the left-hand layer.

        Returns:
            list[PlacedEdgeDAO]: That layer's outgoing edges.
        """
        keys: set[str] = {node.key for node in self._layout.layers[layer_index]}
        return [edge for edge in self._layout.edges if edge.source_key in keys]

    def _node_height(self, *, node: PlacedNodeDAO) -> int:
        """Return how many rows one node occupies.

        Args:
            node (PlacedNodeDAO): The node being measured.

        Returns:
            int: Three for a drawn box, one for a pass-through node.
        """
        if node.is_virtual:
            return 1
        return _BOX_HEIGHT

    def _layer_height(self, *, layer: list[PlacedNodeDAO]) -> int:
        """Return how many rows one column of boxes occupies.

        Args:
            layer (list[PlacedNodeDAO]): The layer to measure.

        Returns:
            int: Total height including one blank row between boxes.
        """
        boxes: int = sum(self._node_height(node=node) for node in layer)
        return boxes + max(len(layer) - 1, 0)

    def _layer_column_width(self, *, layer: list[PlacedNodeDAO]) -> int:
        """Return the width of the widest box in one layer.

        Args:
            layer (list[PlacedNodeDAO]): The layer to measure.

        Returns:
            int: Column count.
        """
        return max((_box_width(node=node) for node in layer), default=1)

    def _band_width(self, *, layer_index: int) -> int:
        """Return how many columns the band right of a layer needs.

        Args:
            layer_index (int): Index of the left-hand layer.

        Returns:
            int: A stub column, a routing column, the widest label in the
                band, and an arrow column.
        """
        if layer_index >= len(self._layout.layers) - 1:
            return 0
        labels: list[int] = [len(edge.label) for edge in self._edges_leaving(layer_index=layer_index)]
        return 3 + max(labels, default=0)


class MermaidGraphRenderer:
    """Draws mermaid flowchart source as box-drawing text, or declines it.

    WHAT: The gateway from raw fence body to a finished drawing. It parses,
    arranges, paints, and finally refuses anything too large for a pane.
    Every stage may decline; the card shows a note when one does.
    WHO: ``MermaidChartBlock`` calls ``render`` once per card mount.
    WHEN: At card mount, on the already-extracted fence body.
    """

    @classmethod
    def render(cls, *, source: str) -> MermaidDrawingDAO:
        """Draw one mermaid fence body as a diagram.

        WHAT: Runs parse, arrange, and paint in order, and returns either the
        drawn text or a plain-language note saying why this source was not
        drawn. It never returns a partial drawing.
        WHO: ``MermaidChartBlock._body_visual`` is the only caller.
        WHEN: Once per chart card mount.

        Args:
            source (str): Verbatim mermaid fence body, without fence lines.

        Returns:
            MermaidDrawingDAO: The drawing, or the reason there is none.
        """
        graph: Optional[MermaidGraphDAO] = MermaidGraphParser.parse(source=source)
        if graph is None:
            return MermaidDrawingDAO(note="only graph and flowchart diagrams are drawn")
        layout: Optional[LayeredGraphDAO] = MermaidGraphLayout.arrange(graph=graph)
        if layout is None:
            return MermaidDrawingDAO(note=_layout_note(graph=graph))
        return cls._painted(layout=layout)

    @classmethod
    def _painted(cls, *, layout: LayeredGraphDAO) -> MermaidDrawingDAO:
        """Paint an arranged layout and enforce the size caps.

        Args:
            layout (LayeredGraphDAO): The arranged graph.

        Returns:
            MermaidDrawingDAO: The drawing, or a note when it is oversized.
        """
        canvas: _Canvas = cls._painter_for(layout=layout).paint()
        height, width = canvas.size()
        if width > _MAXIMUM_CANVAS_WIDTH or height > _MAXIMUM_CANVAS_HEIGHT:
            return MermaidDrawingDAO(note="this diagram is too large to draw here")
        return MermaidDrawingDAO(drawing=canvas.to_text())

    @classmethod
    def _painter_for(cls, *, layout: LayeredGraphDAO) -> Union[_LeftToRightPainter, _TopDownPainter]:
        """Return the painter that draws this layout's direction.

        Args:
            layout (LayeredGraphDAO): The arranged graph.

        Returns:
            Union[_LeftToRightPainter, _TopDownPainter]: The painter to use.
        """
        if layout.direction == "LR":
            return _LeftToRightPainter(layout=layout)
        return _TopDownPainter(layout=layout)


def _layout_note(*, graph: MermaidGraphDAO) -> str:
    """Say plainly why an arranged layout could not be produced.

    WHAT: ``MermaidGraphLayout.arrange`` declines for exactly two reasons;
    this decides which one applies so the card can tell the reader.
    WHO: ``MermaidGraphRenderer.render`` calls it when arranging failed.
    WHEN: Once, only on the declined path.

    Args:
        graph (MermaidGraphDAO): The graph that could not be arranged.

    Returns:
        str: A short, plain-language reason.
    """
    if len(graph.nodes) > MAXIMUM_NODES:
        return "this diagram has too many nodes to draw here"
    return "this diagram has a loop, which cannot be drawn as layers"
