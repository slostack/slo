"""Behavioural tests for ``Hook`` defaults, the evaluator, and ``TurnAccumulatorDAO``."""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.hooks import (
    Hook,
    ShouldStopAfterTurnHookContextDAO,
    TurnAccumulatorDAO,
)


def _build_context() -> ShouldStopAfterTurnHookContextDAO:
    return ShouldStopAfterTurnHookContextDAO(
        message=AIMessage(content="hi"),
        tool_results=[],
        messages=[AIMessage(content="hi")],
    )


class TestDefaultShouldStopAfterTurnHook:
    """Default hook behaviour."""

    @pytest.mark.asyncio
    async def test_returns_false(self) -> None:
        """The shipped default never requests a stop."""
        assert await Hook.should_stop_after_turn_hook(context=_build_context()) is False


class TestEvaluateShouldStopAfterTurnHook:
    """``Hook.evaluate_should_stop_after_turn_hook`` dispatch behaviour."""

    @pytest.mark.asyncio
    async def test_runs_sync_hook(self) -> None:
        """A sync callable returning True is honoured."""
        def sync_hook(context: ShouldStopAfterTurnHookContextDAO) -> bool:
            return True

        assert await Hook.evaluate_should_stop_after_turn_hook(
            hook=sync_hook,
            context=_build_context(),
        ) is True

    @pytest.mark.asyncio
    async def test_runs_async_hook(self) -> None:
        """An async callable is awaited and its result honoured."""
        async def async_hook(context: ShouldStopAfterTurnHookContextDAO) -> bool:
            return True

        assert await Hook.evaluate_should_stop_after_turn_hook(
            hook=async_hook,
            context=_build_context(),
        ) is True

    @pytest.mark.asyncio
    async def test_coerces_truthy_value_to_bool(self) -> None:
        """Non-bool truthy return is coerced (defensive — contract is bool)."""
        def truthy_hook(context: ShouldStopAfterTurnHookContextDAO) -> bool:
            return bool("yes")

        assert await Hook.evaluate_should_stop_after_turn_hook(
            hook=truthy_hook,
            context=_build_context(),
        ) is True


class TestTurnAccumulatorDAO:
    """``TurnAccumulatorDAO.absorb`` routes by concrete message type."""

    def test_absorbs_assistant_message(self) -> None:
        accumulator: TurnAccumulatorDAO = TurnAccumulatorDAO()
        accumulator.absorb(message=AIMessage(content="hi"))
        assert accumulator.assistant_message is not None
        assert accumulator.assistant_message.content == "hi"
        assert accumulator.tool_results == []

    def test_absorbs_tool_message(self) -> None:
        accumulator: TurnAccumulatorDAO = TurnAccumulatorDAO()
        accumulator.absorb(
            message=ToolMessage(tool_call_id="t1", name="echo", content="result"),
        )
        assert accumulator.assistant_message is None
        assert len(accumulator.tool_results) == 1
        assert accumulator.tool_results[0].name == "echo"

    def test_ignores_unrelated_message_types(self) -> None:
        """Non-AIMessage, non-ToolMessage messages (e.g. HumanMessage) are no-ops."""
        accumulator: TurnAccumulatorDAO = TurnAccumulatorDAO()
        accumulator.absorb(message=HumanMessage(content="ignored"))
        assert accumulator.assistant_message is None
        assert accumulator.tool_results == []
