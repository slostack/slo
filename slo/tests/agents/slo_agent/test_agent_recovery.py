"""Tests for the LLM-driven recovery layer in ``SloAgent._react_loop`` (Feature 50, sub-spec 50.a.3)."""

from __future__ import annotations

from typing import AsyncIterator, Optional

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGenerationChunk

from src.agents.providers import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.recovery.dao import RecoveryClass, RecoveryDecisionDAO
from src.agents.slo_agent.recovery.service import IterationRecoveryPolicy

# ── helpers ──────────────────────────────────────────────────────────────────


def _recoverable_policy() -> IterationRecoveryPolicy:
    """Return a policy that always says LLM_RECOVERABLE.

    Returns:
        IterationRecoveryPolicy: Always-recoverable policy.
    """

    def _decide(exc: BaseException, recoveries_used: int) -> RecoveryDecisionDAO:
        return RecoveryDecisionDAO(
            recovery_class=RecoveryClass.LLM_RECOVERABLE,
            reason="Test: always recoverable.",
        )

    return _decide


def _fatal_policy() -> IterationRecoveryPolicy:
    """Return a policy that always says FATAL.

    Returns:
        IterationRecoveryPolicy: Always-fatal policy.
    """

    def _decide(exc: BaseException, recoveries_used: int) -> RecoveryDecisionDAO:
        return RecoveryDecisionDAO(
            recovery_class=RecoveryClass.FATAL,
            reason="Test: always fatal.",
        )

    return _decide


def _mechanical_policy() -> IterationRecoveryPolicy:
    """Return a policy that always says MECHANICAL.

    Returns:
        IterationRecoveryPolicy: Always-mechanical policy.
    """

    def _decide(exc: BaseException, recoveries_used: int) -> RecoveryDecisionDAO:
        return RecoveryDecisionDAO(
            recovery_class=RecoveryClass.MECHANICAL,
            reason="Test: always mechanical.",
        )

    return _decide


def _kinds(events: list[AgentStreamEventDAO]) -> list[str]:
    """Extract the ``kind`` field from each event.

    Args:
        events (list[AgentStreamEventDAO]): Collected events.

    Returns:
        list[str]: Ordered list of kind strings.
    """
    return [e.kind for e in events]


def _make_fail_once_faux(
    *,
    responses: list,
    raise_on_first: list[bool],
    seen_messages: Optional[list[list]] = None,
) -> FauxChatModel:
    """Build a FauxChatModel subclass that raises on the first _astream call.

    Args:
        responses (list): Scripted responses for the backing FauxChatModel.
        raise_on_first (list[bool]): Single-element mutable flag; cleared on first raise.
        seen_messages (Optional[list[list]]): If provided, each call's messages are appended.

    Returns:
        FauxChatModel: A one-failure FauxChatModel instance.
    """
    base = FauxChatModel(responses=responses)

    class _FailOnceFaux(FauxChatModel):
        def __init__(self, *, responses: list[AIMessage]) -> None:
            """Initialize the scripted queue used by the recovery fixture."""
            super().__init__(responses=responses)

        async def _astream(
            self,
            messages,
            stop=None,
            run_manager=None,
            **kwargs,
        ) -> AsyncIterator[ChatGenerationChunk]:
            if seen_messages is not None:
                seen_messages.append(list(messages))
            if raise_on_first[0]:
                raise_on_first[0] = False
                raise RuntimeError("transient failure")
            async for chunk in base._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                yield chunk

    return _FailOnceFaux(responses=responses)


def _make_always_fail_faux() -> FauxChatModel:
    """Build a FauxChatModel that always raises on _astream.

    Returns:
        FauxChatModel: Always-failing FauxChatModel instance.
    """

    class _AlwaysFailFaux(FauxChatModel):
        def __init__(self, *, responses: list[AIMessage]) -> None:
            """Initialize the scripted queue used by the recovery fixture."""
            super().__init__(responses=responses)

        async def _astream(
            self,
            messages,
            stop=None,
            run_manager=None,
            **kwargs,
        ) -> AsyncIterator[ChatGenerationChunk]:
            raise RuntimeError("persistent failure")
            # pragma: no cover — generator protocol requires at least one yield
            yield ChatGenerationChunk(
                message=AIMessageChunk(content=""),
            )

    return _AlwaysFailFaux(responses=[])


def _make_fail_n_times_faux(*, fail_count: int, responses: list) -> FauxChatModel:
    """Build a FauxChatModel that raises on the first ``fail_count`` _astream calls.

    Args:
        fail_count (int): Number of initial calls that raise RuntimeError.
        responses (list): Scripted responses returned after failures.

    Returns:
        FauxChatModel: N-failure FauxChatModel instance.
    """
    call_count: list[int] = [0]
    base = FauxChatModel(responses=responses)

    class _FailNFaux(FauxChatModel):
        def __init__(self, *, responses: list[AIMessage]) -> None:
            """Initialize the scripted queue used by the recovery fixture."""
            super().__init__(responses=responses)

        async def _astream(
            self,
            messages,
            stop=None,
            run_manager=None,
            **kwargs,
        ) -> AsyncIterator[ChatGenerationChunk]:
            call_count[0] += 1
            if call_count[0] <= fail_count:
                raise RuntimeError(f"failure #{call_count[0]}")
            async for chunk in base._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                yield chunk

    return _FailNFaux(responses=responses)


# ── tests ─────────────────────────────────────────────────────────────────────


class TestRecoverableErrorRecovery:
    """``LLM_RECOVERABLE`` path within budget."""

    async def test_recoverable_error_on_first_iteration_recovers_then_completes(
        self,
    ) -> None:
        """A recoverable exception -> recovery_started -> recovery_succeeded -> run_completed."""
        raise_on_first: list[bool] = [True]
        agent = SloAgent(
            llm=_make_fail_once_faux(
                responses=[FauxChatModel.assistant_message(content="recovered!")],
                raise_on_first=raise_on_first,
            ),
            tools=[],
        )
        events: list[AgentStreamEventDAO] = []
        async for event in agent.invoke(
            query="test",
            iteration_recovery_policy=_recoverable_policy(),
        ):
            events.append(event)

        kinds = _kinds(events)
        assert "recovery_started" in kinds
        assert "recovery_succeeded" in kinds
        assert "run_completed" in kinds
        assert "run_failed" not in kinds

    async def test_observation_appended_to_context_exactly_once(self) -> None:
        """After a recovery, the next iteration request includes exactly one observation."""
        seen_messages: list[list] = []
        raise_on_first: list[bool] = [True]
        agent = SloAgent(
            llm=_make_fail_once_faux(
                responses=[FauxChatModel.assistant_message(content="recovered")],
                raise_on_first=raise_on_first,
                seen_messages=seen_messages,
            ),
            tools=[],
        )
        async for _ in agent.invoke(
            query="test",
            iteration_recovery_policy=_recoverable_policy(),
        ):
            pass

        # The second call (recovery iteration) should have received the
        # observation as the last message.
        assert len(seen_messages) == 2
        recovery_context = seen_messages[1]
        assert any(isinstance(m, HumanMessage) and "RuntimeError" in str(m.content) for m in recovery_context)

    async def test_recovery_succeeded_emitted_exactly_once_after_recovery(
        self,
    ) -> None:
        """``recovery_succeeded`` is emitted exactly once even with one recovery."""
        raise_on_first: list[bool] = [True]
        agent = SloAgent(
            llm=_make_fail_once_faux(
                responses=[FauxChatModel.assistant_message(content="ok")],
                raise_on_first=raise_on_first,
            ),
            tools=[],
        )
        events: list[AgentStreamEventDAO] = []
        async for event in agent.invoke(
            query="test",
            iteration_recovery_policy=_recoverable_policy(),
        ):
            events.append(event)

        succeeded = [e for e in events if e.kind == "recovery_succeeded"]
        assert len(succeeded) == 1


class TestBudgetExhaustion:
    """Budget guard — once spent, next error emits ``recovery_exhausted`` + ``run_failed``."""

    async def test_budget_exhaustion_emits_recovery_exhausted_then_run_failed(
        self,
    ) -> None:
        """With budget=1 and two consecutive failures -> exhausted path."""
        agent = SloAgent(
            llm=_make_always_fail_faux(),
            tools=[],
        )
        agent._recovery_budget = 1
        events: list[AgentStreamEventDAO] = []
        raised: list[Exception] = []
        try:
            async for event in agent.invoke(
                query="test",
                iteration_recovery_policy=_recoverable_policy(),
            ):
                events.append(event)
        except Exception as exc:  # noqa: BLE001
            raised.append(exc)

        kinds = _kinds(events)
        assert "recovery_started" in kinds
        assert "recovery_exhausted" in kinds
        assert "run_failed" in kinds
        assert len(raised) == 1
        # exhausted appears BEFORE run_failed
        assert kinds.index("recovery_exhausted") < kinds.index("run_failed")

    async def test_no_recovery_exhausted_on_first_failure_with_no_prior_recovery(
        self,
    ) -> None:
        """FATAL on first failure with no prior recovery -> no ``recovery_exhausted``."""
        agent = SloAgent(
            llm=_make_always_fail_faux(),
            tools=[],
        )
        events: list[AgentStreamEventDAO] = []
        try:
            async for event in agent.invoke(
                query="test",
                iteration_recovery_policy=_fatal_policy(),
            ):
                events.append(event)
        except Exception:  # noqa: BLE001
            pass

        kinds = _kinds(events)
        assert "recovery_exhausted" not in kinds
        assert "run_failed" in kinds


class TestFatalAndMechanicalErrors:
    """FATAL and MECHANICAL decisions are never LLM-recovered."""

    async def test_fatal_error_is_not_recovered(self) -> None:
        """FATAL decision -> no recovery_started; only run_failed."""
        agent = SloAgent(
            llm=_make_always_fail_faux(),
            tools=[],
        )
        events: list[AgentStreamEventDAO] = []
        try:
            async for event in agent.invoke(
                query="test",
                iteration_recovery_policy=_fatal_policy(),
            ):
                events.append(event)
        except Exception:  # noqa: BLE001
            pass

        kinds = _kinds(events)
        assert "recovery_started" not in kinds
        assert "run_failed" in kinds

    async def test_mechanical_error_is_not_recovered_by_llm_layer(self) -> None:
        """MECHANICAL decision -> not LLM-recovered; only run_failed."""
        agent = SloAgent(
            llm=_make_always_fail_faux(),
            tools=[],
        )
        events: list[AgentStreamEventDAO] = []
        try:
            async for event in agent.invoke(
                query="test",
                iteration_recovery_policy=_mechanical_policy(),
            ):
                events.append(event)
        except Exception:  # noqa: BLE001
            pass

        kinds = _kinds(events)
        assert "recovery_started" not in kinds
        assert "run_failed" in kinds


class TestNoPolicyLegacyPath:
    """With no recovery policy injected, behavior is identical to today."""

    async def test_no_recovery_policy_preserves_legacy_fail_fast(self) -> None:
        """``iteration_recovery_policy=None`` -> escaped exception -> run_failed + re-raise."""
        agent = SloAgent(
            llm=_make_always_fail_faux(),
            tools=[],
        )
        events: list[AgentStreamEventDAO] = []
        raised: list[Exception] = []
        try:
            async for event in agent.invoke(query="test"):
                events.append(event)
        except Exception as exc:  # noqa: BLE001
            raised.append(exc)

        kinds = _kinds(events)
        assert "recovery_started" not in kinds
        assert "run_failed" in kinds
        assert len(raised) == 1

    async def test_no_recovery_policy_does_not_emit_recovery_exhausted(self) -> None:
        """Legacy path never emits recovery_exhausted (no recoveries attempted)."""
        agent = SloAgent(
            llm=_make_always_fail_faux(),
            tools=[],
        )
        events: list[AgentStreamEventDAO] = []
        try:
            async for event in agent.invoke(query="test"):
                events.append(event)
        except Exception:  # noqa: BLE001
            pass

        assert "recovery_exhausted" not in _kinds(events)


class TestExecuteIterationWithRetryNoLongerEmitsRunFailed:
    """``_execute_iteration_with_retry`` must not emit run_failed — only _react_loop does."""

    async def test_inner_helper_re_raises_without_emitting_run_failed(self) -> None:
        """Non-retryable exception from inner helper: no run_failed, just re-raise."""
        agent = SloAgent(
            llm=_make_always_fail_faux(),
            tools=[],
        )
        accumulated: list = [HumanMessage(content="hi")]
        events: list[AgentStreamEventDAO] = []
        raised: list[Exception] = []
        try:
            async for event in agent._execute_iteration_with_retry(
                accumulated_messages=accumulated,
                iteration=0,
                runtime_handler=None,
                iteration_retry_policy=None,
            ):
                events.append(event)
        except Exception as exc:  # noqa: BLE001
            raised.append(exc)

        # The inner helper must NOT have emitted run_failed
        assert "run_failed" not in _kinds(events)
        assert len(raised) == 1


class TestDecideIterationRecovery:
    """``_decide_iteration_recovery`` unit tests."""

    def test_returns_fatal_when_no_policy_injected(self) -> None:
        """No policy -> FATAL decision."""
        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        result = agent._decide_iteration_recovery(
            exc=RuntimeError("x"),
            recoveries_used=0,
            iteration_recovery_policy=None,
        )
        assert result.recovery_class is RecoveryClass.FATAL

    def test_delegates_to_injected_policy(self) -> None:
        """With a policy injected, the decision comes from the policy."""
        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        result = agent._decide_iteration_recovery(
            exc=RuntimeError("x"),
            recoveries_used=0,
            iteration_recovery_policy=_recoverable_policy(),
        )
        assert result.recovery_class is RecoveryClass.LLM_RECOVERABLE


class TestRecoveryBudget:
    """``_recovery_budget`` attribute defaults and is respected."""

    def test_recovery_budget_default_is_two(self) -> None:
        """``_recovery_budget`` defaults to 2."""
        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        assert agent._recovery_budget == 2

    async def test_two_recoveries_allowed_before_exhaustion(self) -> None:
        """With default budget=2, two recoveries proceed; third triggers exhaustion."""
        # Fail 3 times so: fail(1)->recover, fail(2)->recover, fail(3)->exhausted
        agent = SloAgent(
            llm=_make_fail_n_times_faux(
                fail_count=3,
                responses=[FauxChatModel.assistant_message(content="finally")],
            ),
            tools=[],
        )
        events: list[AgentStreamEventDAO] = []
        raised: list[Exception] = []
        try:
            async for event in agent.invoke(
                query="test",
                iteration_recovery_policy=_recoverable_policy(),
            ):
                events.append(event)
        except Exception as exc:  # noqa: BLE001
            raised.append(exc)

        kinds = _kinds(events)
        # Two recovery_started events (budget=2), then exhaustion on the 3rd failure
        recovery_started_count = sum(1 for k in kinds if k == "recovery_started")
        assert recovery_started_count == 2
        assert "recovery_exhausted" in kinds
        assert "run_failed" in kinds
