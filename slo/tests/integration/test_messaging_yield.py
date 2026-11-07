"""Real local-client urgency must interrupt a provider without releasing its token."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, Optional, Literal
from uuid import uuid4

import pytest
import pytest_asyncio
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import BaseMessage, AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.history.transcript import ReplayEntryProjector
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
from src.agents.slo_agent.messaging.dao import MessageReceiptDAO, MessageSubmissionDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.agents.slo_agent.messaging.test_delivery import RecordingModel, RealAgentFactory
from tests.integration.test_session_messaging import read_closed_message_rows


class InterruptedProvider(RecordingModel):
    """Hold only the first external request; record joined cancellation before retry."""

    cancelled: asyncio.Event = Field(default_factory=asyncio.Event, description="First request joined.")
    resumed: asyncio.Event = Field(
        default_factory=asyncio.Event, description="Next provider request entered."
    )
    cancellation_count: int = Field(default=0, description="Observed cancellation requests.")
    suppress: bool = Field(default=False, description="Return a complete opening after cancellation.")
    partial: bool = Field(default=False, description="Emit visible output before holding the next token.")
    thinking: bool = Field(default=False, description="Emit structured thinking before holding.")

    def __init__(self, *, responses: Sequence[AIMessage]) -> None:
        """Keep the explicit provider-script construction contract under Pydantic."""
        super().__init__(responses=responses)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """The second request cannot arrive until the first request has joined."""
        self.requests.append(list(messages))
        if len(self.requests) == 1:
            if self.partial:
                content: str | list[str | dict[str, Any]] = (
                    [
                        {"type": "thinking", "thinking": "Private plan audit"},
                        {"type": "text", "text": "Partial audit only"},
                    ]
                    if self.thinking
                    else "Partial audit only"
                )
                yield ChatGenerationChunk(message=AIMessageChunk(content=content))
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancellation_count += 1
                if not self.suppress:
                    raise
            finally:
                self.cancelled.set()
        else:
            assert self.cancelled.is_set()
            self.resumed.set()
        async for chunk in FauxChatModel._astream(
            self, messages=messages, stop=stop, run_manager=run_manager, **kwargs
        ):
            yield chunk


@pytest_asyncio.fixture
async def isolated_journey_tasks() -> AsyncIterator[None]:
    """Join leaked handles even when acquisition, assertions or session close fail.

    Pytest gives each test in this module its own function-scoped event loop.
    Snapshot membership is valid only in that isolated loop, never in production.
    The pre-cleanup handles remain a failing assertion, not a cleanup success.
    """
    prior_tasks: set[asyncio.Task] = set(asyncio.all_tasks())
    try:
        yield
    finally:
        pending: list[asyncio.Task] = [
            task
            for task in asyncio.all_tasks()
            if task not in prior_tasks and not task.done() and task is not asyncio.current_task()
        ]
        for task in pending:
            task.cancel()
        joined = asyncio.gather(*pending, return_exceptions=True)
        while not joined.done():
            try:
                await asyncio.shield(joined)
            except asyncio.CancelledError:
                continue
        joined.result()
        assert not pending, f"Session left owned tasks after close (before cleanup): {pending}"


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
@pytest.mark.parametrize(argnames="partial", argvalues=[False, True])
async def test_silent_provider_urgent_delivery(
    tmp_path: Path, tree: bool, partial: bool, isolated_journey_tasks: None
) -> None:
    """Urgency reaches one next boundary and durable receipt without a provider token."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    history = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    session_id: str = str(uuid4())
    model = InterruptedProvider(responses=[FauxChatModel.assistant_message(content="Urgent answer.")])
    model.partial = partial
    model.thinking = partial
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    client: Optional[LocalSessionMessagingClient] = None
    observed: list[Any] = []

    async def capture(event: Any) -> None:
        """Capture emitted metadata without owning execution progress."""
        observed.append(event)

    session.subscribe(handler=capture)
    try:
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        original = MessageSubmissionDAO(
            message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="Original"
        )
        urgent = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text="Urgent",
            priority="urgent",
        )
        assert isinstance(await client.submit(submission=original), MessageReceiptDAO)
        async with asyncio.timeout(delay=5):
            await model.entered.wait()
        if partial:
            async with asyncio.timeout(delay=5):
                while True:
                    live_events = await history.load_events(session_id=session_id)
                    deltas = [event.payload for event in live_events if event.kind == "assistant_delta"]
                    if any(payload.delta == "Partial audit only" for payload in deltas) and any(
                        payload.delta == "Private plan audit" for payload in deltas
                    ):
                        break
                    await asyncio.sleep(delay=0)
        assert isinstance(await client.submit(submission=urgent), MessageReceiptDAO)
        async with asyncio.timeout(delay=3):
            await model.resumed.wait()
        assert not model.release.is_set()
        receipt = await client.get_receipt(message_id=urgent.message_id)
        assert isinstance(receipt, MessageReceiptDAO) and receipt.state == "applied"
        assert model.cancellation_count == 1
        assert len(model.requests) == 2
        assert [message.content for message in model.requests[1] if message.type == "human"] == [
            "Original",
            "Urgent",
        ]
        events = await history.load_events(session_id=session_id)
        interruptions = [
            event
            for event in events
            if event.payload.metadata.get("cooperative_yield_v1", {}).get("disposition") == "interrupted"
        ]
        assert len(interruptions) == 1
        metadata = interruptions[0].payload.metadata["cooperative_yield_v1"]
        assert metadata["disposition"] == "interrupted"
        async with asyncio.timeout(delay=5):
            while not any(event.kind == "iteration_interrupted" for event in observed):
                await asyncio.sleep(delay=0)
        public_interruption = next(event for event in observed if event.kind == "iteration_interrupted")
        assert public_interruption.metadata["cooperative_yield_v1"] == metadata
        requested_notice = next(event for event in observed if event.kind == "yield_requested")
        requested_audit = next(
            event.payload.metadata["cooperative_yield_v1"]
            for event in events
            if event.payload.metadata.get("cooperative_yield_v1", {}).get("disposition") == "requested"
        )
        assert requested_notice.metadata["cooperative_yield_v1"] == requested_audit
        traced = [event for event in events if event.kind in {"assistant_delta", "assistant_message"}]
        assert all(event.payload.metadata.get("attempt_turn_id") == event.turn_id for event in traced)
        assert metadata["boundary_index"] == 0 and metadata["iteration"] == 0
        applications = [event for event in events if "messaging_v1" in event.payload.metadata]
        assert [event.payload.content for event in applications] == ["Original", "Urgent"]
        assert interruptions[0].sequence < applications[1].sequence
        async with asyncio.timeout(delay=5):
            while session.is_running:
                await asyncio.sleep(delay=0)
        events = await history.load_events(session_id=session_id)
        replay = await SessionHistoryProjector.build_message_history(events=events)
        assert all("Partial audit only" not in str(message.content) for message in replay)
        entries = ReplayEntryProjector.build_entries(events=events)
        notices = [entry for entry in entries if entry.content == "Response interrupted for urgent input."]
        assert len(notices) == 1
        assert "Response interrupted for urgent input." in ReplayEntryProjector.render_markdown(events=events)
        if partial:
            interrupted_entries = [entry for entry in entries if getattr(entry, "interrupted", False)]
            assert len(interrupted_entries) == 1
            assert interrupted_entries[0].answer == "Partial audit only"
    finally:
        model.release.set()
        session.abort()

        async def close_owned_session() -> None:
            """Close the session even if the client close fails."""
            try:
                if client is not None:
                    await client.close()
            finally:
                await session.close_messaging()

        cleanup: asyncio.Task[None] = asyncio.create_task(coro=close_owned_session())
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                continue
        cleanup.result()
    rows = read_closed_message_rows(
        database_path=root / session_id / "messaging.v1.sqlite3", temporary_root=tmp_path
    )
    assert rows == ((original.message_id, 0, "applied"), (urgent.message_id, 0, "applied"))


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
@pytest.mark.parametrize(argnames="history_enabled", argvalues=[False, True])
@pytest.mark.parametrize(argnames="tool_opening", argvalues=[False, True])
async def test_suppressed_provider_completion_has_durable_no_start(
    tmp_path: Path, tree: bool, history_enabled: bool, tool_opening: bool, isolated_journey_tasks: None
) -> None:
    """A completed cancellation-race opening is audited but never dispatched or retained."""
    from langchain_core.tools import tool

    starts: list[str] = []

    @tool
    async def forbidden_effect() -> str:
        """Record an effect that a reserved provider response must never start."""
        starts.append("started")
        return "effect"

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    history = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    session_id = str(uuid4())
    opening = AIMessage(
        content="Completed race audit",
        tool_calls=[{"id": "reserved-call", "name": "forbidden_effect", "args": {}}] if tool_opening else [],
        usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
    )
    opening.additional_kwargs["slo_provider_extension"] = {
        "provider": "openai",
        "source_model_name": "gpt-5.4",
        "reasoning_details": [{"private_anchor": "reserved-private-anchor"}],
    }
    model = InterruptedProvider(responses=[opening, AIMessage(content="Urgent answer")])
    model.suppress = True
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        enable_history=history_enabled,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path, tools=[forbidden_effect]),
    )
    client = None
    try:
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        original = MessageSubmissionDAO(
            message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="Original"
        )
        urgent = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text="Urgent",
            priority="urgent",
        )
        await client.submit(submission=original)
        async with asyncio.timeout(delay=5):
            await model.entered.wait()
        await client.submit(submission=urgent)
        async with asyncio.timeout(delay=5):
            await model.resumed.wait()
        async with asyncio.timeout(delay=5):
            while session.is_running:
                await asyncio.sleep(delay=0)
        events = await history.load_events(session_id=session_id)
        marked = [event for event in events if "tool_group_v1" in event.payload.metadata]
        if history_enabled:
            if tool_opening:
                assert [event.kind for event in marked] == ["tool_call", "run_retrying"]
                assert marked[1].payload.metadata["tool_group_v1"]["disposition"] == "not_started"
                assert marked[0].sequence < marked[1].sequence
            else:
                assert not marked
                assert any(
                    event.kind == "assistant_message" and event.payload.content == "Completed race audit"
                    for event in events
                )
            diagnostics = [
                event.payload.metadata["cooperative_yield_v1"]["disposition"]
                for event in events
                if "cooperative_yield_v1" in event.payload.metadata
            ]
            assert diagnostics == ["requested", "interrupted"]
        else:
            assert not marked
        assert not starts
        assert all(
            not isinstance(message, AIMessage) or not message.tool_calls for message in model.requests[1]
        )
        replay = await SessionHistoryProjector.build_message_history(events=events)
        assert all("Completed race audit" not in str(message.content) for message in replay)
        assert "reserved-private-anchor" not in str([message.model_dump() for message in replay])
        assert "reserved-private-anchor" not in str([message.model_dump() for message in model.requests[1]])
        receipt = await client.get_receipt(message_id=urgent.message_id)
        assert isinstance(receipt, MessageReceiptDAO) and receipt.state == "applied"
        assert receipt.durable is history_enabled
        assert session.usage_snapshot().session_totals.total_tokens == 10
    finally:
        model.release.set()
        session.abort()
        try:
            if client is not None:
                await client.close()
        finally:
            await session.close_messaging()


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
@pytest.mark.parametrize(argnames="cancel_confirmed", argvalues=[False, True])
async def test_real_tool_defers_and_denies_remainder(
    tmp_path: Path, tree: bool, cancel_confirmed: bool, isolated_journey_tasks: None
) -> None:
    """Running file work finishes truthfully; newer urgency denies sequential remainder."""
    from langchain_core.messages import ToolMessage
    from langchain_core.tools import tool
    from langchain_core.runnables import RunnableConfig

    entered = asyncio.Event()
    release = asyncio.Event()
    starts: list[str] = []
    live_output = asyncio.Event()
    second_output = asyncio.Event()
    observer_entered = asyncio.Event()
    observer_release = asyncio.Event()

    async def held_observer(event: Any) -> None:
        """Hold optional presentation without gaining execution ownership."""
        if event.kind == "tool_output_update":
            live_output.set()
            if event.content == "still working":
                second_output.set()
        if event.kind == "tool_result":
            observer_entered.set()
            await observer_release.wait()

    effect = tmp_path / "effect.txt"
    assert effect.resolve().is_relative_to(tmp_path.resolve())

    @tool
    async def write_effect(label: str, config: RunnableConfig) -> str:
        """Perform one test-owned file effect after an explicit release gate."""
        starts.append(label)
        entered.set()
        from src.agents.tools.tool_output import ToolOutputUpdateDAO

        callback = config["configurable"]["slo_tool_output_update_callback"]
        await callback(
            snapshot=ToolOutputUpdateDAO(tool_call_id="", tool_name="", content_snapshot="working")
        )
        await live_output.wait()
        live_output.clear()
        await callback(
            snapshot=ToolOutputUpdateDAO(tool_call_id="", tool_name="", content_snapshot="still working")
        )
        await release.wait()
        effect.write_text(data=label, encoding="utf-8")
        return "written:" + label

    from src.agents.slo_agent.tool_execution.dao import ToolCancellationRegistrationDAO, ToolInvocationDAO
    from src.agents.slo_agent.tool_execution.yield_policy import ToolYieldPolicy

    class Port:
        async def cancel_and_join(self, *, invocation: ToolInvocationDAO) -> ToolMessage:
            """Cancel only this pure async test tool and join its actual invocation."""
            invocation.task.cancel()
            await asyncio.gather(invocation.task, return_exceptions=True)
            return ToolMessage(tool_call_id=invocation.tool_call_id, content="cancelled", status="error")

    policy = ToolYieldPolicy(
        cancellations=(
            (ToolCancellationRegistrationDAO(tool=write_effect, port=Port()),) if cancel_confirmed else ()
        )
    )
    root = tmp_path / "history"
    history = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    session_id = str(uuid4())
    model = RecordingModel(
        responses=[
            AIMessage(
                content="Writing",
                additional_kwargs={
                    "slo_provider_extension": {
                        "provider": "openai",
                        "source_model_name": "gpt-5.4",
                        "reasoning_details": [{"private_anchor": "actual-tools-anchor"}],
                    }
                },
                tool_calls=[
                    {"id": "first-write", "name": "write_effect", "args": {"label": "first"}},
                    {"id": "second-write", "name": "write_effect", "args": {"label": "second"}},
                ],
            ),
            AIMessage(content="Urgent handled"),
        ]
    )
    model.release.set()
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path, tools=[write_effect]),
        tool_yield_policy=policy,
    )
    client = None
    try:
        session.subscribe(handler=held_observer)
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        await client.submit(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="Write"
            )
        )
        async with asyncio.timeout(delay=5):
            await entered.wait()
        urgent = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text="Urgent",
            priority="urgent",
        )
        async with asyncio.timeout(delay=2):
            await second_output.wait()
        await client.submit(submission=urgent)
        await asyncio.sleep(delay=0.02)
        if not cancel_confirmed:
            assert len(model.requests) == 1
        if not cancel_confirmed:
            release.set()
        async with asyncio.timeout(delay=5):
            while session.is_running or len(model.requests) < 2:
                await asyncio.sleep(delay=0)
        assert observer_entered.is_set()
        assert not observer_release.is_set()
        assert starts == ["first"]
        if cancel_confirmed:
            assert not effect.exists()
        else:
            assert effect.read_text(encoding="utf-8") == "first"
        assert "actual-tools-anchor" in str([message.model_dump() for message in model.requests[1]])
        results = [message for message in model.requests[1] if isinstance(message, ToolMessage)]
        assert [(message.tool_call_id, message.status) for message in results] == [
            ("first-write", "error" if cancel_confirmed else "success"),
            ("second-write", "error"),
        ]
        assert results[1].content == "not_started: cooperative yield before dispatch"
        events = await history.load_events(session_id=session_id)
        marked = [event for event in events if "tool_group_v1" in event.payload.metadata]
        assert [event.kind for event in marked] == ["tool_call", "tool_call", "tool_result", "tool_result"]
        assert [event.payload.metadata["tool_group_v1"]["tool_result_status"] for event in marked[2:]] == (
            ["error", "error"] if cancel_confirmed else ["success", "error"]
        )
        diagnostics = [
            event.payload.metadata["cooperative_yield_v1"]
            for event in events
            if "cooperative_yield_v1" in event.payload.metadata
        ]
        assert [item["disposition"] for item in diagnostics] == ([] if cancel_confirmed else ["deferred"])
        replay = await SessionHistoryProjector.build_message_history(events=events)
        assert [message.status for message in replay if isinstance(message, ToolMessage)] == (
            ["error", "error"] if cancel_confirmed else ["success", "error"]
        )
        receipt = await client.get_receipt(message_id=urgent.message_id)
        assert isinstance(receipt, MessageReceiptDAO) and receipt.state == "applied"
    finally:
        observer_release.set()
        release.set()
        session.abort()
        try:
            if client is not None:
                await client.close()
        finally:
            await session.close_messaging()


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_two_provider_interruptions_then_success_reopen_export(
    tmp_path: Path, tree: bool, isolated_journey_tasks: None
) -> None:
    """Two urgent admissions keep one run/cursor and durable exact interrupted iterations."""

    class TwiceInterrupted(InterruptedProvider):
        entered_twice: asyncio.Event = Field(default_factory=asyncio.Event)
        joined: int = 0

        def __init__(self, *, responses: Sequence[AIMessage]) -> None:
            """Preserve explicit external provider construction under Pydantic."""
            super().__init__(responses=responses)

        async def _astream(
            self,
            messages: list[BaseMessage],
            stop: Optional[list[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: object,
        ) -> AsyncIterator[ChatGenerationChunk]:
            """Hold two actual provider calls and let the third complete normally."""
            self.requests.append(list(messages))
            index = len(self.requests)
            if index < 3:
                yield ChatGenerationChunk(message=AIMessageChunk(content=f"Partial {index}"))
                (self.entered if index == 1 else self.entered_twice).set()
                try:
                    await self.release.wait()
                finally:
                    self.joined += 1
                return
            assert self.joined == 2
            async for chunk in FauxChatModel._astream(
                self, messages=messages, stop=stop, run_manager=run_manager, **kwargs
            ):
                yield chunk

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    history = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    session_id = str(uuid4())
    model = TwiceInterrupted(responses=[AIMessage(content="Final success")])
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    client = None
    try:
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        await client.submit(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="First"
            )
        )
        for index, entered in enumerate((model.entered, model.entered_twice), start=1):
            async with asyncio.timeout(delay=5):
                await entered.wait()
            await client.submit(
                submission=MessageSubmissionDAO(
                    message_id=str(uuid4()),
                    target=session.messaging_target,
                    kind="agent_input",
                    text=f"Urgent {index}",
                    priority="urgent",
                )
            )
        async with asyncio.timeout(delay=5):
            while session.is_running or len(model.requests) < 3:
                await asyncio.sleep(delay=0)
        assert model.joined == 2
        assert [message.content for message in model.requests[2] if message.type == "human"] == [
            "First",
            "Urgent 1",
            "Urgent 2",
        ]
    finally:
        model.release.set()
        session.abort()
        try:
            if client is not None:
                await client.close()
        finally:
            await session.close_messaging()
    reopened = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    events = await reopened.load_events(session_id=session_id)
    interruptions = [
        event
        for event in events
        if event.payload.metadata.get("cooperative_yield_v1", {}).get("disposition") == "interrupted"
    ]
    assert [event.iteration for event in interruptions] == [0, 1]
    assert len({event.turn_id for event in interruptions}) == 1
    assert len({event.payload.metadata["cooperative_yield_v1"]["run_id"] for event in interruptions}) == 1
    entries = ReplayEntryProjector.build_entries(events=events)
    assert [entry.answer for entry in entries if entry.interrupted] == ["Partial 1", "Partial 2"]
    markdown = ReplayEntryProjector.render_markdown(events=events)
    assert markdown.count("Response interrupted for urgent input.") == 2
    assert "Final success" in markdown
    context = await SessionHistoryProjector.build_message_history(events=events)
    assert not any("Partial" in str(message.content) for message in context)


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_live_writer_unknown_reply_blocks_next_provider(
    tmp_path: Path, tree: bool, isolated_journey_tasks: None
) -> None:
    """A real producer's durable-but-unknown opening cannot enter any retry planner."""
    from tests.agents.slo_agent.messaging.test_history_cooperative_append import (
        _LostReplyFlatStore,
        _LostReplyTreeStore,
        _ScriptedFileCertification,
    )

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    history = (
        _LostReplyTreeStore(root=root, file_certification=_ScriptedFileCertification())
        if tree
        else _LostReplyFlatStore(root=root, file_certification=_ScriptedFileCertification())
    )
    model = InterruptedProvider(
        responses=[
            AIMessage(content="Completed", tool_calls=[{"id": "reserved", "name": "read", "args": {}}]),
            AIMessage(content="must not request"),
        ]
    )
    model.suppress = True
    session_id = str(uuid4())
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    client = None
    try:
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        await client.submit(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="Original"
            )
        )
        async with asyncio.timeout(delay=5):
            await model.entered.wait()
        urgent = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text="Urgent",
            priority="urgent",
        )
        await client.submit(submission=urgent)
        async with asyncio.timeout(delay=5):
            while session.is_running:
                await asyncio.sleep(delay=0)
        assert len(model.requests) == 1
        assert model.cancellation_count == 1
        from src.agents.slo_agent.messaging.dao import MessageErrorDAO

        receipt = await client.get_receipt(message_id=urgent.message_id)
        assert isinstance(receipt, MessageErrorDAO) and receipt.code == "storage_unavailable"
        events = await history.load_events(session_id=session_id)
        assert not any(event.kind == "run_completed" for event in events)
        assert any(event.kind == "run_failed" for event in events)
        diagnostics = [
            event.payload.metadata["cooperative_yield_v1"]
            for event in events
            if "cooperative_yield_v1" in event.payload.metadata
        ]
        assert [item["disposition"] for item in diagnostics] == ["requested"]
    finally:
        model.release.set()
        session.abort()
        if client is not None:
            await client.close()
        await session.close_messaging()
    rows = read_closed_message_rows(
        database_path=root / session_id / "messaging.v1.sqlite3", temporary_root=tmp_path
    )
    assert (urgent.message_id, 1, "accepted") in rows


async def test_real_model_pool_retains_live_thinking_and_member_on_urgent_yield(
    tmp_path: Path, isolated_journey_tasks: None
) -> None:
    """The existing bound pool yields live chunks and never reroutes cancellation."""
    from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
    from src.auth.credential_dao import ProviderName
    from src.agents.slo_agent.agent import SloAgent

    member = InterruptedProvider(responses=[AIMessage(content="Urgent answer")])
    member.partial = True
    member.thinking = True
    fallback = RecordingModel(responses=[AIMessage(content="forbidden fallback")])
    fallback.release.set()
    pool = ModelPool(
        pool_dao=ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI),
                ModelPoolEntryDAO(model_name="gpt-5.4-mini", provider=ProviderName.OPENAI, priority=1),
            ]
        ),
        models={"gpt-5.4": member, "gpt-5.4-mini": fallback},
    )
    agent = SloAgent(llm=pool, tools=[], cwd=str(tmp_path))
    bound = agent.llm
    live = asyncio.Event()
    seen: list[str] = []

    async def observe(event: Any) -> None:
        """Require visible thinking before submitting urgency."""
        seen.append(event.kind)
        if event.kind == "thinking_delta":
            live.set()

    session_id = str(uuid4())
    root = tmp_path / "history"
    session = SloAgentSession(
        agent=agent,
        session_id=session_id,
        workdir=tmp_path,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=FilesystemSessionHistoryStore(root=root),
    )
    client = None
    try:
        session.subscribe(handler=observe)
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        await client.submit(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="Original"
            )
        )
        async with asyncio.timeout(delay=5):
            await live.wait()
        urgent = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text="Urgent",
            priority="urgent",
        )
        await client.submit(submission=urgent)
        async with asyncio.timeout(delay=5):
            while session.is_running or len(member.requests) < 2:
                await asyncio.sleep(delay=0)
        assert agent.llm is bound
        assert member.cancellation_count == 1 and not fallback.requests
        assert len(member.requests) == 2
        assert "text_delta" in seen and "thinking_delta" in seen
        assert any(message.content == "Urgent" for message in member.requests[1])
    finally:
        member.release.set()
        session.abort()
        if client is not None:
            await client.close()
        await session.close_messaging()


async def test_older_urgent_backlog_does_not_interrupt_itself_or_block_normal_tail(
    tmp_path: Path, isolated_journey_tasks: None
) -> None:
    """Selected high-water covers old urgency; later normal boundary may snapshot zero."""

    class BacklogProvider(RecordingModel):
        first_joined: asyncio.Event = Field(default_factory=asyncio.Event)
        second_entered: asyncio.Event = Field(default_factory=asyncio.Event)
        allow_first_join: asyncio.Event = Field(default_factory=asyncio.Event)
        allow_second: asyncio.Event = Field(default_factory=asyncio.Event)
        cancellations: int = 0

        def __init__(self, *, responses: Sequence[AIMessage]) -> None:
            """Retain the explicit external request script."""
            super().__init__(responses=responses)

        async def _astream(
            self,
            messages: list[BaseMessage],
            stop: Optional[list[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: object,
        ) -> AsyncIterator[ChatGenerationChunk]:
            """Hold initial cancellation cleanup until all backlog admissions commit."""
            self.requests.append(list(messages))
            if len(self.requests) == 1:
                self.entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    self.cancellations += 1
                    self.first_joined.set()
                    await self.allow_first_join.wait()
            elif len(self.requests) == 2:
                self.second_entered.set()
                await self.allow_second.wait()
            async for chunk in FauxChatModel._astream(
                self, messages=messages, stop=stop, run_manager=run_manager, **kwargs
            ):
                yield chunk

    root = tmp_path / "history"
    session_id = str(uuid4())
    model = BacklogProvider(
        responses=[
            AIMessage(content="first urgent answer"),
            AIMessage(content="second urgent answer"),
            AIMessage(content="normal tail"),
        ]
    )
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=FilesystemSessionHistoryStore(root=root),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    client = None
    submissions: list[MessageSubmissionDAO] = []
    try:
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        await client.submit(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="Original"
            )
        )
        await model.entered.wait()
        backlog: tuple[tuple[str, Literal["normal", "urgent"]], ...] = (
            ("Urgent A", "urgent"),
            ("Urgent B", "urgent"),
            ("Normal tail", "normal"),
        )
        for text, priority in backlog:
            submission = MessageSubmissionDAO(
                message_id=str(uuid4()),
                target=session.messaging_target,
                kind="agent_input",
                text=text,
                priority=priority,
            )
            submissions.append(submission)
            await client.submit(submission=submission)
        await model.first_joined.wait()
        model.allow_first_join.set()
        async with asyncio.timeout(delay=5):
            await model.second_entered.wait()
        # Cross several owner-loop turns with old urgent backlog still pending.
        for _ in range(5):
            await asyncio.sleep(delay=0)
        assert len(model.requests) == 2 and model.cancellations == 1
        model.allow_second.set()
        async with asyncio.timeout(delay=5):
            while session.is_running:
                await asyncio.sleep(delay=0)
        assert len(model.requests) == 4
        for submission in submissions:
            receipt = await client.get_receipt(message_id=submission.message_id)
            assert isinstance(receipt, MessageReceiptDAO) and receipt.state == "applied"
    finally:
        model.allow_first_join.set()
        model.allow_second.set()
        session.abort()
        if client is not None:
            await client.close()
        await session.close_messaging()


@pytest.mark.parametrize(argnames="failure_kind", argvalues=["protocol", "read"])
async def test_pool_cleanup_transport_failure_never_starts_fallback(
    tmp_path: Path, failure_kind: str, isolated_journey_tasks: None
) -> None:
    """Owner cancellation remains authoritative if member cleanup raises transport errors."""
    import httpx
    from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
    from src.auth.credential_dao import ProviderName
    from src.agents.slo_agent.agent import SloAgent

    class FailingCleanupProvider(RecordingModel):
        cleanup_entered: asyncio.Event = Field(default_factory=asyncio.Event)
        cleanup_release: asyncio.Event = Field(default_factory=asyncio.Event)
        cleanup_joined: asyncio.Event = Field(default_factory=asyncio.Event)

        def __init__(self, *, responses: Sequence[AIMessage]) -> None:
            """Construct the explicit provider script."""
            super().__init__(responses=responses)

        async def _astream(
            self,
            messages: list[BaseMessage],
            stop: Optional[list[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: object,
        ) -> AsyncIterator[ChatGenerationChunk]:
            """Expose cancellation cleanup at the external provider boundary."""
            self.requests.append(list(messages))
            self.entered.set()
            try:
                await self.release.wait()
                yield ChatGenerationChunk(message=AIMessageChunk(content="unreachable"))
            finally:
                self.cleanup_entered.set()
                try:
                    await self.cleanup_release.wait()
                finally:
                    self.cleanup_joined.set()
                if failure_kind == "read":
                    raise httpx.ReadError("private transport failure")
                raise httpx.RemoteProtocolError("private transport failure")

    from src.agents.model_catalog.service import ModelCatalogService

    snapshot = ModelCatalogService.load()
    entries = dict(snapshot.entries)
    entry = entries["gpt-5.4"]
    entries["gpt-5.4"] = entry.model_copy(
        update={
            "runtime_profile": entry.runtime_profile.model_copy(
                update={"automatic_retry_attempts": 1, "local_retry_wait_cap_seconds": 1}
            )
        }
    )
    entries["gpt-5.4-mini"] = entries["gpt-5.4"].model_copy(update={"model_name": "gpt-5.4-mini"})
    snapshot = snapshot.model_copy(update={"entries": entries})
    member = FailingCleanupProvider(responses=[])
    fallback = RecordingModel(responses=[AIMessage(content="forbidden fallback")])
    fallback.release.set()
    pool = ModelPool(
        pool_dao=ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI),
                ModelPoolEntryDAO(model_name="gpt-5.4-mini", provider=ProviderName.OPENAI, priority=1),
            ]
        ),
        models={"gpt-5.4": member, "gpt-5.4-mini": fallback},
        snapshot=snapshot,
    )
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id = str(uuid4())
    history = FilesystemSessionHistoryStore(root=root)
    session = SloAgentSession(
        agent=SloAgent(llm=pool, tools=[], cwd=str(tmp_path), snapshot=snapshot),
        catalog_snapshot=snapshot,
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path,
            history_root=root,
            session_id=session_id,
            model_name="gpt-5.4",
        ),
        history_store=history,
    )
    client: Optional[LocalSessionMessagingClient] = None
    try:
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        original = MessageSubmissionDAO(
            message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="Original"
        )
        urgent = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text="Urgent",
            priority="urgent",
        )
        await client.submit(submission=original)
        async with asyncio.timeout(delay=5):
            await member.entered.wait()
        await client.submit(submission=urgent)
        async with asyncio.timeout(delay=5):
            await member.cleanup_entered.wait()
        assert session.is_running and not fallback.requests
        member.cleanup_release.set()
        async with asyncio.timeout(delay=5):
            while session.is_running:
                await asyncio.sleep(delay=0)
        assert member.cleanup_joined.is_set()
        assert not fallback.requests
        assert len(member.requests) == 1
        events = await history.load_events(session_id=session_id)
        assert [event.kind for event in events if event.kind in {"run_failed", "run_completed"}] == [
            "run_failed"
        ]
        assert "cooperative_yield_settlement_failed" in str(
            [event.payload for event in events if event.kind == "run_failed"]
        )
        assert [event.payload.content for event in events if "messaging_v1" in event.payload.metadata] == [
            "Original"
        ]
    finally:
        member.release.set()
        member.cleanup_release.set()
        session.abort()
        try:
            if client is not None:
                await client.close()
        finally:
            await session.close_messaging()
    rows = read_closed_message_rows(
        database_path=root / session_id / "messaging.v1.sqlite3", temporary_root=tmp_path
    )
    assert rows == ((original.message_id, 0, "applied"), (urgent.message_id, 1, "accepted"))


@pytest.mark.parametrize(argnames="fail_cleanup", argvalues=[False, True])
async def test_abort_during_reserved_provider_join_persists_only_aborted(
    tmp_path: Path, fail_cleanup: bool, isolated_journey_tasks: None
) -> None:
    """Abort after reservation is re-arbitrated after actual provider cleanup joins."""
    from tests.agents.slo_agent.test_graph_stream_lifetime import HeldCloseProvider
    from src.agents.slo_agent.agent import SloAgent
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    model = HeldCloseProvider(responses=[], fail_close=fail_cleanup)
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id = str(uuid4())
    history = FilesystemSessionHistoryStore(root=root)
    session = SloAgentSession(
        agent=SloAgent(llm=model, tools=[], cwd=str(tmp_path)),
        workdir=tmp_path,
        session_id=session_id,
        history_store=history,
        config=SessionConfigDAO(
            workdir=tmp_path,
            history_root=root,
            session_id=session_id,
            model_name="gpt-5.4",
        ),
    )
    seen: list[AgentStreamEventDAO] = []

    async def observe(event: AgentStreamEventDAO) -> None:
        """Record public terminals without delaying execution."""
        seen.append(event)

    client: Optional[LocalSessionMessagingClient] = None
    try:
        session.subscribe(handler=observe)
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        original = MessageSubmissionDAO(
            message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="Original"
        )
        urgent = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text="Urgent",
            priority="urgent",
        )
        await client.submit(submission=original)
        async with asyncio.timeout(delay=5):
            await model.entered.wait()
        await client.submit(submission=urgent)
        async with asyncio.timeout(delay=5):
            await model.closing.wait()
        session.abort()
        assert not any(event.is_terminal for event in seen)
        model.release.set()
        async with asyncio.timeout(delay=5):
            while session.is_running:
                await asyncio.sleep(delay=0)
        events = await history.load_events(session_id=session_id)
        assert [
            event.kind for event in events if event.kind in {"run_completed", "run_aborted", "run_failed"}
        ] == (["run_failed"] if fail_cleanup else ["run_aborted"])
        if not fail_cleanup:
            async with asyncio.timeout(delay=5):
                while not any(event.is_terminal for event in seen):
                    await asyncio.sleep(delay=0)
            assert [event.kind for event in seen if event.is_terminal] == ["run_aborted"]
        else:
            assert not any(event.kind == "run_completed" for event in seen)
        assert [event.payload.content for event in events if "messaging_v1" in event.payload.metadata] == [
            "Original"
        ]
        assert model.close_count == 1
    finally:
        model.release.set()
        session.abort()
        try:
            if client is not None:
                await client.close()
        finally:
            await session.close_messaging()
    rows = read_closed_message_rows(
        database_path=root / session_id / "messaging.v1.sqlite3", temporary_root=tmp_path
    )
    assert rows == ((original.message_id, 0, "applied"), (urgent.message_id, 1, "accepted"))


async def test_requested_notice_is_observable_before_join_and_matches_durable_audit(
    tmp_path: Path, isolated_journey_tasks: None
) -> None:
    """Requested is a nonblocking reservation observation, not a settlement acknowledgement."""
    from tests.agents.slo_agent.test_graph_stream_lifetime import HeldCloseProvider
    from src.agents.slo_agent.agent import SloAgent
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    model = HeldCloseProvider(responses=[AIMessage(content="next")])
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id = str(uuid4())
    history = FilesystemSessionHistoryStore(root=root)
    session = SloAgentSession(
        agent=SloAgent(llm=model, tools=[], cwd=str(tmp_path)),
        workdir=tmp_path,
        session_id=session_id,
        history_store=history,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
    )
    seen: list[AgentStreamEventDAO] = []
    requested = asyncio.Event()

    async def observe(event: AgentStreamEventDAO) -> None:
        """Observe reservation before provider cleanup releases."""
        seen.append(event)
        if event.kind == "yield_requested":
            requested.set()

    client: Optional[LocalSessionMessagingClient] = None
    try:
        session.subscribe(handler=observe)
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        await client.submit(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="Original"
            )
        )
        async with asyncio.timeout(delay=5):
            await model.entered.wait()
        await client.submit(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()),
                target=session.messaging_target,
                kind="agent_input",
                text="Urgent",
                priority="urgent",
            )
        )
        async with asyncio.timeout(delay=2):
            await model.closing.wait()
            await requested.wait()
        notice = next(event for event in seen if event.kind == "yield_requested")
        assert not notice.is_terminal and not model.release.is_set()
        assert notice.metadata["cooperative_yield_v1"]["disposition"] == "requested"
        events = await history.load_events(session_id=session_id)
        assert not any(event.payload.metadata.get("cooperative_yield_v1") for event in events)
        # Abort avoids requesting this deliberately always-held provider a second time.
        session.abort()
        model.release.set()
        async with asyncio.timeout(delay=5):
            while session.is_running:
                await asyncio.sleep(delay=0)
    finally:
        model.release.set()
        session.abort()
        try:
            if client is not None:
                await client.close()
        finally:
            await session.close_messaging()


@pytest.mark.parametrize(argnames="retirement", argvalues=["failure", "overflow"])
async def test_retired_subscriber_does_not_own_tool_settlement_or_next_application(
    tmp_path: Path, retirement: str, isolated_journey_tasks: None
) -> None:
    """Failed/overflow observers cannot alter defer/result/application/terminal truth."""
    from langchain_core.tools import tool
    from langchain_core.messages import ToolMessage
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    entered, release = asyncio.Event(), asyncio.Event()
    observer_entered, observer_joined = asyncio.Event(), asyncio.Event()
    defer_seen = asyncio.Event()

    @tool
    async def held_effect() -> str:
        """Return actual work only when the test releases the safe boundary."""
        entered.set()
        await release.wait()
        return "actual result"

    async def retired_observer(event: AgentStreamEventDAO) -> None:
        """Retire through callback failure or byte overflow while in flight."""
        observer_entered.set()
        try:
            if retirement == "failure":
                raise ValueError("isolated presentation failure")
            await asyncio.Event().wait()
        finally:
            observer_joined.set()

    async def observe(event: AgentStreamEventDAO) -> None:
        """Observe defer through an independent bounded registration."""
        if event.kind == "yield_deferred":
            defer_seen.set()

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id = str(uuid4())
    history = FilesystemSessionHistoryStore(root=root)
    model = RecordingModel(
        responses=[
            AIMessage(content="work", tool_calls=[{"id": "held", "name": "held_effect", "args": {}}]),
            AIMessage(content="done"),
        ]
    )
    model.release.set()
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        history_store=history,
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path, tools=[held_effect]),
    )
    client = None
    try:
        session.subscribe(handler=retired_observer)
        session.subscribe(handler=observe)
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        await client.submit(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="original"
            )
        )
        async with asyncio.timeout(delay=5):
            await entered.wait()
            await observer_entered.wait()
        if retirement == "overflow":
            # Only optional observation; no extra execution request or canonical event.
            await session.event_relay(AgentStreamEventDAO(kind="text_delta", delta="x" * (1024 * 1024)))
        urgent = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text="urgent",
            priority="urgent",
        )
        await client.submit(submission=urgent)
        if retirement == "failure":
            async with asyncio.timeout(delay=5):
                await defer_seen.wait()
        # Overflow retires both optional observers, not the canonical defer capture.
        release.set()
        async with asyncio.timeout(delay=5):
            while session.is_running or len(model.requests) < 2:
                await asyncio.sleep(delay=0)
        assert observer_joined.is_set()
        results = [message for message in model.requests[1] if isinstance(message, ToolMessage)]
        assert len(results) == 1 and results[0].content == "actual result" and results[0].status == "success"
        events = await history.load_events(session_id=session_id)
        assert [event.payload.content for event in events if "messaging_v1" in event.payload.metadata] == [
            "original",
            "urgent",
        ]
        assert sum(event.kind == "run_completed" for event in events) == 1
        assert [
            event.payload.metadata["cooperative_yield_v1"]["disposition"]
            for event in events
            if "cooperative_yield_v1" in event.payload.metadata
        ] == ["deferred"]
    finally:
        release.set()
        session.abort()
        try:
            if client is not None:
                await client.close()
        finally:
            await session.close_messaging()
    rows = read_closed_message_rows(
        database_path=root / session_id / "messaging.v1.sqlite3", temporary_root=tmp_path
    )
    assert (urgent.message_id, 0, "applied") in rows
