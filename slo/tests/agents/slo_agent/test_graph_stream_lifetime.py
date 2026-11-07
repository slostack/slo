"""Public graph transport closure must precede abort publication."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Optional

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field
import pytest
from tests.integration.test_messaging_yield import isolated_journey_tasks

pytestmark = pytest.mark.usefixtures("isolated_journey_tasks")

from src.agents.providers import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO


class HeldCloseProvider(FauxChatModel):
    """External provider whose cancellation cleanup is explicitly released."""

    entered: asyncio.Event = Field(default_factory=asyncio.Event)
    closing: asyncio.Event = Field(default_factory=asyncio.Event)
    release: asyncio.Event = Field(default_factory=asyncio.Event)
    close_count: int = 0
    fail_close: bool = False

    def __init__(self, *, responses: list[AIMessage], fail_close: bool = False) -> None:
        """Keep the external provider's explicit construction contract."""
        super().__init__(responses=responses)
        self.fail_close = fail_close

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Hold provider progress and then hold its owned cleanup."""
        self.entered.set()
        try:
            await asyncio.Event().wait()
            if False:
                yield ChatGenerationChunk(message=FauxChatModel.assistant_message(content="unused"))
        finally:
            self.close_count += 1
            self.closing.set()
            await self.release.wait()
            if self.fail_close:
                raise RuntimeError("provider cleanup failed")


class TestGraphEventStreamProviderOwnership:
    """Exercise the existing transport owner's provider lifecycle contract directly."""

    async def test_owner_assembles_actual_provider_chunks(self) -> None:
        """The transport owner consumes the retained provider, not a replacement driver."""
        from src.agents.slo_agent.graph.event_stream import GraphEventStream

        model: FauxChatModel = FauxChatModel(
            responses=[AIMessage(content="hello world")],
            chunk_scripts=[[AIMessageChunk(content="hello "), AIMessageChunk(content="world")]],
        )
        response: BaseMessage = await GraphEventStream.invoke_joined_provider(
            llm=model, messages=[], kwargs={}
        )
        assert isinstance(response, AIMessage)
        assert response.content == "hello world"
        assert not model.queue and not model.chunk_queue

    async def test_graph_caller_preserves_provider_context_and_retained_completion(self) -> None:
        """The real graph inherits caller context and retains its actual assembled message."""
        from src.agents.slo_agent.graph.dao import SloAgentBuildResult, SloAgentStateDAO
        from src.agents.slo_agent.graph.event_stream import GraphEventStream
        from src.agents.slo_agent.graph.service import build_slo_agent

        request_context: ContextVar[str] = ContextVar("iy07_request_context", default="missing")
        observed_contexts: list[str] = []

        class ContextProvider(FauxChatModel):
            """Record task-local context at the external provider boundary only."""

            def __init__(self, *, responses: list[AIMessage]) -> None:
                """Retain explicit external provider script construction."""
                super().__init__(responses=responses)

            async def _astream(
                self,
                messages: list[BaseMessage],
                stop: Optional[list[str]] = None,
                run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
                **kwargs: object,
            ) -> AsyncIterator[ChatGenerationChunk]:
                """Record inherited context, then use the original scripted chunks."""
                observed_contexts.append(request_context.get())
                async for chunk in super()._astream(
                    messages=messages, stop=stop, run_manager=run_manager, **kwargs
                ):
                    yield chunk

        model: ContextProvider = ContextProvider(responses=[AIMessage(content="retained")])
        built: SloAgentBuildResult = build_slo_agent(llm=model, tools=[])
        completed_responses: list[BaseMessage] = []
        stream: AsyncGenerator[object, None] = GraphEventStream.invoke(
            graph=built.graph, state=SloAgentStateDAO(messages=[]), completed_responses=completed_responses
        )
        token: Token[str] = request_context.set("original-request")
        try:
            async with asyncio.timeout(delay=5):
                async for _ in stream:
                    pass
        finally:
            await stream.aclose()
            request_context.reset(token)
        assert built.llm is model
        assert observed_contexts == ["original-request"]
        assert [message.content for message in completed_responses] == ["retained"]
        assert request_context.get() == "missing"

    async def test_owner_joins_cleanup_once_under_repeated_cancellation(self) -> None:
        """Cancellation stays with the same provider until its held cleanup completes."""
        from src.agents.slo_agent.graph.event_stream import GraphEventStream

        model: HeldCloseProvider = HeldCloseProvider(responses=[])
        owner: asyncio.Task[BaseMessage] = asyncio.create_task(
            coro=GraphEventStream.invoke_joined_provider(llm=model, messages=[], kwargs={})
        )
        try:
            async with asyncio.timeout(delay=5):
                await model.entered.wait()
                owner.cancel()
                await model.closing.wait()
            owner.cancel()
            await asyncio.sleep(delay=0)
            assert not owner.done() and model.close_count == 1
            model.release.set()
            async with asyncio.timeout(delay=5):
                with pytest.raises(asyncio.CancelledError):
                    await owner
            assert model.close_count == 1
        finally:
            model.release.set()
            if not owner.done():
                owner.cancel()
            await asyncio.gather(owner, return_exceptions=True)


async def test_abort_waits_for_provider_cleanup(tmp_path: Path) -> None:
    """No abort terminal is observable while provider cleanup is held."""
    model = HeldCloseProvider(responses=[])
    agent = SloAgent(llm=model, tools=[], cwd=str(tmp_path))
    events: list[AgentStreamEventDAO] = []

    async def consume() -> None:
        """Own the public invocation until every graph operation joins."""
        async for event in agent.invoke(query="hello"):
            events.append(event)

    owner = asyncio.create_task(coro=consume())
    try:
        async with asyncio.timeout(delay=5):
            await model.entered.wait()
        agent.abort()
        async with asyncio.timeout(delay=5):
            await model.closing.wait()
        assert not any(event.is_terminal for event in events)
        assert not owner.done()
        model.release.set()
        async with asyncio.timeout(delay=5):
            await owner
        assert [event.kind for event in events if event.is_terminal] == ["run_aborted"]
        assert model.close_count == 1
    finally:
        model.release.set()
        if not owner.done():
            owner.cancel()
        await asyncio.gather(owner, return_exceptions=True)


async def test_abort_cleanup_failure_is_not_reported_as_successful_abort(tmp_path: Path) -> None:
    """A failed reader cleanup must fail closed instead of publishing run_aborted."""
    model = HeldCloseProvider(responses=[], fail_close=True)
    agent = SloAgent(llm=model, tools=[], cwd=str(tmp_path))
    events: list[AgentStreamEventDAO] = []

    async def consume() -> None:
        """Retain the public invocation's failure and terminal events."""
        async for event in agent.invoke(query="hello"):
            events.append(event)

    owner = asyncio.create_task(coro=consume())
    try:
        async with asyncio.timeout(delay=5):
            await model.entered.wait()
        agent.abort()
        async with asyncio.timeout(delay=5):
            await model.closing.wait()
        model.release.set()
        async with asyncio.timeout(delay=5):
            result = await asyncio.gather(owner, return_exceptions=True)
        from src.agents.slo_agent.history.message_contract_reconciler import CooperativeYieldSettlementError

        assert model.fail_close is True
        assert isinstance(result[0], CooperativeYieldSettlementError), (result, events)
        assert not any(event.kind == "run_aborted" for event in events)
        assert model.close_count == 1
    finally:
        model.release.set()
        if not owner.done():
            owner.cancel()
        await asyncio.gather(owner, return_exceptions=True)


async def test_saturated_graph_transport_close_joins_exact_driver(tmp_path: Path) -> None:
    """Closing a paused consumer releases count/byte backpressure before joining driver."""
    from langchain_core.messages import AIMessage, AIMessageChunk
    from src.agents.slo_agent.graph.event_stream import GraphEventStream
    from src.agents.slo_agent.graph.dao import SloAgentStateDAO

    class SaturatingProvider(FauxChatModel):
        saturated: asyncio.Event = Field(default_factory=asyncio.Event)
        joined: asyncio.Event = Field(default_factory=asyncio.Event)
        produced: int = 0

        def __init__(self, *, responses: list[AIMessage]) -> None:
            """Retain the explicit external provider script construction contract."""
            super().__init__(responses=responses)

        def bind_tools(self, tools: object, **kwargs: object) -> "SaturatingProvider":
            """Keep the exact provider identity for retained-lifetime assertions."""
            return self

        async def _astream(
            self,
            messages: list[BaseMessage],
            stop: Optional[list[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: object,
        ) -> AsyncIterator[ChatGenerationChunk]:
            """Produce enough large chunks to hit the invocation byte budget."""
            try:
                for index in range(500):
                    self.produced += 1
                    if index == 4:
                        self.saturated.set()
                    yield ChatGenerationChunk(message=AIMessageChunk(content="x" * 300_000))
            finally:
                self.joined.set()

    model = SaturatingProvider(responses=[AIMessage(content="unused")])
    from src.agents.slo_agent.graph.service import build_slo_agent

    built = build_slo_agent(llm=model, tools=[])
    stream = GraphEventStream.invoke(
        graph=built.graph, state=SloAgentStateDAO(messages=[]), completed_responses=[]
    )
    try:
        await anext(stream)
        async with asyncio.timeout(delay=5):
            await model.saturated.wait()
        assert model.produced < 500 and not model.joined.is_set()
        async with asyncio.timeout(delay=5):
            await stream.aclose()
        assert model.joined.is_set()
    finally:
        await stream.aclose()


async def test_timeout_repeated_cancellation_retains_provider_cleanup(tmp_path: Path) -> None:
    """Timeout and repeated caller cancellation cannot publish or release before close."""
    from src.agents.slo_agent.watchdog_timer import WatchDogTimer
    from src.agents.slo_agent.graph.service import build_slo_agent
    from src.agents.slo_agent.graph.event_stream import GraphEventStream
    from src.agents.slo_agent.graph.dao import SloAgentStateDAO

    model = HeldCloseProvider(responses=[])
    built = build_slo_agent(llm=model, tools=[])
    # Faux binding clones by default; retain the explicit provider boundary instead.
    assert isinstance(built.llm, HeldCloseProvider)
    model = built.llm
    stream = GraphEventStream.invoke(
        graph=built.graph, state=SloAgentStateDAO(messages=[]), completed_responses=[]
    )
    timer = WatchDogTimer(first_progress_timeout_seconds=0.01, idle_timeout_seconds=0.01)
    owner = asyncio.create_task(coro=timer.invoke(graph_stream=stream))
    try:
        async with asyncio.timeout(delay=5):
            await model.closing.wait()
        owner.cancel()
        await asyncio.sleep(delay=0)
        owner.cancel()
        await asyncio.sleep(delay=0)
        assert not owner.done() and model.close_count == 1
        model.release.set()
        result = await asyncio.gather(owner, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        await stream.aclose()
        assert model.close_count == 1
    finally:
        model.release.set()
        await asyncio.gather(owner, return_exceptions=True)
        await stream.aclose()


async def test_consumer_close_after_live_chunk_joins_provider_once(tmp_path: Path) -> None:
    """A downstream consumer leaving mid-response still owns provider generator closure."""
    from langchain_core.messages import AIMessage, AIMessageChunk
    from src.agents.slo_agent.graph.service import build_slo_agent
    from src.agents.slo_agent.graph.event_stream import GraphEventStream
    from src.agents.slo_agent.graph.dao import SloAgentStateDAO

    class LiveThenHeld(HeldCloseProvider):
        def __init__(self, *, responses: list[AIMessage]) -> None:
            """Keep the external provider construction contract explicit."""
            super().__init__(responses=responses)

        async def _astream(
            self,
            messages: list[BaseMessage],
            stop: Optional[list[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: object,
        ) -> AsyncIterator[ChatGenerationChunk]:
            """Deliver live truth, then require the consumer to join actual close."""
            yield ChatGenerationChunk(message=AIMessageChunk(content="partial"))
            async for chunk in super()._astream(
                messages=messages, stop=stop, run_manager=run_manager, **kwargs
            ):
                yield chunk

    model = LiveThenHeld(responses=[AIMessage(content="unused")])
    built = build_slo_agent(llm=model, tools=[])
    stream = GraphEventStream.invoke(
        graph=built.graph, state=SloAgentStateDAO(messages=[]), completed_responses=[]
    )
    close = None
    try:
        assert await anext(stream) is not None
        await model.entered.wait()
        close = asyncio.create_task(coro=stream.aclose())
        await model.closing.wait()
        close.cancel()
        await asyncio.sleep(delay=0)
        close.cancel()
        await asyncio.sleep(delay=0)
        assert not close.done() and model.close_count == 1
        model.release.set()
        await asyncio.gather(close, return_exceptions=True)
        assert model.close_count == 1
    finally:
        model.release.set()
        if close is not None:
            await asyncio.gather(close, return_exceptions=True)
        await stream.aclose()


async def test_live_trace_failure_still_joins_provider_cleanup(tmp_path: Path) -> None:
    """Trusted output history failure cannot skip the retained graph close owner."""
    from langchain_core.messages import AIMessageChunk
    from src.agents.slo_agent.events.runtime import AgentRuntimeEventDAO

    class LiveFailureProvider(HeldCloseProvider):
        def __init__(self, *, responses: list[AIMessage]) -> None:
            """Keep the fixture provider construction explicit."""
            super().__init__(responses=responses)

        async def _astream(
            self,
            messages: list[BaseMessage],
            stop: Optional[list[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: object,
        ) -> AsyncIterator[ChatGenerationChunk]:
            """Make history fail on a live chunk, with cleanup held after cancellation."""
            yield ChatGenerationChunk(message=AIMessageChunk(content="live"))
            async for chunk in super()._astream(
                messages=messages, stop=stop, run_manager=run_manager, **kwargs
            ):
                yield chunk

    model = LiveFailureProvider(responses=[])
    agent = SloAgent(llm=model, tools=[], cwd=str(tmp_path))
    events: list[AgentStreamEventDAO] = []

    async def history(event: AgentRuntimeEventDAO) -> None:
        """Raise at actual trusted output persistence, not at the external provider."""
        if event.kind == "assistant_delta":
            raise RuntimeError("history failure")

    async def consume() -> None:
        """Retain the consumer task through history failure and provider close."""
        async for event in agent.invoke(query="hello", runtime_handler=history):
            events.append(event)

    owner = asyncio.create_task(coro=consume())
    try:
        async with asyncio.timeout(delay=5):
            await model.closing.wait()
        assert not owner.done() and not any(event.is_terminal for event in events)
        model.release.set()
        result = await asyncio.gather(owner, return_exceptions=True)
        assert isinstance(result[0], RuntimeError)
        assert model.close_count == 1
    finally:
        model.release.set()
        await asyncio.gather(owner, return_exceptions=True)


async def test_public_consumer_close_joins_chain_before_idle(tmp_path: Path) -> None:
    """Public invoke close retains every delegate until provider cleanup joins once."""
    from langchain_core.messages import AIMessageChunk

    class PublicLiveProvider(HeldCloseProvider):
        def __init__(self, *, responses: list[AIMessage]) -> None:
            """Retain the explicit provider construction boundary."""
            super().__init__(responses=responses)

        async def _astream(
            self,
            messages: list[BaseMessage],
            stop: Optional[list[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: object,
        ) -> AsyncIterator[ChatGenerationChunk]:
            """Emit a public event before holding cancellable provider work."""
            yield ChatGenerationChunk(message=AIMessageChunk(content="partial"))
            async for chunk in super()._astream(
                messages=messages, stop=stop, run_manager=run_manager, **kwargs
            ):
                yield chunk

    model = PublicLiveProvider(responses=[])
    agent = SloAgent(llm=model, tools=[], cwd=str(tmp_path))
    stream = agent.invoke(query="hello")
    close: Optional[asyncio.Task[None]] = None
    try:
        async with asyncio.timeout(delay=5):
            while (await anext(stream)).kind != "text_delta":
                pass
            await model.entered.wait()
        close = asyncio.create_task(coro=stream.aclose())
        async with asyncio.timeout(delay=2):
            await model.closing.wait()
        assert not close.done()
        competing = agent.invoke(query="must refuse while closing")
        with pytest.raises(RuntimeError, match="processing"):
            await anext(competing)
        await competing.aclose()
        close.cancel()
        await asyncio.sleep(delay=0)
        close.cancel()
        await asyncio.sleep(delay=0)
        assert not close.done() and model.close_count == 1
        model.release.set()
        await asyncio.gather(close, return_exceptions=True)
        assert model.close_count == 1
    finally:
        model.release.set()
        if close is not None:
            await asyncio.gather(close, return_exceptions=True)
        await stream.aclose()
