"""TreeMarkdownExporter — generates Markdown from a SessionTreeNode."""

from __future__ import annotations

from src.agents.slo_agent.history.tree_builder import MAX_TREE_DEPTH, SessionTreeNode

__all__ = ["TreeMarkdownExporter"]


class TreeMarkdownExporter:
    """Stateless Markdown exporter for session trees."""

    @classmethod
    def export(cls, *, tree: SessionTreeNode) -> str:
        """Export a session tree to a Markdown string.

        Args:
            tree: Root node of the session tree.

        Returns:
            str: Markdown representation of the tree.
        """
        lines: list[str] = ["# Session Tree\n"]
        lines.extend(cls._render_node(node=tree, depth=0))
        return "\n".join(lines)

    @classmethod
    def _render_node(cls, *, node: SessionTreeNode, depth: int) -> list[str]:
        """Render one node and its children as Markdown lines.

        Args:
            node: SessionTreeNode to render.
            depth: Current nesting depth (0 = root).

        Returns:
            list[str]: Markdown lines for this node and its children.
        """
        lines: list[str] = []
        indent = "  " * depth

        # Bound recursion so a malformed (pathologically deep) tree degrades to a
        # truncation marker instead of overflowing the stack with a RecursionError.
        if depth >= MAX_TREE_DEPTH:
            lines.append(f"{indent}- … (tree depth limit reached)")
            return lines

        # Skip the synthetic root node for cleaner output
        if depth > 0:
            kind_label = cls._kind_label(kind=node.kind)
            content = cls._extract_content(label=node.label)
            lines.append(f"{indent}- **{kind_label}:** {content}")

        for child in node.children:
            lines.extend(cls._render_node(node=child, depth=depth + 1))

        return lines

    @staticmethod
    def _kind_label(*, kind: str) -> str:
        """Return a human-readable kind label for Markdown."""
        kind_map: dict[str, str] = {
            "session": "Session",
            "turn": "Turn",
            "user_message": "UserMessage",
            "steering_message": "SteeringMessage",
            "assistant_message": "AIMessage",
            "assistant_delta": "AIMessage",
            "tool_call": "ToolCall",
            "tool_result": "ToolResult",
            "compaction_summary": "CompactionSummary",
            "session_started": "SessionStarted",
            "run_started": "RunStarted",
            "run_completed": "RunCompleted",
            "run_aborted": "RunAborted",
            "run_failed": "RunFailed",
            "run_retrying": "RunRetrying",
            "route_switched": "RouteSwitched",
            "slash_command": "SlashCommand",
            "orchestrator_started": "OrchestratorStarted",
            "sub_agent_spawned": "SubAgentSpawned",
            "sub_agent_completed": "SubAgentCompleted",
        }
        return kind_map.get(kind, kind)

    @staticmethod
    def _extract_content(*, label: str) -> str:
        """Extract content from a label string, removing emoji prefix."""
        # Remove emoji prefix (everything before first space)
        if " " in label:
            return label.split(" ", 1)[1]
        return label
