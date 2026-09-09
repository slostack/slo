"""Unit tests for parsing mermaid ``graph``/``flowchart`` source into a graph."""

from __future__ import annotations

from typing import Optional

from src.tui.mermaid_graph_parser import (
    MermaidEdgeDAO,
    MermaidGraphDAO,
    MermaidGraphParser,
    MermaidNodeDAO,
)


class TestMermaidGraphParserHappyPaths:
    """Sources the parser is expected to understand."""

    def test_minimal_top_down_graph_is_parsed(self) -> None:
        """A two-node ``graph TD`` yields both nodes and the edge between them."""
        source: str = "graph TD\n  A[Start] --> B[End]\n"

        graph: Optional[MermaidGraphDAO] = MermaidGraphParser.parse(source=source)

        assert graph == MermaidGraphDAO(
            direction="TD",
            nodes=[
                MermaidNodeDAO(key="A", label="Start", shape="rectangle"),
                MermaidNodeDAO(key="B", label="End", shape="rectangle"),
            ],
            edges=[MermaidEdgeDAO(source_key="A", target_key="B", label="")],
        )

    def test_flowchart_keyword_is_accepted(self) -> None:
        """``flowchart`` is the modern spelling of ``graph`` and parses the same."""
        graph: Optional[MermaidGraphDAO] = MermaidGraphParser.parse(source="flowchart LR\n  A --> B\n")

        assert graph is not None
        assert graph.direction == "LR"

    def test_tb_direction_normalizes_to_td(self) -> None:
        """``TB`` and ``TD`` are the same top-down direction."""
        graph: Optional[MermaidGraphDAO] = MermaidGraphParser.parse(source="graph TB\n  A --> B\n")

        assert graph is not None
        assert graph.direction == "TD"

    def test_missing_direction_defaults_to_top_down(self) -> None:
        """A bare ``graph`` directive is top-down, as mermaid itself defaults."""
        graph: Optional[MermaidGraphDAO] = MermaidGraphParser.parse(source="graph\n  A --> B\n")

        assert graph is not None
        assert graph.direction == "TD"

    def test_every_node_shape_is_recognized(self) -> None:
        """Rectangle, rounded, decision, and circle brackets map to shapes."""
        source: str = "graph TD\n  A[Rect] --> B(Round)\n  B --> C{Choice}\n  C --> D((Dot))\n"

        graph: Optional[MermaidGraphDAO] = MermaidGraphParser.parse(source=source)

        assert graph is not None
        assert [(node.key, node.shape) for node in graph.nodes] == [
            ("A", "rectangle"),
            ("B", "rounded"),
            ("C", "decision"),
            ("D", "circle"),
        ]

    def test_bare_node_key_becomes_its_own_label(self) -> None:
        """A node declared without brackets is labelled with its key."""
        graph: Optional[MermaidGraphDAO] = MermaidGraphParser.parse(source="graph TD\n  A --> B\n")

        assert graph is not None
        assert graph.nodes[0] == MermaidNodeDAO(key="A", label="A", shape="rectangle")

    def test_label_declared_once_is_reused_at_later_mentions(self) -> None:
        """A node keeps the label from its first bracketed declaration."""
        source: str = "graph TD\n  A[Start] --> B[Middle]\n  B --> C[End]\n"

        graph: Optional[MermaidGraphDAO] = MermaidGraphParser.parse(source=source)

        assert graph is not None
        assert [node.label for node in graph.nodes] == ["Start", "Middle", "End"]

    def test_pipe_edge_label_is_captured(self) -> None:
        """``-->|text|`` attaches ``text`` to the edge."""
        graph: Optional[MermaidGraphDAO] = MermaidGraphParser.parse(source="graph TD\n  A -->|yes| B\n")

        assert graph is not None
        assert graph.edges == [MermaidEdgeDAO(source_key="A", target_key="B", label="yes")]

    def test_inline_edge_label_is_captured(self) -> None:
        """``-- text -->`` is the other spelling of an edge label."""
        graph: Optional[MermaidGraphDAO] = MermaidGraphParser.parse(source="graph TD\n  A -- no --> B\n")

        assert graph is not None
        assert graph.edges == [MermaidEdgeDAO(source_key="A", target_key="B", label="no")]

    def test_dotted_and_thick_arrows_are_ordinary_edges(self) -> None:
        """Arrow styling carries no layout meaning, so every arrow is one edge."""
        source: str = "graph TD\n  A -.-> B\n  B ==> C\n  C --- D\n"

        graph: Optional[MermaidGraphDAO] = MermaidGraphParser.parse(source=source)

        assert graph is not None
        assert [(edge.source_key, edge.target_key) for edge in graph.edges] == [
            ("A", "B"),
            ("B", "C"),
            ("C", "D"),
        ]

    def test_chained_edges_on_one_line_are_split(self) -> None:
        """``A --> B --> C`` declares two edges, not one."""
        graph: Optional[MermaidGraphDAO] = MermaidGraphParser.parse(source="graph TD\n  A --> B --> C\n")

        assert graph is not None
        assert [(edge.source_key, edge.target_key) for edge in graph.edges] == [("A", "B"), ("B", "C")]

    def test_comments_and_blank_lines_are_ignored(self) -> None:
        """``%%`` comments and blank lines never reach the graph."""
        source: str = "graph TD\n\n  %% a comment\n  A --> B\n\n"

        graph: Optional[MermaidGraphDAO] = MermaidGraphParser.parse(source=source)

        assert graph is not None
        assert len(graph.edges) == 1

    def test_standalone_node_declaration_is_kept(self) -> None:
        """A node declared on its own line still belongs to the graph."""
        source: str = "graph TD\n  A[Lonely]\n  B[Start] --> C[End]\n"

        graph: Optional[MermaidGraphDAO] = MermaidGraphParser.parse(source=source)

        assert graph is not None
        assert [node.key for node in graph.nodes] == ["A", "B", "C"]


class TestMermaidGraphParserRejections:
    """Sources the parser must decline rather than half-render."""

    def test_non_graph_diagram_is_declined(self) -> None:
        """``sequenceDiagram`` is a different language and is not parsed."""
        source: str = "sequenceDiagram\n  Alice->>Bob: Hi\n"

        assert MermaidGraphParser.parse(source=source) is None

    def test_bottom_up_direction_is_declined(self) -> None:
        """``BT`` is not drawn, because the renderer only lays out TD and LR."""
        assert MermaidGraphParser.parse(source="graph BT\n  A --> B\n") is None

    def test_right_to_left_direction_is_declined(self) -> None:
        """``RL`` is not drawn, for the same reason as ``BT``."""
        assert MermaidGraphParser.parse(source="graph RL\n  A --> B\n") is None

    def test_subgraph_is_declined(self) -> None:
        """Nested subgraphs need grouping the renderer does not implement."""
        source: str = "graph TD\n  subgraph one\n    A --> B\n  end\n"

        assert MermaidGraphParser.parse(source=source) is None

    def test_unreadable_line_declines_the_whole_graph(self) -> None:
        """A line that is neither node nor edge means the drawing would be a lie."""
        source: str = 'graph TD\n  A --> B\n  click A callback "tooltip"\n'

        assert MermaidGraphParser.parse(source=source) is None

    def test_graph_without_edges_is_declined(self) -> None:
        """With no edges there is no diagram to draw, only a list."""
        assert MermaidGraphParser.parse(source="graph TD\n  A[Only]\n") is None

    def test_empty_source_is_declined(self) -> None:
        """An empty body cannot be a graph."""
        assert MermaidGraphParser.parse(source="") is None
