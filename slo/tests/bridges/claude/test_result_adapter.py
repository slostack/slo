"""Portable response-result ownership and joined borrowed-receiver delivery."""

import asyncio

import pytest

from src.bridges.claude.sdk.dao import (
    ClaudeInteractionBindingDAO,
    ClaudeTextDAO,
    ClaudeToolCallDAO,
    ClaudeToolResultBatchDAO,
    ClaudeToolResultDAO,
    ClaudeToolResultSubmissionDAO,
)
from src.bridges.claude.sdk.events import ClaudeResponseCompletedDAO
from src.bridges.claude.sdk.exceptions import ClaudeBridgeError
from src.bridges.claude.tool_result import ToolCallResponseAdapter


async def test_result_adapter_validates_binding_and_retains_acceptance_across_reset() -> None:
    """A16: wrong bindings/sets never send; reset cannot allow duplicate/conflicting sends."""
    accepted: list[ClaudeToolResultSubmissionDAO] = []

    async def receive(submission: ClaudeToolResultSubmissionDAO) -> None:
        """Record only portable values accepted by the borrowed SDK receiver."""
        accepted.append(submission)

    adapter = ToolCallResponseAdapter.register(
        binding=ClaudeInteractionBindingDAO(session_id="s", invocation_id="i", binding_version=0),
        expected=ClaudeResponseCompletedDAO(
            session_id="s",
            invocation_id="i",
            response_id="r",
            sequence=1,
            stop_reason="tool_calls",
            tool_calls=(ClaudeToolCallDAO(tool_call_id="c", name="read", arguments={}),),
        ),
        receiver=receive,
    )
    submission = ClaudeToolResultSubmissionDAO(
        invocation_id="i",
        tool_result_batch=ClaudeToolResultBatchDAO(
            response_id="r",
            results=(
                ClaudeToolResultDAO(
                    tool_call_id="c",
                    content=(ClaudeTextDAO(text=""),),
                    is_error=False,
                ),
            ),
        ),
    )
    for invalid in (
        submission.model_copy(update={"invocation_id": "stale"}),
        submission.model_copy(
            update={"tool_result_batch": ClaudeToolResultBatchDAO(response_id="other", results=())}
        ),
        submission.model_copy(
            update={"tool_result_batch": ClaudeToolResultBatchDAO(response_id="r", results=())}
        ),
    ):
        with pytest.raises((ValueError, ClaudeBridgeError)):
            await adapter.handle(event=invalid)
    assert accepted == []
    await adapter.handle(event=submission)
    await adapter.reset()
    await adapter.handle(event=submission)
    assert accepted == [submission]
    with pytest.raises(ValueError):
        await adapter.handle(
            event=ClaudeToolResultSubmissionDAO(
                invocation_id="i",
                tool_result_batch=ClaudeToolResultBatchDAO(
                    response_id="r",
                    results=(
                        ClaudeToolResultDAO(
                            tool_call_id="c",
                            content=(ClaudeTextDAO(text="changed"),),
                            is_error=False,
                        ),
                    ),
                ),
            )
        )
    assert accepted == [submission]
    await adapter.close()
    await adapter.close()
    with pytest.raises(RuntimeError):
        await adapter.handle(event=submission)


async def test_failed_result_delivery_is_never_replayed_and_does_not_prevent_retirement() -> None:
    """A16/A12: uncertain acceptance stays protected, but settled failure owns no live work."""
    sends: list[ClaudeToolResultSubmissionDAO] = []

    async def receive(submission: ClaudeToolResultSubmissionDAO) -> None:
        """Record a send whose local acceptance is uncertain, then refuse retry."""
        sends.append(submission)
        raise ValueError("synthetic delivery failure")

    adapter = ToolCallResponseAdapter.register(
        binding=ClaudeInteractionBindingDAO(session_id="s", invocation_id="i", binding_version=0),
        expected=ClaudeResponseCompletedDAO(
            session_id="s",
            invocation_id="i",
            response_id="r",
            sequence=1,
            stop_reason="tool_calls",
            tool_calls=(ClaudeToolCallDAO(tool_call_id="c", name="read", arguments={}),),
        ),
        receiver=receive,
    )
    submission = ClaudeToolResultSubmissionDAO(
        invocation_id="i",
        tool_result_batch=ClaudeToolResultBatchDAO(
            response_id="r",
            results=(ClaudeToolResultDAO(tool_call_id="c", content=(), is_error=False),),
        ),
    )
    for _ in range(2):
        with pytest.raises(ValueError, match="synthetic delivery failure"):
            await adapter.handle(event=submission)
    assert sends == [submission]
    await adapter.close()
    await adapter.close()


async def test_result_adapter_validates_whole_set_before_borrowed_receiver() -> None:
    """A8: later bad IDs cannot release earlier valid results; reorder/repeat sends once."""
    accepted: list[ClaudeToolResultSubmissionDAO] = []

    async def receive(submission: ClaudeToolResultSubmissionDAO) -> None:
        """Record complete local acceptance through the supported receiver seam."""
        accepted.append(submission)

    adapter = ToolCallResponseAdapter.register(
        binding=ClaudeInteractionBindingDAO(session_id="s", invocation_id="i", binding_version=0),
        expected=ClaudeResponseCompletedDAO(
            session_id="s",
            invocation_id="i",
            response_id="r",
            sequence=1,
            stop_reason="tool_calls",
            tool_calls=tuple(
                ClaudeToolCallDAO(tool_call_id=i, name="read", arguments={}) for i in ("a", "b")
            ),
        ),
        receiver=receive,
    )
    results = tuple(
        ClaudeToolResultDAO(
            tool_call_id=i,
            content=(ClaudeTextDAO(text=i),),
            is_error=False,
        )
        for i in ("a", "b", "foreign")
    )
    try:
        for invalid in (results[:1], results, (*results[:2], results[1])):
            with pytest.raises((ValueError, ClaudeBridgeError)):
                await adapter.handle(
                    event=ClaudeToolResultSubmissionDAO(
                        invocation_id="i",
                        tool_result_batch=ClaudeToolResultBatchDAO(response_id="r", results=invalid),
                    )
                )
            assert accepted == []
        for ordered in (tuple(reversed(results[:2])), results[:2]):
            await adapter.handle(
                event=ClaudeToolResultSubmissionDAO(
                    invocation_id="i",
                    tool_result_batch=ClaudeToolResultBatchDAO(response_id="r", results=ordered),
                )
            )
        assert len(accepted) == 1
        assert accepted[0].tool_result_batch.results == results[:2]
        with pytest.raises(ValueError, match="conflicts"):
            await adapter.handle(
                event=ClaudeToolResultSubmissionDAO(
                    invocation_id="i",
                    tool_result_batch=ClaudeToolResultBatchDAO(
                        response_id="r",
                        results=(results[0], results[1].model_copy(update={"is_error": True})),
                    ),
                )
            )
        assert len(accepted) == 1
    finally:
        await adapter.close()


@pytest.mark.parametrize("cancel_close", [False, True])
async def test_result_adapter_close_joins_delivery_after_caller_cancellation(cancel_close: bool) -> None:
    """A16: cancelling a caller cannot orphan an admitted result receiver."""
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    accepted: list[ClaudeToolResultSubmissionDAO] = []

    async def receive(submission: ClaudeToolResultSubmissionDAO) -> None:
        """Hold local acceptance until explicitly released by the test."""
        started.set()
        await release.wait()
        accepted.append(submission)
        finished.set()

    adapter = ToolCallResponseAdapter.register(
        binding=ClaudeInteractionBindingDAO(session_id="s", invocation_id="i", binding_version=0),
        expected=ClaudeResponseCompletedDAO(
            session_id="s",
            invocation_id="i",
            response_id="r",
            sequence=1,
            stop_reason="tool_calls",
            tool_calls=(ClaudeToolCallDAO(tool_call_id="c", name="read", arguments={}),),
        ),
        receiver=receive,
    )
    submission = ClaudeToolResultSubmissionDAO(
        invocation_id="i",
        tool_result_batch=ClaudeToolResultBatchDAO(
            response_id="r",
            results=(ClaudeToolResultDAO(tool_call_id="c", content=(), is_error=False),),
        ),
    )
    task = asyncio.create_task(coro=adapter.handle(event=submission))
    closing: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(5):
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            closing = asyncio.create_task(coro=adapter.close())
            await asyncio.sleep(0)
            assert not closing.done() and not finished.is_set()
            if cancel_close:
                closing.cancel()
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                assert not closing.done(), "cancelled close must keep joining its admitted receiver"
                closing.cancel()
                await asyncio.sleep(0)
                assert not closing.done(), "repeated cancellation cannot discard delivery ownership"
            with pytest.raises(RuntimeError, match="closed"):
                await adapter.handle(event=submission)
            release.set()
            if cancel_close:
                with pytest.raises(asyncio.CancelledError):
                    await closing
            else:
                await closing
            assert finished.is_set() and accepted == [submission]
            await adapter.close()
            await adapter.close()
            assert accepted == [submission]
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        if closing is not None:
            await asyncio.gather(closing, return_exceptions=True)
        await adapter.close()
