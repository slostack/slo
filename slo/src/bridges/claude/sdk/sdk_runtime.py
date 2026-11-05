"""SDK task ownership and native response decoding, not a replacement process supervisor."""

import asyncio
import json

import anyio
from collections.abc import AsyncIterator
from typing import Any, Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    SystemMessage,
)
from claude_agent_sdk._internal.transport import Transport
from .native_transport import ClaudeNativeTransport

from .authentication import ClaudeNativeAuthentication
from .dao import (
    ClaudeBridgeConfigurationDAO,
    ClaudeInvocationOptionsDAO,
    ClaudeSessionOptionsDAO,
    ClaudeInteractionBindingDAO,
    ClaudeToolResultBatchDAO,
    ClaudeUsageDAO,
)
from .tool_bridge import ClaudeToolBridge
from .inventory import ClaudeToolInventory
from .response import NativeResponseAssembly
from .transport import ValidatedClaudeTransport
from .events import (
    ClaudeBridgeEvent,
    ClaudeResponseEventDAO,
    ClaudeResponseCompletedDAO,
    ClaudeTextEventDAO,
    ClaudeThinkingEventDAO,
)
from .exceptions import ClaudeBridgeError, ClaudeSubmissionNotStartedError


class ClaudeSDKRuntime:
    """Connect/query/disconnect in one retained owner task and stream bounded text."""

    def __init__(
        self,
        *,
        transport: Optional[Transport] = None,
        configuration: Optional[ClaudeBridgeConfigurationDAO] = None,
        resume_session_id: Optional[str] = None,
        cleanup_grace_seconds: float = 5,
        cleanup_force_seconds: float = 5,
    ) -> None:
        """Store an optional SDK transport without opening it or capturing a loop."""
        self._transport = transport
        self._cleanup_grace_seconds = cleanup_grace_seconds
        self._cleanup_force_seconds = cleanup_force_seconds
        self._resume_session_id = resume_session_id
        self._native_session_id: Optional[str] = None
        if not 0 < cleanup_grace_seconds <= 5 or not 0 < cleanup_force_seconds <= 5:
            raise ValueError("Claude cleanup deadlines must be positive and at most five seconds.")
        self._configuration = configuration or ClaudeBridgeConfigurationDAO()
        self._connected = False
        self._query_attempted = False
        self._events: asyncio.Queue[ClaudeBridgeEvent | BaseException | None] = asyncio.Queue(maxsize=256)
        self._owner: Optional[asyncio.Task[None]] = None
        self._cancel_requested = asyncio.Event()
        self._terminal = False
        self._cleanup_error: Optional[ClaudeBridgeError] = None
        self._cleanup_deadline: Optional[float] = None
        self._cleanup_finished = asyncio.Event()
        self._retry_cleanup = asyncio.Event()
        self._delivery_finished = asyncio.Event()
        self._failure: Optional[BaseException] = None
        self._completion: Optional[ClaudeResponseCompletedDAO] = None
        self._tool_bridge: Optional[ClaudeToolBridge] = None
        self._binding: Optional[ClaudeInteractionBindingDAO] = None
        self._sequence = 0
        self._queued_bytes = 0

    def start(
        self, *, session_options: ClaudeSessionOptionsDAO, invocation_options: ClaudeInvocationOptionsDAO
    ) -> None:
        """Start exactly one SDK owner after adapter admission and authentication."""
        if self._owner is not None:
            raise RuntimeError("Native submission already started.")
        self._owner = asyncio.create_task(
            coro=self._run(session_options=session_options, invocation_options=invocation_options)
        )

    async def read_response(self) -> AsyncIterator[ClaudeBridgeEvent]:
        """Deliver ordered text; EOF without an acknowledged result is never success."""
        while not self._delivery_finished.is_set() or not self._events.empty():
            if not self._events.empty():
                event = self._events.get_nowait()
                self._release_event(event=event)
                if isinstance(event, BaseException):
                    raise event
                if event is not None:
                    yield event
                    if isinstance(event, ClaudeResponseCompletedDAO):
                        return
                continue
            available = asyncio.create_task(coro=self._events.get())
            finished = asyncio.create_task(coro=self._delivery_finished.wait())
            try:
                await asyncio.wait({available, finished}, return_when=asyncio.FIRST_COMPLETED)
                if available.done():
                    event = available.result()
                    self._release_event(event=event)
                    if isinstance(event, BaseException):
                        raise event
                    if event is not None:
                        yield event
                        if isinstance(event, ClaudeResponseCompletedDAO):
                            return
            finally:
                for task in (available, finished):
                    task.cancel()
                await asyncio.gather(available, finished, return_exceptions=True)
        if self._failure is not None:
            raise self._failure
        if self._completion is not None:
            yield self._completion

    def completed_session_id(self) -> str:
        """Return native resume identity only after successful result and settled cleanup.

        The adapter calls this after draining a terminal response, never after a
        tool boundary. Uncertain delivery cannot authorize another submission.

        Raises:
            RuntimeError: Completion or native identity is not established.
        """
        if self._failure is not None or self._completion is None or not self._cleanup_finished.is_set():
            raise RuntimeError("Claude conversation is uncertain; start a new session.")
        if not self._native_session_id:
            raise RuntimeError("Claude conversation identity is missing; start a new session.")
        return self._native_session_id

    async def cancel(self) -> None:
        """Wake the control path independently of the response queue and join closure."""
        self._begin_cleanup_deadline()
        self._cancel_requested.set()
        await self.close()

    async def close(self) -> None:
        """Join the retained SDK owner despite caller cancellation, then propagate it."""
        if self._owner is None:
            return
        if self._cleanup_error is not None:
            self._cleanup_finished.clear()
            self._cleanup_deadline = None
            self._retry_cleanup.set()
        cancelled = False
        waiter = asyncio.create_task(coro=self._cleanup_finished.wait())
        while not waiter.done():
            try:
                await asyncio.shield(waiter)
            except asyncio.CancelledError:
                cancelled = True
                self._cancel_requested.set()
        if self._cleanup_error is not None:
            raise self._cleanup_error
        await asyncio.shield(self._owner)
        if cancelled:
            raise asyncio.CancelledError

    async def _run(
        self, *, session_options: ClaudeSessionOptionsDAO, invocation_options: ClaudeInvocationOptionsDAO
    ) -> None:
        """Own SDK lifetime until result/failure/cancel and publish completion only after disconnect."""
        client: Optional[ClaudeSDKClient] = None
        completion: Optional[ClaudeResponseCompletedDAO] = None
        failure: Optional[BaseException] = None
        try:
            self._binding = ClaudeInteractionBindingDAO(
                session_id=session_options.session_id,
                invocation_id=invocation_options.invocation_id,
                binding_version=0,
            )
            self._tool_bridge = ClaudeToolBridge.register(
                binding=self._binding,
                tools=session_options.tools,
            )
            options = self._build_options(session_options=session_options)
            options.resume = self._resume_session_id
            if session_options.tools:
                options.mcp_servers = {"slo": self._tool_bridge.build_mcp_server()}
            options.cli_path = str(
                ClaudeNativeAuthentication(configuration=self._configuration).get_executable()
            )
            # Retain partial startup ownership even before SDK query construction.
            if self._transport is None:
                self._transport = ClaudeNativeTransport(
                    options=options,
                    grace_seconds=self._cleanup_grace_seconds,
                    force_seconds=self._cleanup_force_seconds,
                )
            validated_transport = ValidatedClaudeTransport(transport=self._transport)
            client = ClaudeSDKClient(options=options, transport=validated_transport)
            await self._connect_and_query(client=client, prompt=invocation_options.native_prompt())
            completion = await self._read_native_response(client=client, transport=validated_transport)
        except asyncio.CancelledError:
            failure = ClaudeBridgeError(code="cancelled", safe_message="Claude bridge invocation cancelled.")
        except ClaudeBridgeError as error:
            failure = error
        except Exception:
            failure = ClaudeBridgeError(
                code="provider_unavailable",
                safe_message="Claude Code request failed. Check native login and model access outside Slo.",
            )
        finally:
            self._terminal = True
            if self._tool_bridge is not None:
                await self._tool_bridge.close()
            await self._disconnect_until_settled(client=client, failure=failure, completion=completion)

    @staticmethod
    async def _user_message(*, content: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        """Yield one user message carrying ordered content blocks."""
        yield {
            "type": "user",
            "message": {"role": "user", "content": content},
            "parent_tool_use_id": None,
        }

    async def _connect_and_query(
        self, *, client: ClaudeSDKClient, prompt: str | list[dict[str, Any]]
    ) -> None:
        """Cancel blocked SDK startup in its owning anyio context, without another send."""
        owner = asyncio.current_task()
        assert owner is not None
        with anyio.CancelScope() as startup_scope:
            monitor = asyncio.create_task(coro=self._cancel_startup(scope=startup_scope, owner=owner))
            try:
                await client.connect()
                self._connected = True
                if not self._cancel_requested.is_set():
                    self._query_attempted = True
                    await client.query(
                        prompt=prompt if isinstance(prompt, str) else self._user_message(content=prompt)
                    )
                    monitor.cancel()
            finally:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
        if self._cancel_requested.is_set():
            if self._connected:
                await self._interrupt_bounded(client=client)
            raise asyncio.CancelledError

    def _begin_cleanup_deadline(self) -> float:
        """Share one grace ceiling across interrupt, startup rollback and disconnect."""
        if self._cleanup_deadline is None:
            self._cleanup_deadline = asyncio.get_running_loop().time() + self._cleanup_grace_seconds
        return self._cleanup_deadline

    async def _interrupt_bounded(self, *, client: ClaudeSDKClient) -> None:
        """Treat missing control acknowledgement as a reason to disconnect, never to wait forever."""
        try:
            async with asyncio.timeout_at(self._begin_cleanup_deadline()):
                await client.interrupt()
        except TimeoutError:
            return

    async def _cancel_startup(self, *, scope: anyio.CancelScope, owner: asyncio.Task[None]) -> None:
        """Cancel startup in its owner, bounding the SDK's shielded partial-connect rollback."""
        await self._cancel_requested.wait()
        scope.cancel()
        await asyncio.sleep(self._cleanup_grace_seconds)
        # SDK connect catches cancellation and calls shielded disconnect itself.
        # Raw asyncio cancellation interrupts that shield in the SAME owner task;
        # the runtime's retained finally then owns bounded cleanup/retry.
        owner.cancel()

    async def _disconnect_until_settled(
        self,
        *,
        client: Optional[ClaudeSDKClient],
        failure: Optional[BaseException],
        completion: Optional[ClaudeResponseCompletedDAO],
    ) -> None:
        """Retain the SDK context after raised cleanup; only explicit close retries it."""
        while True:
            try:
                await self._disconnect_bounded(client=client)
            except Exception:
                self._cleanup_error = ClaudeBridgeError(
                    code="cleanup_failed",
                    safe_message="Claude SDK cleanup failed; native process closure is unconfirmed.",
                )
                self._failure = self._cleanup_error
                self._delivery_finished.set()
                self._cleanup_finished.set()
                await self._retry_cleanup.wait()
                self._retry_cleanup.clear()
                continue
            self._cleanup_error = None
            if failure is not None and not self._cancel_requested.is_set():
                if not self._query_attempted:
                    failure = ClaudeSubmissionNotStartedError(
                        safe_message="Claude prompt was not submitted. Fix native login/connectivity and retry explicitly."
                    )
                else:
                    failure = ClaudeBridgeError(
                        code="submission_uncertain",
                        safe_message=f"{failure} Submission may have occurred; start a new session. Do not replay automatically.",
                    )
            self._failure = failure
            self._completion = completion
            self._delivery_finished.set()
            self._cleanup_finished.set()
            return

    async def _disconnect_bounded(self, *, client: Optional[ClaudeSDKClient]) -> None:
        """Bound shielded SDK cleanup in its owner task, then force the owned transport.

        An inner asyncio deadline can interrupt the SDK's anyio shield without
        moving its task-affine context to another task. Unknown custom transports
        have no force contract: timeout retains failed ownership for explicit retry.
        """
        try:
            async with asyncio.timeout_at(self._begin_cleanup_deadline()):
                if client is not None:
                    await client.disconnect()
                if not self._connected and self._transport is not None:
                    await self._transport.close()
            return
        except TimeoutError:
            if not isinstance(self._transport, ClaudeNativeTransport):
                raise
        async with asyncio.timeout(self._cleanup_force_seconds):
            await self._transport.force_close()
            if client is not None:
                await client.disconnect()

    @staticmethod
    def _build_options(*, session_options: ClaudeSessionOptionsDAO) -> ClaudeAgentOptions:
        """Use only pinned supported controls; preserve native account state without copying secrets."""
        return ClaudeAgentOptions(
            model=session_options.model_id.removeprefix("claude-bridge:"),
            cwd=session_options.working_directory,
            system_prompt={"type": "preset", "preset": "claude_code", "append": session_options.instructions},
            effort=session_options.effort,
            thinking={"type": "adaptive"} if session_options.effort is not None else {"type": "disabled"},
            tools=[],
            allowed_tools=[f"mcp__slo__{tool.name}" for tool in session_options.tools],
            mcp_servers={},
            strict_mcp_config=True,
            setting_sources=[],
            skills=[],
            plugins=[],
            hooks={},
            include_partial_messages=True,
            env={"DISABLE_AUTO_COMPACT": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "0"},
            stderr=lambda _: None,
        )

    async def _read_native_response(
        self, *, client: ClaudeSDKClient, transport: ValidatedClaudeTransport
    ) -> ClaudeResponseCompletedDAO:
        """Race response waiting with cancellation; owner sends interrupt, not the reader task."""
        stream = client.receive_response()
        cancelled: asyncio.Task[object] = asyncio.create_task(coro=self._cancel_requested.wait())
        assembly = NativeResponseAssembly()
        inventory_admitted = False
        assembly.validate_scope(session_id=self._resume_session_id, parent_tool_use_id=None)
        try:
            while True:
                next_message: asyncio.Task[object] = asyncio.create_task(
                    coro=self._read_next_message(stream=stream)
                )
                try:
                    pending_reads: set[asyncio.Future[object] | asyncio.Future[ClaudeBridgeError]] = {
                        next_message,
                        cancelled,
                        transport.failure,
                    }
                    if self._tool_bridge is not None:
                        pending_reads.add(self._tool_bridge.failure)
                    done, _ = await asyncio.wait(pending_reads, return_when=asyncio.FIRST_COMPLETED)
                    if transport.failure in done:
                        raise transport.failure.result()
                    if self._tool_bridge is not None and self._tool_bridge.failure in done:
                        raise self._tool_bridge.failure.result()
                    if next_message not in done:
                        await self._interrupt_bounded(client=client)
                        raise asyncio.CancelledError
                    message = next_message.result()
                except StopAsyncIteration:
                    raise ClaudeBridgeError(
                        code="stream_protocol_failed",
                        safe_message="Claude stream ended without a terminal result.",
                    ) from None
                finally:
                    if not next_message.done():
                        next_message.cancel()
                    await asyncio.gather(next_message, return_exceptions=True)
                if isinstance(message, SystemMessage) and message.subtype == "init":
                    if inventory_admitted:
                        raise ClaudeToolInventory.initialization_error(reason="duplicate initialization")
                    assert self._tool_bridge is not None
                    native_session_id = ClaudeToolInventory.validate_initialization(
                        metadata=message.data,
                        tools=self._tool_bridge.tools,
                    )
                    assembly.validate_scope(session_id=native_session_id, parent_tool_use_id=None)
                    inventory_admitted = True
                    continue
                if not inventory_admitted and isinstance(
                    message, (ResultMessage, StreamEvent, AssistantMessage)
                ):
                    raise ClaudeToolInventory.initialization_error()
                if isinstance(message, ResultMessage):
                    assembly.validate_scope(session_id=message.session_id, parent_tool_use_id=None)
                    assembly.validate_terminal()
                    self._native_session_id = message.session_id
                    if self._tool_bridge is not None:
                        self._tool_bridge.validate_terminal()
                    return self._validate_result(
                        message=message,
                        text=assembly.text,
                        response_id=assembly.response_id,
                        usage=assembly.usage,
                    )
                if isinstance(message, StreamEvent):
                    assembly.validate_scope(
                        session_id=message.session_id, parent_tool_use_id=message.parent_tool_use_id
                    )
                    consumed = assembly.consume(event=message.event)
                    fragment, boundary = consumed.text, consumed.boundary
                    if consumed.thinking:
                        self._queue_event(
                            event=ClaudeThinkingEventDAO(
                                text=consumed.thinking,
                                block_index=consumed.thinking_index,
                                **self._event_binding(response_id=assembly.response_id).model_dump(),
                            )
                        )
                    if fragment:
                        self._queue_event(
                            event=ClaudeTextEventDAO(
                                text=fragment,
                                **self._event_binding(response_id=assembly.response_id).model_dump(),
                            )
                        )
                    if boundary and assembly.calls:
                        assert self._tool_bridge is not None
                        self._tool_bridge.publish_tool_batch(
                            response_id=assembly.response_id, tool_calls=assembly.calls
                        )
                        self._queue_event(
                            event=ClaudeResponseCompletedDAO(
                                stop_reason="tool_calls",
                                **self._event_binding(response_id=assembly.response_id).model_dump(),
                                tool_calls=assembly.calls,
                                usage=assembly.usage,
                            )
                        )
                    continue
                if isinstance(message, AssistantMessage):
                    assembly.reconcile_echo(message=message)
        finally:
            cancelled.cancel()
            await asyncio.gather(cancelled, return_exceptions=True)

    async def submit_tool_results(
        self, *, invocation_id: str, tool_result_batch: ClaudeToolResultBatchDAO
    ) -> None:
        """Continue the same native query by releasing its MCP result waiters."""
        if self._terminal or self._tool_bridge is None:
            raise RuntimeError("Claude invocation is not active.")
        await self._tool_bridge.submit_tool_results(
            invocation_id=invocation_id, tool_result_batch=tool_result_batch
        )

    @staticmethod
    async def _read_next_message(*, stream: AsyncIterator[object]) -> object:
        """Adapt the SDK's Awaitable iterator signature to an asyncio-owned coroutine."""
        return await anext(stream)

    def _queue_event(self, *, event: ClaudeBridgeEvent) -> None:
        """Fail rather than drop a complete response when content capacity is full."""
        size = len(event.model_dump_json().encode())
        if self._queued_bytes + size > 8 * 1024 * 1024:
            raise ClaudeBridgeError(
                code="buffer_limit_exceeded", safe_message="Claude queued content exceeded its limit."
            )
        try:
            self._events.put_nowait(event)
            self._queued_bytes += size
        except asyncio.QueueFull:
            raise ClaudeBridgeError(
                code="buffer_limit_exceeded", safe_message="Claude response queue exceeded its limit."
            ) from None

    def _release_event(self, *, event: ClaudeBridgeEvent | BaseException | None) -> None:
        """Release aggregate byte capacity when a reader consumes an event."""
        if isinstance(event, (ClaudeTextEventDAO, ClaudeThinkingEventDAO, ClaudeResponseCompletedDAO)):
            self._queued_bytes -= len(event.model_dump_json().encode())

    def _event_binding(self, *, response_id: str) -> ClaudeResponseEventDAO:
        """Allocate monotonically ordered correlation from the retained owner."""
        assert self._binding is not None
        self._sequence += 1
        return ClaudeResponseEventDAO(
            session_id=self._binding.session_id,
            invocation_id=self._binding.invocation_id,
            response_id=response_id,
            sequence=self._sequence,
        )

    def _validate_result(
        self, *, message: ResultMessage, text: str, response_id: str, usage: ClaudeUsageDAO
    ) -> ClaudeResponseCompletedDAO:
        """Require explicit successful native result and consistent final echo."""
        if message.is_error or message.subtype != "success":
            subtype = (
                message.subtype
                if message.subtype
                in {
                    "success",
                    "error_during_execution",
                    "error_max_turns",
                    "error_max_budget_usd",
                    "error_max_structured_output_retries",
                }
                else "unknown_error"
            )
            status = message.api_error_status
            http_detail = f"; HTTP {status}" if isinstance(status, int) and 400 <= status <= 599 else ""
            raise ClaudeBridgeError(
                code="provider_unavailable",
                safe_message=(
                    f"Claude Code rejected the selected model ({subtype}{http_detail}). "
                    "Check native model access, login and quota outside Slo; no fallback was attempted."
                ),
            )
        if message.result is not None and message.result != text:
            raise ClaudeBridgeError(
                code="stream_protocol_failed", safe_message="Claude result contradicted streamed text."
            )
        return ClaudeResponseCompletedDAO(
            stop_reason="length" if message.stop_reason == "max_tokens" else "stop",
            usage=usage,
            **self._event_binding(response_id=response_id).model_dump(),
        )
