"""Portable response and completed-call ownership, including cancelled receivers."""

import asyncio

import pytest

from src.bridges.claude.response import AIAgentResponseAdapter, ClaudeResponseTranslationDAO
from src.bridges.claude.tool_call import ToolCallAdapter, ClaudeCompletedCallBatchDAO
from src.bridges.claude.sdk.dao import ClaudeInteractionBindingDAO, ClaudeToolDefinitionDAO, ClaudeToolCallDAO
from src.bridges.claude.sdk.events import (
    ClaudeBridgeEvent,
    ClaudeResponseClosedDAO,
    ClaudeResponseCompletedDAO,
    ClaudeTextEventDAO,
)


async def test_response_adapter_correlates_orders_and_retains_accepted_events() -> None:
    """Echoes are inert, stale/order conflicts cannot mutate a completed response."""
    binding = ClaudeInteractionBindingDAO(session_id="s", invocation_id="i", binding_version=2)
    accepted: list[ClaudeBridgeEvent] = []

    async def receive(event: ClaudeResponseTranslationDAO) -> None:
        """Record the portable response accepted by the borrowed builder."""
        accepted.append(event.event)

    adapter = AIAgentResponseAdapter.register(
        binding=binding, response_receiver=receive, tool_call_receiver=receive
    )
    text = ClaudeTextEventDAO(session_id="s", invocation_id="i", response_id="r", sequence=1, text="hello")
    done = ClaudeResponseCompletedDAO(
        session_id="s", invocation_id="i", response_id="r", sequence=2, stop_reason="stop"
    )
    await adapter.handle(event=text)
    await adapter.handle(event=text)
    await adapter.handle(event=done)
    await adapter.reset()
    await adapter.handle(event=done)
    assert accepted == [text, done]
    for event in (
        text.model_copy(update={"text": "changed"}),
        text.model_copy(update={"invocation_id": "old"}),
        text.model_copy(update={"sequence": 3}),
    ):
        with pytest.raises(ValueError):
            await adapter.handle(event=event)
    next_text = text.model_copy(update={"response_id": "next", "sequence": 7})
    await adapter.handle(event=next_text)
    with pytest.raises(ValueError):
        await adapter.handle(event=text.model_copy(update={"response_id": "overlap", "sequence": 8}))
    await adapter.close()
    with pytest.raises(RuntimeError):
        await adapter.handle(event=next_text)
    assert accepted == [text, done, next_text]


async def test_native_closure_retains_text_and_allows_only_latest_terminal_once() -> None:
    """Native closure retires IDs, not host text; old terminal/text cannot mutate history."""
    accepted: list[ClaudeResponseTranslationDAO] = []

    async def receive(translation: ClaudeResponseTranslationDAO) -> None:
        """Record host text snapshots at the real response-owner boundary."""
        accepted.append(translation)

    adapter = AIAgentResponseAdapter.register(
        binding=ClaudeInteractionBindingDAO(session_id="s", invocation_id="i", binding_version=0),
        response_receiver=receive,
        tool_call_receiver=receive,
    )
    prefix = ClaudeTextEventDAO(
        session_id="s", invocation_id="i", response_id="refused", sequence=1, text="before "
    )
    closed = ClaudeResponseClosedDAO(session_id="s", invocation_id="i", response_id="refused", sequence=2)
    answer = prefix.model_copy(update={"response_id": "answer", "sequence": 3, "text": "after"})
    answer_closed = closed.model_copy(update={"response_id": "answer", "sequence": 4})
    terminal = ClaudeResponseCompletedDAO(
        session_id="s", invocation_id="i", response_id="answer", sequence=5, stop_reason="stop"
    )
    try:
        for event in (prefix, closed, closed, answer, answer_closed):
            await adapter.handle(event=event)
        for invalid in (
            prefix.model_copy(update={"sequence": 5}),
            terminal.model_copy(update={"response_id": "refused"}),
            terminal.model_copy(update={"invocation_id": "foreign"}),
        ):
            with pytest.raises(ValueError):
                await adapter.handle(event=invalid)
        await adapter.handle(event=terminal)
        await adapter.handle(event=terminal)
        with pytest.raises(ValueError):
            await adapter.handle(event=terminal.model_copy(update={"sequence": 6}))
        assert [translation.text for translation in accepted] == [
            "before ",
            "before ",
            "before after",
            "before after",
            "before after",
        ]
        # A later host generation starts empty even within the same invocation.
        await adapter.handle(event=prefix.model_copy(update={"response_id": "next", "sequence": 7}))
        assert accepted[-1].text == "before "
    finally:
        await adapter.close()


async def test_call_adapter_translates_complete_batch_once_and_joins_receiver() -> None:
    """Completed calls stay ordered/detached; close joins a cancelled handle's delivery."""
    binding = ClaudeInteractionBindingDAO(session_id="s", invocation_id="i", binding_version=0)
    entered, release = asyncio.Event(), asyncio.Event()
    accepted: list[ClaudeCompletedCallBatchDAO] = []

    async def receive(event: ClaudeCompletedCallBatchDAO) -> None:
        """Hold acceptance while a caller is cancelled, without borrowing ownership."""
        entered.set()
        await release.wait()
        accepted.append(event)

    expected = ClaudeResponseCompletedDAO(
        session_id="s",
        invocation_id="i",
        response_id="r",
        sequence=2,
        stop_reason="tool_calls",
        tool_calls=tuple(
            ClaudeToolCallDAO(tool_call_id=name, name="read", arguments={"path": "same"})
            for name in ("b", "a")
        ),
    )
    adapter = ToolCallAdapter.register(
        binding=binding,
        response_id="r",
        tools=(ClaudeToolDefinitionDAO(name="read", description="Read", input_schema={"type": "object"}),),
        receiver=receive,
    )
    caller = asyncio.create_task(adapter.handle(event=expected))
    await entered.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    closing = asyncio.create_task(adapter.close())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await closing
    await adapter.reset()
    assert len(accepted) == 1
    assert [call.tool_call_id for call in accepted[0].calls] == ["b", "a"]
    assert [call.arguments_json for call in accepted[0].calls] == ['{"path": "same"}'] * 2
    with pytest.raises(RuntimeError):
        await adapter.handle(event=expected)


async def test_rejected_oversized_response_does_not_reserve_assembly() -> None:
    """A rejected first text leaves binding/sequence/response association untouched."""
    accepted: list[ClaudeResponseTranslationDAO] = []

    async def receive(value: ClaudeResponseTranslationDAO) -> None:
        """Record only accepted portable events."""
        accepted.append(value)

    adapter = AIAgentResponseAdapter.register(
        binding=ClaudeInteractionBindingDAO(session_id="s", invocation_id="i", binding_version=0),
        response_receiver=receive,
        tool_call_receiver=receive,
    )
    try:
        with pytest.raises(ValueError, match="limit"):
            await adapter.handle(
                event=ClaudeTextEventDAO(
                    session_id="s",
                    invocation_id="i",
                    response_id="rejected",
                    sequence=1,
                    text="x" * (32 * 1024 * 1024 + 1),
                )
            )
        await adapter.handle(
            event=ClaudeTextEventDAO(
                session_id="s",
                invocation_id="i",
                response_id="valid",
                sequence=1,
                text="ok",
            )
        )
        assert [value.text for value in accepted] == ["ok"]
    finally:
        await adapter.close()


async def test_call_receiver_cannot_mutate_retained_acceptance_after_reset() -> None:
    """Nested receiver mutation cannot corrupt repeat/conflict protection."""
    delivered: list[ClaudeCompletedCallBatchDAO] = []

    async def receive(batch: ClaudeCompletedCallBatchDAO) -> None:
        """Mutate only the borrowed translation, not the source event."""
        nested = batch.completion.tool_calls[0].arguments["nested"]
        assert isinstance(nested, dict)
        nested["value"] = "receiver"
        delivered.append(batch)

    event = ClaudeResponseCompletedDAO(
        session_id="s",
        invocation_id="i",
        response_id="r",
        sequence=1,
        stop_reason="tool_calls",
        tool_calls=(
            ClaudeToolCallDAO(tool_call_id="a", name="read", arguments={"nested": {"value": "source"}}),
        ),
    )
    adapter = ToolCallAdapter.register(
        binding=ClaudeInteractionBindingDAO(session_id="s", invocation_id="i", binding_version=0),
        response_id="r",
        tools=(ClaudeToolDefinitionDAO(name="read", description="read", input_schema={"type": "object"}),),
        receiver=receive,
    )
    try:
        await adapter.handle(event=event)
        await adapter.reset()
        await adapter.handle(event=event)
        changed = event.model_copy(deep=True)
        nested = changed.tool_calls[0].arguments["nested"]
        assert isinstance(nested, dict)
        nested["value"] = "conflict"
        with pytest.raises(ValueError, match="conflict"):
            await adapter.handle(event=changed)
        assert len(delivered) == 1
        assert event.tool_calls[0].arguments == {"nested": {"value": "source"}}
    finally:
        await adapter.close()


@pytest.mark.parametrize("kind", ["response", "call"])
async def test_failed_receiver_is_not_replayed_by_reset_or_repeat(kind: str) -> None:
    """Receiver failure remains observable; close retires it without another delivery."""
    attempts: list[ClaudeResponseTranslationDAO | ClaudeCompletedCallBatchDAO] = []

    async def refuse(value: ClaudeResponseTranslationDAO | ClaudeCompletedCallBatchDAO) -> None:
        """Record then fail acceptance."""
        attempts.append(value)
        raise OSError("receiver refusal")

    binding = ClaudeInteractionBindingDAO(session_id="s", invocation_id="i", binding_version=0)
    event = ClaudeResponseCompletedDAO(
        session_id="s",
        invocation_id="i",
        response_id="r",
        sequence=1,
        stop_reason="tool_calls",
        tool_calls=(ClaudeToolCallDAO(tool_call_id="a", name="read", arguments={}),),
    )
    adapter = (
        AIAgentResponseAdapter.register(binding=binding, response_receiver=refuse, tool_call_receiver=refuse)
        if kind == "response"
        else ToolCallAdapter.register(
            binding=binding,
            response_id="r",
            receiver=refuse,
            tools=(
                ClaudeToolDefinitionDAO(name="read", description="read", input_schema={"type": "object"}),
            ),
        )
    )
    for operation in (adapter.handle(event=event), adapter.reset(), adapter.handle(event=event)):
        with pytest.raises(OSError, match="receiver refusal"):
            await operation
    await adapter.close()
    with pytest.raises(RuntimeError, match="closed"):
        await adapter.handle(event=event)
    assert len(attempts) == 1


@pytest.mark.parametrize("kind", ["response", "call"])
async def test_response_cancel_and_close_join_borrowed_receiver(kind: str) -> None:
    """Cancelling a handle or close never abandons the admitted builder."""
    entered, release = asyncio.Event(), asyncio.Event()
    accepted: list[ClaudeResponseTranslationDAO | ClaudeCompletedCallBatchDAO] = []

    async def receive(value: ClaudeResponseTranslationDAO | ClaudeCompletedCallBatchDAO) -> None:
        """Hold the real receiver across caller cancellation."""
        entered.set()
        await release.wait()
        accepted.append(value)

    binding = ClaudeInteractionBindingDAO(session_id="s", invocation_id="i", binding_version=0)
    adapter: AIAgentResponseAdapter | ToolCallAdapter
    if kind == "response":
        adapter = AIAgentResponseAdapter.register(
            binding=binding, response_receiver=receive, tool_call_receiver=receive
        )
        text_event = ClaudeTextEventDAO(
            session_id="s", invocation_id="i", response_id="r", sequence=1, text="hello"
        )
        caller = asyncio.create_task(coro=adapter.handle(event=text_event))
    else:
        adapter = ToolCallAdapter.register(
            binding=binding,
            response_id="r",
            receiver=receive,
            tools=(
                ClaudeToolDefinitionDAO(name="read", description="read", input_schema={"type": "object"}),
            ),
        )
        completed_event = ClaudeResponseCompletedDAO(
            session_id="s",
            invocation_id="i",
            response_id="r",
            sequence=1,
            stop_reason="tool_calls",
            tool_calls=(ClaudeToolCallDAO(tool_call_id="a", name="read", arguments={}),),
        )
        caller = asyncio.create_task(coro=adapter.handle(event=completed_event))
    await entered.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    closing = asyncio.create_task(coro=adapter.close())
    await asyncio.sleep(0)
    closing.cancel()
    await asyncio.sleep(0)
    assert not closing.done(), "close must retain its receiver join despite caller cancellation"
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    await adapter.reset()
    assert len(accepted) == 1


@pytest.mark.parametrize("change", ["foreign", "duplicate", "stale", "nonfinite"])
async def test_call_adapter_rejects_entire_invalid_batch_before_delivery(change: str) -> None:
    """No valid prefix escapes when a completed batch has an invalid suffix."""
    accepted: list[ClaudeCompletedCallBatchDAO] = []

    async def receive(event: ClaudeCompletedCallBatchDAO) -> None:
        """Record forbidden delivery."""
        accepted.append(event)

    call = ClaudeToolCallDAO(tool_call_id="a", name="read", arguments={})
    suffix = ClaudeToolCallDAO(tool_call_id="b", name="read", arguments={})
    if change == "foreign":
        suffix = suffix.model_copy(update={"name": "bash"})
    elif change == "duplicate":
        suffix = call
    elif change == "nonfinite":
        suffix = suffix.model_copy(update={"arguments": {"n": float("inf")}})
    event = ClaudeResponseCompletedDAO(
        session_id="s",
        invocation_id="old" if change == "stale" else "i",
        response_id="r",
        sequence=1,
        stop_reason="tool_calls",
        tool_calls=(call, suffix),
    )
    adapter = ToolCallAdapter.register(
        binding=ClaudeInteractionBindingDAO(session_id="s", invocation_id="i", binding_version=0),
        response_id="r",
        tools=(ClaudeToolDefinitionDAO(name="read", description="Read", input_schema={"type": "object"}),),
        receiver=receive,
    )
    with pytest.raises(ValueError):
        await adapter.handle(event=event)
    await adapter.close()
    assert not accepted


async def test_response_adapter_accepts_long_streams_and_bounds_response_identities() -> None:
    """A long answer streams any number of fragments; only response identities are capped."""
    binding = ClaudeInteractionBindingDAO(session_id="s", invocation_id="i", binding_version=0)

    async def receive(event: ClaudeResponseTranslationDAO) -> None:
        """Accept every translated event."""

    adapter = AIAgentResponseAdapter.register(
        binding=binding, response_receiver=receive, tool_call_receiver=receive
    )
    for sequence in range(1, 10_003):
        await adapter.handle(
            event=ClaudeTextEventDAO(
                session_id="s", invocation_id="i", response_id="r", sequence=sequence, text="x"
            )
        )
    sequence = 10_002
    for response in ["r", *(f"r{n}" for n in range(1, AIAgentResponseAdapter.RESPONSE_LIMIT))]:
        sequence += 1
        await adapter.handle(
            event=ClaudeResponseCompletedDAO(
                session_id="s", invocation_id="i", response_id=response, sequence=sequence, stop_reason="stop"
            )
        )
    with pytest.raises(ValueError, match="identity limit"):
        await adapter.handle(
            event=ClaudeTextEventDAO(
                session_id="s", invocation_id="i", response_id="over", sequence=sequence + 1, text="x"
            )
        )
