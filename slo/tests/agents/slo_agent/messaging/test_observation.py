"""Real session observation authority, application evidence and bounded buffering (DC03)."""

from uuid import uuid4
import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.messaging.dao import (
    MessageAdmissionError,
    MessagePrincipalDAO,
    MessageReceiptDAO,
    MessageSubmissionDAO,
)
from tests.tui.test_durable_composer import _build_factory_session
from tests.agents.slo_agent.messaging.test_delivery import RecordingModel


@pytest.mark.asyncio
async def test_observation_authority_single_stream_and_close(tmp_path: Path) -> None:
    """A registered stream excludes competitors; detaching cannot stop execution."""
    model = RecordingModel(responses=[AIMessage(content="answer")])
    session = _build_factory_session(tmp_path=tmp_path, model=model)
    await session.start_messaging()
    owner = session.messaging_owner_principal
    stream = session.observe_messaging(principal=owner)
    try:
        first = await anext(stream)
        assert first.revision == 1
        assert first.application is None
        assert first.target == session.messaging_target
        other = session.observe_messaging(principal=owner)
        with pytest.raises(MessageAdmissionError) as conflict:
            await anext(other)
        assert conflict.value.error.code == "conflict"
        foreign = session.observe_messaging(
            principal=MessagePrincipalDAO(principal_id="foreign", kind="human")
        )
        with pytest.raises(MessageAdmissionError) as unauthorized:
            await anext(foreign)
        assert unauthorized.value.error.code == "unauthorized"
        await stream.aclose()
        stream = session.observe_messaging(principal=owner)
        await anext(stream)
        receipt = await session.admit_message(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()),
                kind="agent_input",
                target=session.messaging_target,
                text="observed input",
            ),
            principal=owner,
        )
        assert isinstance(receipt, MessageReceiptDAO)
        async with asyncio.timeout(5):
            while True:
                observation = await anext(stream)
                if observation.application is not None:
                    break
        assert observation.revision > first.revision
        assert observation.application.payload.content == "observed input"
        assert observation.application.payload.metadata["messaging_v1"]["message_id"] == receipt.message_id
        await stream.aclose()
        # The detached iterator does not own or cancel the held model run.
        await asyncio.wait_for(model.entered.wait(), timeout=5)
        assert session.is_running
        stream = session.observe_messaging(principal=owner)
        await anext(stream)
        model.release.set()
        await session.close_messaging()
        with pytest.raises(MessageAdmissionError) as completing:
            await anext(stream)
        assert completing.value.error.code == "completing"
    finally:
        model.release.set()
        await stream.aclose()
        await session.close_messaging()


@pytest.mark.asyncio
@pytest.mark.parametrize(argnames="limit", argvalues=["count", "bytes"])
async def test_overflow_raises_replay_gap(tmp_path: Path, limit: str) -> None:
    """Real settled idle-note applications overflow either bound, never silently dropping evidence."""
    session = _build_factory_session(
        tmp_path=tmp_path, model=RecordingModel(responses=[AIMessage(content="answer")])
    )
    await session.start_messaging()
    owner = session.messaging_owner_principal
    stream = session.observe_messaging(principal=owner)
    await anext(stream)
    try:
        count = 257 if limit == "count" else 18
        text = "note" if limit == "count" else "x" * 60000
        for index in range(count):
            submission = MessageSubmissionDAO(
                message_id=str(uuid4()), target=session.messaging_target, kind="transcript_note", text=text
            )
            receipt = await session.admit_message(submission=submission, principal=owner)
            assert isinstance(receipt, MessageReceiptDAO)
            # Read through the session authority until the real SQLite application settles.
            async with asyncio.timeout(5):
                while True:
                    receipt = await session.get_message_receipt(
                        message_id=submission.message_id, target=session.messaging_target, principal=owner
                    )
                    if isinstance(receipt, MessageReceiptDAO) and receipt.state == "applied":
                        break
                    await asyncio.sleep(0.001)
        with pytest.raises(MessageAdmissionError) as gap:
            await anext(stream)
        assert gap.value.error.code == "replay_gap"
        # Replacement registration precedes barrier replay; all real IDs remain recoverable.
        replacement = session.observe_messaging(principal=owner)
        await anext(replacement)
        entries = await session.hydrate_transcript_entries()
        assert len(entries) == count
        assert (
            len({entry.application.message_id for entry in entries if entry.application is not None}) == count
        )
        await replacement.aclose()
    finally:
        await stream.aclose()
        await session.close_messaging()


@pytest.mark.asyncio
async def test_cancelled_observation_detaches_and_barrier_replay_waits(tmp_path: Path) -> None:
    """Cancellation releases the single slot; hydration cannot cross an active history writer."""
    session = _build_factory_session(tmp_path=tmp_path, model=RecordingModel(responses=[]))
    await session.start_messaging()
    stream = session.observe_messaging(principal=session.messaging_owner_principal)
    await anext(stream)
    waiter = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    replacement = session.observe_messaging(principal=session.messaging_owner_principal)
    await anext(replacement)
    try:
        async with session._history_barrier:
            read = asyncio.create_task(session.hydrate_transcript_entries())
            await asyncio.sleep(0)
            assert not read.done()
        assert await asyncio.wait_for(read, timeout=5) == []
    finally:
        await replacement.aclose()
        await session.close_messaging()
