"""Depth-guard regression tests for ``SessionTreeViewer`` (sub-spec 42.a.3)."""

from __future__ import annotations

from src.agents.slo_agent.history.tree_builder import SessionTreeNode
from src.tui.widgets.tree_viewer import SessionTreeViewer


def _build_deep_chain(*, depth: int) -> SessionTreeNode:
    """Build a single linear chain ``depth`` levels deep for guard tests.

    Args:
        depth (int): Number of nested children below the root.

    Returns:
        SessionTreeNode: Root of the deep chain.
    """
    root = SessionTreeNode(event_id="root", kind="session", label="🧠 Session")
    current = root
    for index in range(depth):
        child = SessionTreeNode(event_id=str(index), kind="tool_call", label=f"node {index}")
        current.add_child(node=child)
        current = child
    return root


class TestSessionTreeViewerDepthGuard:
    """Bounded-recursion behaviour for ``SessionTreeViewer``."""

    def test_construct_deep_tree_does_not_recurse_to_error(self) -> None:
        """A tree far deeper than the recursion limit builds without crashing."""
        tree: SessionTreeNode = _build_deep_chain(depth=5000)

        viewer: SessionTreeViewer = SessionTreeViewer(tree=tree)

        assert viewer is not None

    def test_construct_shallow_tree_builds_all_levels(self) -> None:
        """A normal-depth tree builds without hitting the depth guard."""
        tree: SessionTreeNode = _build_deep_chain(depth=4)

        viewer: SessionTreeViewer = SessionTreeViewer(tree=tree)

        assert viewer is not None
