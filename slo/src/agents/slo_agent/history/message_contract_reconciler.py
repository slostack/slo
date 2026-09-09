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

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

__all__ = ["MessageContractReconciler"]


class MessageContractReconciler:
    """Make a projected message list satisfy the provider message contract.

    Stateless service with one public entry point, ``reconcile``. It chains
    every provider message-contract rule:

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
