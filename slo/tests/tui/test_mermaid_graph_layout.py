"""Unit tests for arranging a parsed mermaid graph into ordered layers."""

from __future__ import annotations

from typing import Optional

from src.tui.mermaid_graph_layout import LayeredGraphDAO, MermaidGraphLayout
from src.tui.mermaid_graph_parser import MermaidGraphDAO, MermaidGraphParser


def _layout_of(*, source: str) -> Optional[LayeredGraphDAO]:
    """Parse and lay out one source, for tests that only care about the layout.

    Args:
        source (str): Mermaid fence body.

    Returns:
        Optional[LayeredGraphDAO]: The layout, or ``None`` when undrawable.
    """
    graph: Optional[MermaidGraphDAO] = MermaidGraphParser.parse(source=source)
    assert graph is not None, "test source must parse"
    return MermaidGraphLayout.arrange(graph=graph)


def _keys_by_layer(*, layout: LayeredGraphDAO) -> list[list[str]]:
    """Return each layer's node keys in drawn order.

    Args:
        layout (LayeredGraphDAO): An arranged graph.

    Returns:
        list[list[str]]: Keys per layer, top layer first.
    """
    return [[node.key for node in layer] for layer in layout.layers]


class TestMermaidGraphLayoutLayering:
    """Assigning nodes to layers."""

    def test_a_chain_becomes_one_node_per_layer(self) -> None:
        """``A --> B --> C`` stacks three layers of one node each."""
        layout: Optional[LayeredGraphDAO] = _layout_of(source="graph TD\n A --> B --> C\n")

        assert layout is not None
        assert _keys_by_layer(layout=layout) == [["A"], ["B"], ["C"]]

    def test_siblings_share_a_layer(self) -> None:
        """Two children of one parent sit side by side."""
        layout: Optional[LayeredGraphDAO] = _layout_of(source="graph TD\n A --> B\n A --> C\n")

        assert layout is not None
        assert _keys_by_layer(layout=layout) == [["A"], ["B", "C"]]

    def test_a_node_sinks_below_its_deepest_parent(self) -> None:
        """A join lands one layer under whichever parent is lowest."""
        source: str = "graph TD\n A --> B\n B --> D\n A --> C\n C --> D\n"

        layout: Optional[LayeredGraphDAO] = _layout_of(source=source)

        assert layout is not None
        assert _keys_by_layer(layout=layout) == [["A"], ["B", "C"], ["D"]]

    def test_multiple_roots_share_the_top_layer(self) -> None:
        """Every node without a parent starts at the top."""
        layout: Optional[LayeredGraphDAO] = _layout_of(source="graph TD\n A --> C\n B --> C\n")

        assert layout is not None
        assert _keys_by_layer(layout=layout) == [["A", "B"], ["C"]]


class TestMermaidGraphLayoutVirtualNodes:
    """Edges that skip layers are routed through pass-through columns."""

    def test_a_skipping_edge_gains_a_virtual_node(self) -> None:
        """``A --> C`` alongside ``A --> B --> C`` routes through layer 1."""
        source: str = "graph TD\n A --> B\n B --> C\n A --> C\n"

        layout: Optional[LayeredGraphDAO] = _layout_of(source=source)

        assert layout is not None
        assert [node.is_virtual for node in layout.layers[1]].count(True) == 1

    def test_every_edge_is_between_adjacent_layers_after_arranging(self) -> None:
        """Virtualization leaves no edge spanning more than one layer."""
        source: str = "graph TD\n A --> B\n B --> C\n C --> D\n A --> D\n"

        layout: Optional[LayeredGraphDAO] = _layout_of(source=source)

        assert layout is not None
        depth: dict[str, int] = {
            node.key: index for index, layer in enumerate(layout.layers) for node in layer
        }
        assert all(depth[edge.target_key] - depth[edge.source_key] == 1 for edge in layout.edges)

    def test_the_skipping_edge_keeps_its_label_on_the_first_hop(self) -> None:
        """A routed edge's label is drawn once, where the arrow leaves."""
        source: str = "graph TD\n A --> B\n B --> C\n A -->|skip| C\n"

        layout: Optional[LayeredGraphDAO] = _layout_of(source=source)

        assert layout is not None
        assert [edge.label for edge in layout.edges if edge.source_key == "A"].count("skip") == 1


class TestMermaidGraphLayoutRejections:
    """Graphs the layout declines rather than draw wrongly."""

    def test_a_cycle_is_declined(self) -> None:
        """A back edge has no place in a layered drawing."""
        layout: Optional[LayeredGraphDAO] = _layout_of(source="graph TD\n A --> B\n B --> A\n")

        assert layout is None

    def test_a_self_loop_is_declined(self) -> None:
        """A node pointing at itself is the smallest cycle."""
        layout: Optional[LayeredGraphDAO] = _layout_of(source="graph TD\n A --> A\n A --> B\n")

        assert layout is None

    def test_an_oversized_graph_is_declined(self) -> None:
        """Past the node cap the drawing would not fit a terminal."""
        edges: str = "\n".join(f"  N{index} --> N{index + 1}" for index in range(60))

        layout: Optional[LayeredGraphDAO] = _layout_of(source=f"graph TD\n{edges}\n")

        assert layout is None


class TestMermaidGraphLayoutOrdering:
    """Ordering within a layer."""

    def test_children_follow_their_parents_left_to_right(self) -> None:
        """Ordering pulls each child under its parent to reduce crossings."""
        source: str = "graph TD\n A --> C\n B --> D\n A --> D\n B --> C\n"

        layout: Optional[LayeredGraphDAO] = _layout_of(source=source)

        assert layout is not None
        assert _keys_by_layer(layout=layout)[0] == ["A", "B"]
        assert sorted(_keys_by_layer(layout=layout)[1]) == ["C", "D"]

    def test_direction_is_carried_through_to_the_layout(self) -> None:
        """The renderer needs to know whether layers are rows or columns."""
        layout: Optional[LayeredGraphDAO] = _layout_of(source="flowchart LR\n A --> B\n")

        assert layout is not None
        assert layout.direction == "LR"
