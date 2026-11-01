"""FauxChatModel — deterministic LangChain BaseChatModel for tests.

Construct with a queue of pre-built ``AIMessage`` responses; each call to
``invoke`` / ``ainvoke`` / ``stream`` / ``astream`` dequeues one. Real
provider keys never appear in unit tests — everything routes through here.

Per parent spec §5.9 and sub-spec 01.b §4.2.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Any, AsyncIterator, Iterator, Optional, Sequence
from uuid import uuid4

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool
from pydantic import ConfigDict, Field

__all__ = ["FauxScriptUnderrun", "FauxChatModel"]


class FauxScriptUnderrun(RuntimeError):
    """Raised when a test asks for more responses than were scripted."""


class FauxChatModel(BaseChatModel):
    """Deterministic chat model for tests.

    Construct with a list of pre-built ``AIMessage`` responses. Each call
    dequeues the next response.

    Behavioural notes:
    - ``bind_tools`` returns a clone with ``bound_tools`` captured so tests
      can assert what was bound.
    - The model does NOT inspect input messages to decide what to return —
      the queue is the only oracle.
    - Running off the end of the queue raises ``FauxScriptUnderrun``.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    queue: deque[AIMessage] = Field(
        default_factory=deque, description="Remaining scripted completed responses in consumption order."
    )
    chunk_queue: deque[list[AIMessageChunk]] = Field(
        default_factory=deque,
        description="Remaining per-response streaming chunk scripts in consumption order.",
    )
    bound_tools: list[dict[str, object] | type | Callable[..., object] | BaseTool] = Field(
        default_factory=list, description="Tool definitions captured on the clone returned by bind_tools."
    )
    model_name: str = "faux"
    _call_count: int = 0

    def __init__(
        self,
        *,
        responses: Sequence[AIMessage],
        chunk_scripts: Optional[Sequence[Sequence[AIMessageChunk]]] = None,
        **data: Any,
    ) -> None:
        """Store completed responses plus optional streaming chunk scripts.

        Args:
            responses (Sequence[AIMessage]): Completed responses consumed by
                ``invoke`` and ``ainvoke``.
            chunk_scripts (Optional[Sequence[Sequence[AIMessageChunk]]]):
                Optional per-response chunk scripts consumed by
                ``stream`` and ``astream``. When omitted, each response is
                streamed as one single chunk containing the full content.
            **data (Any): Pydantic/BaseChatModel passthrough.
        """
        super().__init__(**data)
        self.queue = deque(responses)
        self.chunk_queue = deque(
            [list(script) for script in chunk_scripts]
            if chunk_scripts is not None
            else [self._default_chunks(response=response) for response in responses]
        )

    @property
    def _llm_type(self) -> str:
        return "faux"

    def bind_tools(
        self,
        tools: Sequence[dict[str, object] | type | Callable[..., object] | BaseTool],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: object,
    ) -> "FauxChatModel":
        """Return a clone preserving both responses and chunk scripts.

        Args:
            tools: Upstream-supported tool schemas, classes, callables or tools.
            tool_choice: Unused upstream tool-choice option.
            **kwargs: Unused LangChain passthrough.

        Returns:
            FauxChatModel: Cloned model with identical scripted behavior.
        """
        clone = FauxChatModel(
            responses=list(self.queue),
            chunk_scripts=list(self.chunk_queue),
        )
        clone.bound_tools = list(tools)
        return clone

    def _next(self) -> AIMessage:
        """Pop the next completed response.

        Returns:
            AIMessage: The next scripted completed response.

        Raises:
            FauxScriptUnderrun: If the completed-response queue is empty.
        """
        if not self.queue:
            raise FauxScriptUnderrun("FauxChatModel queue is empty. Add more scripted AIMessages.")
        return self.queue.popleft()

    def _next_chunks(self) -> list[AIMessageChunk]:
        """Pop the next per-response chunk script.

        Returns:
            list[AIMessageChunk]: Scripted chunks for one response.

        Raises:
            FauxScriptUnderrun: If the chunk-script queue is empty.
        """
        if not self.chunk_queue:
            raise FauxScriptUnderrun("FauxChatModel chunk queue is empty. Add more scripted AIMessageChunks.")
        return self.chunk_queue.popleft()

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._call_count += 1
        msg = self._next()
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._call_count += 1
        msg = self._next()
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Yield the scripted chunk sequence for one response.

        Args:
            messages (list[BaseMessage]): Unused prompt history.
            stop (Optional[list[str]]): Unused stop sequence list.
            run_manager (Optional[CallbackManagerForLLMRun]): Unused callback manager.
            **kwargs (Any): Unused LangChain passthrough.

        Yields:
            ChatGenerationChunk: One chunk per scripted assistant delta.
        """
        self._next()
        for chunk in self._next_chunks():
            yield ChatGenerationChunk(message=chunk)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Yield the scripted async chunk sequence for one response.

        Args:
            messages (list[BaseMessage]): Unused prompt history.
            stop (Optional[list[str]]): Unused stop sequence list.
            run_manager (Optional[AsyncCallbackManagerForLLMRun]): Unused callback manager.
            **kwargs (Any): Unused LangChain passthrough.

        Yields:
            ChatGenerationChunk: One chunk per scripted assistant delta.
        """
        self._next()
        for chunk in self._next_chunks():
            yield ChatGenerationChunk(message=chunk)

    @staticmethod
    def _default_chunks(*, response: AIMessage) -> list[AIMessageChunk]:
        """Preserve pre-feature-13 single-chunk behavior by default.

        Args:
            response (AIMessage): Completed response.

        Returns:
            list[AIMessageChunk]: One single chunk mirroring the full response.
        """
        return [
            AIMessageChunk(
                content=response.content,
                tool_calls=response.tool_calls,
                additional_kwargs=response.additional_kwargs,
                usage_metadata=response.usage_metadata,
            )
        ]

    @classmethod
    def tool_call_dict(
        cls,
        *,
        name: str,
        args: dict,
        call_id: Optional[str] = None,
    ) -> dict:
        """Build a single LangChain-style tool call dict for ``AIMessage.tool_calls``.

        Args:
            name (str): Tool name the assistant is invoking.
            args (dict): Arguments passed to the tool.
            call_id (Optional[str]): Explicit call id. When ``None``, a unique
                ``call_<hex>`` id is generated.

        Returns:
            dict: A LangChain-shaped tool-call dict with ``name``, ``args``,
                ``id``, and ``type`` keys.
        """
        return {
            "name": name,
            "args": args,
            "id": call_id or f"call_{uuid4().hex[:8]}",
            "type": "tool_call",
        }

    @classmethod
    def assistant_message(
        cls,
        *,
        content: str = "",
        tool_calls: Optional[Sequence[dict]] = None,
    ) -> AIMessage:
        """Build an ``AIMessage`` for queueing into ``FauxChatModel``.

        Args:
            content (str): Final assistant text (empty when the message is
                purely a tool call).
            tool_calls (Optional[Sequence[dict]]): Optional list of tool-call
                dicts built via :meth:`tool_call_dict`.

        Returns:
            AIMessage: A LangChain ``AIMessage`` ready to enqueue.
        """
        return AIMessage(content=content, tool_calls=list(tool_calls or []))
