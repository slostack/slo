"""Agent-loop hooks invoked by ``SloAgent`` between turns.

Hooks are stateless callables. The ``Hook`` class is a namespace that
groups (a) the canonical type aliases for each hook's signature and
(b) the default implementations. ``SloAgent`` always invokes the hook
via ``Hook.evaluate_*`` so it never has to inspect the callable's
shape (sync vs. async) at the call site.

The ``_hook`` suffix on every name marks these as slo-shaped
indirections rather than direct ports — pi's equivalents are named
``shouldStopAfterTurn`` etc. in
``pi/packages/agent/src/types.ts:208``.

All data types in this module are Pydantic ``BaseModel`` DAOs — no
``TypedDict``, no ``@dataclass``.
"""
from __future__ import annotations

import inspect
from typing import Awaitable, Callable, Optional, Union

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field


__all__ = [
    "Hook",
    "ShouldStopAfterTurnHook",
    "ShouldStopAfterTurnHookContextDAO",
    "TurnAccumulatorDAO",
]


class TurnAccumulatorDAO(BaseModel):
    """Per-turn collector for the assistant message and tool results.

    Encapsulates the LangChain message-type dispatch the loop body
    would otherwise inline. The loop tells the accumulator to
    ``absorb`` each message in a graph-update delta; the accumulator
    routes by concrete type internally.

    Fields:
        assistant_message: The assistant ``AIMessage`` produced this
            turn. Remains ``None`` until the agent node fires.
        tool_results: ``ToolMessage`` instances produced by the tools
            node during this turn. Empty when the assistant did not
            call any tools.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    assistant_message: Optional[AIMessage] = None
    tool_results: list[ToolMessage] = Field(default_factory=list)

    def absorb(self, *, message: BaseMessage) -> None:
        """Slot ``message`` into the right bucket by its concrete type.

        Args:
            message (BaseMessage): A LangChain message produced by the
                agent or tools node in the current turn.
        """
        if isinstance(message, AIMessage):
            self.assistant_message = message
        elif isinstance(message, ToolMessage):
            self.tool_results.append(message)


class ShouldStopAfterTurnHookContextDAO(BaseModel):
    """Context passed to ``should_stop_after_turn_hook``.

    Mirrors pi's ``ShouldStopAfterTurnContext`` at
    ``pi/packages/agent/src/types.ts:111``, adapted for slo's message
    shapes.

    Fields:
        message: The assistant ``AIMessage`` that completed the turn.
        tool_results: Tool result messages produced during the same
            turn. Empty when the assistant did not call any tools.
        messages: The full accumulated message list at this point in
            the run — what the loop would yield if it exited now.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    message: AIMessage
    tool_results: list[ToolMessage] = Field(default_factory=list)
    messages: list[BaseMessage] = Field(default_factory=list)


ShouldStopAfterTurnHook = Callable[
    [ShouldStopAfterTurnHookContextDAO],
    Union[bool, Awaitable[bool]],
]
"""Type alias for a ``should_stop_after_turn_hook`` callable.

Sync or async. Returns ``True`` to exit the loop before the next LLM
call; ``False`` to continue. Must not raise — exceptions propagate
out of the loop and break the ProgressEventDAO stream.
"""


class Hook:
    """Namespace for agent-loop hooks invoked by ``SloAgent``.

    Hook methods are ``classmethod``s so they can be passed around as
    callables (``Hook.should_stop_after_turn_hook``) or overridden by
    subclassing. The shipped defaults are no-ops that preserve
    pi-parity behaviour — the loop only stops on "no tool calls" or
    abort — when callers do not supply a custom hook.
    """

    @classmethod
    async def should_stop_after_turn_hook(
        cls,
        context: ShouldStopAfterTurnHookContextDAO,
    ) -> bool:
        """Default ``should_stop_after_turn_hook`` — never request a stop.

        Accepts ``context`` positionally to match the
        ``ShouldStopAfterTurnHook`` ``Callable[[Context], bool]``
        contract. Override by passing a custom callable to
        ``SloAgent(should_stop_after_turn_hook=...)``.

        Args:
            context (ShouldStopAfterTurnHookContextDAO): The turn's
                outcome. Unused by the default implementation.

        Returns:
            bool: Always ``False`` — the loop continues until the
                model emits no tool calls or the user aborts.
        """
        return False

    @classmethod
    async def evaluate_should_stop_after_turn_hook(
        cls,
        *,
        hook: ShouldStopAfterTurnHook,
        context: ShouldStopAfterTurnHookContextDAO,
    ) -> bool:
        """Run a ``should_stop_after_turn_hook``, awaiting it iff awaitable.

        Centralises the sync-or-async dispatch so ``SloAgent`` never
        has to inspect the callable's shape itself (tell, don't ask).

        Args:
            hook (ShouldStopAfterTurnHook): The hook to invoke.
            context (ShouldStopAfterTurnHookContextDAO): Context to
                pass.

        Returns:
            bool: The hook's verdict, coerced to ``bool``.
        """
        outcome = hook(context)
        if inspect.isawaitable(outcome):
            outcome = await outcome
        return bool(outcome)
