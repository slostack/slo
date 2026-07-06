"""Unit tests for ``TreeHtmlExporter`` (sub-spec 42.a.4)."""

from __future__ import annotations

from src.agents.slo_agent.history.tree_builder import SessionTreeBuilder, SessionTreeNode
from src.tui.widgets.tree_html_exporter import TreeHtmlExporter


class TestTreeHtmlExporter:
    """Tests for ``TreeHtmlExporter.export()``."""

    def test_export_creates_file(self) -> None:
        """A simple tree produces a non-empty HTML file."""
        tree = SessionTreeBuilder.build(events=[])
        path = TreeHtmlExporter.export(tree=tree, session_name="test")

        assert path.exists()
        assert path.stat().st_size > 0
        content = path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content

    def test_export_contains_session_name(self) -> None:
        """HTML body contains the session name."""
        tree = SessionTreeBuilder.build(events=[])
        path = TreeHtmlExporter.export(tree=tree, session_name="test-session")
        content = path.read_text(encoding="utf-8")

        assert "Session: test-session" in content

    def test_export_contains_tree_structure(self) -> None:
        """HTML contains branch lines and colored spans."""
        from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
        from datetime import datetime, timezone

        events = [
            SessionHistoryEventDAO(
                event_id="e1",
                session_id="s1",
                turn_id="t1",
                sequence=1,
                kind="user_message",
                payload=SessionHistoryEventPayloadDAO(content="hello"),
            ),
            SessionHistoryEventDAO(
                event_id="e2",
                session_id="s1",
                turn_id="t1",
                sequence=2,
                kind="assistant_message",
                payload=SessionHistoryEventPayloadDAO(content="hi"),
            ),
        ]
        tree = SessionTreeBuilder.build(events=events)
        path = TreeHtmlExporter.export(tree=tree, session_name="test")
        content = path.read_text(encoding="utf-8")

        assert "├──" in content or "└──" in content
        assert "<span" in content

    def test_export_escapes_html(self) -> None:
        """HTML content is escaped to prevent XSS."""
        from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO

        events = [
            SessionHistoryEventDAO(
                event_id="e1",
                session_id="s1",
                turn_id="t1",
                sequence=1,
                kind="user_message",
                payload=SessionHistoryEventPayloadDAO(content="<script>alert('xss')</script>"),
            ),
        ]
        tree = SessionTreeBuilder.build(events=events)
        path = TreeHtmlExporter.export(tree=tree, session_name="test")
        content = path.read_text(encoding="utf-8")

        assert "<script>" not in content
        assert "&lt;script&gt;" in content

    def test_export_matches_reference_style(self) -> None:
        """Generated HTML has the dark theme and monospace font from the spec."""
        tree = SessionTreeBuilder.build(events=[])
        path = TreeHtmlExporter.export(tree=tree, session_name="test")
        content = path.read_text(encoding="utf-8")

        assert "#1a1b26" in content
        assert "monospace" in content


def _build_deep_chain(*, depth: int) -> SessionTreeNode:
    """Build a single linear chain ``depth`` levels deep for guard tests."""
    root = SessionTreeNode(event_id="root", kind="session", label="🧠 Session")
    current = root
    for index in range(depth):
        child = SessionTreeNode(event_id=str(index), kind="tool_call", label=f"node {index}")
        current.add_child(node=child)
        current = child
    return root


class TestTreeHtmlExporterDepthGuard:
    """Depth-guard regression tests for ``TreeHtmlExporter``."""

    def test_export_deep_tree_does_not_recurse_to_error(self) -> None:
        """A tree far deeper than the recursion limit exports without crashing."""
        tree = _build_deep_chain(depth=5000)

        path = TreeHtmlExporter.export(tree=tree, session_name="deep")
        content = path.read_text(encoding="utf-8")

        assert "tree depth limit reached" in content

    def test_export_shallow_tree_has_no_truncation_marker(self) -> None:
        """A normal-depth tree is never truncated."""
        tree = _build_deep_chain(depth=4)

        path = TreeHtmlExporter.export(tree=tree, session_name="shallow")
        content = path.read_text(encoding="utf-8")

        assert "tree depth limit reached" not in content
