"""TreeHtmlExporter — generates self-contained HTML from a SessionTreeNode.

Style matches the reference conversation-tree.html:
- Dark background (#1a1b26)
- Monospace font
- Colored spans per event kind
- Emoji prefixes
- ASCII branch lines
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.agents.slo_agent.history.tree_builder import MAX_TREE_DEPTH, SessionTreeNode

__all__ = ["TreeHtmlExporter"]


@dataclass(frozen=True)
class _HtmlColorScheme:
    """Color scheme for one event kind in HTML output."""

    color: str
    weight: str = "normal"
    style: str = "normal"


class TreeHtmlExporter:
    """Stateless HTML exporter for session trees."""

    _COLORS: dict[str, _HtmlColorScheme] = {
        "session": _HtmlColorScheme(color="#7dcfff", weight="bold"),
        "turn": _HtmlColorScheme(color="#000080", weight="bold"),
        "user_message": _HtmlColorScheme(color="#c0c0c0"),
        "steering_message": _HtmlColorScheme(color="#c0c0c0", style="italic"),
        "assistant_message": _HtmlColorScheme(color="#008000"),
        "assistant_delta": _HtmlColorScheme(color="#008000"),
        "tool_call": _HtmlColorScheme(color="#c0c0c0"),
        "tool_result": _HtmlColorScheme(color="#008000", weight="bold"),
        "compaction_summary": _HtmlColorScheme(color="#ffffff", weight="bold"),
        "session_started": _HtmlColorScheme(color="#dfdfdf", style="italic"),
        "run_started": _HtmlColorScheme(color="#dfdfdf", style="italic"),
        "run_completed": _HtmlColorScheme(color="#dfdfdf", style="italic"),
        "run_aborted": _HtmlColorScheme(color="#dfdfdf", style="italic"),
        "run_failed": _HtmlColorScheme(color="#dfdfdf", style="italic"),
        "run_retrying": _HtmlColorScheme(color="#dfdfdf", style="italic"),
        "preflight_bypassed": _HtmlColorScheme(color="#dfdfdf", style="italic"),
        "provider_limit_observed": _HtmlColorScheme(color="#dfdfdf", style="italic"),
        "route_switched": _HtmlColorScheme(color="#dfdfdf", style="italic"),
        "slash_command": _HtmlColorScheme(color="#dfdfdf", style="italic"),
    }

    _BRANCH_COLOR: str = "#808080"
    _SESSION_COLOR: str = "#008080"
    _META_COLOR: str = "#bfbf7f"
    _DATE_COLOR: str = "#dfdfdf"
    _ID_COLOR: str = "#dfdfdf"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    @classmethod
    def export(
        cls,
        *,
        tree: SessionTreeNode,
        session_name: str,
        model_name: Optional[str] = None,
    ) -> Path:
        """Export a session tree to a self-contained HTML file.

        Args:
            tree: Root node of the session tree.
            session_name: Human-readable session name.
            model_name: Active model name (optional).

        Returns:
            Path: Path to the generated HTML file.
        """
        html = cls._generate_html(
            tree=tree,
            session_name=session_name,
            model_name=model_name,
        )
        path = cls._write_to_temp_file(html=html, session_name=session_name)
        return path

    # ------------------------------------------------------------------
    # HTML generation
    # ------------------------------------------------------------------

    @classmethod
    def _generate_html(
        cls,
        *,
        tree: SessionTreeNode,
        session_name: str,
        model_name: Optional[str] = None,
    ) -> str:
        """Generate the complete HTML document."""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        model_tag = f" &nbsp;·&nbsp; {model_name}" if model_name else ""

        body_lines = cls._render_tree_lines(tree=tree)
        body = "\n".join(body_lines)

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
body {{
    color: #000000;
    background-color: #ffffff;
}}
</style>
</head>
<body style="margin:0;padding:0;background:#1a1b26;font-size:13px;">
<div style="max-width:1400px;margin:0 auto;padding:32px 24px;">
<h1 style="font-family:monospace;color:#7dcfff;margin-bottom:4px;font-size:18px;">
  🧠 Slo Conversation Tree
</h1>
<p style="font-family:monospace;color:#565f89;font-size:12px;margin-top:0;margin-bottom:24px;">
  Session: {session_name} &nbsp;·&nbsp; {model_name or 'unknown model'} &nbsp;·&nbsp; {timestamp}
</p>
    <pre style="font-family:Menlo,'DejaVu Sans Mono',consolas,'Courier New',monospace"><code style="font-family:inherit">
{body}
    </code></pre>
</div>
</body>
</html>"""

    # ------------------------------------------------------------------
    # Tree rendering (recursive)
    # ------------------------------------------------------------------

    @classmethod
    def _render_tree_lines(
        cls,
        *,
        tree: SessionTreeNode,
        prefix: str = "",
        depth: int = 0,
    ) -> list[str]:
        """Render tree nodes as HTML lines with colored spans.

        Recursion is bounded by ``MAX_TREE_DEPTH`` so a malformed (pathologically
        deep) tree degrades to a truncation marker instead of overflowing the
        stack with a RecursionError.

        Args:
            tree: Root node to render.
            prefix: Indentation prefix (for recursive calls).
            depth: Current recursion depth (0 at the root).

        Returns:
            list[str]: HTML lines.
        """
        if depth >= MAX_TREE_DEPTH:
            return [f"{prefix}… (tree depth limit reached)"]

        lines: list[str] = []
        kind = tree.kind
        color = cls._COLORS.get(kind, cls._COLORS["session"])

        # Escape HTML in the label
        label = cls._escape_html(text=tree.label)

        # Render the current node
        lines.append(
            f'{prefix}<span style="color: {color.color}; '
            f"font-weight: {color.weight}; "
            f'font-style: {color.style}">{label}</span>'
        )

        # Render children with branch lines
        for i, child in enumerate(tree.children):
            is_last = i == len(tree.children) - 1
            branch = "└── " if is_last else "├── "
            child_prefix = prefix + ("    " if is_last else "│   ")

            # Add branch line prefix
            branch_span = f'<span style="color: {cls._BRANCH_COLOR}">{branch}</span>'
            child_lines = cls._render_tree_lines(
                tree=child,
                prefix=child_prefix,
                depth=depth + 1,
            )
            if child_lines:
                # Prepend branch to first child line
                first_child = child_lines[0].lstrip()
                lines.append(f"{prefix}{branch_span}{first_child}")
                lines.extend(child_lines[1:])

        return lines

    @staticmethod
    def _escape_html(*, text: str) -> str:
        """Escape HTML special characters in text."""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    @staticmethod
    def _write_to_temp_file(*, html: str, session_name: str) -> Path:
        """Write HTML to a temp file and return the path.

        Args:
            html: Complete HTML document.
            session_name: Used in the filename.

        Returns:
            Path: Path to the written file.
        """
        safe_name = "".join(c if c.isalnum() else "-" for c in session_name)
        path = Path(tempfile.gettempdir()) / f"slo-tree-{safe_name}.html"
        path.write_text(html, encoding="utf-8")
        return path
