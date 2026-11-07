"""Provider message-contract reconciliation (sub-spec 42).

The LLM provider enforces structural rules on a request's message list. Both
Anthropic and the OpenAI/Kimi lane reject a tool result with no matching tool
call, a tool call with no matching result, and an assistant message that is
empty (no content and no tool calls). ``MessageContractReconciler`` is the
single component that makes a projected ``list[BaseMessage]`` satisfy every
such rule before it is replayed.

It is applied by ``SessionHistoryProjector.build_message_history`` to the
output of event projection. Keeping the contract in one stateless class keeps
the projector focused on selection/ordering and gives provider legality a
single, independently testable home. New provider rules are added here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

__all__ = [
    "CooperativeYieldSettlementError",
    "MessageContractReconciler",
    "UnsettledToolGroupError",
    "is_settlement_failure",
]


def is_settlement_failure(*, exc: BaseException) -> bool:
    """Return whether ``exc`` is a terminal live-settlement failure.

    Settlement failures are never eligible for generic provider retry, stream
    reconnect, compaction or LLM recovery. The agent and session call this
    before any generic classification so a permissive classifier cannot
    override the invariant. Cooperative-yield settlement errors share the
    same terminal family so no producer can be retried as a provider failure.

    Args:
        exc (BaseException): The escaped exception to classify.

    Returns:
        bool: True when the exception must terminate the attempt unrecovered.
    """
    from src.agents.slo_agent.tool_execution.yield_policy import ToolYieldCapabilityError

    return isinstance(
        exc, (UnsettledToolGroupError, CooperativeYieldSettlementError, ToolYieldCapabilityError)
    )


class CooperativeYieldSettlementError(Exception):
    """Report certain or uncertain cooperative-yield history settlement failure.

    A conflict, invalid evidence, redaction change or unknown persistence reply
    means the exact canonical event cannot be proven durable. The caller must
    stop rather than reconstruct an ID/timestamp or retry automatically.
    """

    code: str = "cooperative_yield_settlement_failed"

    def __init__(self) -> None:
        """Build the fixed, safe error text."""
        super().__init__(self.code)


class UnsettledToolGroupError(Exception):
    """Report a live message list whose tool-call group is not settled.

    The strict live guard never repairs history: an orphan, interleaved,
    duplicated, malformed or missing tool result means the provider response
    under way must not be replayed or continued.
    """

    code: str = "unsettled_tool_group"

    def __init__(self) -> None:
        """Build the fixed, safe error text."""
        super().__init__(self.code)


class MessageContractReconciler:
    """Make a projected message list satisfy the provider message contract.

    Stateless service with two public entry points: the legacy repairing
    ``reconcile`` and the strict, non-mutating ``require_settled_live`` guard.
    ``reconcile`` chains every provider message-contract rule:

    1. ``_drop_orphan_tool_results`` — drop a ``ToolMessage`` whose
       ``tool_call_id`` is empty, or was never declared by a preceding
       ``AIMessage`` (its opening ``tool_call`` was compacted into a summary).
    2. ``_heal_dangling_tool_calls`` — synthesise a placeholder ``ToolMessage``
       for an ``AIMessage`` tool call with no following ``ToolMessage`` so a
       hung/aborted call does not leave a ``tool_use`` block unanswered.
    3. ``_drop_empty_assistant_messages`` — drop an ``AIMessage`` that carries
       no text and no tool calls (illegal to replay: the provider rejects an
       assistant message that is empty).
    """

    _INTERRUPTED_TOOL_RESULT: str = "[interrupted: this tool call did not complete before the session ended]"

    @classmethod
    def reconcile(cls, *, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Return ``messages`` made legal for the provider, in order.

        Orphan results are dropped first so the heal pass never treats a
        dropped result as an answer; empty assistant messages are removed last
        as the final legality sweep.

        Args:
            messages (list[BaseMessage]): Projected history, in order.

        Returns:
            list[BaseMessage]: A provider-contract-valid message list — every
                ``ToolMessage`` answers a preceding ``AIMessage`` tool call,
                every ``AIMessage`` tool call has a following ``ToolMessage``,
                and no ``AIMessage`` is empty.
        """
        without_orphans: list[BaseMessage] = cls._drop_orphan_tool_results(
            messages=messages,
        )
        healed: list[BaseMessage] = cls._heal_dangling_tool_calls(
            messages=without_orphans,
        )
        return cls._drop_empty_assistant_messages(messages=healed)

    @classmethod
    def require_settled_live(cls, *, messages: list[BaseMessage]) -> None:
        """Require a live message list to carry only settled tool groups.

        Performs no repair and returns nothing. A group is settled only when
        one assistant message declares distinct nonblank call IDs, then each
        nonblank result removes its pending ID exactly once, with no other
        message interleaved. Call IDs are unique across the whole provider
        context, and parser-invalid or partial tool-call structures are
        rejected. Result source ordering belongs to the executor (spec §5.4).

        Args:
            messages (list[BaseMessage]): Live provider-context messages, in order.

        Raises:
            UnsettledToolGroupError: If any orphan, duplicate, reused, blank or
                malformed ID, interleaving message, invalid tool-call structure
                or missing result leaves the group unsettled.
        """
        seen_ids: set[str] = set()
        pending_ids: list[str] = []
        for message in messages:
            if isinstance(message, ToolMessage):
                pending_ids = cls._settle_pending_result(
                    message=message,
                    pending_ids=pending_ids,
                )
                continue
            cls._require_no_pending_group(pending_ids=pending_ids)
            if isinstance(message, AIMessage):
                pending_ids = cls._open_live_group(message=message, seen_ids=seen_ids)
        cls._require_no_pending_group(pending_ids=pending_ids)

    @classmethod
    def _open_live_group(cls, *, message: AIMessage, seen_ids: set[str]) -> list[str]:
        """Validate one assistant tool-call group and return its pending IDs.

        Args:
            message (AIMessage): The assistant message opening the group.
            seen_ids (set[str]): Call IDs already used in this provider context.

        Returns:
            list[str]: Distinct nonblank call IDs in source order.

        Raises:
            UnsettledToolGroupError: If the group is malformed, has a non-list
                outer call container, is partial, or reuses a call ID from this
                provider context.
        """
        if message.invalid_tool_calls:
            raise UnsettledToolGroupError()
        raw_tool_calls: Any = message.tool_calls
        if not isinstance(raw_tool_calls, list):
            raise UnsettledToolGroupError()
        pending_ids: list[str] = []
        for tool_call in raw_tool_calls:
            tool_call_id: str = cls._live_tool_call_id(tool_call=tool_call)
            if tool_call_id in seen_ids or tool_call_id in pending_ids:
                raise UnsettledToolGroupError()
            pending_ids.append(tool_call_id)
        seen_ids.update(pending_ids)
        return pending_ids

    @classmethod
    def _live_tool_call_id(cls, *, tool_call: Any) -> str:
        """Return one complete tool call's ID or reject the structure.

        Args:
            tool_call (Any): One raw entry from ``AIMessage.tool_calls``.

        Returns:
            str: The call's nonblank ID.

        Raises:
            UnsettledToolGroupError: If the entry is not a mapping, its ID or
                name is blank, or ``args`` is not a mapping (partial structure).
        """
        if not isinstance(tool_call, Mapping):
            raise UnsettledToolGroupError()
        tool_call_id: Any = tool_call.get("id")
        name: Any = tool_call.get("name")
        args: Any = tool_call.get("args")
        if not isinstance(tool_call_id, str) or not tool_call_id.strip():
            raise UnsettledToolGroupError()
        if not isinstance(name, str) or not name.strip():
            raise UnsettledToolGroupError()
        if not isinstance(args, Mapping):
            raise UnsettledToolGroupError()
        return tool_call_id

    @classmethod
    def _settle_pending_result(
        cls,
        *,
        message: ToolMessage,
        pending_ids: list[str],
    ) -> list[str]:
        """Require one result to answer a pending call and remove that ID once.

        Args:
            message (ToolMessage): The result arriving in the live context.
            pending_ids (list[str]): Open call IDs in source order.

        Returns:
            list[str]: Remaining open call IDs.

        Raises:
            UnsettledToolGroupError: If the result ID is blank, orphaned or
                already settled. Source ordering of results is the executor's
                obligation (spec §5.4/§9.1), not this guard's.
        """
        tool_call_id: str = message.tool_call_id
        if not isinstance(tool_call_id, str) or not tool_call_id.strip():
            raise UnsettledToolGroupError()
        if tool_call_id not in pending_ids:
            raise UnsettledToolGroupError()
        return [pending_id for pending_id in pending_ids if pending_id != tool_call_id]

    @classmethod
    def _require_no_pending_group(cls, *, pending_ids: list[str]) -> None:
        """Reject any non-result message or list end while calls are open.

        Args:
            pending_ids (list[str]): Open call IDs in source order.

        Raises:
            UnsettledToolGroupError: If at least one call is still open.
        """
        if pending_ids:
            raise UnsettledToolGroupError()

    @classmethod
    def _drop_orphan_tool_results(
        cls,
        *,
        messages: list[BaseMessage],
    ) -> list[BaseMessage]:
        """Drop ``ToolMessage``s that cannot be paired with a preceding tool call.

        Walks the messages in order, tracking the ``tool_call`` ids declared by
        ``AIMessage``s seen so far. A ``ToolMessage`` is dropped when its
        ``tool_call_id`` is empty (a partial/id-less "error without the ID") or
        was never declared by a preceding ``AIMessage`` (its call was compacted
        into a summary — the summary already covers it).

        Args:
            messages (list[BaseMessage]): Projected history, in order.

        Returns:
            list[BaseMessage]: History with no unanchored or id-less
                ``ToolMessage``.
        """
        declared_ids: set[str] = set()
        kept: list[BaseMessage] = []
        for message in messages:
            if isinstance(message, AIMessage):
                cls._collect_declared_ids(message=message, declared_ids=declared_ids)
                kept.append(message)
                continue
            if isinstance(message, ToolMessage):
                if not message.tool_call_id or message.tool_call_id not in declared_ids:
                    continue
                kept.append(message)
                continue
            kept.append(message)
        return kept

    @classmethod
    def _heal_dangling_tool_calls(
        cls,
        *,
        messages: list[BaseMessage],
    ) -> list[BaseMessage]:
        """Synthesize a placeholder ``ToolMessage`` for every unanswered tool call.

        A completed turn can carry a ``tool_call`` whose ``tool_result`` was
        never recorded — the tool hung, the process died, or the session was
        aborted mid-call. Replaying that history sends the provider a
        ``tool_use`` block with no matching ``tool_result``, which it rejects
        with a 400. Each dangling tool-call id gets a synthetic ``ToolMessage``
        appended immediately after the ``AIMessage`` that opened it.

        Args:
            messages (list[BaseMessage]): Reconciled history (orphans already
                dropped), in order.

        Returns:
            list[BaseMessage]: History with every tool call answered.
        """
        answered_ids: set[str] = {
            message.tool_call_id
            for message in messages
            if isinstance(message, ToolMessage) and message.tool_call_id
        }
        healed: list[BaseMessage] = []
        for message in messages:
            healed.append(message)
            if not isinstance(message, AIMessage):
                continue
            for tool_call in message.tool_calls or []:
                tool_call_id: str = tool_call.get("id") or ""
                if not tool_call_id or tool_call_id in answered_ids:
                    continue
                answered_ids.add(tool_call_id)
                healed.append(
                    ToolMessage(
                        content=cls._INTERRUPTED_TOOL_RESULT,
                        name=tool_call.get("name") or "",
                        tool_call_id=tool_call_id,
                        status="error",
                    )
                )
        return healed

    @classmethod
    def _drop_empty_assistant_messages(
        cls,
        *,
        messages: list[BaseMessage],
    ) -> list[BaseMessage]:
        """Drop ``AIMessage``s with no text content and no tool calls.

        An empty assistant message (e.g. a turn that produced no final text
        after its tool calls) is illegal to replay — the provider rejects an
        assistant message that carries neither content nor tool calls.

        Args:
            messages (list[BaseMessage]): Reconciled history, in order.

        Returns:
            list[BaseMessage]: History with no empty ``AIMessage``.
        """
        return [message for message in messages if not cls._is_empty_assistant_message(message=message)]

    @classmethod
    def _collect_declared_ids(
        cls,
        *,
        message: AIMessage,
        declared_ids: set[str],
    ) -> None:
        """Record every ``tool_call`` id declared by one ``AIMessage``.

        Args:
            message (AIMessage): The assistant message whose tool calls to read.
            declared_ids (set[str]): Accumulator updated in place with each
                non-empty ``tool_call`` id.
        """
        for tool_call in message.tool_calls or []:
            tool_call_id: str = tool_call.get("id") or ""
            if tool_call_id:
                declared_ids.add(tool_call_id)

    @classmethod
    def _is_empty_assistant_message(cls, *, message: BaseMessage) -> bool:
        """Return True when ``message`` is an empty ``AIMessage``.

        An ``AIMessage`` is empty when it declares no tool calls and its visible
        text is blank (empty or whitespace).

        Args:
            message (BaseMessage): The message to inspect.

        Returns:
            bool: ``True`` only for an empty assistant message.
        """
        if not isinstance(message, AIMessage):
            return False
        if message.tool_calls:
            return False
        return not cls._message_text(message=message).strip()

    @classmethod
    def _message_text(cls, *, message: AIMessage) -> str:
        """Return the concatenated visible text of an ``AIMessage``.

        Handles both plain string content and Anthropic-style structured
        content blocks, where only ``text`` blocks count as visible text.

        Args:
            message (AIMessage): The assistant message.

        Returns:
            str: The message's visible text (possibly empty).
        """
        content = message.content
        if isinstance(content, str):
            return content
        parts: list[str] = []
        for block in content or []:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
