"""Tests for RecoveryObservationBuilder (Feature 50, sub-spec 50.a.1)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.slo_agent.recovery.dao import RecoveryClass, RecoveryDecisionDAO
from src.agents.slo_agent.recovery.service import RecoveryObservationBuilder


def _llm_recoverable_decision(*, hint: str | None = None) -> RecoveryDecisionDAO:
    """Build a canned LLM_RECOVERABLE decision for observation builder tests."""
    return RecoveryDecisionDAO(
        recovery_class=RecoveryClass.LLM_RECOVERABLE,
        reason="RuntimeError may be recoverable by the model.",
        observation_hint=hint,
    )


class TestRecoveryObservationBuilderContent:
    """Core message content is correct for various inputs."""

    def test_build_returns_human_message_with_error_text(self) -> None:
        """Result is a HumanMessage and contains the exception type and text."""
        exc = RuntimeError("disk quota exceeded")
        decision = _llm_recoverable_decision()

        result = RecoveryObservationBuilder.build(
            exc=exc,
            decision=decision,
            accumulated_messages=[],
        )

        assert isinstance(result, HumanMessage)
        assert "RuntimeError" in str(result.content)
        assert "disk quota exceeded" in str(result.content)

    def test_build_appends_hint_when_present(self) -> None:
        """A decision with observation_hint set includes the hint in content."""
        exc = TimeoutError("timed out after 30s")
        decision = _llm_recoverable_decision(hint="Try a smaller step next time.")

        result = RecoveryObservationBuilder.build(
            exc=exc,
            decision=decision,
            accumulated_messages=[],
        )

        assert "Try a smaller step next time." in str(result.content)

    def test_build_no_hint_when_none(self) -> None:
        """A decision with observation_hint=None adds no extra line to content."""
        exc = RuntimeError("something failed")
        decision = _llm_recoverable_decision(hint=None)

        result = RecoveryObservationBuilder.build(
            exc=exc,
            decision=decision,
            accumulated_messages=[],
        )

        # The body ends at the "stop." sentence with no trailing hint line.
        content = str(result.content)
        assert content.endswith("explain why and stop.")

    def test_build_contains_recovery_instruction(self) -> None:
        """The body always includes the 'Analyze whether you can recover' instruction."""
        exc = RuntimeError("oops")
        decision = _llm_recoverable_decision()

        result = RecoveryObservationBuilder.build(
            exc=exc,
            decision=decision,
            accumulated_messages=[],
        )

        assert "Analyze whether you can recover" in str(result.content)


class TestRecoveryObservationBuilderCoalescence:
    """Message coalescing behaviour when accumulated_messages has a trailing HumanMessage."""

    def test_build_coalesces_into_trailing_human_message(self) -> None:
        """When accumulated_messages[-1] is HumanMessage, result starts with prior text."""
        prior_msg = HumanMessage(content="What is the capital of France?")
        exc = RuntimeError("tool call failed")
        decision = _llm_recoverable_decision()

        result = RecoveryObservationBuilder.build(
            exc=exc,
            decision=decision,
            accumulated_messages=[prior_msg],
        )

        assert isinstance(result, HumanMessage)
        content = str(result.content)
        assert content.startswith("What is the capital of France?")
        assert "RuntimeError" in content

    def test_build_appends_new_message_after_assistant_turn(self) -> None:
        """Trailing AIMessage → a fresh HumanMessage with only the body."""
        ai_msg = AIMessage(content="I found the file you asked for.")
        exc = RuntimeError("write failed")
        decision = _llm_recoverable_decision()

        result = RecoveryObservationBuilder.build(
            exc=exc,
            decision=decision,
            accumulated_messages=[ai_msg],
        )

        assert isinstance(result, HumanMessage)
        # Must NOT start with the assistant text.
        content = str(result.content)
        assert "I found the file" not in content
        assert "RuntimeError" in content

    def test_build_empty_accumulated_messages(self) -> None:
        """An empty accumulated_messages list produces a fresh HumanMessage."""
        exc = RuntimeError("nothing in context yet")
        decision = _llm_recoverable_decision()

        result = RecoveryObservationBuilder.build(
            exc=exc,
            decision=decision,
            accumulated_messages=[],
        )

        assert isinstance(result, HumanMessage)
        assert "RuntimeError" in str(result.content)

    def test_build_handles_list_content_trailing_message(self) -> None:
        """HumanMessage with list content does not raise and coalesces cleanly."""
        # Some providers represent multimodal content as a list of dicts.
        prior_msg = HumanMessage(content=[{"type": "text", "text": "Summarise this image."}])
        exc = RuntimeError("vision API failed")
        decision = _llm_recoverable_decision()

        # Should not raise; the list content is coerced to str.
        result = RecoveryObservationBuilder.build(
            exc=exc,
            decision=decision,
            accumulated_messages=[prior_msg],
        )

        assert isinstance(result, HumanMessage)
        content = str(result.content)
        assert "RuntimeError" in content
