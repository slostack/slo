"""Tests for the shared terminal settlement-failure family."""

from __future__ import annotations

from src.agents.slo_agent.history.message_contract_reconciler import (
    CooperativeYieldSettlementError,
    UnsettledToolGroupError,
    is_settlement_failure,
)


def test_unsettled_tool_group_remains_terminal() -> None:
    """The existing strict live-guard failure keeps its terminal classification."""
    assert is_settlement_failure(exc=UnsettledToolGroupError())


def test_cooperative_yield_settlement_is_terminal() -> None:
    """A future cooperative-yield producer joins the same terminal predicate."""
    error: CooperativeYieldSettlementError = CooperativeYieldSettlementError()

    assert str(error) == "cooperative_yield_settlement_failed"
    assert is_settlement_failure(exc=error)


def test_unrelated_errors_are_not_settlement_failures() -> None:
    """Generic provider/session failures stay eligible for their own policies."""
    assert not is_settlement_failure(exc=RuntimeError("provider failed"))
    assert not is_settlement_failure(exc=ValueError("invalid input"))
