"""Trusted cancellation capability and actual terminal truth."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from src.agents.slo_agent.plugins.dao import AfterToolResultPatchDAO
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool

from tests.agents.slo_agent.tool_execution.test_yield_control import RecordingMessageSource, _delivery


@tool
async def cancellable_tool() -> str:
    """Represent one explicitly trusted original tool object."""
    return "unused"


@pytest.mark.parametrize(
    argnames="ack_kind", argvalues=["valid", "wrong", "success", "exception", "late", "normal"]
)
async def test_cancellation_ack_matrix(ack_kind: str) -> None:
    """One port call joins both handles; invalid acknowledgement never invents success."""
    from src.agents.slo_agent.tool_execution.dao import ToolInvocationDAO, ToolCancellationRegistrationDAO
    from src.agents.slo_agent.tool_execution.yield_policy import ToolYieldPolicy, ToolExecutionControl
    from src.agents.slo_agent.history.message_contract_reconciler import UnsettledToolGroupError

    entered = asyncio.Event()
    release = asyncio.Event()
    calls: list[object] = []

    async def invoke() -> ToolMessage:
        """An owned invocation either returns actual truth or joins cancellation."""
        entered.set()
        await release.wait()
        return ToolMessage(content="actual", tool_call_id="call", status="success")

    class Port:
        """Injected trusted port owns invocation termination, not the policy clock."""

        async def cancel_and_join(self, *, invocation: ToolInvocationDAO) -> ToolMessage:
            """Return the selected acknowledgement only after joining the invocation."""
            calls.append(invocation.task)
            if ack_kind == "normal":
                release.set()
                await invocation.task
            else:
                invocation.task.cancel()
                await asyncio.gather(invocation.task, return_exceptions=True)
            if ack_kind == "late":
                await asyncio.sleep(delay=0.02)
            if ack_kind == "exception":
                raise RuntimeError("external details must not escape")
            return ToolMessage(
                content="cancelled",
                tool_call_id="wrong" if ack_kind == "wrong" else "call",
                status="success" if ack_kind == "success" else "error",
            )

    source = RecordingMessageSource(urgent_high_water=0)
    notices: list[object] = []
    control = ToolExecutionControl(source=source, on_deferred=notices.append)
    control.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
    control.enter_tools(tool_call_ids=("call",))
    source.publish_newer_urgency(sequence=1)
    policy = ToolYieldPolicy(
        cancellations=(ToolCancellationRegistrationDAO(tool=cancellable_tool, port=Port()),),
        acknowledgement_seconds=0.005,
    )
    task = asyncio.create_task(coro=invoke())
    try:
        await entered.wait()
        invocation = ToolInvocationDAO(tool=cancellable_tool, tool_call_id="call", task=task)
        if ack_kind in ("wrong", "success", "exception"):
            with pytest.raises(UnsettledToolGroupError):
                await policy.cancel_and_join(invocation=invocation, control=control)
        else:
            result = await policy.cancel_and_join(invocation=invocation, control=control)
            assert result.disposition == ("completed" if ack_kind == "normal" else "cancelled")
            assert result.result is not None
            assert result.result.tool_call_id == "call"
            again = await policy.cancel_and_join(invocation=invocation, control=control)
            assert again == result
        assert calls == [task]
        assert task.done()
        assert bool(notices) == (ack_kind in ("wrong", "success", "exception", "late"))
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_capability_matches_original_identity_and_rejects_duplicates() -> None:
    """A same-name copy inherits no capability; duplicate identity fails closed."""
    from src.agents.slo_agent.tool_execution.dao import ToolCancellationRegistrationDAO
    from src.agents.slo_agent.tool_execution.yield_policy import ToolYieldPolicy, ToolYieldCapabilityError

    class Port:
        async def cancel_and_join(self, *, invocation: object) -> ToolMessage:
            """Unused explicit test port."""
            raise AssertionError("must not run")

    registration = ToolCancellationRegistrationDAO(tool=cancellable_tool, port=Port())
    policy = ToolYieldPolicy(cancellations=(registration,))
    assert policy.mode_for(tool=cancellable_tool) == "cancel_confirmed"
    assert policy.mode_for(tool=cancellable_tool.model_copy()) == "defer"
    with pytest.raises(ToolYieldCapabilityError, match="tool_yield_capability_invalid"):
        ToolYieldPolicy(cancellations=(registration, registration))


async def test_presentation_retirement_retains_suppressing_callback() -> None:
    """Overflow seals one mailbox but close still joins the actual suppressing callback."""
    from src.agents.slo_agent.sessions.presentation import PresentationMailbox
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    entered = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()

    async def observer(event: AgentStreamEventDAO) -> None:
        """Suppress cancellation until an explicit test-owned leaf gate releases."""
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()

    mailbox = PresentationMailbox(handler=observer)
    owner = None
    try:
        mailbox.publish(event=AgentStreamEventDAO(kind="text_delta", content="first"))
        await entered.wait()
        for _ in range(257):
            mailbox.publish(event=AgentStreamEventDAO(kind="text_delta", content="queued"))
        await cancelled.wait()
        assert mailbox.diagnostic == "presentation_replay_gap"
        owner = asyncio.create_task(coro=mailbox.join())
        await asyncio.sleep(delay=0)
        assert not owner.done()
        release.set()
        await owner
    finally:
        release.set()
        await mailbox.join()
        if owner is not None:
            await asyncio.gather(owner, return_exceptions=True)


async def test_concurrent_urgency_joins_all_started_tasks_in_source_order() -> None:
    """Registered concurrent work still defers; urgency cannot cancel siblings or lose results."""
    from src.agents.slo_agent.tool_execution.executors import ConcurrentToolExecutor
    from src.agents.slo_agent.tool_execution.dao import (
        ToolCallEnvelopeDAO,
        ToolConcurrencyClass,
        ToolExecutionPlanDAO,
        ToolCancellationRegistrationDAO,
    )
    from src.agents.slo_agent.tool_execution.yield_policy import ToolYieldPolicy, ToolExecutionControl

    entered: set[str] = set()
    release = asyncio.Event()
    starts = asyncio.Event()

    @tool
    async def read_owned(label: str) -> str:
        """Hold actual read work until both registered invocations have started."""
        entered.add(label)
        if len(entered) == 2:
            starts.set()
        await release.wait()
        return label

    class Port:
        async def cancel_and_join(self, *, invocation: object) -> ToolMessage:
            """Concurrent executor must never invoke this cancellation port."""
            raise AssertionError("eager concurrent cancellation")

    source = RecordingMessageSource(urgent_high_water=0)
    notices: list[object] = []
    control = ToolExecutionControl(source=source, on_deferred=notices.append)
    control.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
    control.enter_tools(tool_call_ids=("a", "b"))
    policy = ToolYieldPolicy(cancellations=(ToolCancellationRegistrationDAO(tool=read_owned, port=Port()),))
    plan = ToolExecutionPlanDAO(
        run_concurrently=True,
        calls=[
            ToolCallEnvelopeDAO(
                source_index=index,
                call={"id": label, "name": "read_owned", "args": {"label": label}},
                concurrency_class=ToolConcurrencyClass.READ_ONLY,
            )
            for index, label in enumerate(("a", "b"))
        ],
    )
    executor = ConcurrentToolExecutor(tools_by_name={"read_owned": read_owned})
    owner = asyncio.create_task(coro=executor.execute(plan=plan, control=control, policy=policy))
    try:
        await starts.wait()
        source.publish_newer_urgency(sequence=1)
        async with asyncio.timeout(delay=2):
            while not notices:
                await asyncio.sleep(delay=0)
        assert len(notices) == 1 and not owner.done()
        assert getattr(notices[0], "reason") == "concurrent_batch"
        release.set()
        result = await owner
        assert [(item.tool_call_id, item.content, item.status) for item in result] == [
            ("a", "a", "success"),
            ("b", "b", "success"),
        ]
    finally:
        release.set()
        await asyncio.gather(owner, return_exceptions=True)


async def test_presentation_uses_one_worker_not_task_per_event() -> None:
    """The callback executes on the stable worker rather than allocating an event task."""
    from src.agents.slo_agent.sessions.presentation import PresentationMailbox
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    tasks: list[asyncio.Task | None] = []
    delivered = asyncio.Event()

    async def observer(event: AgentStreamEventDAO) -> None:
        """Record public task identity across separate mailbox admissions."""
        tasks.append(asyncio.current_task())
        delivered.set()

    mailbox = PresentationMailbox(handler=observer)
    try:
        for _ in range(2):
            delivered.clear()
            mailbox.publish(event=AgentStreamEventDAO(kind="text_delta", content="next"))
            await delivered.wait()
        assert tasks[0] is tasks[1]
    finally:
        await mailbox.join()


async def test_cancellation_threshold_is_one_monotonic_budget() -> None:
    """Invocation cancellation before the threshold must not restart the five-second budget."""
    from src.agents.slo_agent.tool_execution.dao import ToolInvocationDAO, ToolCancellationRegistrationDAO
    from src.agents.slo_agent.tool_execution.yield_policy import ToolYieldPolicy, ToolExecutionControl

    release = asyncio.Event()
    entered = asyncio.Event()
    notices = asyncio.Event()

    async def invoke() -> ToolMessage:
        """Hold until the port cancels this exact invocation."""
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    class Port:
        async def cancel_and_join(self, *, invocation: ToolInvocationDAO) -> ToolMessage:
            """Join cancellation early but acknowledge only after explicit release."""
            await asyncio.sleep(delay=0.04)
            invocation.task.cancel()
            await asyncio.gather(invocation.task, return_exceptions=True)
            await release.wait()
            return ToolMessage(tool_call_id="call", content="cancelled", status="error")

    source = RecordingMessageSource(urgent_high_water=0)
    control = ToolExecutionControl(source=source, on_deferred=lambda metadata: notices.set())
    control.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
    control.enter_tools(tool_call_ids=("call",))
    source.publish_newer_urgency(sequence=1)
    policy = ToolYieldPolicy(
        cancellations=(ToolCancellationRegistrationDAO(tool=cancellable_tool, port=Port()),),
        acknowledgement_seconds=0.08,
    )
    task = asyncio.create_task(coro=invoke())
    await entered.wait()
    owner = asyncio.create_task(
        coro=policy.cancel_and_join(
            invocation=ToolInvocationDAO(tool=cancellable_tool, tool_call_id="call", task=task),
            control=control,
        )
    )
    try:
        async with asyncio.timeout(delay=0.105):
            await notices.wait()
        assert not owner.done()
    finally:
        release.set()
        await asyncio.gather(owner, task, return_exceptions=True)


async def test_unknown_tool_is_denied_before_lookup_when_urgency_exists() -> None:
    """Every unstarted call, including unknown names, obeys the same final dispatch guard."""
    from src.agents.slo_agent.tool_execution.executors import SequentialToolExecutor
    from src.agents.slo_agent.tool_execution.dao import (
        ToolCallEnvelopeDAO,
        ToolExecutionPlanDAO,
        ToolConcurrencyClass,
    )
    from src.agents.slo_agent.tool_execution.yield_policy import ToolExecutionControl

    source = RecordingMessageSource(urgent_high_water=0)
    control = ToolExecutionControl(source=source, on_deferred=lambda metadata: None)
    control.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
    control.enter_tools(tool_call_ids=("unknown",))
    source.publish_newer_urgency(sequence=1)
    result = await SequentialToolExecutor(tools_by_name={}).execute(
        plan=ToolExecutionPlanDAO(
            run_concurrently=False,
            calls=[
                ToolCallEnvelopeDAO(
                    source_index=0,
                    call={"id": "unknown", "name": "unknown", "args": {}},
                    concurrency_class=ToolConcurrencyClass.MUTATING,
                )
            ],
        ),
        control=control,
    )
    assert result[0].content == "not_started: cooperative yield before dispatch"
    assert result[0].status == "error"


async def test_sealed_source_without_urgency_does_not_defer_started_tool() -> None:
    """A source lifecycle wake is not evidence of newer urgency during tools."""
    from src.agents.slo_agent.tool_execution.yield_policy import ToolExecutionControl

    class SealedSource(RecordingMessageSource):
        async def wait_for_yield(self, *, after_sequence: int) -> None:
            """Simulate an already sealed source returning without a newer sequence."""
            return

    notices: list[object] = []
    control = ToolExecutionControl(source=SealedSource(urgent_high_water=0), on_deferred=notices.append)
    control.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
    control.enter_tools(tool_call_ids=("call",))
    await control.defer(tool_call_id="call")
    assert not notices


async def test_mailbox_registration_is_bounded_across_retirement(tmp_path: object) -> None:
    """Repeated subscribe/unsubscribe cannot accumulate unbounded retained mailbox owners."""
    from pathlib import Path
    from src.agents.slo_agent.sessions.service import SloAgentSession

    async def observer(event: object) -> None:
        """Observe nothing; retirement must still retain finite ownership."""
        return

    from src.agents.slo_agent.sessions.dao import SessionConfigDAO

    root = Path(str(tmp_path))
    session_id = str(uuid4())
    session = SloAgentSession(
        workdir=root,
        session_id=session_id,
        enable_history=False,
        config=SessionConfigDAO(
            workdir=root, history_root=root / "history", session_id=session_id, model_name="gpt-5.4"
        ),
    )
    try:
        await session.start_messaging()
        for _ in range(64):
            session.subscribe(handler=observer)
            session.unsubscribe(handler=observer)
        with pytest.raises(ValueError, match="presentation_capacity_exceeded"):
            session.subscribe(handler=observer)
    finally:
        await session.close_messaging()


async def test_graph_queue_backpressure_is_bounded_and_close_cannot_deadlock() -> None:
    """A full live callback queue backpressures the provider, then close releases ownership."""
    from src.agents.slo_agent.graph.event_stream import GraphStreamCallbacks
    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGenerationChunk

    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=1)
    callbacks = GraphStreamCallbacks(queue=queue)
    agent_run, model_run = uuid4(), uuid4()
    await callbacks.on_chain_start(
        None, {}, run_id=agent_run, name="agent", metadata={"langgraph_node": "agent"}
    )
    await callbacks.on_chat_model_start({}, [[]], run_id=model_run, parent_run_id=agent_run)
    chunk = ChatGenerationChunk(message=AIMessageChunk(content="first"))
    await callbacks.on_llm_new_token("", chunk=chunk, run_id=model_run)
    producer = asyncio.create_task(coro=callbacks.on_llm_new_token("", chunk=chunk, run_id=model_run))
    try:
        await asyncio.sleep(delay=0)
        assert not producer.done() and queue.qsize() == 1
        queue.get_nowait()
        await producer
        assert queue.qsize() == 1
        foreign = uuid4()
        queue.get_nowait()
        await callbacks.on_chat_model_start({}, [[]], run_id=foreign, parent_run_id=uuid4())
        await callbacks.on_llm_new_token("", chunk=chunk, run_id=foreign)
        assert queue.empty()
    finally:
        if not producer.done():
            producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)


async def test_controlled_trace_failure_is_terminal_before_recovery(tmp_path: object) -> None:
    """A trusted trace failure cannot masquerade as a recoverable provider exception."""
    from pathlib import Path
    from src.agents.slo_agent.agent import SloAgent
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.tool_execution.yield_policy import ToolExecutionControl
    from src.agents.slo_agent.history.message_contract_reconciler import CooperativeYieldSettlementError
    from src.agents.slo_agent.messaging.delivery import MessageRunState

    from src.agents.slo_agent.messaging.dao import BoundaryDAO, BoundaryDeliveryDAO

    run = MessageRunState(run_id=str(uuid4()))

    class Source(RecordingMessageSource):
        async def take_one(self, *, boundary: BoundaryDAO) -> BoundaryDeliveryDAO:
            """Return the test's explicit empty cached boundary selection."""
            from src.agents.slo_agent.messaging.dao import BoundaryDeliveryDAO

            run.delivery = BoundaryDeliveryDAO(boundary=boundary, urgent_high_water=0)
            return run.delivery

    source = Source(urgent_high_water=0)
    control = ToolExecutionControl(source=source, on_deferred=lambda metadata: None)
    model = FauxChatModel(responses=[FauxChatModel.assistant_message(content="answer")])
    agent = SloAgent(
        llm=model, tools=[], cwd=str(tmp_path), message_source=source, tool_execution_control=control
    )

    async def history(event: object) -> None:
        """Fail trusted streaming audit, not the external provider."""
        if getattr(event, "kind") == "assistant_delta":
            raise RuntimeError("history unavailable")

    with pytest.raises(CooperativeYieldSettlementError):
        async for _ in agent.invoke(
            query="hello", runtime_handler=history, message_run=run, attempt_turn_id=str(uuid4())
        ):
            pass


async def test_binding_same_control_rejects_policy_replacement(tmp_path: object) -> None:
    """Idempotence means exact control AND policy, not silent capability replacement."""
    from src.agents.slo_agent.agent import SloAgent
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.tool_execution.yield_policy import (
        ToolExecutionControl,
        ToolYieldPolicy,
        ToolYieldCapabilityError,
    )

    source = RecordingMessageSource(urgent_high_water=0)
    control = ToolExecutionControl(source=source, on_deferred=lambda metadata: None)
    original, replacement = ToolYieldPolicy(), ToolYieldPolicy()
    agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[], cwd=str(tmp_path), message_source=source)
    agent.bind_tool_execution(tool_execution_control=control, tool_yield_policy=original)
    agent.bind_tool_execution(tool_execution_control=control, tool_yield_policy=original)
    with pytest.raises(ToolYieldCapabilityError):
        agent.bind_tool_execution(tool_execution_control=control, tool_yield_policy=replacement)
    agent.release_tool_execution(tool_execution_control=control)


async def test_concurrent_interception_joins_before_any_tool_start() -> None:
    """Urgency while one preflight is held denies the entire still-unstarted batch."""
    from src.agents.slo_agent.plugins.dao import BeforeToolCallDecisionDAO, AfterToolResultPatchDAO
    from src.agents.slo_agent.tool_execution.executors import ConcurrentToolExecutor
    from src.agents.slo_agent.tool_execution.dao import (
        ToolCallEnvelopeDAO,
        ToolConcurrencyClass,
        ToolExecutionPlanDAO,
    )
    from src.agents.slo_agent.tool_execution.yield_policy import ToolExecutionControl

    held, release = asyncio.Event(), asyncio.Event()
    effects: list[str] = []

    @tool
    async def read_owned(label: str) -> str:
        """Record any premature tool start as a forbidden effect."""
        effects.append(label)
        return label

    class Interceptor:
        async def run_before_tool_call(
            self, *, tool_name: str, tool_call_id: str, tool_input: dict[str, object]
        ) -> BeforeToolCallDecisionDAO:
            """Hold the second preflight while the first is already eligible."""
            if tool_call_id == "b":
                held.set()
                await release.wait()
            return BeforeToolCallDecisionDAO()

        async def run_after_tool_result(self, **kwargs: object) -> AfterToolResultPatchDAO:
            """Preserve actual results without extra work."""
            return AfterToolResultPatchDAO()

    source = RecordingMessageSource(urgent_high_water=0)
    control = ToolExecutionControl(source=source, on_deferred=lambda _: None)
    control.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
    control.enter_tools(tool_call_ids=("a", "b"))
    plan = ToolExecutionPlanDAO(
        run_concurrently=True,
        calls=[
            ToolCallEnvelopeDAO(
                source_index=index,
                call={"id": label, "name": "read_owned", "args": {"label": label}},
                concurrency_class=ToolConcurrencyClass.READ_ONLY,
            )
            for index, label in enumerate(("a", "b"))
        ],
    )
    executor = ConcurrentToolExecutor(
        tools_by_name={"read_owned": read_owned}, plugin_dispatcher=Interceptor()
    )
    owner = asyncio.create_task(coro=executor.execute(plan=plan, control=control))
    try:
        async with asyncio.timeout(delay=2):
            await held.wait()
        source.publish_newer_urgency(sequence=1)
        release.set()
        results = await owner
        assert not effects
        assert [(result.tool_call_id, result.status) for result in results] == [
            ("a", "error"),
            ("b", "error"),
        ]
        assert all(result.content == "not_started: cooperative yield before dispatch" for result in results)
    finally:
        release.set()
        await asyncio.gather(owner, return_exceptions=True)


@pytest.mark.parametrize(argnames="phase", argvalues=["provider", "tools_without_urgency", "foreign_id"])
async def test_cancellation_capability_requires_active_tools_and_newer_urgency(phase: str) -> None:
    """Direct policy callers cannot bypass the dispatch phase/high-water authority."""
    from src.agents.slo_agent.tool_execution.dao import ToolInvocationDAO, ToolCancellationRegistrationDAO
    from src.agents.slo_agent.tool_execution.yield_policy import (
        ToolYieldPolicy,
        ToolExecutionControl,
        ToolYieldCapabilityError,
    )

    calls: list[str] = []

    async def completed() -> ToolMessage:
        """Return real normal truth without any external work."""
        return ToolMessage(content="actual", tool_call_id="call")

    class Port:
        async def cancel_and_join(self, *, invocation: ToolInvocationDAO) -> ToolMessage:
            """Record forbidden authority escalation."""
            calls.append("called")
            return ToolMessage(content="cancelled", tool_call_id=invocation.tool_call_id, status="error")

    source = RecordingMessageSource(urgent_high_water=0)
    control = ToolExecutionControl(source=source, on_deferred=lambda _: None)
    control.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
    if phase != "provider":
        control.enter_tools(tool_call_ids=("call",))
    if phase != "tools_without_urgency":
        source.publish_newer_urgency(sequence=1)
    policy = ToolYieldPolicy(
        cancellations=(ToolCancellationRegistrationDAO(tool=cancellable_tool, port=Port()),)
    )
    task = asyncio.create_task(coro=completed())
    try:
        with pytest.raises(ToolYieldCapabilityError):
            await policy.cancel_and_join(
                invocation=ToolInvocationDAO(
                    tool=cancellable_tool,
                    tool_call_id="foreign" if phase == "foreign_id" else "call",
                    task=task,
                ),
                control=control,
            )
        assert not calls
    finally:
        await asyncio.gather(task, return_exceptions=True)


def test_capability_failure_is_terminal_settlement_family() -> None:
    """Every generic retry/recovery planner must see the fixed terminal classification."""
    from src.agents.slo_agent.tool_execution.yield_policy import ToolYieldCapabilityError
    from src.agents.slo_agent.history.message_contract_reconciler import is_settlement_failure

    assert is_settlement_failure(exc=ToolYieldCapabilityError())


async def test_unsubscribe_join_retains_exact_suppressing_observer(tmp_path: object) -> None:
    """Sync unsubscribe seals immediately; explicit retirement join cannot finish early."""
    from pathlib import Path
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def observer(event: AgentStreamEventDAO) -> None:
        """Retain a real callback leaf after retirement cancellation."""
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()

    session = SloAgentSession(
        session_id=str(uuid4()),
        workdir=Path(str(tmp_path)),
        config=SessionConfigDAO(workdir=Path(str(tmp_path)), model_name="gpt-5.4"),
        enable_history=False,
    )
    session.subscribe(handler=observer)
    owner = None
    try:
        await session.start_messaging()
        await session.event_relay(AgentStreamEventDAO(kind="text_delta", content="audit"))
        await entered.wait()
        session.unsubscribe(handler=observer)
        await cancelled.wait()
        owner = asyncio.create_task(coro=session.join_unsubscribed(handler=observer))
        await asyncio.sleep(delay=0)
        assert not owner.done()
        release.set()
        await owner
    finally:
        release.set()
        if owner is not None:
            await asyncio.gather(owner, return_exceptions=True)
        await session.close_messaging()


async def test_graph_transport_bounds_bytes_without_losing_large_chunk_truth() -> None:
    """A single large provider chunk backpressures safely rather than dropping completion."""
    from src.agents.slo_agent.graph.event_stream import GraphEventQueue

    queue = GraphEventQueue(maxsize=256, max_bytes=1024)
    first = ("messages", "a" * 700)
    second = ("messages", "b" * 700)
    await queue.put(first)
    producer = asyncio.create_task(coro=queue.put(second))
    try:
        await asyncio.sleep(delay=0)
        assert not producer.done()
        assert await queue.get() == first
        await producer
        assert await queue.get() == second
        large = ("messages", "x" * 2048)
        await queue.put(large)
        producer = asyncio.create_task(coro=queue.put(first))
        await asyncio.sleep(delay=0)
        assert not producer.done()
        assert await queue.get() == large
        await producer
        assert await queue.get() == first
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)


async def test_graph_callback_accepts_nested_agent_model_lineage_only() -> None:
    """Pooled/bound model descendants keep structured thinking, foreign tools do not."""
    from src.agents.slo_agent.graph.event_stream import GraphStreamCallbacks
    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGenerationChunk

    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=8)
    callbacks = GraphStreamCallbacks(queue=queue)
    agent, binding, model = uuid4(), uuid4(), uuid4()
    await callbacks.on_chain_start(None, {}, run_id=agent, name="agent", metadata={"langgraph_node": "agent"})
    await callbacks.on_chain_start(None, {}, run_id=binding, parent_run_id=agent, name="binding")
    await callbacks.on_chat_model_start({}, [[]], run_id=model, parent_run_id=binding)
    chunk = AIMessageChunk(content=[{"type": "thinking", "thinking": "live thought"}])
    await callbacks.on_llm_new_token("", chunk=ChatGenerationChunk(message=chunk), run_id=model)
    assert queue.get_nowait() == ("messages", (chunk, {}))
    foreign = uuid4()
    await callbacks.on_chat_model_start({}, [[]], run_id=foreign, parent_run_id=uuid4())
    await callbacks.on_llm_new_token("", chunk=ChatGenerationChunk(message=chunk), run_id=foreign)
    assert queue.empty()


async def test_policy_release_run_prunes_joined_invocation_ownership() -> None:
    """Run retirement releases exact tasks only after ports and invocations joined."""
    from src.agents.slo_agent.tool_execution.dao import ToolInvocationDAO, ToolCancellationRegistrationDAO
    from src.agents.slo_agent.tool_execution.yield_policy import (
        ToolYieldPolicy,
        ToolExecutionControl,
        ToolYieldCapabilityError,
    )
    import weakref
    import gc

    calls: list[str] = []

    class Port:
        async def cancel_and_join(self, *, invocation: ToolInvocationDAO) -> ToolMessage:
            """Completed actual work wins without invoking this port."""
            calls.append("unexpected")
            return ToolMessage(content="cancelled", tool_call_id="call", status="error")

    async def actual() -> ToolMessage:
        """Produce terminal truth on an exact owned task."""
        return ToolMessage(content="actual", tool_call_id="call")

    source = RecordingMessageSource(urgent_high_water=0)
    control = ToolExecutionControl(source=source, on_deferred=lambda _: None)
    control.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
    control.enter_tools(tool_call_ids=("call",))
    source.publish_newer_urgency(sequence=1)
    policy = ToolYieldPolicy(
        cancellations=(ToolCancellationRegistrationDAO(tool=cancellable_tool, port=Port()),)
    )
    task = asyncio.create_task(coro=actual())
    await task
    reference = weakref.ref(task)
    await policy.cancel_and_join(
        invocation=ToolInvocationDAO(tool=cancellable_tool, tool_call_id="call", task=task), control=control
    )
    control.enter_settling()
    control.settle_attempt()
    control.close()
    policy.release_run(control=control)
    del task
    await asyncio.sleep(delay=0)
    gc.collect()
    assert reference() is None
    assert not calls


@pytest.mark.parametrize(argnames="ack_kind", argvalues=["unfinished", "naked"])
async def test_unproven_cancellation_joins_port_and_invocation(ack_kind: str) -> None:
    """An early error ack or naked cancellation cannot bypass actual termination."""
    from src.agents.slo_agent.tool_execution.dao import ToolInvocationDAO, ToolCancellationRegistrationDAO
    from src.agents.slo_agent.tool_execution.yield_policy import ToolYieldPolicy, ToolExecutionControl
    from src.agents.slo_agent.history.message_contract_reconciler import UnsettledToolGroupError

    entered, port_called, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def invoke() -> ToolMessage:
        """Retain actual invocation work past an early callback reply."""
        entered.set()
        await release.wait()
        return ToolMessage(content="actual", tool_call_id="call")

    class Port:
        async def cancel_and_join(self, *, invocation: ToolInvocationDAO) -> ToolMessage:
            """Either acknowledge too early or expose naked cancellation."""
            port_called.set()
            if ack_kind == "naked":
                invocation.task.cancel()
                await asyncio.gather(invocation.task, return_exceptions=True)
                raise asyncio.CancelledError()
            return ToolMessage(content="unproven", tool_call_id="call", status="error")

    source = RecordingMessageSource(urgent_high_water=0)
    control = ToolExecutionControl(source=source, on_deferred=lambda _: None)
    control.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
    control.enter_tools(tool_call_ids=("call",))
    source.publish_newer_urgency(sequence=1)
    policy = ToolYieldPolicy(
        cancellations=(ToolCancellationRegistrationDAO(tool=cancellable_tool, port=Port()),)
    )
    task = asyncio.create_task(coro=invoke())
    owner = None
    try:
        await entered.wait()
        owner = asyncio.create_task(
            coro=policy.cancel_and_join(
                invocation=ToolInvocationDAO(tool=cancellable_tool, tool_call_id="call", task=task),
                control=control,
            )
        )
        await port_called.wait()
        if ack_kind == "unfinished":
            await asyncio.sleep(delay=0)
            assert not owner.done()
            release.set()
            outcome = await owner
            assert outcome.disposition == "completed" and outcome.result is not None
            assert outcome.result.content == "actual"
        else:
            with pytest.raises(UnsettledToolGroupError):
                await owner
    finally:
        release.set()
        await asyncio.gather(task, *([owner] if owner is not None else []), return_exceptions=True)


@pytest.mark.parametrize(argnames="boundary", argvalues=["session", "headless", "candidate"])
async def test_nonmessaging_owner_close_joins_presentation_before_reporting(
    tmp_path: Path, boundary: str
) -> None:
    """Every final owner joins observers even when messaging never activated."""
    from pathlib import Path
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO
    from src.cli.headless import HeadlessRunner

    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def observer(event: AgentStreamEventDAO) -> None:
        """Keep the exact callback alive through the owner's cancellation request."""
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()

    session = SloAgentSession(
        session_id=str(uuid4()),
        workdir=Path(str(tmp_path)),
        config=SessionConfigDAO(workdir=Path(str(tmp_path)), model_name="gpt-5.4"),
        enable_history=False,
    )

    async def relay_audit() -> None:
        """Await the public Awaitable relay in the test-owned task coroutine."""
        await session.event_relay(AgentStreamEventDAO(kind="text_delta", content="audit"))

    session.subscribe(handler=observer)

    async def close_owner() -> None:
        """Exercise the selected real final owner without activating messaging."""
        if boundary == "candidate":
            await session.dispose_unmounted_session()
            return
        if boundary == "headless":
            runner = HeadlessRunner(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
            runner._session = session
            await runner._close_messaging()
            return
        await session.close_messaging()

    owner: asyncio.Task[None] | None = None
    delivery: asyncio.Task[None] | None = None
    try:
        delivery = asyncio.create_task(coro=relay_audit())
        await entered.wait()
        assert not delivery.done()
        owner = asyncio.create_task(coro=close_owner())
        await asyncio.sleep(delay=0)
        await asyncio.sleep(delay=0)
        assert not owner.done()
        async with asyncio.timeout(delay=2):
            await cancelled.wait()
        owner.cancel()
        await asyncio.sleep(delay=0)
        assert not owner.done()
        release.set()
        await asyncio.gather(owner, return_exceptions=True)
    finally:
        release.set()
        await asyncio.gather(
            *(task for task in (owner, delivery) if task is not None), return_exceptions=True
        )
        await session.close_messaging()


@pytest.mark.parametrize(argnames="messaging", argvalues=[False, True])
async def test_reporting_only_close_preserves_presentation_delivery(tmp_path: Path, messaging: bool) -> None:
    """Integration cutoff leaves the same optional subscriber usable until final close."""
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    observed: list[str] = []
    delivered = asyncio.Event()

    async def observer(event: AgentStreamEventDAO) -> None:
        """Acknowledge delivery after reporting has already drained."""
        observed.append(event.delta or "")
        delivered.set()

    session = SloAgentSession(
        session_id=str(uuid4()),
        workdir=tmp_path,
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"),
        enable_history=False,
    )
    session.subscribe(handler=observer)
    try:
        if messaging:
            await session.start_messaging()
        outcome = await session.close_external_reporting()
        assert outcome.resources == "drained"
        assert observer in session._subscribers
        await session.event_relay(AgentStreamEventDAO(kind="text_delta", delta="still open"))
        async with asyncio.timeout(delay=2):
            await delivered.wait()
        assert observed == ["still open"]
    finally:
        await session.close_messaging()
    assert observer not in session._subscribers
    await session.event_relay(AgentStreamEventDAO(kind="text_delta", delta="after final close"))
    assert observed == ["still open"]


async def test_policy_repeated_abort_joins_invocation_and_callback() -> None:
    """Repeated caller cancellation cannot abandon either retained cancellation handle."""
    from src.agents.slo_agent.tool_execution.dao import ToolInvocationDAO, ToolCancellationRegistrationDAO
    from src.agents.slo_agent.tool_execution.yield_policy import ToolYieldPolicy, ToolExecutionControl

    invoked, callback_entered, release_tool, release_port = (asyncio.Event() for _ in range(4))

    async def invoke() -> ToolMessage:
        """Keep actual tool work held independently from cancellation acknowledgement."""
        invoked.set()
        await release_tool.wait()
        return ToolMessage(content="actual", tool_call_id="call")

    class Port:
        async def cancel_and_join(self, *, invocation: ToolInvocationDAO) -> ToolMessage:
            """A threshold does not cancel either this callback or actual work."""
            callback_entered.set()
            await release_port.wait()
            await invocation.task
            return ToolMessage(content="cancelled", tool_call_id="call", status="error")

    source = RecordingMessageSource(urgent_high_water=0)
    control = ToolExecutionControl(source=source, on_deferred=lambda _: None)
    control.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
    control.enter_tools(tool_call_ids=("call",))
    source.publish_newer_urgency(sequence=1)
    policy = ToolYieldPolicy(
        cancellations=(ToolCancellationRegistrationDAO(tool=cancellable_tool, port=Port()),)
    )
    task = asyncio.create_task(coro=invoke())
    owner = None
    try:
        await invoked.wait()
        owner = asyncio.create_task(
            coro=policy.cancel_and_join(
                invocation=ToolInvocationDAO(tool=cancellable_tool, tool_call_id="call", task=task),
                control=control,
            )
        )
        await callback_entered.wait()
        owner.cancel()
        await asyncio.sleep(delay=0)
        owner.cancel()
        await asyncio.sleep(delay=0)
        assert not owner.done() and not task.done()
        release_tool.set()
        await task
        await asyncio.sleep(delay=0)
        assert not owner.done()
        release_port.set()
        result = await asyncio.gather(owner, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
    finally:
        release_tool.set()
        release_port.set()
        await asyncio.gather(task, *([owner] if owner is not None else []), return_exceptions=True)


async def test_plugin_reload_joins_retiring_dispatcher_before_replacement(tmp_path: object) -> None:
    """Reload cannot lose the callback owner or retain the old dispatcher mailbox."""
    from pathlib import Path
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    root = Path(str(tmp_path))
    plugin = root / "held_plugin.py"
    assert plugin.resolve().is_relative_to(root.resolve())
    plugin.write_text(
        data="""import asyncio
entered = asyncio.Event()
cancelled = asyncio.Event()
release = asyncio.Event()
async def observe(event):
    entered.set()
    try:
        await release.wait()
    except asyncio.CancelledError:
        cancelled.set()
        await release.wait()
def register(slo):
    slo.on(event_kind="text_delta", handler=observe)
""",
        encoding="utf-8",
    )
    session = SloAgentSession(
        session_id=str(uuid4()),
        workdir=root,
        config=SessionConfigDAO(workdir=root, model_name="gpt-5.4"),
        enable_history=False,
        plugin_paths=[plugin],
        plugin_loader_kwargs={"managed_root": root / "managed", "trust_store_path": root / "trust.json"},
    )
    import sys

    modules = [module for module in sys.modules.values() if getattr(module, "__file__", None) == str(plugin)]
    assert len(modules) == 1
    loaded = modules[0]
    owner = None
    try:
        await session.start_messaging()
        await session.event_relay(AgentStreamEventDAO(kind="text_delta", content="audit"))
        await loaded.entered.wait()
        owner = asyncio.create_task(coro=session.reload_plugins())
        await asyncio.sleep(delay=0)
        await asyncio.sleep(delay=0)
        assert not owner.done()
        async with asyncio.timeout(delay=2):
            await loaded.cancelled.wait()
        loaded.release.set()
        await owner
    finally:
        loaded.release.set()
        if owner is not None:
            await asyncio.gather(owner, return_exceptions=True)
        await session.close_messaging()


async def test_bound_method_unsubscribe_retires_the_registered_callback(tmp_path: object) -> None:
    """Repeated bound-method lookup must identify the same subscriber owner."""
    from pathlib import Path
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Observer:
        async def observe(self, event: AgentStreamEventDAO) -> None:
            """Expose retirement cancellation while retaining exact leaf ownership."""
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()

    observer = Observer()
    session = SloAgentSession(
        session_id=str(uuid4()),
        workdir=Path(str(tmp_path)),
        config=SessionConfigDAO(workdir=Path(str(tmp_path)), model_name="gpt-5.4"),
        enable_history=False,
    )
    session.subscribe(handler=observer.observe)
    owner = None
    try:
        await session.start_messaging()
        await session.event_relay(AgentStreamEventDAO(kind="text_delta", content="audit"))
        await entered.wait()
        session.unsubscribe(handler=observer.observe)
        async with asyncio.timeout(delay=0.1):
            await cancelled.wait()
        owner = asyncio.create_task(coro=session.join_unsubscribed(handler=observer.observe))
        await asyncio.sleep(delay=0)
        assert not owner.done()
        release.set()
        await owner
    finally:
        release.set()
        if owner is not None:
            await asyncio.gather(owner, return_exceptions=True)
        await session.close_messaging()


@pytest.mark.parametrize(argnames="failure", argvalues=["bytes", "exception", "budget"])
async def test_observer_retirement_failure_is_once_and_joined(failure: str) -> None:
    """Byte overflow, callback error and real one-second expiry retire only one worker."""
    from src.agents.slo_agent.sessions.presentation import PresentationMailbox
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls: list[object] = []

    async def observer(event: AgentStreamEventDAO) -> None:
        """Expose the actual callback failure/budget lifetime without replacement work."""
        calls.append(asyncio.current_task())
        entered.set()
        if failure == "exception":
            raise RuntimeError("private details")
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()

    mailbox = PresentationMailbox(handler=observer)
    owner = None
    try:
        mailbox.publish(event=AgentStreamEventDAO(kind="text_delta", content="first"))
        await entered.wait()
        if failure == "bytes":
            mailbox.publish(event=AgentStreamEventDAO(kind="text_delta", content="x" * (1024 * 1024)))
        if failure != "exception":
            async with asyncio.timeout(delay=2):
                await cancelled.wait()
        await asyncio.sleep(delay=0)
        assert mailbox.diagnostic == "presentation_replay_gap"
        mailbox.publish(event=AgentStreamEventDAO(kind="text_delta", content="must not run"))
        owner = asyncio.create_task(coro=mailbox.join())
        await asyncio.sleep(delay=0)
        if failure != "exception":
            assert not owner.done()
            owner.cancel()
            await asyncio.sleep(delay=0)
            owner.cancel()
            assert not owner.done()
        release.set()
        await owner
        assert len(calls) == 1 and mailbox.is_joined()
    finally:
        release.set()
        await mailbox.join()
        if owner is not None:
            await asyncio.gather(owner, return_exceptions=True)


async def test_cancellation_post_result_plugin_remains_part_of_exact_invocation() -> None:
    """An opt-in port cannot bypass a cancellation-suppressing result plugin."""
    from src.agents.slo_agent.plugins.dao import BeforeToolCallDecisionDAO, AfterToolResultPatchDAO
    from src.agents.slo_agent.tool_execution.dao import (
        ToolCallEnvelopeDAO,
        ToolConcurrencyClass,
        ToolExecutionPlanDAO,
        ToolInvocationDAO,
        ToolCancellationRegistrationDAO,
    )
    from src.agents.slo_agent.tool_execution.executors import SequentialToolExecutor
    from src.agents.slo_agent.tool_execution.yield_policy import ToolYieldPolicy, ToolExecutionControl

    entered, cancelled, release, port_joined = (asyncio.Event() for _ in range(4))
    actual_tasks: list[object] = []
    callback_tasks: list[object] = []

    @tool
    async def actual_tool() -> str:
        """Record the exact task that owns both tool and plugin."""
        return "actual"

    class Interceptor:
        async def run_before_tool_call(self, **kwargs: object) -> BeforeToolCallDecisionDAO:
            """Allow the actual invocation."""
            return BeforeToolCallDecisionDAO()

        async def run_after_tool_result(self, **kwargs: object) -> AfterToolResultPatchDAO:
            """Retain the plugin leaf until released, including after cancellation."""
            actual_tasks.append(asyncio.current_task())
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
            return AfterToolResultPatchDAO()

    class Port:
        async def cancel_and_join(self, *, invocation: ToolInvocationDAO) -> ToolMessage:
            """Join exactly the task running the original tool and post-result plugin."""
            callback_tasks.append(invocation.task)
            invocation.task.cancel()
            await asyncio.gather(invocation.task, return_exceptions=True)
            port_joined.set()
            return ToolMessage(content="cancelled", tool_call_id="call", status="error")

    source = RecordingMessageSource(urgent_high_water=0)
    control = ToolExecutionControl(source=source, on_deferred=lambda _: None)
    control.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
    control.enter_tools(tool_call_ids=("call",))
    policy = ToolYieldPolicy(cancellations=(ToolCancellationRegistrationDAO(tool=actual_tool, port=Port()),))
    executor = SequentialToolExecutor(
        tools_by_name={"actual_tool": actual_tool}, plugin_dispatcher=Interceptor()
    )
    plan = ToolExecutionPlanDAO(
        run_concurrently=False,
        calls=[
            ToolCallEnvelopeDAO(
                source_index=0,
                call={"id": "call", "name": "actual_tool", "args": {}},
                concurrency_class=ToolConcurrencyClass.MUTATING,
            )
        ],
    )
    owner = asyncio.create_task(coro=executor.execute(plan=plan, control=control, policy=policy))
    try:
        await entered.wait()
        source.publish_newer_urgency(sequence=1)
        await cancelled.wait()
        assert not owner.done() and not port_joined.is_set()
        assert callback_tasks == actual_tasks
        release.set()
        results = await owner
        assert [(item.status, item.content) for item in results] == [("success", "actual")]
        assert port_joined.is_set()
    finally:
        release.set()
        await asyncio.gather(owner, return_exceptions=True)


async def test_concurrent_preflight_failure_joins_every_sibling_before_propagation() -> None:
    """A failed decision cannot strand a held sibling or start already-approved work."""
    from src.agents.slo_agent.plugins.dao import BeforeToolCallDecisionDAO
    from src.agents.slo_agent.tool_execution.dao import (
        ToolCallEnvelopeDAO,
        ToolConcurrencyClass,
        ToolExecutionPlanDAO,
    )
    from src.agents.slo_agent.tool_execution.executors import ConcurrentToolExecutor

    held, release = asyncio.Event(), asyncio.Event()
    effects: list[str] = []

    @tool
    async def read_owned() -> str:
        """Record any forbidden invocation before the whole preflight settles."""
        effects.append("started")
        return "actual"

    class Interceptor:
        async def run_before_tool_call(
            self, *, tool_name: str, tool_call_id: str, tool_input: dict[str, object]
        ) -> BeforeToolCallDecisionDAO:
            """Fail one decision while keeping its sibling explicitly owned."""
            if tool_call_id == "a":
                raise RuntimeError("decision failed")
            held.set()
            await release.wait()
            return BeforeToolCallDecisionDAO()

        async def run_after_tool_result(self, **kwargs: object) -> "AfterToolResultPatchDAO":
            """No result exists when preflight fails; satisfy the typed interceptor seam."""
            from src.agents.slo_agent.plugins.dao import AfterToolResultPatchDAO

            return AfterToolResultPatchDAO()

    plan = ToolExecutionPlanDAO(
        run_concurrently=True,
        calls=[
            ToolCallEnvelopeDAO(
                source_index=index,
                call={"id": label, "name": "read_owned", "args": {}},
                concurrency_class=ToolConcurrencyClass.READ_ONLY,
            )
            for index, label in enumerate(("a", "b"))
        ],
    )
    executor = ConcurrentToolExecutor(
        tools_by_name={"read_owned": read_owned}, plugin_dispatcher=Interceptor()
    )
    owner = asyncio.create_task(coro=executor.execute(plan=plan))
    try:
        await held.wait()
        assert not owner.done() and not effects
        release.set()
        with pytest.raises(RuntimeError, match="decision failed"):
            await owner
        assert not effects
    finally:
        release.set()
        await asyncio.gather(owner, return_exceptions=True)


async def test_closed_run_cannot_reinvoke_port_after_policy_pruning() -> None:
    """Pruning strong task ownership does not permit a second callback on retired control."""
    from src.agents.slo_agent.tool_execution.dao import ToolInvocationDAO, ToolCancellationRegistrationDAO
    from src.agents.slo_agent.tool_execution.yield_policy import (
        ToolYieldPolicy,
        ToolExecutionControl,
        ToolYieldCapabilityError,
    )

    calls: list[object] = []

    class Port:
        async def cancel_and_join(self, *, invocation: ToolInvocationDAO) -> ToolMessage:
            """Join actual cancellation once for the exact invocation."""
            calls.append(invocation.task)
            invocation.task.cancel()
            await asyncio.gather(invocation.task, return_exceptions=True)
            return ToolMessage(content="cancelled", tool_call_id="call", status="error")

    async def invoke() -> ToolMessage:
        """Keep invocation incomplete until the port joins it."""
        await asyncio.Event().wait()
        return ToolMessage(content="unreachable", tool_call_id="call")

    source = RecordingMessageSource(urgent_high_water=0)
    control = ToolExecutionControl(source=source, on_deferred=lambda _: None)
    control.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
    control.enter_tools(tool_call_ids=("call",))
    source.publish_newer_urgency(sequence=1)
    task = asyncio.create_task(coro=invoke())
    invocation = ToolInvocationDAO(tool=cancellable_tool, tool_call_id="call", task=task)
    policy = ToolYieldPolicy(
        cancellations=(ToolCancellationRegistrationDAO(tool=cancellable_tool, port=Port()),)
    )
    try:
        await policy.cancel_and_join(invocation=invocation, control=control)
        control.enter_settling()
        control.settle_attempt()
        control.close()
        policy.release_run(control=control)
        with pytest.raises(ToolYieldCapabilityError):
            await policy.cancel_and_join(invocation=invocation, control=control)
        replacement = ToolExecutionControl(source=source, on_deferred=lambda _: None)
        replacement.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
        replacement.enter_tools(tool_call_ids=("call",))
        with pytest.raises(ToolYieldCapabilityError):
            await policy.cancel_and_join(invocation=invocation, control=replacement)
        assert calls == [task]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_early_ack_cannot_become_valid_after_unrelated_naked_cancel() -> None:
    """An ack returned before task join never gains authority from later naked cancellation."""
    from src.agents.slo_agent.tool_execution.dao import ToolInvocationDAO, ToolCancellationRegistrationDAO
    from src.agents.slo_agent.tool_execution.yield_policy import ToolYieldPolicy, ToolExecutionControl
    from src.agents.slo_agent.history.message_contract_reconciler import UnsettledToolGroupError

    entered, ack_returned, deferred = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def invoke() -> ToolMessage:
        """Remain active after the dishonest callback returns."""
        entered.set()
        await asyncio.Event().wait()
        return ToolMessage(content="unreachable", tool_call_id="call")

    class Port:
        async def cancel_and_join(self, *, invocation: ToolInvocationDAO) -> ToolMessage:
            """Return an invalid ack without joining the actual invocation."""
            ack_returned.set()
            return ToolMessage(content="unproven", tool_call_id="call", status="error")

    source = RecordingMessageSource(urgent_high_water=0)
    control = ToolExecutionControl(source=source, on_deferred=lambda _: deferred.set())
    control.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
    control.enter_tools(tool_call_ids=("call",))
    source.publish_newer_urgency(sequence=1)
    policy = ToolYieldPolicy(
        cancellations=(ToolCancellationRegistrationDAO(tool=cancellable_tool, port=Port()),)
    )
    task = asyncio.create_task(coro=invoke())
    owner = None
    try:
        await entered.wait()
        owner = asyncio.create_task(
            coro=policy.cancel_and_join(
                invocation=ToolInvocationDAO(tool=cancellable_tool, tool_call_id="call", task=task),
                control=control,
            )
        )
        await ack_returned.wait()
        await deferred.wait()
        task.cancel()
        with pytest.raises(UnsettledToolGroupError):
            await owner
    finally:
        task.cancel()
        await asyncio.gather(task, *([owner] if owner is not None else []), return_exceptions=True)


async def test_cancellation_rejects_task_owned_by_another_loop() -> None:
    """A trusted tool object alone grants no authority over a foreign invocation task."""
    from src.agents.slo_agent.tool_execution.dao import ToolInvocationDAO, ToolCancellationRegistrationDAO
    from src.agents.slo_agent.tool_execution.yield_policy import (
        ToolYieldPolicy,
        ToolExecutionControl,
        ToolYieldCapabilityError,
    )

    async def actual() -> ToolMessage:
        """Finish on the explicitly separate test loop before handing over its task."""
        return ToolMessage(content="actual", tool_call_id="call")

    def foreign_task() -> asyncio.Task[ToolMessage]:
        """Create and join only the test-owned foreign loop, then close it."""
        loop = asyncio.new_event_loop()
        try:
            task = loop.create_task(coro=actual())
            loop.run_until_complete(task)
            return task
        finally:
            loop.close()

    class Port:
        async def cancel_and_join(self, *, invocation: ToolInvocationDAO) -> ToolMessage:
            """Foreign-loop validation must refuse before this callback starts."""
            raise AssertionError("foreign invocation")

    task = await asyncio.to_thread(foreign_task)
    source = RecordingMessageSource(urgent_high_water=0)
    control = ToolExecutionControl(source=source, on_deferred=lambda _: None)
    control.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
    control.enter_tools(tool_call_ids=("call",))
    source.publish_newer_urgency(sequence=1)
    policy = ToolYieldPolicy(
        cancellations=(ToolCancellationRegistrationDAO(tool=cancellable_tool, port=Port()),)
    )
    with pytest.raises(ToolYieldCapabilityError):
        await policy.cancel_and_join(
            invocation=ToolInvocationDAO(tool=cancellable_tool, tool_call_id="call", task=task),
            control=control,
        )


async def test_concurrent_all_tasks_registered_before_first_tool_body() -> None:
    """A whole eligible batch is registered in one no-await start window."""
    from src.agents.slo_agent.tool_execution.dao import (
        ToolCallEnvelopeDAO,
        ToolConcurrencyClass,
        ToolExecutionPlanDAO,
    )
    from src.agents.slo_agent.tool_execution.executors import ConcurrentToolExecutor

    observed: list[int] = []

    @tool
    async def read_owned() -> str:
        """Inspect the exact invocation-message tasks when the first body can run."""
        observed.append(
            sum(
                getattr(task.get_coro(), "__qualname__", "") == "ToolExecutor._invoke_message"
                for task in asyncio.all_tasks()
            )
        )
        await asyncio.sleep(delay=0)
        return "actual"

    plan = ToolExecutionPlanDAO(
        run_concurrently=True,
        calls=[
            ToolCallEnvelopeDAO(
                source_index=index,
                call={"id": f"call-{index}", "name": "read_owned", "args": {}},
                concurrency_class=ToolConcurrencyClass.READ_ONLY,
            )
            for index in range(3)
        ],
    )
    executor = ConcurrentToolExecutor(tools_by_name={"read_owned": read_owned})
    results = await executor.execute(plan=plan)
    assert observed == [3, 3, 3]
    assert [result.tool_call_id for result in results] == ["call-0", "call-1", "call-2"]


async def test_automatically_failed_session_subscribers_release_strong_references(tmp_path: Path) -> None:
    """Repeated automatic retirement cannot grow handler ownership outside the bounded registry."""
    import gc
    import weakref
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    class FailedObserver:
        async def __call__(self, event: AgentStreamEventDAO) -> None:
            """Retire this best-effort observer on its first publication."""
            raise ValueError("observer failed")

    from src.agents.slo_agent.sessions.dao import SessionConfigDAO

    session = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"),
        enable_history=False,
    )
    references: list[weakref.ReferenceType[FailedObserver]] = []
    try:
        await session.start_messaging()
        for index in range(70):
            observer = FailedObserver()
            references.append(weakref.ref(observer))
            session.subscribe(handler=observer)
            assert isinstance(session._subscribers, tuple)
            assert observer in session._subscribers
            del observer
            await session.event_relay(AgentStreamEventDAO(kind="text_delta", delta="audit", iteration=index))
            # One worker per subscriber; allow callback retirement and task exit.
            for _ in range(3):
                await asyncio.sleep(delay=0)
        gc.collect()
        assert sum(reference() is not None for reference in references) <= 1
    finally:
        await session.close_external_reporting()
        await session.close_messaging()
    gc.collect()
    assert not any(reference() is not None for reference in references)
