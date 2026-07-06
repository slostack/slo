"""Version-safe parser for LangGraph dual-stream items."""

from __future__ import annotations

from typing import Any, Literal, Optional

from langchain_core.messages import AIMessageChunk, BaseMessage
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ParsedGraphStreamItemDAO",
    "parse_graph_stream_item",
]


class ParsedGraphStreamItemDAO(BaseModel):
    """One decoded LangGraph stream item.

    Attributes:
        mode (Literal["messages", "updates"]): Originating stream mode.
        namespace (tuple[str, ...]): Optional LangGraph namespace path.
        message_chunk (Optional[BaseMessage]): Present for ``messages`` items.
        message_metadata (dict[str, Any]): Per-chunk metadata from LangGraph.
        update_chunk (Optional[dict[str, Any]]): Present for ``updates`` items.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    mode: Literal["messages", "updates"]
    namespace: tuple[str, ...] = ()
    message_chunk: Optional[BaseMessage] = None
    message_metadata: dict[str, Any] = Field(default_factory=dict)
    update_chunk: Optional[dict[str, Any]] = None


def parse_graph_stream_item(*, raw_item: object) -> ParsedGraphStreamItemDAO:
    """Parse one raw LangGraph dual-stream item.

    Supported shapes:

    1. ``("messages", (AIMessageChunk, metadata))``
    2. ``("messages", AIMessageChunk)``
    3. ``("updates", update_dict)``
    4. ``(namespace, "messages", (AIMessageChunk, metadata))``
    5. ``(namespace, "updates", update_dict)``

    Args:
        raw_item (object): Raw item yielded by ``graph.astream(...)``.

    Returns:
        ParsedGraphStreamItemDAO: Parsed stream item.

    Raises:
        ValueError: When the raw item shape is unknown.
    """
    if not isinstance(raw_item, tuple):
        raise ValueError(f"Unsupported LangGraph stream item: {raw_item!r}")

    if len(raw_item) == 2:
        return _parse_pair(
            mode_token=raw_item[0],
            payload=raw_item[1],
            namespace=(),
        )

    if len(raw_item) == 3:
        namespace: tuple[str, ...] = _coerce_namespace(raw_namespace=raw_item[0])
        return _parse_pair(
            mode_token=raw_item[1],
            payload=raw_item[2],
            namespace=namespace,
        )

    raise ValueError(f"Unsupported LangGraph stream tuple length: {len(raw_item)}")


def _parse_pair(
    *,
    mode_token: object,
    payload: object,
    namespace: tuple[str, ...],
) -> ParsedGraphStreamItemDAO:
    """Parse one already-split ``(mode, payload)`` pair.

    Args:
        mode_token (object): Stream mode token.
        payload (object): Payload for the mode.
        namespace (tuple[str, ...]): Parsed namespace path.

    Returns:
        ParsedGraphStreamItemDAO: Parsed item.

    Raises:
        ValueError: When the mode token or payload is unsupported.
    """
    if mode_token == "messages":
        message_chunk, message_metadata = _parse_message_payload(payload=payload)
        return ParsedGraphStreamItemDAO(
            mode="messages",
            namespace=namespace,
            message_chunk=message_chunk,
            message_metadata=message_metadata,
        )

    if mode_token == "updates":
        if not isinstance(payload, dict):
            raise ValueError(f"Unsupported updates payload: {payload!r}")
        return ParsedGraphStreamItemDAO(
            mode="updates",
            namespace=namespace,
            update_chunk=dict(payload),
        )

    raise ValueError(f"Unsupported stream mode token: {mode_token!r}")


def _parse_message_payload(*, payload: object) -> tuple[BaseMessage, dict[str, Any]]:
    """Parse one ``messages`` payload.

    Args:
        payload (object): Payload from LangGraph's ``messages`` mode.

    Returns:
        tuple[BaseMessage, dict[str, Any]]: Decoded message chunk and metadata.

    Raises:
        ValueError: When the payload shape is unsupported.
    """
    if isinstance(payload, BaseMessage):
        return payload, {}

    if (
        isinstance(payload, tuple)
        and len(payload) == 2
        and isinstance(payload[0], BaseMessage)
        and isinstance(payload[1], dict)
    ):
        return payload[0], dict(payload[1])

    raise ValueError(f"Unsupported messages payload: {payload!r}")


def _coerce_namespace(*, raw_namespace: object) -> tuple[str, ...]:
    """Normalize the optional LangGraph namespace component.

    Args:
        raw_namespace (object): Namespace payload from LangGraph.

    Returns:
        tuple[str, ...]: Normalized namespace path.
    """
    if raw_namespace is None:
        return ()
    if isinstance(raw_namespace, str):
        return (raw_namespace,)
    if isinstance(raw_namespace, tuple):
        return tuple(str(item) for item in raw_namespace)
    if isinstance(raw_namespace, list):
        return tuple(str(item) for item in raw_namespace)
    return (str(raw_namespace),)
