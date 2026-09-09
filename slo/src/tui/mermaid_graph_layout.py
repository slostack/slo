"""Arrangement of a parsed mermaid graph into ordered, drawable layers.

This module owns flowchart *geometry decisions* — which layer each node sits
in, in what order, and how an edge that skips layers is routed. It knows
nothing about glyphs; ``MermaidGraphRenderer`` draws what this produces.

Splitting it out keeps the drawing code free of graph theory: layering,
cycle rejection, and crossing reduction are all testable here without a
single box-drawing character.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.tui.mermaid_graph_parser import GraphDirection, MermaidGraphDAO, NodeShape

__all__ = [
    "MAXIMUM_NODES",
    "LayeredGraphDAO",
    "MermaidGraphLayout",
    "PlacedEdgeDAO",
    "PlacedNodeDAO",
]

MAXIMUM_NODES: int = 40
"""Node budget past which a drawing stops fitting a terminal pane.

Public because ``MermaidGraphRenderer`` words its declined-drawing note from
it, and one budget with two spellings would drift apart.
"""

_ORDERING_PASSES: int = 2
"""How many barycenter sweeps run; two settles the small graphs LLMs emit."""

_VIRTUAL_KEY_PREFIX: str = "\x00virtual-"
"""Prefix for synthesized pass-through keys; unreachable from mermaid syntax."""


class PlacedNodeDAO(BaseModel):
    """One node assigned to a layer.

    Attributes:
        key (str): The node's key; synthesized for pass-through nodes.
        label (str): Text drawn in the box; empty for pass-through nodes.
        shape (NodeShape): Outline to draw; ignored for pass-through nodes.
        is_virtual (bool): True when this only carries an edge through a
            layer and draws as a line rather than a box.
    """

    key: str
    label: str
    shape: NodeShape
    is_virtual: bool


class PlacedEdgeDAO(BaseModel):
    """One edge between adjacent layers.

    Attributes:
        source_key (str): Key of the node in the upper layer.
        target_key (str): Key of the node in the next layer down.
        label (str): Text drawn beside the arrow; empty when unlabelled.
    """

    source_key: str
    target_key: str
    label: str = ""


class LayeredGraphDAO(BaseModel):
    """A whole graph arranged into layers, ready to draw.

    Attributes:
        direction (GraphDirection): ``TD`` draws layers as rows, ``LR`` as
            columns.
        layers (list[list[PlacedNodeDAO]]): Nodes per layer, in drawn order.
        edges (list[PlacedEdgeDAO]): Edges, every one between adjacent layers.
    """

    direction: GraphDirection
    layers: list[list[PlacedNodeDAO]]
    edges: list[PlacedEdgeDAO]


def _has_cycle(*, keys: list[str], successors: dict[str, list[str]]) -> bool:
    """Return True when the graph cannot be drawn as layers.

    WHAT: Runs an iterative depth-first search and reports whether any edge
    points back into the path being explored — a self-loop included.
    WHO: ``MermaidGraphLayout.arrange`` calls it before layering.
    WHEN: Once per arrange, before any layer is assigned.

    Args:
        keys (list[str]): Every node key.
        successors (dict[str, list[str]]): Outgoing keys per node key.

    Returns:
        bool: True when at least one back edge exists.
    """
    settled: set[str] = set()
    on_path: set[str] = set()
    for start in keys:
        if start in settled:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        while stack:
            key, index = stack.pop()
            if index == 0:
                on_path.add(key)
            if index < len(successors.get(key, [])):
                stack.append((key, index + 1))
                successor: str = successors[key][index]
                if successor in on_path:
                    return True
                if successor not in settled:
                    stack.append((successor, 0))
                continue
            on_path.discard(key)
            settled.add(key)
    return False


def _layer_indices(*, keys: list[str], predecessors: dict[str, list[str]]) -> dict[str, int]:
    """Return the layer each node belongs to.

    WHAT: Longest-path layering — a node sits one layer below its deepest
    parent, so every edge points strictly downward.
    WHO: ``MermaidGraphLayout.arrange`` calls it after the cycle check.
    WHEN: Once per arrange, on a graph already known to be acyclic.

    Args:
        keys (list[str]): Every node key.
        predecessors (dict[str, list[str]]): Incoming keys per node key.

    Returns:
        dict[str, int]: Layer index per node key.
    """
    depths: dict[str, int] = {}
    while len(depths) < len(keys):
        for key in keys:
            if key in depths:
                continue
            parents: list[str] = predecessors.get(key, [])
            if any(parent not in depths for parent in parents):
                continue
            depths[key] = 1 + max((depths[parent] for parent in parents), default=-1)
    return depths


class _LayerBuilder:
    """Builds the layer lists and the adjacent-layer edge list.

    WHAT: Places every real node in its layer, then rewrites each edge that
    skips layers into a chain of pass-through nodes, so the renderer only
    ever draws between neighbours.
    WHO: ``MermaidGraphLayout.arrange`` builds one per call.
    WHEN: For the lifetime of a single arrange.
    """

    def __init__(self, *, graph: MermaidGraphDAO, depths: dict[str, int]) -> None:
        """Seed the builder with empty layers sized to the deepest node.

        Args:
            graph (MermaidGraphDAO): The parsed graph being arranged.
            depths (dict[str, int]): Layer index per node key.
        """
        self._graph: MermaidGraphDAO = graph
        self._depths: dict[str, int] = depths
        self._layers: list[list[PlacedNodeDAO]] = [[] for _ in range(max(depths.values()) + 1)]
        self._edges: list[PlacedEdgeDAO] = []
        self._virtual_count: int = 0

    def place_nodes(self) -> None:
        """Put every declared node into its layer, in declaration order.

        WHO: ``MermaidGraphLayout.arrange`` calls it first.
        WHEN: Once per arrange, before any edge is routed.
        """
        for node in self._graph.nodes:
            self._layers[self._depths[node.key]].append(
                PlacedNodeDAO(key=node.key, label=node.label, shape=node.shape, is_virtual=False)
            )

    def route_edges(self) -> None:
        """Rewrite every edge into one or more adjacent-layer hops.

        WHO: ``MermaidGraphLayout.arrange`` calls it after ``place_nodes``.
        WHEN: Once per arrange.
        """
        for edge in self._graph.edges:
            self._route_one(source_key=edge.source_key, target_key=edge.target_key, label=edge.label)

    def result(self, *, direction: GraphDirection) -> LayeredGraphDAO:
        """Return the finished layout.

        Args:
            direction (GraphDirection): Direction carried from the parse.

        Returns:
            LayeredGraphDAO: Layers and adjacent-layer edges.
        """
        return LayeredGraphDAO(direction=direction, layers=self._layers, edges=self._edges)

    def _route_one(self, *, source_key: str, target_key: str, label: str) -> None:
        """Route one edge, inserting pass-through nodes when it skips layers.

        Args:
            source_key (str): Key the arrow leaves.
            target_key (str): Key the arrow enters.
            label (str): The edge's label, drawn on its first hop only.
        """
        span: int = self._depths[target_key] - self._depths[source_key]
        if span == 1:
            self._edges.append(PlacedEdgeDAO(source_key=source_key, target_key=target_key, label=label))
            return
        self._route_through_layers(source_key=source_key, target_key=target_key, label=label)

    def _route_through_layers(self, *, source_key: str, target_key: str, label: str) -> None:
        """Chain pass-through nodes between two non-adjacent layers.

        Args:
            source_key (str): Key the arrow leaves.
            target_key (str): Key the arrow enters.
            label (str): Drawn on the first hop only, where the arrow leaves.
        """
        previous_key: str = source_key
        hop_label: str = label
        for layer_index in range(self._depths[source_key] + 1, self._depths[target_key]):
            virtual_key: str = self._add_virtual_node(layer_index=layer_index)
            self._edges.append(
                PlacedEdgeDAO(source_key=previous_key, target_key=virtual_key, label=hop_label)
            )
            previous_key = virtual_key
            hop_label = ""
        self._edges.append(PlacedEdgeDAO(source_key=previous_key, target_key=target_key, label=hop_label))

    def _add_virtual_node(self, *, layer_index: int) -> str:
        """Add one pass-through node to a layer and return its key.

        Args:
            layer_index (int): Layer the pass-through belongs to.

        Returns:
            str: The synthesized key.
        """
        self._virtual_count += 1
        key: str = f"{_VIRTUAL_KEY_PREFIX}{self._virtual_count}"
        self._layers[layer_index].append(PlacedNodeDAO(key=key, label="", shape="rectangle", is_virtual=True))
        return key


def _order_layers(*, layout: LayeredGraphDAO) -> None:
    """Reorder each layer to pull children under their parents.

    WHAT: Sweeps top-down a fixed number of times, sorting every layer by the
    mean drawn position of each node's parents — the standard barycenter
    heuristic for reducing edge crossings. Nodes with no parent keep their
    place, so declaration order still reads through.
    WHO: ``MermaidGraphLayout.arrange`` calls it after routing.
    WHEN: Once per arrange, mutating ``layout.layers`` in place.

    Args:
        layout (LayeredGraphDAO): The layout whose layers are reordered.
    """
    parents: dict[str, list[str]] = {}
    for edge in layout.edges:
        parents.setdefault(edge.target_key, []).append(edge.source_key)
    for _ in range(_ORDERING_PASSES):
        for layer_index in range(1, len(layout.layers)):
            positions: dict[str, int] = {
                node.key: index for index, node in enumerate(layout.layers[layer_index - 1])
            }
            layout.layers[layer_index].sort(
                key=lambda node: _barycenter(parent_keys=parents.get(node.key, []), positions=positions)
            )


def _barycenter(*, parent_keys: list[str], positions: dict[str, int]) -> float:
    """Return the mean drawn position of a node's parents.

    WHAT: The sort key that pulls a node toward the nodes feeding it. A node
    with no parent in the layer above returns infinity, which parks it after
    the connected nodes rather than scattering it.
    WHO: ``_order_layers`` uses it as its sort key.
    WHEN: Once per node per ordering pass.

    Args:
        parent_keys (list[str]): Keys feeding this node.
        positions (dict[str, int]): Drawn index per key in the layer above.

    Returns:
        float: Mean parent position, or infinity when there is no parent.
    """
    known: list[int] = [positions[key] for key in parent_keys if key in positions]
    if not known:
        return float("inf")
    return sum(known) / len(known)


class MermaidGraphLayout:
    """Arranges a parsed graph into ordered layers, or declines it.

    WHAT: The single owner of flowchart geometry decisions. It returns a
    whole layout or nothing — a graph it cannot layer honestly (a cycle, or
    one too large for a pane) is declined so the card can say so.
    WHO: ``MermaidGraphRenderer.render`` is the only caller.
    WHEN: Once per chart card mount, on a successfully parsed graph.
    """

    @classmethod
    def arrange(cls, *, graph: MermaidGraphDAO) -> Optional[LayeredGraphDAO]:
        """Arrange a parsed graph into drawable layers.

        WHAT: Rejects cycles and oversized graphs, assigns layers, routes
        skipping edges through pass-through nodes, then orders each layer.
        WHO: ``MermaidGraphRenderer.render`` calls it once per card.
        WHEN: Immediately after a successful parse.

        Args:
            graph (MermaidGraphDAO): The parsed flowchart.

        Returns:
            Optional[LayeredGraphDAO]: The layout, or ``None`` when the graph
                is cyclic or larger than the node budget.
        """
        if len(graph.nodes) > MAXIMUM_NODES:
            return None
        keys: list[str] = [node.key for node in graph.nodes]
        successors: dict[str, list[str]] = {}
        predecessors: dict[str, list[str]] = {}
        for edge in graph.edges:
            successors.setdefault(edge.source_key, []).append(edge.target_key)
            predecessors.setdefault(edge.target_key, []).append(edge.source_key)
        if _has_cycle(keys=keys, successors=successors):
            return None
        builder: _LayerBuilder = _LayerBuilder(
            graph=graph, depths=_layer_indices(keys=keys, predecessors=predecessors)
        )
        builder.place_nodes()
        builder.route_edges()
        layout: LayeredGraphDAO = builder.result(direction=graph.direction)
        _order_layers(layout=layout)
        return layout
