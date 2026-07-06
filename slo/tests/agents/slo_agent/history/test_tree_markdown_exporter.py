"""Unit tests for ``TreeMarkdownExporter`` (sub-spec 42.a.5)."""

from __future__ import annotations

from src.agents.slo_agent.history.tree_builder import SessionTreeBuilder, SessionTreeNode
from src.tui.widgets.tree_markdown_exporter import TreeMarkdownExporter

from tests.agents.slo_agent.history.test_tree_builder import _build_event


class TestTreeMarkdownExporter:
    """Tests for ``TreeMarkdownExporter.export()``."""

    def test_export_simple_tree(self) -> None:
        """A simple tree produces correct Markdown hierarchy."""
        events = [
            _build_event(
                kind="user_message",
                turn_id="turn-1",
                sequence=1,
                content="hello",
            ),
        ]
        tree = SessionTreeBuilder.build(events=events)
        md = TreeMarkdownExporter.export(tree=tree)

        assert "# Session Tree" in md
        assert "**Turn:**" in md
        assert "**UserMessage:**" in md
        assert "hello" in md

    def test_export_nested_tree(self) -> None:
        """Nested events produce indented Markdown."""
        events = [
            _build_event(
                kind="user_message",
                turn_id="turn-1",
                sequence=1,
                content="hi",
            ),
            _build_event(
                kind="assistant_message",
                turn_id="turn-1",
                sequence=2,
                content="hello",
            ),
            _build_event(
                kind="tool_call",
                turn_id="turn-1",
                sequence=3,
                tool_name="bash",
                tool_call_id="tc1",
                metadata={"entry_id": "e3", "parent_entry_id": "e2"},
            ),
            _build_event(
                kind="tool_result",
                turn_id="turn-1",
                sequence=4,
                tool_name="bash",
                tool_call_id="tc1",
                tool_output="ok",
                metadata={"entry_id": "e4", "parent_entry_id": "e3"},
            ),
        ]
        tree = SessionTreeBuilder.build(events=events)
        md = TreeMarkdownExporter.export(tree=tree)

        # Four levels deep under root (root is skipped)
        lines = [l for l in md.split("\n") if l.strip() and l.strip().startswith("-")]
        # Should have Turn, UserMessage, AIMessage, ToolCall, ToolResult
        assert any("ToolCall" in l for l in lines)
        assert any("ToolResult" in l for l in lines)

    def test_export_no_emoji(self) -> None:
        """Emoji are stripped from Markdown labels."""
        events = [
            _build_event(
                kind="user_message",
                turn_id="turn-1",
                sequence=1,
                content="hello",
            ),
        ]
        tree = SessionTreeBuilder.build(events=events)
        md = TreeMarkdownExporter.export(tree=tree)

        # The emoji should not appear in the Markdown output
        assert "👤" not in md
        assert "UserMessage:" in md


def _build_deep_chain(*, depth: int) -> SessionTreeNode:
    """Build a single linear chain ``depth`` levels deep for guard tests."""
    root = SessionTreeNode(event_id="root", kind="session", label="🧠 Session")
    current = root
    for index in range(depth):
        child = SessionTreeNode(event_id=str(index), kind="tool_call", label=f"node {index}")
        current.add_child(node=child)
        current = child
    return root


class TestTreeMarkdownExporterDepthGuard:
    """Depth-guard regression tests for ``TreeMarkdownExporter``."""

    def test_export_deep_tree_does_not_recurse_to_error(self) -> None:
        """A tree far deeper than the recursion limit exports without crashing."""
        tree = _build_deep_chain(depth=5000)

        md = TreeMarkdownExporter.export(tree=tree)

        assert "tree depth limit reached" in md

    def test_export_shallow_tree_has_no_truncation_marker(self) -> None:
        """A normal-depth tree is never truncated."""
        tree = _build_deep_chain(depth=4)

        md = TreeMarkdownExporter.export(tree=tree)

        assert "tree depth limit reached" not in md
