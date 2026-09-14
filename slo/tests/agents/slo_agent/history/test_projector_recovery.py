"""Tests for LLM-driven recovery kinds in ``SessionHistoryProjector`` (sub-spec 50.a.2)."""

from __future__ import annotations

import pytest

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.projector import SessionHistoryProjector


def _make_event(
    kind: str,
    content: str | None = None,
    error_message: str | None = None,
    session_id: str = "s1",
    turn_id: str = "t1",
) -> SessionHistoryEventDAO:
    """Build a ``SessionHistoryEventDAO`` for recovery projector tests."""
    return SessionHistoryEventDAO(
        session_id=session_id,
        turn_id=turn_id,
        kind=kind,  # type: ignore[arg-type]
        payload=SessionHistoryEventPayloadDAO(
            content=content,
            error_message=error_message,
        ),
    )


class TestProjectorRecoveryKinds:
    """``SessionHistoryProjector`` behaviour for feature-50 recovery event kinds."""

    @pytest.mark.asyncio
    async def test_projector_excludes_run_recovering_from_context(self) -> None:
        """``run_recovering`` must not appear in the rebuilt message history."""
        events = [
            _make_event(kind="run_recovering", error_message="tool failed: permission denied"),
            _make_event(kind="assistant_message", content="I will try a different approach."),
            _make_event(kind="run_completed"),
        ]
        messages = await SessionHistoryProjector.build_message_history(events=events)
        # No message should reference the error_message from run_recovering.
        for msg in messages:
            assert "permission denied" not in str(msg.content)
        # The assistant reply must still be present.
        assert any(isinstance(m, AIMessage) for m in messages)

    @pytest.mark.asyncio
    async def test_projector_rebuilds_recovery_observation_as_human_message(self) -> None:
        """``recovery_observation`` must be projected as a ``HumanMessage``."""
        events = [
            _make_event(kind="recovery_observation", content="obs text"),
            _make_event(kind="assistant_message", content="Got it."),
            _make_event(kind="run_completed"),
        ]
        messages = await SessionHistoryProjector.build_message_history(events=events)
        human_messages = [m for m in messages if isinstance(m, HumanMessage)]
        assert any(
            m.content == "obs text" for m in human_messages
        ), f"Expected a HumanMessage with content='obs text'; got {messages}"

    @pytest.mark.asyncio
    async def test_projector_recovery_observation_round_trips_with_assistant_response(
        self,
    ) -> None:
        """user_message → recovery_observation → assistant_message projects in order."""
        events = [
            _make_event(kind="user_message", content="do the thing"),
            _make_event(kind="recovery_observation", content="recovery note"),
            _make_event(kind="assistant_message", content="done"),
            _make_event(kind="run_completed"),
        ]
        messages = await SessionHistoryProjector.build_message_history(events=events)
        assert len(messages) == 3
        assert isinstance(messages[0], HumanMessage), f"Expected HumanMessage, got {type(messages[0])}"
        assert isinstance(messages[1], HumanMessage), f"Expected HumanMessage, got {type(messages[1])}"
        assert isinstance(messages[2], AIMessage), f"Expected AIMessage, got {type(messages[2])}"

    @pytest.mark.asyncio
    async def test_history_event_kind_additive_parse_safety(self) -> None:
        """A turn with no recovery kinds projects identically to the pre-feature baseline."""
        events = [
            _make_event(kind="user_message", content="hello"),
            _make_event(kind="assistant_message", content="world"),
            _make_event(kind="run_completed"),
        ]
        messages = await SessionHistoryProjector.build_message_history(events=events)
        assert messages, "Expected at least one message"
        assert isinstance(
            messages[0], HumanMessage
        ), f"First message should be HumanMessage; got {type(messages[0])}"

    @pytest.mark.asyncio
    async def test_recovery_observation_excluded_when_turn_incomplete(self) -> None:
        """An incomplete turn (no terminal event) must be excluded from model context."""
        events = [
            _make_event(kind="recovery_observation", content="partial obs"),
            # No run_completed / run_aborted / run_failed — turn is incomplete.
        ]
        messages = await SessionHistoryProjector.build_message_history(events=events)
        assert messages == [], f"Incomplete turn should produce no messages; got {messages}"

    @pytest.mark.asyncio
    async def test_recovery_observation_replayed_on_run_failed_terminated_turn(self) -> None:
        """``recovery_observation`` is included when the turn terminated with ``run_failed``.

        On the exhausted-recovery path the observation survives into resumed
        context so the model can reason about what was attempted.
        """
        events = [
            _make_event(kind="recovery_observation", content="last obs before failure"),
            _make_event(kind="run_failed", error_message="budget exhausted"),
        ]
        messages = await SessionHistoryProjector.build_message_history(events=events)
        human_messages = [m for m in messages if isinstance(m, HumanMessage)]
        assert any(
            m.content == "last obs before failure" for m in human_messages
        ), f"Expected HumanMessage with obs content in {messages}"

    def test_stream_event_kind_includes_recovery_kinds(self) -> None:
        """``StreamEventKind`` must include all three feature-50 recovery kinds."""
        # Import the Literal type args at runtime via __args__.
        from src.agents.slo_agent.events.stream import StreamEventKind

        kind_args: tuple[str, ...] = StreamEventKind.__args__  # type: ignore[attr-defined]
        assert "recovery_started" in kind_args, "recovery_started missing from StreamEventKind"
        assert "recovery_succeeded" in kind_args, "recovery_succeeded missing from StreamEventKind"
        assert "recovery_exhausted" in kind_args, "recovery_exhausted missing from StreamEventKind"

    def test_is_terminal_unchanged(self) -> None:
        """Recovery stream kinds must NOT be terminal events."""
        from src.agents.slo_agent.events.stream import AgentStreamEventDAO

        for kind in ("recovery_started", "recovery_succeeded", "recovery_exhausted"):
            event = AgentStreamEventDAO(kind=kind)  # type: ignore[arg-type]
            assert event.is_terminal is False, f"is_terminal should be False for kind={kind!r}; got True"
