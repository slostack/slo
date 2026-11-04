"""Claude SDK model integration on Slo's existing LangChain core 0.3 interface."""

import asyncio
import json
from copy import deepcopy
from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal, Optional
from uuid import uuid4

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    AIMessage,
    ToolMessage,
)
from src.agents.tools.bundles import create_read_only_tools
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.language_models.chat_models import agenerate_from_stream
from pydantic import ConfigDict, PrivateAttr

from src.bridges.dao import SloBridgeCancellationReason, SloBridgeSessionOptionsDAO
from .sdk.dao import (
    ClaudeInvocationOptionsDAO,
    ClaudeSessionOptionsDAO,
    ClaudeToolDefinitionDAO,
    ClaudeToolResultBatchDAO,
    ClaudeToolResultDAO,
    ClaudeTextDAO,
)
from .sdk.events import ClaudeResponseCompletedDAO, ClaudeTextEventDAO
from .sdk.protocol import SloBridgeAdapterProtocol
from .sdk.exceptions import ClaudeSubmissionNotStartedError


class SloClaudeBridge(BaseChatModel):
    """Translate fresh host text to SDK events while retaining the same lifecycle owner."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    model_name: str
    effort: Optional[Literal["low", "medium", "high", "xhigh", "max"]] = None
    bridge_adapter: SloBridgeAdapterProtocol
    _session_options: Optional[SloBridgeSessionOptionsDAO] = PrivateAttr(default=None)
    _invocation_id: Optional[str] = PrivateAttr(default=None)
    _cancellation_task: Optional[asyncio.Task[None]] = PrivateAttr(default=None)
    _closed: bool = PrivateAttr(default=False)
    _startup_active: bool = PrivateAttr(default=False)
    _tools: tuple[ClaudeToolDefinitionDAO, ...] = PrivateAttr(default=())
    _pending: Optional[ClaudeResponseCompletedDAO] = PrivateAttr(default=None)
    _consumed: list[dict[str, object]] = PrivateAttr(default_factory=list)
    _completed_history: list[BaseMessage] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        """Identify the native runtime without pretending it is direct Anthropic HTTP."""
        return "slo-claude-bridge"

    def configure_session(self, *, session_options: SloBridgeSessionOptionsDAO) -> None:
        """Store final host context inertly and reject implicit rebinding."""
        if self._closed:
            raise RuntimeError("Claude bridge is closed.")
        if self._session_options is not None and self._session_options != session_options:
            raise ValueError("Claude bridge session configuration cannot change.")
        self._session_options = session_options

    def bind_tools(self, tools: Sequence[object], **kwargs: Any) -> BaseChatModel:
        """Freeze only canonical read-only definitions without starting native work."""
        canonical = {t.name: t for t in create_read_only_tools()}
        if kwargs or len({getattr(t, "name", None) for t in tools}) != len(tools):
            raise ValueError("Unsupported Claude tool binding.")
        definitions = []
        for tool in tools:
            if not isinstance(tool, BaseTool) or not any(
                tool is candidate for candidate in canonical.values()
            ):
                raise ValueError("Claude bridge requires canonical read-only tools.")
            schema = tool.args_schema
            if schema is None or isinstance(schema, dict):
                raise ValueError("Claude tool requires a typed argument schema.")
            definitions.append(
                ClaudeToolDefinitionDAO(
                    name=tool.name, description=tool.description, input_schema=schema.model_json_schema()
                )
            )
        frozen = tuple(definitions)
        if self._session_options is not None and self._tools != frozen:
            raise ValueError("Claude bridge tool binding cannot change.")
        self._tools = frozen
        return self

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Stream one new text answer; the final chunk follows SDK closure."""
        if self._closed or self._session_options is None:
            raise RuntimeError("Claude bridge is closed or unconfigured; start a new session.")
        text = "" if self._pending is not None else self._validate_messages(
            messages=messages, stop=stop, kwargs=kwargs,
        )
        boundary = False
        proven_unsent = False
        self._startup_active = True
        try:
            await self._admit_response(messages=messages, text=text, stop=stop, kwargs=kwargs)
            self._startup_active = False
            assert self._invocation_id is not None
            response_text = ""
            async for event in self.bridge_adapter.read_response(invocation_id=self._invocation_id):
                if isinstance(event, ClaudeTextEventDAO):
                    response_text += event.text
                    yield ChatGenerationChunk(message=AIMessageChunk(content=event.text))
                elif isinstance(event, ClaudeResponseCompletedDAO):
                    self._record_response_boundary(
                        messages=messages, response_text=response_text, event=event,
                    )
                    boundary = True
                    yield self._build_boundary_chunk(event=event)
        except ClaudeSubmissionNotStartedError:
            proven_unsent = True
            self._retain_unsent_audit_prefix(messages=messages)
            raise
        finally:
            await self._finish_response_stream(boundary=boundary, proven_unsent=proven_unsent)

    async def _admit_response(
        self, *, messages: list[BaseMessage], text: str,
        stop: Optional[list[str]], kwargs: dict[str, Any],
    ) -> None:
        """Submit a validated continuation or one new prompt, never replay history.

        Called by the stream while startup cancellation is active. Validation or
        submission errors propagate to its existing unsent/uncertain failure policy.
        """
        if self._pending is not None:
            if stop or kwargs:
                raise ValueError("Unsupported continuation options.")
            assert self._invocation_id is not None
            await self.bridge_adapter.submit_tool_results(
                invocation_id=self._invocation_id,
                tool_result_batch=self._build_tool_result_submission(messages=messages),
            )
            return
        assert self._session_options is not None
        await self._start_invocation(text=text, options=self._session_options)

    def _record_response_boundary(
        self, *, messages: list[BaseMessage], response_text: str, event: ClaudeResponseCompletedDAO,
    ) -> None:
        """Select the history transition after a native response boundary is validated."""
        if event.stop_reason == "tool_calls":
            self._record_tool_boundary(messages=messages, response_text=response_text, event=event)
            return
        self._record_terminal_context(messages=messages, response_text=response_text)

    def _record_tool_boundary(
        self, *, messages: list[BaseMessage], response_text: str, event: ClaudeResponseCompletedDAO,
    ) -> None:
        """Retain exact assistant calls and semantic prefix for the next result batch.

        The stream calls this before yielding calls to the host graph. Native
        callbacks remain owned by the adapter; this transition does not close them.
        """
        assistant = AIMessage(
            content=response_text,
            tool_calls=[
                {"name": call.name, "args": call.arguments, "id": call.tool_call_id, "type": "tool_call"}
                for call in event.tool_calls
            ],
        )
        self._pending = event
        self._consumed = self._semantic_messages(messages=[*messages, assistant])

    def _record_terminal_context(self, *, messages: list[BaseMessage], response_text: str) -> None:
        """Save completed live context only after native terminal cleanup has settled."""
        self._pending = None
        self._record_live_context(messages=[*messages, AIMessage(content=response_text)])

    def _retain_unsent_audit_prefix(self, *, messages: list[BaseMessage]) -> None:
        """Keep a proven-unsent input as audit context, never as a future native query.

        Only the typed pre-submission failure reaches this transition. Clearing
        invocation identity allows an explicit retry with the retained native session.
        """
        self._record_live_context(messages=messages)
        self._invocation_id = None

    def _record_live_context(self, *, messages: list[BaseMessage]) -> None:
        """Detach semantic admission history and system-free history-off host context."""
        self._consumed = self._semantic_messages(messages=messages)
        self._completed_history = deepcopy(
            [message for message in messages if not isinstance(message, SystemMessage)]
        )

    @staticmethod
    def _build_boundary_chunk(*, event: ClaudeResponseCompletedDAO) -> ChatGenerationChunk:
        """Convert a native boundary to host calls without changing lifecycle state."""
        return ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {"name": call.name, "args": json.dumps(call.arguments),
                     "id": call.tool_call_id, "index": index}
                    for index, call in enumerate(event.tool_calls)
                ],
                response_metadata={"stop_reason": event.stop_reason},
            )
        )

    async def _finish_response_stream(self, *, boundary: bool, proven_unsent: bool) -> None:
        """Seal uncertain submissions; keep validated boundaries and safe retries reusable.

        The stream's finally block owns this cleanup decision. Adapter close errors
        propagate without discarding the SDK owner, allowing explicit cleanup retry.
        """
        self._startup_active = False
        if boundary or proven_unsent:
            return
        self._closed = True
        await self.bridge_adapter.close()

    @staticmethod
    def _semantic_messages(*, messages: list[BaseMessage]) -> list[dict[str, object]]:
        """Compare meaningful content, ignoring regenerated message identifiers."""
        return deepcopy(
            [
                {
                    "type": m.type,
                    "content": m.content,
                    "tool_calls": m.tool_calls if isinstance(m, AIMessage) else None,
                    "tool_call_id": m.tool_call_id if isinstance(m, ToolMessage) else None,
                    "status": m.status if isinstance(m, ToolMessage) else None,
                }
                for m in messages
            ]
        )

    def _build_tool_result_submission(self, *, messages: list[BaseMessage]) -> ClaudeToolResultBatchDAO:
        """Validate consumed prefix and the complete exact-ID result suffix before send."""
        assert self._pending is not None
        prefix = self._semantic_messages(messages=messages[: len(self._consumed)])
        suffix = messages[len(self._consumed) :]
        if prefix != self._consumed:
            raise ValueError("Claude tool result prefix changed.")
        expected = self._pending.tool_calls
        results: list[ToolMessage] = []
        for message in suffix:
            if not isinstance(message, ToolMessage) or not isinstance(message.content, str):
                raise ValueError("Unsupported Claude tool result continuation.")
            results.append(message)
        ids = [m.tool_call_id for m in results]
        if len(ids) != len(set(ids)) or set(ids) != {c.tool_call_id for c in expected}:
            raise ValueError("Claude requires the complete tool result set.")
        return ClaudeToolResultBatchDAO(
            response_id=self._pending.response_id,
            results=tuple(
                ClaudeToolResultDAO(
                    tool_call_id=m.tool_call_id,
                    content=(ClaudeTextDAO(text=str(m.content)),),
                    is_error=m.status == "error",
                )
                for m in results
            ),
        )

    async def _start_invocation(self, *, text: str, options: SloBridgeSessionOptionsDAO) -> None:
        """Configure and submit exactly once; result continuations never enter here."""
        await self.bridge_adapter.start_session(
            session_options=ClaudeSessionOptionsDAO(
                session_id=options.session_id,
                model_id=self.model_name,
                working_directory=options.working_directory,
                instructions=options.instructions,
                effort=self.effort,
                tools=self._tools,
            )
        )
        self._invocation_id = str(uuid4())
        invocation_id = self._invocation_id
        await self.bridge_adapter.invoke_agent(
            invocation_options=ClaudeInvocationOptionsDAO(invocation_id=invocation_id, text=text)
        )

    def _validate_messages(
        self, *, messages: list[BaseMessage], stop: Optional[list[str]], kwargs: dict[str, Any]
    ) -> str:
        """Reject unsupported history and media before starting the native runtime."""
        if self._closed or self._session_options is None:
            raise RuntimeError("Claude bridge is closed or unconfigured.")
        if self._consumed:
            prefix = self._semantic_messages(messages=messages[: len(self._consumed)])
            if prefix != self._consumed:
                raise ValueError("Claude conversation prefix changed; start a new session.")
            messages = messages[len(self._consumed) :]
        conversation = [message for message in messages if not isinstance(message, SystemMessage)]
        if stop or kwargs or len(conversation) != 1 or not isinstance(conversation[0], HumanMessage):
            raise ValueError(
                "Claude bridge supports one fresh text prompt without history or generation options."
            )
        text = conversation[0].content
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Claude bridge requires nonempty text; images are unavailable.")
        return text

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Aggregate the same stream without a second native submission."""
        return await agenerate_from_stream(
            self._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs)
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Reject synchronous use rather than move native resources across event loops."""
        raise RuntimeError("Claude bridge is async-only.")

    def request_cancellation(self, *, reason: SloBridgeCancellationReason) -> None:
        """Retain one asynchronous native cancellation; intent alone is not closure."""
        if self._cancellation_task is not None:
            return
        if self._startup_active:
            self._cancellation_task = asyncio.create_task(coro=self.bridge_adapter.close())
        elif self._invocation_id is not None:
            self._cancellation_task = asyncio.create_task(
                coro=self.bridge_adapter.cancel_invocation(invocation_id=self._invocation_id)
            )

    def live_message_history(self) -> list[BaseMessage]:
        """Return detached completed live context when the host disables persistence."""
        return deepcopy(self._completed_history)

    async def finish_host_turn(self) -> None:
        """Join parked native work when a host hook stops before native completion.

        The graph calls this before publishing its terminal event. Successful
        native completion keeps the conversation reusable; a pending tool boundary
        requires cancellation and permanent closure rather than implied success.
        """
        if self._pending is not None:
            await self.close()

    async def close(self) -> None:
        """Seal admission and join cancellation and adapter closure without closing history."""
        self._closed = True
        cancellation_failure: Optional[BaseException] = None
        if self._cancellation_task is not None:
            try:
                await asyncio.shield(self._cancellation_task)
            except Exception as error:
                cancellation_failure = error
        await self.bridge_adapter.close()
        if cancellation_failure is not None:
            # Successful explicit adapter close settles a previously failed cancel.
            self._cancellation_task = None
