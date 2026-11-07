"""Unit tests for ``MessageContractReconciler`` (sub-specs 41, 42).

Pure ``list[BaseMessage]`` in -> ``list[BaseMessage]`` out. No events, no
compaction, no provider. One test per decision point.
"""

from __future__ import annotations

from typing import Any

import pytest

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from src.agents.slo_agent.history.message_contract_reconciler import (
    MessageContractReconciler,
    UnsettledToolGroupError,
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


def _detached_snapshot(*, messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Serialize every message into a detached, comparable snapshot."""
    return [message.model_dump(mode="json") for message in messages]


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


# ---------------------------------------------------------------------------
# Strict live guard (sub-spec 96.a.2 §6.1, A12)
# ---------------------------------------------------------------------------


def test_live_guard_accepts_exact_ordered_group_without_mutation() -> None:
    """A complete source-ordered group passes and its detached content is untouched."""
    messages: list[BaseMessage] = [
        HumanMessage(content="run both"),
        _ai_with_tool_calls(ids=["A", "B"]),
        ToolMessage(content="a", name="bash", tool_call_id="A", status="success"),
        ToolMessage(content="b", name="bash", tool_call_id="B", status="error"),
        AIMessage(content="done"),
    ]
    before: list[dict[str, Any]] = _detached_snapshot(messages=messages)
    MessageContractReconciler.require_settled_live(messages=messages)
    assert _detached_snapshot(messages=messages) == before


def test_live_guard_rejection_leaves_detached_snapshot_unchanged() -> None:
    """A rejected group mutates neither shared messages nor their status or args."""
    messages: list[BaseMessage] = [
        _ai_with_tool_calls(ids=["A"]),
        ToolMessage(content="a", name="bash", tool_call_id="A", status="error"),
        ToolMessage(content="duplicate", name="bash", tool_call_id="A", status="success"),
    ]
    before: list[dict[str, Any]] = _detached_snapshot(messages=messages)
    with pytest.raises(UnsettledToolGroupError):
        MessageContractReconciler.require_settled_live(messages=messages)
    assert _detached_snapshot(messages=messages) == before


def test_live_guard_accepts_plain_conversation() -> None:
    """History with no tool calls is settled."""
    MessageContractReconciler.require_settled_live(
        messages=[HumanMessage(content="hello"), AIMessage(content="hi")],
    )


def test_live_guard_rejects_orphan_result() -> None:
    """A ToolMessage with no open call is an orphan, not a heal candidate."""
    with pytest.raises(UnsettledToolGroupError) as raised:
        MessageContractReconciler.require_settled_live(
            messages=[HumanMessage(content="summary"), _tool_message(tool_call_id="orphan")],
        )
    assert str(raised.value) == "unsettled_tool_group"


def test_live_guard_rejects_blank_result_id() -> None:
    """A ToolMessage without an ID cannot settle a live group."""
    with pytest.raises(UnsettledToolGroupError):
        MessageContractReconciler.require_settled_live(
            messages=[_ai_with_tool_calls(ids=["A"]), ToolMessage(content="x", name="bash", tool_call_id="")],
        )


def test_live_guard_rejects_missing_result() -> None:
    """A declared call with no result never heals live."""
    messages: list[BaseMessage] = [_ai_with_tool_calls(ids=["A", "B"]), _tool_message(tool_call_id="A")]
    with pytest.raises(UnsettledToolGroupError):
        MessageContractReconciler.require_settled_live(messages=messages)
    assert len(messages) == 2


def test_live_guard_rejects_duplicate_result() -> None:
    """A second result for the same call is a duplicate, not a new settlement."""
    with pytest.raises(UnsettledToolGroupError):
        MessageContractReconciler.require_settled_live(
            messages=[
                _ai_with_tool_calls(ids=["A"]),
                _tool_message(tool_call_id="A"),
                _tool_message(tool_call_id="A"),
            ],
        )


def test_live_guard_accepts_result_order_not_matching_call_order() -> None:
    """A result removes its matching pending ID once; source order is not required.

    Spec §6.1 says a ``ToolMessage`` "requires nonblank pending ID and removes
    it once". It does not require the result to be the first pending call;
    executors own source-ordering of their outputs. Rejecting a matching
    non-first result here would enforce a rule the spec does not state.
    """
    MessageContractReconciler.require_settled_live(
        messages=[
            _ai_with_tool_calls(ids=["A", "B"]),
            _tool_message(tool_call_id="B"),
            _tool_message(tool_call_id="A"),
        ],
    )


def test_live_guard_rejects_interleaved_non_tool_message() -> None:
    """A non-tool message while a group is pending is interleaving."""
    with pytest.raises(UnsettledToolGroupError):
        MessageContractReconciler.require_settled_live(
            messages=[
                _ai_with_tool_calls(ids=["A"]),
                HumanMessage(content="wait"),
                _tool_message(tool_call_id="A"),
            ],
        )


def test_live_guard_rejects_blank_call_id() -> None:
    """A blank declared call ID is malformed."""
    with pytest.raises(UnsettledToolGroupError):
        MessageContractReconciler.require_settled_live(
            messages=[_ai_with_tool_calls(ids=[""])],
        )


@pytest.mark.parametrize(
    ("tool_call", "reason"),
    [
        ({"name": "bash", "args": {}, "id": ""}, "blank ID"),
        ({"name": "bash", "args": {}, "id": "   "}, "whitespace ID"),
        ({"name": "bash", "args": {}, "id": 7}, "non-string ID"),
        ({"name": "", "args": {}, "id": "A"}, "blank name"),
        ({"name": 7, "args": {}, "id": "A"}, "non-string name"),
        ({"args": {}, "id": "A"}, "missing name"),
        ("not-a-mapping", "non-mapping entry"),
    ],
    ids=[
        "blank-id",
        "whitespace-id",
        "non-string-id",
        "blank-name",
        "non-string-name",
        "missing-name",
        "non-mapping",
    ],
)
def test_live_tool_call_validator_rejects_malformed_entries(*, tool_call: Any, reason: str) -> None:
    """The pure call validator rejects each malformed shape it owns.

    The public guard can be masked by its result guard for blank IDs, so this
    direct decision test proves the opening-side validation itself.
    """
    with pytest.raises(UnsettledToolGroupError):
        MessageContractReconciler._live_tool_call_id(tool_call=tool_call)


def test_live_guard_rejects_duplicate_call_ids_in_one_group() -> None:
    """One opening cannot declare the same call ID twice even when one result settles it."""
    with pytest.raises(UnsettledToolGroupError):
        MessageContractReconciler.require_settled_live(
            messages=[
                _ai_with_tool_calls(ids=["A", "A"]),
                _tool_message(tool_call_id="A"),
            ],
        )


def test_live_guard_rejects_reused_call_id_across_groups() -> None:
    """A later group cannot reuse a call ID seen earlier in the context."""
    with pytest.raises(UnsettledToolGroupError):
        MessageContractReconciler.require_settled_live(
            messages=[
                _ai_with_tool_calls(ids=["A"]),
                _tool_message(tool_call_id="A"),
                _ai_with_tool_calls(ids=["A"]),
                _tool_message(tool_call_id="A"),
            ],
        )


def test_live_guard_rejects_malformed_partial_tool_call() -> None:
    """A raw partial tool-call structure with no ID is rejected."""
    partial = AIMessage.model_construct(
        content="",
        tool_calls=[{"name": "bash", "args": {}}],
        invalid_tool_calls=[],
        type="ai",
    )
    with pytest.raises(UnsettledToolGroupError):
        MessageContractReconciler.require_settled_live(messages=[partial])


def test_live_guard_rejects_tool_call_without_args() -> None:
    """An ID and name without ``args`` is a partial structure."""
    partial = AIMessage.model_construct(
        content="",
        tool_calls=[{"name": "bash", "id": "A"}],
        invalid_tool_calls=[],
        type="ai",
    )
    with pytest.raises(UnsettledToolGroupError):
        MessageContractReconciler.require_settled_live(
            messages=[partial, _tool_message(tool_call_id="A")],
        )


def test_live_guard_rejects_tool_call_with_non_mapping_args() -> None:
    """A partial JSON-string argument value is not an executable tool call."""
    partial = AIMessage.model_construct(
        content="",
        tool_calls=[{"name": "bash", "args": '{"command":', "id": "A"}],
        invalid_tool_calls=[],
        type="ai",
    )
    with pytest.raises(UnsettledToolGroupError):
        MessageContractReconciler.require_settled_live(
            messages=[partial, _tool_message(tool_call_id="A")],
        )


@pytest.mark.parametrize(
    "tool_calls",
    [None, 0, "", (), {}, object()],
    ids=["null", "zero", "empty-string", "empty-tuple", "empty-mapping", "non-iterable"],
)
def test_live_guard_rejects_unsupported_outer_call_container(*, tool_calls: Any) -> None:
    """Only the canonical list shape is accepted; every other container is unsettled."""
    malformed = AIMessage.model_construct(
        content="",
        tool_calls=tool_calls,
        invalid_tool_calls=[],
        type="ai",
    )
    with pytest.raises(UnsettledToolGroupError) as raised:
        MessageContractReconciler.require_settled_live(messages=[malformed])
    assert str(raised.value) == "unsettled_tool_group"


def test_live_guard_accepts_omitted_and_explicit_empty_tool_calls() -> None:
    """The canonical missing/default and empty-list forms remain accepted."""
    MessageContractReconciler.require_settled_live(
        messages=[
            AIMessage(content="omitted"),
            AIMessage(content="explicit", tool_calls=[]),
        ],
    )


def test_live_guard_rejects_invalid_tool_calls_with_settled_normal_group() -> None:
    """A settled normal group cannot mask parser-invalid calls in the same response."""
    invalid = AIMessage(
        content="",
        tool_calls=[{"name": "bash", "args": {}, "id": "A"}],
        invalid_tool_calls=[{"name": "bash", "args": "oops", "id": "bad", "error": "bad args"}],
    )
    with pytest.raises(UnsettledToolGroupError):
        MessageContractReconciler.require_settled_live(
            messages=[invalid, _tool_message(tool_call_id="A")],
        )


def test_reconcile_healing_placeholder_status_is_error() -> None:
    """Historical healing is marked ``error`` and never implies live settlement."""
    result = MessageContractReconciler.reconcile(messages=[_ai_with_tool_calls(ids=["call-x"])])
    tool_messages = [message for message in result if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].status == "error"
