"""Unit tests for ``MessageContractReconciler`` (sub-specs 41, 42).

Pure ``list[BaseMessage]`` in -> ``list[BaseMessage]`` out. No events, no
compaction, no provider. One test per decision point.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from src.agents.slo_agent.history.message_contract_reconciler import (
    MessageContractReconciler,
)


def _ai_with_tool_calls(*, ids: list[str]) -> AIMessage:
    """Build an ``AIMessage`` declaring one ``tool_call`` per id."""
    tool_calls: list[dict[str, Any]] = [
        {"name": "bash", "args": {"command": "ls"}, "id": tool_call_id, "type": "tool_call"}
        for tool_call_id in ids
    ]
    return AIMessage(content="", tool_calls=tool_calls)


def _tool_message(*, tool_call_id: str, content: str = "ok") -> ToolMessage:
    """Build a ``ToolMessage`` answering ``tool_call_id``."""
    return ToolMessage(content=content, name="bash", tool_call_id=tool_call_id)


def test_drops_orphan_tool_result_with_no_preceding_call() -> None:
    """A ToolMessage whose id no AIMessage declared is removed."""
    messages: list[BaseMessage] = [
        HumanMessage(content="[Previous conversation summary]\n\n…"),
        _tool_message(tool_call_id="orphan-1"),
    ]
    result = MessageContractReconciler.reconcile(messages=messages)
    assert not any(isinstance(m, ToolMessage) for m in result)


def test_keeps_tool_result_with_preceding_call() -> None:
    """A normally-paired tool_call/tool_result survives reconciliation."""
    messages: list[BaseMessage] = [
        _ai_with_tool_calls(ids=["call-1"]),
        _tool_message(tool_call_id="call-1"),
    ]
    result = MessageContractReconciler.reconcile(messages=messages)
    tool_messages = [m for m in result if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "call-1"


def test_drops_only_orphans_in_parallel_batch() -> None:
    """Given an AIMessage declaring [A, B] and results A, B, C — only C is dropped."""
    messages: list[BaseMessage] = [
        _ai_with_tool_calls(ids=["A", "B"]),
        _tool_message(tool_call_id="A"),
        _tool_message(tool_call_id="B"),
        _tool_message(tool_call_id="C"),  # orphan
    ]
    result = MessageContractReconciler.reconcile(messages=messages)
    kept_ids = [m.tool_call_id for m in result if isinstance(m, ToolMessage)]
    assert kept_ids == ["A", "B"]


def test_heals_dangling_tool_call_with_no_result() -> None:
    """An AIMessage tool_call with no following result gets a placeholder."""
    messages: list[BaseMessage] = [
        _ai_with_tool_calls(ids=["call-x"]),
    ]
    result = MessageContractReconciler.reconcile(messages=messages)
    tool_messages = [m for m in result if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "call-x"
    assert "interrupted" in tool_messages[0].content


def test_orphan_drop_runs_before_heal() -> None:
    """A dropped orphan does not count as an answer; the call is still healed.

    The AIMessage declares ``call-1`` but the only ToolMessage is an orphan
    (``other``). The orphan is dropped, then ``call-1`` is healed with a
    placeholder — so exactly one ToolMessage (for ``call-1``) remains.
    """
    messages: list[BaseMessage] = [
        _ai_with_tool_calls(ids=["call-1"]),
        _tool_message(tool_call_id="other"),  # orphan, dropped first
    ]
    result = MessageContractReconciler.reconcile(messages=messages)
    tool_messages = [m for m in result if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "call-1"
    assert "interrupted" in tool_messages[0].content


def test_drops_tool_result_with_empty_id() -> None:
    """A ToolMessage with an empty tool_call_id (id-less partial) is removed."""
    messages: list[BaseMessage] = [
        _ai_with_tool_calls(ids=["call-1"]),
        _tool_message(tool_call_id="call-1"),
        ToolMessage(content="error", name="bash", tool_call_id=""),  # id-less
    ]
    result = MessageContractReconciler.reconcile(messages=messages)
    kept_ids = [m.tool_call_id for m in result if isinstance(m, ToolMessage)]
    assert kept_ids == ["call-1"]


def test_non_tool_messages_pass_through() -> None:
    """HumanMessage and a plain AIMessage (no tool calls) are untouched."""
    human = HumanMessage(content="hello")
    assistant = AIMessage(content="hi there")
    result = MessageContractReconciler.reconcile(messages=[human, assistant])
    assert result == [human, assistant]


# ---------------------------------------------------------------------------
# Empty assistant messages (sub-spec 42)
# ---------------------------------------------------------------------------


def test_drops_empty_assistant_message() -> None:
    """An AIMessage with empty content and no tool calls is removed."""
    human = HumanMessage(content="hello")
    empty = AIMessage(content="")
    follow_up = HumanMessage(content="Are you done?")
    result = MessageContractReconciler.reconcile(messages=[human, empty, follow_up])
    assert result == [human, follow_up]


def test_keeps_assistant_message_with_text() -> None:
    """An AIMessage that carries text survives."""
    assistant = AIMessage(content="here is my answer")
    result = MessageContractReconciler.reconcile(messages=[assistant])
    assert result == [assistant]


def test_keeps_assistant_message_with_tool_calls_and_no_text() -> None:
    """An AIMessage with empty text but tool calls (a normal tool turn) survives."""
    assistant = _ai_with_tool_calls(ids=["call-1"])  # content="" but has tool_calls
    tool_result = _tool_message(tool_call_id="call-1")
    result = MessageContractReconciler.reconcile(messages=[assistant, tool_result])
    assert assistant in result


def test_drops_whitespace_only_assistant_message() -> None:
    """An AIMessage whose content is only whitespace is treated as empty."""
    whitespace = AIMessage(content="   \n\t ")
    result = MessageContractReconciler.reconcile(messages=[whitespace])
    assert result == []


def test_keeps_assistant_message_with_text_blocks() -> None:
    """Structured content with a non-empty text block survives; without text it is dropped."""
    with_text = AIMessage(content=[{"type": "text", "text": "hello from a block"}])
    no_text = AIMessage(content=[{"type": "thinking", "thinking": "internal only"}])
    result = MessageContractReconciler.reconcile(messages=[with_text, no_text])
    assert with_text in result
    assert no_text not in result
