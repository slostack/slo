"""Tests for feature-69 image result tracing into durable history."""
from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage
from PIL import Image

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.compaction.token_estimator import TokenEstimator
from src.agents.slo_agent.events.runtime import AgentRuntimeEventDAO
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.tool_execution.dao import ToolCallEnvelopeDAO, ToolConcurrencyClass
from src.agents.slo_agent.tool_execution.executors import SequentialToolExecutor
from src.agents.tools._image_content import IMAGE_MAX_EDGE, MAX_ENCODED_BYTES
from src.agents.tools.read import read_tool


_IMAGE_REFERENCE: str = "[image attached: large.jpg, 1568x1045, ref /abs/path/large.jpg]"


def _stub_agent() -> SloAgent:
    """Create the minimal agent state consumed by the tracing helper."""
    agent: SloAgent = object.__new__(SloAgent)
    agent._current_iteration = 0  # type: ignore[attr-defined]
    return agent


def _image_tool_message(*, image_reference: str = _IMAGE_REFERENCE) -> ToolMessage:
    """Build the image ToolMessage shape produced by the production executor."""
    return ToolMessage(
        content=[
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": "aGVsbG8=",
                },
            }
        ],
        name="read",
        tool_call_id="tc_001",
        additional_kwargs={"image_reference": image_reference},
    )


def _persisted_tool_result(*, tool_output: str) -> SessionHistoryEventDAO:
    """Build a minimal persisted event for the unmodified token estimator."""
    return SessionHistoryEventDAO(
        session_id="test_session",
        kind="tool_result",
        payload=SessionHistoryEventPayloadDAO(
            tool_name="read",
            tool_call_id="tc_001",
            tool_output=tool_output,
        ),
    )


@pytest.mark.asyncio
async def test_large_image_executor_trace_persists_reference_not_base64(tmp_path: Path) -> None:
    """The real image path preserves vision live while history stores its reference."""
    target: Path = tmp_path / "large.png"
    Image.new("RGB", (3000, 2000), color="red").save(target, format="PNG")
    executor = SequentialToolExecutor(tools_by_name={"read": read_tool})
    envelope = ToolCallEnvelopeDAO(
        source_index=0,
        call={"id": "tc_img", "name": "read", "args": {"path": str(target)}},
        concurrency_class=ToolConcurrencyClass.READ_ONLY,
    )

    _, message = await executor._invoke_one(envelope=envelope)
    reference: str = message.additional_kwargs["image_reference"]
    data: str = message.content[0]["source"]["data"]
    decoded: bytes = base64.b64decode(data)

    with Image.open(BytesIO(decoded)) as live_image:
        assert max(live_image.size) <= IMAGE_MAX_EDGE
    assert len(data) <= MAX_ENCODED_BYTES

    events: list[AgentRuntimeEventDAO] = _stub_agent()._trace_events_from_message(message=message)

    assert events[0].payload.tool_output == reference
    assert "base64" not in (events[0].payload.tool_output or "")
    assert len(events[0].payload.tool_output or "") < 200
    assert TokenEstimator.estimate(event=_persisted_tool_result(tool_output=reference)) < 50


def test_trace_image_tool_message_uses_image_reference() -> None:
    """Tracing uses the canonical image_reference instead of multimodal base64 content."""
    events: list[AgentRuntimeEventDAO] = _stub_agent()._trace_events_from_message(
        message=_image_tool_message()
    )

    assert events[0].kind == "tool_result"
    assert events[0].payload.tool_output == _IMAGE_REFERENCE
    assert "aGVsbG8=" not in (events[0].payload.tool_output or "")


def test_trace_text_tool_message_preserves_text_content() -> None:
    """Tracing preserves text results when no image_reference is present."""
    message = ToolMessage(content="hello world from the tool", name="read", tool_call_id="tc_002")

    events: list[AgentRuntimeEventDAO] = _stub_agent()._trace_events_from_message(message=message)

    assert events[0].payload.tool_output == "hello world from the tool"


def test_token_estimator_counts_image_reference_as_small_output() -> None:
    """The existing estimator charges only a small number of tokens for a reference."""
    assert TokenEstimator.estimate(event=_persisted_tool_result(tool_output=_IMAGE_REFERENCE)) < 50


def test_token_estimator_would_count_base64_as_large_output() -> None:
    """The regression fixture proves why durable base64 must not be persisted."""
    large_data: str = "A" * (5 * 1024 * 1024)

    assert TokenEstimator.estimate(event=_persisted_tool_result(tool_output=large_data)) > 1_000_000
