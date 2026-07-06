"""SessionTreeViewer — renders a SessionTreeNode as an interactive Textual Tree."""

from __future__ import annotations

from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from src.agents.slo_agent.history.tree_builder import MAX_TREE_DEPTH, SessionTreeNode

__all__ = ["SessionTreeViewer"]


class SessionTreeViewer(Tree):
    """Interactive tree widget for session history visualization.

    Renders a SessionTreeNode hierarchy using Textual's built-in Tree widget.
    Nodes are foldable and colored by event kind via CSS classes.
    """

    DEFAULT_CSS = """
    SessionTreeViewer {
        width: 100%;
        height: auto;
        max-height: 50;
        padding: 0 1;
        margin: 1 0;
        border: solid $primary;
    }
    SessionTreeViewer .tree-node-session {
        color: $primary;
        text-style: bold;
    }
    SessionTreeViewer .tree-node-turn {
        color: $primary;
        text-style: bold;
    }
    SessionTreeViewer .tree-node-user {
        color: $text;
    }
    SessionTreeViewer .tree-node-assistant {
        color: $success;
    }
    SessionTreeViewer .tree-node-thinking {
        color: $text-muted;
    }
    SessionTreeViewer .tree-node-tool {
        color: $warning;
    }
    SessionTreeViewer .tree-node-steering {
        color: $warning;
        text-style: italic;
    }
    SessionTreeViewer .tree-node-compaction {
        color: $error;
        text-style: bold;
    }
    SessionTreeViewer .tree-node-lifecycle {
        color: $text-muted;
        text-style: dim;
    }
    """

    def __init__(self, *, tree: SessionTreeNode) -> None:
        """Construct the tree viewer from a SessionTreeNode root.

        Args:
            tree: Root node of the session tree (from SessionTreeBuilder).
        """
        super().__init__(tree.label)
        self._session_tree = tree
        self._build_tree()

    def _build_tree(self) -> None:
        """Recursively build Textual TreeNodes from SessionTreeNode."""
        root = self.root
        self._build_tree_children(
            parent_node=root,
            session_children=self._session_tree.children,
        )
        # Expand top-level turns by default, collapse everything else
        root.expand()
        for child in root.children:
            if child.data == "turn":
                child.expand()
            else:
                child.collapse()

    def _build_tree_children(
        self,
        *,
        parent_node: TreeNode,
        session_children: list[SessionTreeNode],
        depth: int = 0,
    ) -> None:
        """Recursively add SessionTreeNode children to a Textual TreeNode.

        Recursion is bounded by ``MAX_TREE_DEPTH`` so a malformed (pathologically
        deep) tree degrades to a truncation marker instead of overflowing the
        Python stack with a RecursionError.

        Args:
            parent_node: The Textual TreeNode to add children to.
            session_children: SessionTreeNode children to add.
            depth: Current recursion depth (0 at the root).
        """
        if depth >= MAX_TREE_DEPTH:
            parent_node.add_leaf("… (tree depth limit reached)")
            return
        for child in session_children:
            _ = self._css_class_for_kind(kind=child.kind)
            tree_node = parent_node.add(
                child.label,
                data=child.kind,
                expand=False,
            )
            if child.children:
                self._build_tree_children(
                    parent_node=tree_node,
                    session_children=child.children,
                    depth=depth + 1,
                )

    @staticmethod
    def _css_class_for_kind(*, kind: str) -> str:
        """Return the CSS class for a given event kind.

        Args:
            kind: The HistoryEventKind or synthetic kind.

        Returns:
            str: CSS class name for styling.
        """
        kind_map: dict[str, str] = {
            "session": "tree-node-session",
            "turn": "tree-node-turn",
            "user_message": "tree-node-user",
            "steering_message": "tree-node-steering",
            "assistant_message": "tree-node-assistant",
            "assistant_delta": "tree-node-assistant",
            "tool_call": "tree-node-tool",
            "tool_result": "tree-node-tool",
            "compaction_summary": "tree-node-compaction",
            "session_started": "tree-node-lifecycle",
            "run_started": "tree-node-lifecycle",
            "run_completed": "tree-node-lifecycle",
            "run_aborted": "tree-node-lifecycle",
            "run_failed": "tree-node-lifecycle",
            "run_retrying": "tree-node-lifecycle",
            "route_switched": "tree-node-lifecycle",
            "slash_command": "tree-node-lifecycle",
            "orchestrator_started": "tree-node-lifecycle",
            "sub_agent_spawned": "tree-node-lifecycle",
            "sub_agent_completed": "tree-node-lifecycle",
        }
        return kind_map.get(kind, "tree-node-lifecycle")
