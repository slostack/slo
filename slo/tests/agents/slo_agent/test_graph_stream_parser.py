"""Tests for the LangGraph dual-stream parser."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessageChunk

from src.agents.slo_agent.graph_stream_parser import parse_graph_stream_item


class TestParseGraphStreamItem:
    """Supported raw-item shapes and validation failures."""

    def test_parses_messages_pair_with_metadata(self) -> None:
        """A two-tuple messages item yields the chunk plus metadata."""
        chunk: AIMessageChunk = AIMessageChunk(content="hello")

        parsed = parse_graph_stream_item(
            raw_item=("messages", (chunk, {"langgraph_node": "agent"})),
        )

        assert parsed.mode == "messages"
        assert parsed.namespace == ()
        assert parsed.message_chunk == chunk
        assert parsed.message_metadata == {"langgraph_node": "agent"}
        assert parsed.update_chunk is None

    def test_parses_messages_pair_without_metadata(self) -> None:
        """A bare chunk messages item gets an empty metadata dict."""
        chunk: AIMessageChunk = AIMessageChunk(content="hello")

        parsed = parse_graph_stream_item(raw_item=("messages", chunk))

        assert parsed.mode == "messages"
        assert parsed.message_chunk == chunk
        assert parsed.message_metadata == {}

    def test_parses_updates_pair(self) -> None:
        """A two-tuple updates item yields an updates payload."""
        parsed = parse_graph_stream_item(raw_item=("updates", {"tools": {"messages": []}}))

        assert parsed.mode == "updates"
        assert parsed.update_chunk == {"tools": {"messages": []}}
        assert parsed.message_chunk is None

    def test_parses_namespaced_messages_triplet(self) -> None:
        """A namespaced messages item preserves the normalized namespace."""
        chunk: AIMessageChunk = AIMessageChunk(content="hello")

        parsed = parse_graph_stream_item(
            raw_item=(("outer", "agent"), "messages", (chunk, {"x": 1})),
        )

        assert parsed.mode == "messages"
        assert parsed.namespace == ("outer", "agent")
        assert parsed.message_chunk == chunk
        assert parsed.message_metadata == {"x": 1}

    def test_parses_namespaced_updates_triplet(self) -> None:
        """A namespaced updates item preserves the normalized namespace."""
        parsed = parse_graph_stream_item(
            raw_item=("graph", "updates", {"agent": {"messages": []}}),
        )

        assert parsed.mode == "updates"
        assert parsed.namespace == ("graph",)
        assert parsed.update_chunk == {"agent": {"messages": []}}

    def test_rejects_non_tuple_items(self) -> None:
        """Non-tuple raw items raise a clear ``ValueError``."""
        with pytest.raises(ValueError, match="Unsupported LangGraph stream item"):
            parse_graph_stream_item(raw_item={"messages": []})

    def test_rejects_unknown_tuple_length(self) -> None:
        """Tuple lengths other than 2 or 3 are rejected."""
        with pytest.raises(ValueError, match="Unsupported LangGraph stream tuple length"):
            parse_graph_stream_item(raw_item=("a", "b", "c", "d"))

    def test_rejects_unknown_mode_token(self) -> None:
        """Unknown mode tokens are rejected explicitly."""
        with pytest.raises(ValueError, match="Unsupported stream mode token"):
            parse_graph_stream_item(raw_item=("events", {}))

    def test_rejects_unsupported_messages_payload_shape(self) -> None:
        """Messages payloads must be chunks or ``(chunk, metadata)`` pairs."""
        with pytest.raises(ValueError, match="Unsupported messages payload"):
            parse_graph_stream_item(raw_item=("messages", ("not-a-chunk", {})))

    def test_rejects_unsupported_updates_payload_shape(self) -> None:
        """Updates payloads must be dicts."""
        with pytest.raises(ValueError, match="Unsupported updates payload"):
            parse_graph_stream_item(raw_item=("updates", ["not-a-dict"]))
