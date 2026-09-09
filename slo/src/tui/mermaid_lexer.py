"""Minimal Pygments grammar for mermaid diagram sources.

Pygments ships no mermaid lexer — verified against 2.20.0, where
``get_lexer_by_name("mermaid")`` raises ``ClassNotFound`` and
``Syntax(code, "mermaid")`` renders byte-identically to ``Syntax(code,
"text")``. Rich's ``Syntax`` accepts a ``Lexer`` instance, so the card
supplies its own grammar. Pygments itself is already installed as a hard
requirement of Rich; ``pyproject.toml`` declares it explicitly because a
transitive package is not a contract (see the file's header comment).
"""

from __future__ import annotations

from pygments.lexer import RegexLexer, words
from pygments.token import Keyword, Name, Operator, Punctuation, String, Text

__all__ = ["MermaidLexer"]

_DIAGRAM_KEYWORDS: tuple[str, ...] = (
    "graph",
    "flowchart",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram-v2",
    "stateDiagram",
    "erDiagram",
    "journey",
    "gantt",
    "pie",
    "gitGraph",
    "subgraph",
    "end",
    "participant",
    "actor",
    "loop",
    "alt",
    "else",
    "opt",
    "par",
    "note",
    "class",
    "state",
    "section",
    "title",
    "direction",
)
"""Diagram directives and block keywords across the common mermaid dialects."""


class MermaidLexer(RegexLexer):
    """Highlight mermaid directives, edges, labels, and node punctuation.

    WHAT: A single-state regex grammar. It is deliberately shallow — enough
    to make structure readable in a terminal, not a mermaid validator.
    WHO: ``MermaidSourceSurface`` passes an instance to Rich ``Syntax``.
    WHEN: Once per chart card render.
    """

    name = "mermaid"
    aliases = ["mermaid"]
    filenames = ["*.mmd"]

    tokens = {
        "root": [
            (r"%%.*?$", Text),
            (words(_DIAGRAM_KEYWORDS, suffix=r"\b"), Keyword),
            (r'"[^"]*"', String),
            (r"(-{1,2}>{1,2}|={2,}>|-\.->|-{3,}|\.{2,}>|<-{1,2}>|\|)", Operator),
            (r"[\[\]{}()>]", Punctuation),
            (r"[A-Za-z_][\w-]*", Name),
            (r"\s+", Text),
            (r".", Text),
        ]
    }
