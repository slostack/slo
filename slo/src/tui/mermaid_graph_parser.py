"""Parsing of mermaid ``graph``/``flowchart`` source into a drawable graph.

This module is the ONLY component that understands mermaid's flowchart
grammar. It reads the verbatim fence body handed to a chart card and returns
either a graph the renderer can lay out, or ``None`` — never a partial graph.
Declining is deliberate: half a diagram is a wrong diagram, and the card shows
an honest note instead.

``MermaidLexer`` (syntax colours) and ``MermaidFenceSegmenter`` (fence
boundaries) are separate owners; neither parses flowchart structure.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel

__all__ = [
    "MermaidEdgeDAO",
    "MermaidGraphDAO",
    "MermaidGraphParser",
    "MermaidNodeDAO",
]

NodeShape = Literal["rectangle", "rounded", "decision", "circle"]
GraphDirection = Literal["TD", "LR"]

_COMMENT_PREFIX: str = "%%"
"""Mermaid's line-comment marker."""

_DIRECTIVE_RE: re.Pattern[str] = re.compile(r"^(?:graph|flowchart)(?:\s+(?P<direction>[A-Za-z]{2}))?$")
"""The opening ``graph``/``flowchart`` line, with an optional direction."""

_DRAWN_DIRECTIONS: dict[str, GraphDirection] = {"TD": "TD", "TB": "TD", "LR": "LR"}
"""Directions the renderer lays out; ``BT`` and ``RL`` are absent on purpose."""

_ARROW_RE: re.Pattern[str] = re.compile(
    r"""
    \s*
    (?:
        --   \s* (?P<inline>[^->|]+?) \s* -+>
      | -\.  \s* (?P<dotted>[^.|]+?)  \s* \.-+>
      | ==   \s* (?P<thick>[^=|]+?)   \s* =+>
      | -\.-+>
      | =+>
      | -{2,}>
      | -{3,}
      | -\.-
    )
    \s*
    (?: \| \s* (?P<piped>[^|]*?) \s* \| )?
    \s*
    """,
    re.VERBOSE,
)
"""Any flowchart arrow, with the edge label spelled either way it is written."""

_NODE_RE: re.Pattern[str] = re.compile(
    r"""
    ^
    (?P<key>[A-Za-z_][A-Za-z0-9_]*)
    (?:
        (?P<open>\(\(|\[\[|\(\[|\[\(|\{\{|\[|\(|\{)
        (?P<label>.*?)
        (?:\)\)|\]\]|\]\)|\)\]|\}\}|\]|\)|\})
    )?
    $
    """,
    re.VERBOSE,
)
"""One node mention: a key, optionally carrying a bracketed label."""

_SHAPE_BY_OPENING_BRACKET: dict[str, NodeShape] = {
    "[": "rectangle",
    "[[": "rectangle",
    "[(": "rectangle",
    "(": "rounded",
    "([": "rounded",
    "((": "circle",
    "{": "decision",
    "{{": "decision",
}
"""Which drawn shape each mermaid bracket pair asks for."""


class MermaidNodeDAO(BaseModel):
    """One box in a drawn flowchart.

    Attributes:
        key (str): The identifier the source uses to refer to this node.
        label (str): The text drawn inside the box; the key when undeclared.
        shape (NodeShape): Which outline the renderer draws around the label.
    """

    key: str
    label: str
    shape: NodeShape


class MermaidEdgeDAO(BaseModel):
    """One directed connection between two boxes.

    Attributes:
        source_key (str): Key of the node the arrow leaves.
        target_key (str): Key of the node the arrow enters.
        label (str): Text drawn beside the arrow; empty when unlabelled.
    """

    source_key: str
    target_key: str
    label: str = ""


class MermaidGraphDAO(BaseModel):
    """A whole flowchart, ready to lay out.

    Attributes:
        direction (GraphDirection): ``TD`` stacks layers as rows, ``LR`` as
            columns.
        nodes (list[MermaidNodeDAO]): Every node, in first-mention order.
        edges (list[MermaidEdgeDAO]): Every edge, in source order.
    """

    direction: GraphDirection
    nodes: list[MermaidNodeDAO]
    edges: list[MermaidEdgeDAO]


def _strip_quotes(*, label: str) -> str:
    """Return a node label without its optional surrounding quotes.

    WHAT: Mermaid allows ``A["text"]`` to protect punctuation; the quotes are
    syntax, not content, so they never reach the drawn box.
    WHO: ``_GraphReader._node_from_text`` calls it for every bracketed label.
    WHEN: Once per node declaration.

    Args:
        label (str): Raw text between a node's brackets.

    Returns:
        str: The label with one matching pair of quotes removed.
    """
    if len(label) >= 2 and label[0] == label[-1] and label[0] in {'"', "'"}:
        return label[1:-1]
    return label


class _GraphReader:
    """The accumulated state of one parse over one fence body.

    WHAT: Collects nodes in first-mention order and edges in source order,
    and remembers the first reason the source turned out to be undrawable.
    Once undrawable, it stays undrawable.
    WHO: ``MermaidGraphParser.parse`` builds one per call and discards it.
    WHEN: For the lifetime of a single ``parse`` call.
    """

    def __init__(self) -> None:
        """Start an empty reader with no direction and no failure."""
        self._direction: GraphDirection = "TD"
        self._nodes: dict[str, MermaidNodeDAO] = {}
        self._edges: list[MermaidEdgeDAO] = []
        self._is_drawable: bool = True

    def read_directive(self, *, line: str) -> None:
        """Read the opening ``graph``/``flowchart`` line.

        WHAT: Decides whether the diagram is a flowchart this renderer draws,
        and in which direction — the single decision this method makes.
        WHO: ``MermaidGraphParser.parse`` calls it for the first content line.
        WHEN: Once per parse, before any body line.

        Args:
            line (str): The first non-blank, non-comment source line.
        """
        match: Optional[re.Match[str]] = _DIRECTIVE_RE.match(line)
        if match is None:
            self._decline()
            return
        self._adopt_direction(spelling=match.group("direction"))

    def read_body_line(self, *, line: str) -> None:
        """Read one node or edge line.

        WHAT: Splits the line on its arrows and decides whether what remains
        is readable — the single decision this method makes.
        WHO: ``MermaidGraphParser.parse`` calls it once per body line.
        WHEN: For every non-blank, non-comment line after the directive.

        Args:
            line (str): One body line, already stripped.
        """
        if self._declares_subgraph(line=line):
            self._decline()
            return
        self._read_chain(line=line)

    def result(self) -> Optional[MermaidGraphDAO]:
        """Return the parsed graph, or ``None`` when it cannot be drawn.

        WHAT: Applies the last admissibility rule — a graph with no edges is
        a list, not a diagram — and hands back the finished value.
        WHO: ``MermaidGraphParser.parse`` calls it once, last.
        WHEN: After every source line has been read.

        Returns:
            Optional[MermaidGraphDAO]: The graph, or ``None`` when the source
                is not a drawable flowchart.
        """
        if not self._is_drawable:
            return None
        if not self._edges:
            return None
        return MermaidGraphDAO(
            direction=self._direction,
            nodes=list(self._nodes.values()),
            edges=self._edges,
        )

    def _adopt_direction(self, *, spelling: Optional[str]) -> None:
        """Adopt the directive's direction, or decline an undrawn one.

        Args:
            spelling (Optional[str]): The direction token, absent when the
                directive was a bare ``graph``.
        """
        if spelling is None:
            return
        direction: Optional[GraphDirection] = _DRAWN_DIRECTIONS.get(spelling.upper())
        if direction is None:
            self._decline()
            return
        self._direction = direction

    def _declares_subgraph(self, *, line: str) -> bool:
        """Return True when the line opens or closes a subgraph.

        Args:
            line (str): One body line, already stripped.

        Returns:
            bool: True for ``subgraph …`` and its matching ``end``.
        """
        return line == "end" or line.startswith("subgraph")

    def _read_chain(self, *, line: str) -> None:
        """Read one line as a chain of nodes joined by arrows.

        Args:
            line (str): One body line, already stripped.
        """
        mentions: list[str] = []
        labels: list[str] = []
        cursor: int = 0
        for match in _ARROW_RE.finditer(line):
            mentions.append(line[cursor : match.start()])
            labels.append(_edge_label(match=match))
            cursor = match.end()
        mentions.append(line[cursor:])
        self._record_chain(mentions=mentions, labels=labels)

    def _record_chain(self, *, mentions: list[str], labels: list[str]) -> None:
        """Record every node mention and the edges between them.

        Args:
            mentions (list[str]): Node texts, one more than ``labels``.
            labels (list[str]): Edge labels, in chain order.
        """
        keys: list[str] = [self._record_node(text=mention) for mention in mentions]
        if not self._is_drawable:
            return
        self._edges.extend(
            MermaidEdgeDAO(source_key=keys[index], target_key=keys[index + 1], label=labels[index])
            for index in range(len(labels))
        )

    def _record_node(self, *, text: str) -> str:
        """Record one node mention and return its key.

        Args:
            text (str): One node mention, possibly bracketed.

        Returns:
            str: The node's key, or an empty string when unreadable.
        """
        node: Optional[MermaidNodeDAO] = self._node_from_text(text=text)
        if node is None:
            self._decline()
            return ""
        self._nodes.setdefault(node.key, node)
        self._relabel_if_declared(node=node)
        return node.key

    def _node_from_text(self, *, text: str) -> Optional[MermaidNodeDAO]:
        """Build one node from its mention, or ``None`` when unreadable.

        Args:
            text (str): One node mention, possibly bracketed.

        Returns:
            Optional[MermaidNodeDAO]: The node, or ``None`` when the text is
                not a node mention.
        """
        match: Optional[re.Match[str]] = _NODE_RE.match(text.strip())
        if match is None:
            return None
        return _node_from_match(match=match)

    def _relabel_if_declared(self, *, node: MermaidNodeDAO) -> None:
        """Let a bracketed mention name a node first mentioned bare.

        Args:
            node (MermaidNodeDAO): The freshly read mention.
        """
        if node.label == node.key:
            return
        self._nodes[node.key] = node

    def _decline(self) -> None:
        """Mark the whole source undrawable."""
        self._is_drawable = False


def _edge_label(*, match: re.Match[str]) -> str:
    """Return the label carried by one arrow match.

    WHAT: Mermaid spells an edge label four ways; this collapses them to the
    one that matched, or to no label at all.
    WHO: ``_GraphReader._read_chain`` calls it per arrow.
    WHEN: Once per arrow on a line.

    Args:
        match (re.Match[str]): One ``_ARROW_RE`` match.

    Returns:
        str: The edge label, empty when the arrow carries none.
    """
    for group in ("piped", "inline", "dotted", "thick"):
        captured: Optional[str] = match.group(group)
        if captured is not None:
            return captured.strip()
    return ""


def _node_from_match(*, match: re.Match[str]) -> MermaidNodeDAO:
    """Build one node from a matched mention.

    WHAT: Reads the key, and the label and shape its brackets asked for; a
    bare key labels itself with a plain rectangle.
    WHO: ``_GraphReader._node_from_text`` calls it on a successful match.
    WHEN: Once per readable node mention.

    Args:
        match (re.Match[str]): One ``_NODE_RE`` match.

    Returns:
        MermaidNodeDAO: The node the mention declares.
    """
    key: str = match.group("key")
    opening: Optional[str] = match.group("open")
    if opening is None:
        return MermaidNodeDAO(key=key, label=key, shape="rectangle")
    return MermaidNodeDAO(
        key=key,
        label=_strip_quotes(label=match.group("label")).strip() or key,
        shape=_SHAPE_BY_OPENING_BRACKET.get(opening, "rectangle"),
    )


def _content_lines(*, source: str) -> list[str]:
    """Return the source's meaningful lines, stripped of syntax noise.

    WHAT: Drops blank lines and ``%%`` comments and trims mermaid's optional
    trailing semicolons, so the reader only ever sees content.
    WHO: ``MermaidGraphParser.parse`` calls it once.
    WHEN: Before any line is read.

    Args:
        source (str): Verbatim fence body.

    Returns:
        list[str]: Stripped content lines, in source order.
    """
    lines: list[str] = []
    for raw_line in source.splitlines():
        line: str = raw_line.strip().rstrip(";").strip()
        if line and not line.startswith(_COMMENT_PREFIX):
            lines.append(line)
    return lines


class MermaidGraphParser:
    """Reads mermaid flowchart source into a graph, or declines it.

    WHAT: The single owner of mermaid's flowchart grammar. It returns a whole
    graph or nothing; it never returns a partial one, because a partial
    diagram misleads more than no diagram.
    WHO: ``MermaidChartBlock.compose`` calls it once per card mount, through
    ``MermaidGraphRenderer``.
    WHEN: At card mount, on the already-extracted fence body.
    """

    @classmethod
    def parse(cls, *, source: str) -> Optional[MermaidGraphDAO]:
        """Parse a fence body into a drawable flowchart.

        WHAT: Reads the directive, then every body line, and hands back a
        graph only when the whole source was understood.
        WHO: ``MermaidGraphRenderer.render`` is the only caller.
        WHEN: Once per chart card mount.

        Args:
            source (str): Verbatim mermaid fence body, without fence lines.

        Returns:
            Optional[MermaidGraphDAO]: The parsed graph, or ``None`` when the
                source is not a ``graph``/``flowchart`` this renderer draws.
        """
        lines: list[str] = _content_lines(source=source)
        if not lines:
            return None
        reader: _GraphReader = _GraphReader()
        reader.read_directive(line=lines[0])
        for line in lines[1:]:
            reader.read_body_line(line=line)
        return reader.result()
