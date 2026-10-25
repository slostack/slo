"""Tests for ``TokenEstimator``."""

from __future__ import annotations

import math
from typing import Optional
from uuid import UUID, uuid4, uuid5

from langchain_core.messages import BaseMessage

import pytest

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.compaction.token_estimator import TokenEstimator
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.messaging.dao import MessageApplicationMetadataDAO, MessagePrincipalDAO


def _event(*, kind: str, **payload_kwargs) -> SessionHistoryEventDAO:
    """Build a minimal event for testing.

    Args:
        kind (str): Event kind.
        **payload_kwargs: Payload field overrides.

    Returns:
        SessionHistoryEventDAO: Test event.
    """
    return SessionHistoryEventDAO(
        session_id="test-session",
        kind=kind,  # type: ignore[arg-type]
        payload=SessionHistoryEventPayloadDAO(**payload_kwargs),
    )


class TestEstimateUserMessage:
    """``user_message`` and ``steering_message`` events."""

    def test_user_message_uses_content_length(self) -> None:
        content = "hello world"
        event = _event(kind="user_message", content=content)
        assert TokenEstimator.estimate(event=event) == math.ceil(len(content) / 4)

    def test_steering_message_uses_content_length(self) -> None:
        content = "steer the agent"
        event = _event(kind="steering_message", content=content)
        assert TokenEstimator.estimate(event=event) == math.ceil(len(content) / 4)

    def test_empty_user_message_returns_zero(self) -> None:
        event = _event(kind="user_message", content="")
        assert TokenEstimator.estimate(event=event) == 0

    def test_none_content_returns_zero(self) -> None:
        event = _event(kind="user_message")
        assert TokenEstimator.estimate(event=event) == 0


class TestEstimateAssistantMessage:
    """``assistant_message`` events — text, thinking, tool-calls."""

    def test_text_only_uses_content(self) -> None:
        content = "I will help you."
        event = _event(kind="assistant_message", content=content)
        assert TokenEstimator.estimate(event=event) == math.ceil(len(content) / 4)

    def test_with_thinking_adds_thinking_chars(self) -> None:
        content = "answer"
        thinking = "let me think..."
        event = SessionHistoryEventDAO(
            session_id="s",
            kind="assistant_message",
            payload=SessionHistoryEventPayloadDAO(
                content=content,
                metadata={"thinking": thinking},
            ),
        )
        expected = math.ceil((len(content) + len(thinking)) / 4)
        assert TokenEstimator.estimate(event=event) == expected

    def test_with_tool_calls_adds_serialised_args(self) -> None:
        args = {"path": "/tmp/file.txt", "limit": 100}
        import json

        tool_calls = [{"name": "read", "args": args, "id": "tc1", "type": "tool_call"}]
        event = _event(kind="assistant_message", content="", tool_calls=tool_calls)
        expected = math.ceil(len(json.dumps(args, ensure_ascii=False)) / 4)
        assert TokenEstimator.estimate(event=event) == expected

    def test_non_string_thinking_metadata_ignored(self) -> None:
        event = SessionHistoryEventDAO(
            session_id="s",
            kind="assistant_message",
            payload=SessionHistoryEventPayloadDAO(
                content="hi",
                metadata={"thinking": 42},
            ),
        )
        assert TokenEstimator.estimate(event=event) == math.ceil(len("hi") / 4)


class TestEstimateToolCall:
    """``tool_call`` events."""

    def test_tool_call_serialised_args_counted(self) -> None:
        import json

        args = {"command": "ls -la"}
        tool_calls = [{"name": "bash", "args": args, "id": "tc2", "type": "tool_call"}]
        event = _event(kind="tool_call", content="", tool_calls=tool_calls)
        expected = math.ceil(len(json.dumps(args, ensure_ascii=False)) / 4)
        assert TokenEstimator.estimate(event=event) == expected

    def test_tool_call_fallback_to_tool_input(self) -> None:
        import json

        tool_input = {"path": "/etc/hosts"}
        event = _event(kind="tool_call", tool_input=tool_input)
        expected = math.ceil(len(json.dumps(tool_input, ensure_ascii=False)) / 4)
        assert TokenEstimator.estimate(event=event) == expected


class TestEstimateToolResult:
    """``tool_result`` events."""

    def test_tool_result_uses_tool_output(self) -> None:
        output = "total 0\n-rw-r--r-- 1 user staff 0 Jan 1 file.txt"
        event = _event(kind="tool_result", tool_output=output)
        assert TokenEstimator.estimate(event=event) == math.ceil(len(output) / 4)

    def test_empty_tool_result_returns_zero(self) -> None:
        event = _event(kind="tool_result", tool_output="")
        assert TokenEstimator.estimate(event=event) == 0


class TestEstimateLifecycleEvents:
    """Lifecycle-only events return zero tokens."""

    @pytest.mark.parametrize(
        "kind",
        [
            "session_started",
            "run_started",
            "run_completed",
            "run_aborted",
            "run_failed",
            "run_retrying",
            "route_switched",
            "slash_command",
            "orchestrator_started",
            "sub_agent_spawned",
            "sub_agent_completed",
        ],
    )
    def test_lifecycle_event_returns_zero(self, kind: str) -> None:
        event = _event(kind=kind, content="ignored content")  # type: ignore[arg-type]
        assert TokenEstimator.estimate(event=event) == 0


class TestEstimateAssistantDelta:
    """``assistant_delta`` events use the delta field."""

    def test_delta_uses_delta_field(self) -> None:
        delta = "partial text chunk"
        event = _event(kind="assistant_delta", delta=delta)
        assert TokenEstimator.estimate(event=event) == math.ceil(len(delta) / 4)


class TestEstimateMessageApplication:
    """Canonical messaging estimates follow the actual shared context formatter."""

    @pytest.mark.parametrize(argnames="sender_kind", argvalues=["human", "agent", "workflow", "scheduler"])
    @pytest.mark.parametrize(argnames="kind", argvalues=["agent_input", "context_note", "transcript_note"])
    def test_canonical_application_counts_projected_context(self, sender_kind: str, kind: str) -> None:
        """Count provenance quotation overhead, but no transcript-only content."""
        session_id: str = str(uuid4())
        message_id: str = str(uuid4())
        metadata: MessageApplicationMetadataDAO = MessageApplicationMetadataDAO.model_validate(
            {
                "message_id": message_id,
                "kind": kind,
                "sender": MessagePrincipalDAO.model_validate(
                    {"principal_id": "original-author", "kind": sender_kind}
                ),
                "sequence": 1,
                "run_id": str(uuid4()),
                "execution_generation": str(uuid4()),
            }
        )
        event: SessionHistoryEventDAO = SessionHistoryEventDAO(
            event_id=str(uuid5(namespace=UUID(session_id), name="message:" + message_id)),
            session_id=session_id,
            kind="workflow_update",
            turn_id=metadata.run_id,
            payload=SessionHistoryEventPayloadDAO(
                content="Exact accepted text.", metadata={"messaging_v1": metadata.model_dump(mode="json")}
            ),
        )
        projected: Optional[BaseMessage] = SessionHistoryProjector.project_message_application(event=event)
        expected: int = math.ceil(len(projected.text()) / 4) if projected is not None else 0
        assert TokenEstimator.estimate(event=event) == expected
        if kind == "transcript_note":
            assert expected == 0
        elif sender_kind != "human":
            assert expected > math.ceil(len(event.payload.content or "") / 4)

    def test_legacy_workflow_update_keeps_existing_zero_estimate(self) -> None:
        """The narrow accounting repair does not change legacy event policy."""
        event: SessionHistoryEventDAO = SessionHistoryEventDAO(
            session_id="legacy",
            kind="workflow_update",
            payload=SessionHistoryEventPayloadDAO(content="Legacy workflow notice"),
        )
        assert TokenEstimator.estimate(event=event) == 0


class TestEstimateCompactionSummary:
    """``compaction_summary`` events use payload.content."""

    def test_compaction_summary_uses_content(self) -> None:
        content = "The assistant read foo.py and edited bar.py."
        event = _event(kind="compaction_summary", content=content)
        assert TokenEstimator.estimate(event=event) == math.ceil(len(content) / 4)

    def test_empty_compaction_summary_returns_zero(self) -> None:
        event = _event(kind="compaction_summary", content="")
        assert TokenEstimator.estimate(event=event) == 0
