"""SessionTreeBuilder — builds a tree from SessionHistoryEventDAO events.

Uses entry_id / parent_entry_id metadata from TreeBasedFilesystemSessionHistoryStore
to construct a hierarchical tree suitable for visualization and export.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.agents.slo_agent.history.dao import (
    HistoryEventKind,
    SessionHistoryEventDAO,
)

__all__ = ["SessionTreeNode", "SessionTreeBuilder", "MAX_TREE_DEPTH"]

# Hard ceiling on how deep any consumer is allowed to recurse when walking a
# session tree. A correctly-built tree is at most four levels deep
# (session -> turn -> tool_call -> tool_result), so this generous bound never
# truncates legitimate output; it exists purely so a malformed or future-broken
# tree degrades gracefully instead of raising RecursionError during render.
MAX_TREE_DEPTH: int = 64


class SessionTreeNode(BaseModel):
    """One node in the session tree visualization.

    Attributes:
        event_id: The entry_id of the backing event (or synthetic id).
        kind: The HistoryEventKind (or "turn", "iteration", "session" for synthetics).
        label: Human-readable display label with emoji prefix.
        children: Child nodes in tree order.
        parent: Parent node (None for root).
        metadata: Additional metadata for export/rendering.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    event_id: str = Field(description="The entry_id of the backing event (or synthetic id).")
    kind: str = Field(description="The HistoryEventKind (or 'turn', 'iteration', 'session' for synthetics).")
    label: str = Field(description="Human-readable display label with emoji prefix.")
    children: list["SessionTreeNode"] = Field(default_factory=list, description="Child nodes in tree order.")
    parent: Optional["SessionTreeNode"] = Field(default=None, description="Parent node.")
    metadata: dict = Field(default_factory=dict, description="Additional metadata for export/rendering.")

    def add_child(self, *, node: "SessionTreeNode") -> None:
        """Add a child and set its parent pointer."""
        node.parent = self
        self.children.append(node)


SessionTreeNode.model_rebuild()


class SessionTreeBuilder:
    """Stateless builder that constructs a SessionTreeNode tree from events.

    All methods are classmethods; the class is never instantiated.
    Entry point: ``build(events)``.
    """

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    @classmethod
    def build(cls, *, events: list[SessionHistoryEventDAO]) -> SessionTreeNode:
        """Build a tree from a flat list of events.

        Args:
            events: Events in append order (from load_events).

        Returns:
            SessionTreeNode: Root node of the tree.
        """
        if not events:
            return cls._empty_root()

        # Pass 1: create one node per event, preserving append order.
        nodes: list[SessionTreeNode] = [cls._event_to_node(event=event) for event in events]
        node_by_id: dict[str, SessionTreeNode] = {node.event_id: node for node in nodes}

        # Pass 2: nest tool_results under their opening tool_call; the rest
        # stays on a flat per-turn timeline. ``parent_entry_id`` is NOT a
        # display hierarchy — in the store it is a linear lineage pointer where
        # every event points at the previous one, so following it for all kinds
        # rebuilds the entire event log as one branch as deep as the event count.
        timeline_nodes: list[SessionTreeNode] = cls._attach_tool_results(
            nodes=nodes,
            node_by_id=node_by_id,
        )

        # Pass 3: group the flat timeline into turn nodes under the session root.
        turn_nodes: list[SessionTreeNode] = cls._group_by_turn(timeline_nodes=timeline_nodes)
        return cls._build_session_root(turn_nodes=turn_nodes)

    # ------------------------------------------------------------------
    # Pass 2: tool-call / tool-result pairing
    # ------------------------------------------------------------------

    @classmethod
    def _attach_tool_results(
        cls,
        *,
        nodes: list[SessionTreeNode],
        node_by_id: dict[str, SessionTreeNode],
    ) -> list[SessionTreeNode]:
        """Nest each tool_result under its tool_call; return the flat timeline.

        Only ``tool_result`` nodes are nested, and only beneath a matching
        ``tool_call`` resolved via ``parent_entry_id``. Every other event — and
        any ``tool_result`` whose ``tool_call`` is missing — stays on the flat
        per-turn timeline. This keeps the tree shallow
        (``session -> turn -> tool_call -> tool_result``) instead of
        reconstructing the storage layer's linear ``parent_entry_id`` lineage
        chain, which is as deep as the number of events.

        Args:
            nodes (list[SessionTreeNode]): All event nodes in append order.
            node_by_id (dict[str, SessionTreeNode]): Lookup from entry_id to node.

        Returns:
            list[SessionTreeNode]: Timeline nodes to be grouped into turns.
        """
        timeline_nodes: list[SessionTreeNode] = []
        for node in nodes:
            tool_call_parent: Optional[SessionTreeNode] = cls._tool_call_parent_for(
                node=node,
                node_by_id=node_by_id,
            )
            if tool_call_parent is None:
                timeline_nodes.append(node)
                continue
            tool_call_parent.add_child(node=node)
        return timeline_nodes

    @classmethod
    def _tool_call_parent_for(
        cls,
        *,
        node: SessionTreeNode,
        node_by_id: dict[str, SessionTreeNode],
    ) -> Optional[SessionTreeNode]:
        """Return the opening tool_call for a tool_result node, or None.

        Args:
            node (SessionTreeNode): Candidate node.
            node_by_id (dict[str, SessionTreeNode]): Lookup from entry_id to node.

        Returns:
            Optional[SessionTreeNode]: The matching ``tool_call`` node when
                ``node`` is a ``tool_result`` whose ``parent_entry_id`` resolves
                to a ``tool_call``; otherwise None.
        """
        if node.kind != "tool_result":
            return None
        parent_entry_id: Optional[str] = node.metadata.get("parent_entry_id")
        if not parent_entry_id:
            return None
        parent: Optional[SessionTreeNode] = node_by_id.get(parent_entry_id)
        if parent is None or parent.kind != "tool_call":
            return None
        return parent

    # ------------------------------------------------------------------
    # Pass 1: event → node
    # ------------------------------------------------------------------

    @classmethod
    def _event_to_node(cls, *, event: SessionHistoryEventDAO) -> SessionTreeNode:
        """Convert one event to a tree node."""
        entry_id = str(event.payload.metadata.get("entry_id", event.event_id))
        parent_entry_id = event.payload.metadata.get("parent_entry_id")
        label = cls._label_for_event(event=event)
        return SessionTreeNode(
            event_id=entry_id,
            kind=event.kind,
            label=label,
            metadata={
                "parent_entry_id": parent_entry_id,
                "turn_id": event.turn_id,
                "sequence": event.sequence,
                "iteration": event.iteration,
                "recorded_at": event.recorded_at.isoformat(),
            },
        )

    # ------------------------------------------------------------------
    # Label generation
    # ------------------------------------------------------------------

    _KIND_EMOJI: dict[str, str] = {
        "user_message": "👤",
        "steering_message": "⏳",
        "assistant_message": "🤖",
        "assistant_delta": "🤖",
        "tool_call": "🔧",
        "tool_result": "✅",
        "compaction_summary": "📦",
        "session_started": "🚀",
        "run_started": "▶️",
        "run_completed": "⏹️",
        "run_aborted": "🛑",
        "run_failed": "❌",
        "run_retrying": "🔄",
        "preflight_bypassed": "⚠️",
        "provider_limit_observed": "⚠️",
        "route_switched": "🔀",
        "slash_command": "⚡",
        "orchestrator_started": "🎛️",
        "sub_agent_spawned": "👶",
        "sub_agent_completed": "✅",
    }

    _KIND_LABEL: dict[str, str] = {
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
        "preflight_bypassed": "PreflightBypassed",
        "provider_limit_observed": "ProviderLimitObserved",
        "route_switched": "RouteSwitched",
        "slash_command": "SlashCommand",
        "orchestrator_started": "OrchestratorStarted",
        "sub_agent_spawned": "SubAgentSpawned",
        "sub_agent_completed": "SubAgentCompleted",
    }

    @classmethod
    def _label_for_event(cls, *, event: SessionHistoryEventDAO) -> str:
        """Generate a human-readable label for one event."""
        kind = event.kind
        emoji = cls._KIND_EMOJI.get(kind, "❓")
        kind_label = cls._KIND_LABEL.get(kind, kind)

        content = cls._extract_content(event=event)
        content = cls._truncate(text=content, max_length=80)

        # Add iteration info for assistant messages
        iteration_tag = ""
        if kind in ("assistant_message", "assistant_delta") and event.iteration > 0:
            iteration_tag = f" (iteration {event.iteration})"

        # Add tool call id for tool events
        tool_id_tag = ""
        if kind in ("tool_call", "tool_result") and event.payload.tool_call_id:
            tool_id_tag = f" [id={event.payload.tool_call_id[:12]}]"

        return f"{emoji} {kind_label}{iteration_tag}{tool_id_tag}: {content}"

    @classmethod
    def _extract_content(cls, *, event: SessionHistoryEventDAO) -> str:
        """Extract displayable content from an event payload."""
        payload = event.payload
        if payload.content:
            return payload.content
        if payload.tool_name and payload.tool_input:
            return f"{payload.tool_name}({cls._format_tool_input(payload.tool_input)})"
        if payload.tool_output:
            return payload.tool_output
        if payload.message:
            return payload.message
        if payload.error_message:
            return payload.error_message
        return ""

    @staticmethod
    def _format_tool_input(tool_input: dict) -> str:
        """Format tool input dict as a compact string."""
        parts = [f"{k}={repr(v)[:30]}" for k, v in tool_input.items()]
        return ", ".join(parts)

    @staticmethod
    def _truncate(*, text: str, max_length: int) -> str:
        """Truncate text to max_length, adding ellipsis."""
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."

    # ------------------------------------------------------------------
    # Pass 3: group root nodes by turn
    # ------------------------------------------------------------------

    @classmethod
    def _group_by_turn(cls, *, timeline_nodes: list[SessionTreeNode]) -> list[SessionTreeNode]:
        """Group flat timeline nodes into turn nodes.

        Args:
            timeline_nodes (list[SessionTreeNode]): Flat per-turn timeline nodes
                (tool_results already nested under their tool_call).

        Returns:
            list[SessionTreeNode]: Turn nodes plus any preamble nodes, in order.
        """
        # Sort by sequence to maintain order
        sorted_nodes = sorted(timeline_nodes, key=lambda n: n.metadata.get("sequence", 0))

        # Group by turn_id
        turn_groups: dict[str, list[SessionTreeNode]] = {}
        for node in sorted_nodes:
            turn_id = node.metadata.get("turn_id")
            if turn_id is None:
                turn_id = "preamble"
            turn_groups.setdefault(turn_id, []).append(node)

        # Build turn nodes
        turn_nodes: list[SessionTreeNode] = []
        for turn_idx, (turn_id, nodes) in enumerate(turn_groups.items(), start=1):
            if turn_id == "preamble":
                # Preamble events (session_started, etc.) go directly to root
                turn_nodes.extend(nodes)
                continue

            turn_label = cls._turn_label(turn_id=turn_id, turn_idx=turn_idx, nodes=nodes)
            turn_node = SessionTreeNode(
                event_id=turn_id,
                kind="turn",
                label=turn_label,
                metadata={"turn_id": turn_id, "turn_index": turn_idx},
            )
            for node in nodes:
                turn_node.add_child(node=node)
            turn_nodes.append(turn_node)

        return turn_nodes

    @classmethod
    def _turn_label(cls, *, turn_id: str, turn_idx: int, nodes: list[SessionTreeNode]) -> str:
        """Generate a label for a turn node."""
        # Find first user_message or steering_message for the summary
        summary = ""
        for node in nodes:
            if node.kind in ("user_message", "steering_message"):
                summary = node.label.split(": ", 1)[1] if ": " in node.label else ""
                summary = cls._truncate(text=summary, max_length=60)
                break
        if summary:
            return f"Turn {turn_idx}: {summary}"
        return f"Turn {turn_idx}"

    # ------------------------------------------------------------------
    # Session root
    # ------------------------------------------------------------------

    @classmethod
    def _build_session_root(cls, *, turn_nodes: list[SessionTreeNode]) -> SessionTreeNode:
        """Build the session root node containing all turn nodes."""
        root = SessionTreeNode(
            event_id="session-root",
            kind="session",
            label="🧠 Session",
        )
        for node in turn_nodes:
            root.add_child(node=node)
        return root

    @classmethod
    def _empty_root(cls) -> SessionTreeNode:
        """Return an empty session root."""
        return SessionTreeNode(
            event_id="session-root",
            kind="session",
            label="🧠 Session (empty)",
        )
