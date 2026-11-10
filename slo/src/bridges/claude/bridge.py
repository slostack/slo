"""Claude SDK model integration on Slo's existing LangChain core 0.3 interface."""

import asyncio
import json
from copy import deepcopy
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path
from typing import Any, Literal, Optional, TYPE_CHECKING
from uuid import uuid4

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
)
from src.agents.tools.bundles import create_local_tools
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.language_models.chat_models import agenerate_from_stream
from pydantic import ConfigDict, PrivateAttr

from src.bridges.dao import SloBridgeCancellationReason, SloBridgeSessionOptionsDAO
from .sdk.dao import (
    ClaudeInvocationOptionsDAO,
    ClaudeInteractionBindingDAO,
    ClaudeImageDAO,
    ClaudeSessionOptionsDAO,
    ClaudeSubmissionPlanDAO,
    ClaudeToolDefinitionDAO,
    ClaudeToolResultBatchDAO,
    ClaudeToolResultDAO,
    ClaudeToolResultSubmissionDAO,
    ClaudeTextDAO,
)
from .sdk.events import (
    ClaudeResponseClosedDAO,
    ClaudeResponseCompletedDAO,
    ClaudeTextEventDAO,
    ClaudeThinkingEventDAO,
)
from .sdk.protocol import SloBridgeAdapterProtocol
from .sdk.exceptions import ClaudeBridgeError, ClaudeSubmissionNotStartedError
from .sdk.inventory import ClaudeToolInventory
from .history_transcript import ClaudeHistoryTranscript
from .host_content import ClaudeHostContent
from .host_usage import ClaudeHostUsage
from .tool_result import ToolCallResponseAdapter
from .response import AIAgentResponseAdapter, ClaudeResponseTranslationDAO
from .tool_call import ToolCallAdapter, ClaudeCompletedCallBatchDAO

if TYPE_CHECKING:
    from .summary_bridge import ClaudeSummaryBridge


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
    _retired: bool = PrivateAttr(default=False)
    _startup_active: bool = PrivateAttr(default=False)
    _tools: tuple[ClaudeToolDefinitionDAO, ...] = PrivateAttr(default=())
    _pending: Optional[ClaudeResponseCompletedDAO] = PrivateAttr(default=None)
    _consumed: list[dict[str, object]] = PrivateAttr(default_factory=list)
    _tool_result_adapter: Optional[ToolCallResponseAdapter] = PrivateAttr(default=None)
    _response_adapter: Optional[AIAgentResponseAdapter] = PrivateAttr(default=None)
    _call_adapter: Optional[ToolCallAdapter] = PrivateAttr(default=None)
    _response_messages: list[BaseMessage] = PrivateAttr(default_factory=list)
    _translated_chunks: list[ChatGenerationChunk] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        """Identify the native runtime without pretending it is direct Anthropic HTTP."""
        return "slo-claude-bridge"

    def summary_bridge(
        self, *, bridge_adapter: SloBridgeAdapterProtocol, session_id: str, working_directory: Path
    ) -> "ClaudeSummaryBridge":
        """Build a one-shot, tool-free bridge for the same route and effort as this conversation."""
        from .summary_bridge import ClaudeSummaryBridge

        return ClaudeSummaryBridge(
            model_name=self.model_name,
            effort=self.effort,
            bridge_adapter=bridge_adapter,
            session_id=session_id,
            working_directory=working_directory,
        )

    def configure_session(self, *, session_options: SloBridgeSessionOptionsDAO) -> None:
        """Store final host context inertly and reject implicit rebinding."""
        if self._closed:
            raise RuntimeError("Claude bridge is closed.")
        if self._session_options is not None and self._session_options != session_options:
            raise ValueError("Claude bridge session configuration cannot change.")
        self._session_options = session_options

    def bind_tools(self, tools: Sequence[object], **kwargs: Any) -> BaseChatModel:
        """Freeze local or typed orchestration definitions without starting native work.

        Accepts typed named orchestration tools, an empty inventory or canonical local subsets:
        native initialization is checked per advertised definition, so a subset
        is safe. Unknown, copied or duplicated tools, extra keyword options and
        a binding change after configuration raise ``ValueError`` before native work.
        """
        if kwargs:
            raise ValueError("Unsupported Claude tool binding.")
        frozen = self.freeze_tool_binding(tools=tools)
        if self._session_options is not None and self._tools != frozen:
            raise ValueError("Claude bridge tool binding cannot change.")
        self._tools = frozen
        return self

    @classmethod
    def freeze_tool_binding(cls, *, tools: Sequence[object]) -> tuple[ClaudeToolDefinitionDAO, ...]:
        """Validate and detach the complete proposed host binding without native work.

        Session preparation calls this before retiring its current agent; bind_tools
        uses the same policy before publishing definitions. No adapter is constructed.

        Args:
            tools (Sequence[object]): Complete proposed local and orchestration bundle.

        Returns:
            tuple[ClaudeToolDefinitionDAO, ...]: Independently owned portable definitions.

        Raises:
            ValueError: Names, identities, duplicates or schemas are unsupported.
        """
        canonical: dict[str, BaseTool] = {tool.name: tool for tool in create_local_tools()}
        if len({getattr(tool, "name", None) for tool in tools}) != len(tools):
            raise ValueError("Unsupported Claude tool binding.")
        definitions: list[ClaudeToolDefinitionDAO] = []
        for tool in sorted(tools, key=lambda tool: getattr(tool, "name", "")):
            if not isinstance(tool, BaseTool) or not (
                tool.name in ClaudeToolInventory.ORCHESTRATION_NAMES
                or any(tool is candidate for candidate in canonical.values())
            ):
                raise ValueError(
                    "Claude bridge requires canonical local or typed orchestration tools; "
                    "unsupported extension tools."
                )
            schema = tool.args_schema
            if schema is None or isinstance(schema, dict):
                raise ValueError("Claude tool requires a typed argument schema.")
            definitions.append(
                ClaudeToolDefinitionDAO(
                    name=tool.name, description=tool.description, input_schema=schema.model_json_schema()
                )
            )
        return ClaudeToolInventory.freeze(tools=tuple(definitions))

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[ChatGenerationChunk, None]:
        """Stream one new text answer; the final chunk follows SDK closure."""
        if self._closed or self._session_options is None:
            raise RuntimeError("Claude bridge is closed or unconfigured; start a new session.")
        plan = self._validated_plan(messages=messages, stop=stop, kwargs=kwargs)
        boundary = False
        proven_unsent = False
        self._startup_active = True
        try:
            await self._admit_response(messages=messages, plan=plan)
            self._startup_active = False
            assert self._invocation_id is not None
            assert self._response_adapter is not None
            self._response_messages = messages
            async for event in self.bridge_adapter.read_response(invocation_id=self._invocation_id):
                await self._response_adapter.handle(event=event)
                boundary = isinstance(event, ClaudeResponseCompletedDAO)
                chunks, self._translated_chunks = self._translated_chunks, []
                for chunk in chunks:
                    yield chunk
        except ClaudeSubmissionNotStartedError:
            proven_unsent = True
            self._forget_unsent_submission(
                messages=messages, native_session_dropped=bool(plan and plan.fresh_native_session)
            )
            raise
        except ClaudeBridgeError as error:
            # Only a validated missing subset is correctable. No result has been
            # reserved or sent, so leave this response's waiters parked for its caller.
            if error.code == "tool_result_mismatch":
                boundary = True
            raise
        finally:
            await self._finish_response_stream(boundary=boundary, proven_unsent=proven_unsent)

    async def _admit_response(
        self,
        *,
        messages: list[BaseMessage],
        plan: Optional[ClaudeSubmissionPlanDAO],
    ) -> None:
        """Submit a validated continuation or one planned prompt with its unseen transcript.

        Called by the stream while startup cancellation is active. Validation or
        submission errors propagate to its existing unsent/uncertain failure policy.
        """
        if plan is None:
            assert self._tool_result_adapter is not None
            await self._tool_result_adapter.handle(
                event=self._build_tool_result_submission(messages=messages),
            )
            await self._tool_result_adapter.close()
            self._tool_result_adapter = None
            return
        assert self._session_options is not None
        if plan.abandon_parked_round:
            await self._abandon_parked_round()
        if plan.fresh_native_session:
            self.bridge_adapter.start_fresh_conversation()
        await self._start_invocation(content=plan.content, options=self._session_options)

    async def _abandon_parked_round(self) -> None:
        """Join the parked native invocation before discarding its translators.

        Admission calls this with startup cancellation active. Cancellation needs
        the old invocation identity and releases native waiters before translator
        closure. A cleanup failure propagates to the stream's retained-owner
        failure policy; no successor is started until every close succeeds.
        """
        assert self._invocation_id is not None
        await self.bridge_adapter.cancel_invocation(invocation_id=self._invocation_id)
        if self._tool_result_adapter is not None:
            await self._tool_result_adapter.close()
            self._tool_result_adapter = None
        if self._call_adapter is not None:
            await self._call_adapter.close()
            self._call_adapter = None
        if self._response_adapter is not None:
            await self._response_adapter.close()
            self._response_adapter = None
        self._pending = None
        self._consumed = []
        self._invocation_id = None

    def _record_tool_boundary(
        self,
        *,
        messages: list[BaseMessage],
        response_text: str,
        event: ClaudeResponseCompletedDAO,
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
        assert self._session_options is not None and self._invocation_id is not None
        self._tool_result_adapter = ToolCallResponseAdapter.register(
            binding=ClaudeInteractionBindingDAO(
                session_id=self._session_options.session_id,
                invocation_id=self._invocation_id,
                binding_version=0,
            ),
            expected=event,
            receiver=self._submit_tool_results,
        )

    def _record_terminal_context(self, *, messages: list[BaseMessage], response_text: str) -> None:
        """Record what Claude consumed after native terminal cleanup has settled."""
        self._pending = None
        self._consumed = self._semantic_messages(messages=[*messages, AIMessage(content=response_text)])

    def _forget_unsent_submission(self, *, messages: list[BaseMessage], native_session_dropped: bool) -> None:
        """Forget unsent admission identity; Claude has seen none of the new input.

        ``_consumed`` only ever means what Claude saw, so it never advances here.
        A fresh plan already dropped the native session, so nothing remains seen.
        Clearing invocation identity allows an explicit retry with the retained session.
        """
        if native_session_dropped:
            self._consumed = []
        self._invocation_id = None

    async def _accept_response(self, translation: ClaudeResponseTranslationDAO) -> None:
        """Build host thinking/text/terminal chunks from the sole portable response assembly."""
        event = translation.event
        if isinstance(event, ClaudeTextEventDAO):
            self._translated_chunks.append(ChatGenerationChunk(message=AIMessageChunk(content=event.text)))
            return
        if isinstance(event, ClaudeThinkingEventDAO):
            # Same block shape the shared normalizer reads for every model's reasoning.
            thinking_block = {"type": "thinking", "thinking": event.text, "index": event.block_index}
            self._translated_chunks.append(
                ChatGenerationChunk(message=AIMessageChunk(content=[thinking_block]))
            )
            return
        if isinstance(event, ClaudeResponseClosedDAO):
            # A native refusal can continue within this same host generation.
            # Report message usage without changing consumed history or granting
            # terminal success; only the cleanup-settled result may do that.
            self._translated_chunks.append(
                ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="", usage_metadata=ClaudeHostUsage.translate(usage=event.usage)
                    )
                )
            )
            return
        self._record_terminal_context(messages=self._response_messages, response_text=translation.text)
        self._translated_chunks.append(
            ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    response_metadata={"stop_reason": event.stop_reason},
                    usage_metadata=ClaudeHostUsage.translate(usage=event.usage),
                )
            )
        )

    async def _accept_tool_response(self, translation: ClaudeResponseTranslationDAO) -> None:
        """Register a response-scoped completed-call owner, never partial host calls."""
        event = translation.event
        assert isinstance(event, ClaudeResponseCompletedDAO)
        assert self._session_options is not None and self._invocation_id is not None
        if self._call_adapter is not None:
            await self._call_adapter.close()
        self._call_adapter = ToolCallAdapter.register(
            binding=ClaudeInteractionBindingDAO(
                session_id=self._session_options.session_id,
                invocation_id=self._invocation_id,
                binding_version=0,
            ),
            response_id=event.response_id,
            tools=self._tools,
            receiver=self._accept_call_batch,
        )
        await self._call_adapter.handle(event=event)
        self._record_tool_boundary(
            messages=self._response_messages, response_text=translation.text, event=event
        )

    async def _accept_call_batch(self, batch: ClaudeCompletedCallBatchDAO) -> None:
        """Build the single LangChain call representation from detached ordered calls."""
        self._translated_chunks.append(
            ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": call.name,
                            "args": call.arguments_json,
                            "id": call.tool_call_id,
                            "index": index,
                        }
                        for index, call in enumerate(batch.calls)
                    ],
                    response_metadata={"stop_reason": batch.completion.stop_reason},
                    usage_metadata=ClaudeHostUsage.translate(usage=batch.completion.usage),
                )
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
        await self.close()

    @staticmethod
    def _semantic_messages(*, messages: list[BaseMessage]) -> list[dict[str, object]]:
        """Compare meaningful content, ignoring regenerated message identifiers."""
        return deepcopy(
            [
                {
                    "type": m.type,
                    "content": ClaudeHostContent.model_context(content=m.content),
                    "tool_calls": m.tool_calls if isinstance(m, AIMessage) else None,
                    "tool_call_id": m.tool_call_id if isinstance(m, ToolMessage) else None,
                    "status": m.status if isinstance(m, ToolMessage) else None,
                }
                for m in messages
            ]
        )

    def _build_tool_result_submission(self, *, messages: list[BaseMessage]) -> ClaudeToolResultSubmissionDAO:
        """Translate the unchanged host prefix and all terminal blocks before delivery.

        Args:
            messages: Accumulated graph messages with the pending result suffix.

        Returns:
            ClaudeToolResultSubmissionDAO: Portable live content, never durable image refs.

        Raises:
            ValueError: Earlier content changed or the suffix contains unsupported content.
        """
        assert self._pending is not None and self._invocation_id is not None
        prefix = self._semantic_messages(messages=messages[: len(self._consumed)])
        if prefix != self._consumed:
            raise ValueError("Claude tool result prefix changed.")
        return ClaudeToolResultSubmissionDAO(
            invocation_id=self._invocation_id,
            tool_result_batch=ClaudeToolResultBatchDAO(
                response_id=self._pending.response_id,
                results=tuple(
                    self._build_tool_result(message=message) for message in messages[len(self._consumed) :]
                ),
            ),
        )

    @classmethod
    def _build_tool_result(cls, *, message: BaseMessage) -> ClaudeToolResultDAO:
        """Convert one terminal host message without guessing error status from text.

        Args:
            message: Exact executor output; strings and ordered text/image lists are supported.

        Returns:
            ClaudeToolResultDAO: Live blocks and the executor's semantic error status.

        Raises:
            ValueError: A non-tool message or unsupported block is present.
        """
        if not isinstance(message, ToolMessage):
            raise ValueError("Unsupported Claude tool result continuation.")
        blocks = [message.content] if isinstance(message.content, str) else message.content
        return ClaudeToolResultDAO(
            tool_call_id=message.tool_call_id,
            content=tuple(ClaudeHostContent.translate(block=block) for block in blocks),
            is_error=message.status == "error",
        )

    async def _submit_tool_results(self, submission: ClaudeToolResultSubmissionDAO) -> None:
        """Adapt the portable receiver to the existing SDK result operation, not a query.

        Args:
            submission: Complete response-bound results accepted by the result adapter.
        """
        await self.bridge_adapter.submit_tool_results(
            invocation_id=submission.invocation_id,
            tool_result_batch=submission.tool_result_batch,
        )

    async def _start_invocation(
        self,
        *,
        content: tuple[ClaudeTextDAO | ClaudeImageDAO, ...],
        options: SloBridgeSessionOptionsDAO,
    ) -> None:
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
        if self._response_adapter is not None:
            await self._response_adapter.close()
        self._response_adapter = AIAgentResponseAdapter.register(
            binding=ClaudeInteractionBindingDAO(
                session_id=options.session_id, invocation_id=invocation_id, binding_version=0
            ),
            response_receiver=self._accept_response,
            tool_call_receiver=self._accept_tool_response,
        )
        await self.bridge_adapter.invoke_agent(
            invocation_options=(
                ClaudeInvocationOptionsDAO(invocation_id=invocation_id, text=content[0].text)
                if len(content) == 1 and isinstance(content[0], ClaudeTextDAO)
                else ClaudeInvocationOptionsDAO(invocation_id=invocation_id, content=content)
            )
        )

    def _validated_plan(
        self, *, messages: list[BaseMessage], stop: Optional[list[str]], kwargs: dict[str, Any]
    ) -> Optional[ClaudeSubmissionPlanDAO]:
        """Reject generation options and closed bridges, then plan the submission."""
        if self._closed or self._session_options is None:
            raise RuntimeError("Claude bridge is closed or unconfigured.")
        if stop or kwargs:
            raise ValueError("Claude bridge does not support generation options.")
        return self.plan_submission(messages=messages)

    def plan_submission(self, *, messages: list[BaseMessage]) -> Optional[ClaudeSubmissionPlanDAO]:
        """Choose the native session and order the content Claude has not seen.

        When the messages Claude already saw still prefix the incoming history,
        the live native session continues and only the unseen messages are sent
        as a transcript. Otherwise a fresh native session receives all prior
        messages. A parked round with nonempty tool-only suffix returns None
        before prompt validation; every other parked submission must end in a
        valid human prompt and requests abandon before fresh admission.

        Args:
            messages: Replayed Slo messages ending with the new prompt.

        Returns:
            Optional[ClaudeSubmissionPlanDAO]: Native choice and ordered content,
                or None for a nonempty tool-result suffix; submission validates its prefix.

        Raises:
            ValueError: The last message is not a nonempty HumanMessage.
        """
        suffix = messages[len(self._consumed) :]
        if self._pending is not None and suffix and all(isinstance(m, ToolMessage) for m in suffix):
            return None
        prompt = self._build_prompt(message=messages[-1] if messages else None)
        prior = messages[:-1]
        continues = (
            self._pending is None
            and bool(self._consumed)
            and self._semantic_messages(messages=messages[: len(self._consumed)]) == self._consumed
        )
        unseen = prior[len(self._consumed) :] if continues else prior
        transcript = ClaudeHistoryTranscript.render(messages=unseen)
        return ClaudeSubmissionPlanDAO(
            fresh_native_session=not continues,
            abandon_parked_round=self._pending is not None,
            content=(*transcript, *prompt),
        )

    @staticmethod
    def _build_prompt(*, message: Optional[BaseMessage]) -> tuple[ClaudeTextDAO | ClaudeImageDAO, ...]:
        """Translate the final nonempty human prompt into ordered live content."""
        if not isinstance(message, HumanMessage):
            raise ValueError("Claude bridge requires the final message to be a human prompt.")
        content = ClaudeHostContent.translate_all(content=message.content)
        if not any(isinstance(block, ClaudeImageDAO) or block.text.strip() for block in content):
            raise ValueError("Claude bridge requires nonempty text or an image.")
        return content

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

    async def finish_host_turn(self) -> None:
        """Join parked native work when a host hook stops before native completion.

        The graph calls this before publishing its terminal event. Successful
        native completion keeps the conversation reusable; a pending tool boundary
        requires cancellation and permanent closure rather than implied success.
        Already sealed work stays retained for explicit close; failure reporting
        must not retry failed cleanup or mask the original admission refusal.
        """
        if self._closed:
            return
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
        if self._response_adapter is not None:
            await self._response_adapter.close()
        if self._call_adapter is not None:
            await self._call_adapter.close()
        if self._tool_result_adapter is not None:
            await self._tool_result_adapter.close()
        self._translated_chunks.clear()
        self._response_messages.clear()
        if cancellation_failure is not None:
            # Successful explicit adapter close settles a previously failed cancel.
            self._cancellation_task = None
        self._retired = True

    def is_retired(self) -> bool:
        """Report that closure finished without a retained cleanup failure."""
        return self._retired
