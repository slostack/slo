"""Unit tests for drawing a mermaid flowchart as box-drawing text."""

from __future__ import annotations

from typing import Optional

from src.tui.mermaid_graph_renderer import MermaidDrawingDAO, MermaidGraphRenderer


def _render(*, source: str) -> str:
    """Render one source and assert it was drawable.

    Args:
        source (str): Mermaid fence body.

    Returns:
        str: The drawn diagram.
    """
    result: MermaidDrawingDAO = MermaidGraphRenderer.render(source=source)
    assert result.drawing, f"source was expected to be drawable, got note {result.note!r}"
    return result.drawing


class TestMermaidGraphRendererTopDown:
    """Drawing top-down flowcharts."""

    def test_a_two_node_chain_draws_both_boxes_and_an_arrow(self) -> None:
        """The simplest graph draws two labelled boxes joined by an arrow."""
        drawing: str = _render(source="graph TD\n  A[Start] --> B[End]\n")

        assert "Start" in drawing
        assert "End" in drawing
        assert "▼" in drawing
        assert drawing.index("Start") < drawing.index("End")

    def test_a_rectangle_uses_square_corners(self) -> None:
        """The default node shape is drawn with square box corners."""
        drawing: str = _render(source="graph TD\n  A[Plain] --> B[Next]\n")

        assert "┌" in drawing and "┐" in drawing
        assert "└" in drawing and "┘" in drawing

    def test_a_decision_uses_diamond_corners(self) -> None:
        """A ``{}`` node is drawn with slanted corners so it reads as a diamond."""
        drawing: str = _render(source="graph TD\n  A{Choose} --> B[Next]\n")

        assert "╱" in drawing and "╲" in drawing

    def test_a_rounded_node_uses_rounded_corners(self) -> None:
        """A ``()`` node is drawn with rounded corners."""
        drawing: str = _render(source="graph TD\n  A(Soft) --> B[Next]\n")

        assert "╭" in drawing and "╰" in drawing

    def test_a_circle_node_uses_parenthesis_sides(self) -> None:
        """A ``(())`` node is drawn with parenthesis sides."""
        drawing: str = _render(source="graph TD\n  A((Dot)) --> B[Next]\n")

        assert "( Dot )" in drawing

    def test_siblings_are_drawn_on_the_same_row(self) -> None:
        """Two children of one parent share a layer, so they share a line."""
        drawing: str = _render(source="graph TD\n  A[Top] --> B[Left]\n  A --> C[Right]\n")

        sharing: list[str] = [line for line in drawing.splitlines() if "Left" in line]
        assert sharing and "Right" in sharing[0]

    def test_an_edge_label_is_drawn(self) -> None:
        """``-->|yes|`` puts its text into the drawing."""
        drawing: str = _render(source="graph TD\n  A[Ask] -->|yes| B[Do]\n")

        assert "yes" in drawing

    def test_a_pass_through_edge_draws_a_line_not_a_box(self) -> None:
        """A layer-skipping edge is routed, and adds no extra labelled box."""
        source: str = "graph TD\n  A[One] --> B[Two]\n  B --> C[Three]\n  A --> C\n"

        drawing: str = _render(source=source)

        assert drawing.count("One") == 1
        assert drawing.count("Three") == 1
        assert "│" in drawing

    def test_every_line_is_padded_to_one_width(self) -> None:
        """A rectangular canvas keeps the card from ragged right edges."""
        drawing: str = _render(source="graph TD\n  A[Wide label here] --> B[X]\n")

        widths: set[int] = {len(line) for line in drawing.splitlines()}
        assert len(widths) == 1


class TestMermaidGraphRendererLeftToRight:
    """Drawing left-to-right flowcharts."""

    def test_a_two_node_chain_draws_a_horizontal_arrow(self) -> None:
        """An ``LR`` graph points its arrow rightward, not downward."""
        drawing: str = _render(source="flowchart LR\n  A[Start] --> B[End]\n")

        assert "▶" in drawing
        assert "▼" not in drawing

    def test_layers_advance_across_the_line(self) -> None:
        """In ``LR`` a later layer is drawn further right on the same row."""
        drawing: str = _render(source="flowchart LR\n  A[Start] --> B[End]\n")

        row: str = next(line for line in drawing.splitlines() if "Start" in line)
        assert row.index("Start") < row.index("End")

    def test_siblings_are_drawn_in_one_column(self) -> None:
        """Two children of one parent stack vertically in ``LR``."""
        drawing: str = _render(source="flowchart LR\n  A[T] --> B[Up]\n  A --> C[Down]\n")

        assert "Up" in drawing and "Down" in drawing
        assert not any("Up" in line and "Down" in line for line in drawing.splitlines())

    def test_an_edge_label_is_drawn(self) -> None:
        """``LR`` edge labels reach the drawing too."""
        drawing: str = _render(source="flowchart LR\n  A[Ask] -->|no| B[Stop]\n")

        assert "no" in drawing


class TestMermaidGraphRendererDeclines:
    """Sources that must not be drawn."""

    def test_a_non_flowchart_is_declined(self) -> None:
        """A sequence diagram has no flowchart layout."""
        assert MermaidGraphRenderer.render(source="sequenceDiagram\n  A->>B: hi\n").note

    def test_a_cycle_is_declined(self) -> None:
        """A cyclic graph cannot be layered, so nothing is drawn."""
        assert "loop" in MermaidGraphRenderer.render(source="graph TD\n  A --> B\n  B --> A\n").note

    def test_an_over_wide_drawing_is_declined(self) -> None:
        """A layer too wide for a pane is declined rather than clipped."""
        edges: str = "\n".join(f"  ROOT --> N{index}[Label number {index}]" for index in range(12))

        assert MermaidGraphRenderer.render(source=f"graph TD\n{edges}\n").note
