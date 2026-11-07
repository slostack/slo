"""Tests for the closed provider graph-read outcome carrier."""

import pytest
from pydantic import ValidationError

from src.agents.slo_agent.watchdog_timer import GraphReadOutcomeDAO


class TestGraphReadOutcomeDAO:
    """Verify item/end/yield discrimination and presence validation."""

    def test_item_keeps_a_framework_none_payload_distinct_from_exhaustion(self) -> None:
        """A framework None item is still an item, not the end of the stream."""
        outcome: GraphReadOutcomeDAO = GraphReadOutcomeDAO(kind="item", item=None)

        assert outcome.kind == "item"
        assert outcome.item is None
        assert outcome.settled_item is None
        assert outcome.has_settled_item is False

    def test_end_has_no_item_and_no_settled_item(self) -> None:
        """Normal exhaustion is explicit and carries no payload."""
        outcome: GraphReadOutcomeDAO = GraphReadOutcomeDAO(kind="end")

        assert outcome.kind == "end"
        assert outcome.item is None
        assert outcome.settled_item is None
        assert outcome.has_settled_item is False

    def test_yield_may_report_a_settled_none_item_via_the_presence_flag(self) -> None:
        """A settled race item exists even when its value is None."""
        outcome: GraphReadOutcomeDAO = GraphReadOutcomeDAO(
            kind="yield",
            settled_item=None,
            has_settled_item=True,
        )

        assert outcome.kind == "yield"
        assert outcome.item is None
        assert outcome.settled_item is None
        assert outcome.has_settled_item is True

    def test_yield_may_report_a_settled_item_value(self) -> None:
        """A settled race item may carry an actual value."""
        outcome: GraphReadOutcomeDAO = GraphReadOutcomeDAO(
            kind="yield",
            settled_item="late item",
            has_settled_item=True,
        )

        assert outcome.settled_item == "late item"
        assert outcome.has_settled_item is True

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"kind": "end", "item": "unexpected"},
            {"kind": "yield", "item": "unexpected"},
            {"kind": "item", "settled_item": "unexpected"},
            {"kind": "end", "settled_item": "unexpected"},
            {"kind": "item", "has_settled_item": True},
            {"kind": "end", "has_settled_item": True},
            {"kind": "yield", "settled_item": "unexpected", "has_settled_item": False},
        ],
    )
    def test_inconsistent_payload_combinations_are_rejected(self, kwargs: dict[str, object]) -> None:
        """Only the owning kind may carry its payload or presence flag."""
        with pytest.raises(ValidationError, match="graph_read_outcome_invalid"):
            GraphReadOutcomeDAO.model_validate(kwargs)

    def test_unknown_kind_is_rejected(self) -> None:
        """Unknown outcome kinds fail closed."""
        with pytest.raises(ValidationError):
            GraphReadOutcomeDAO.model_validate({"kind": "unknown"})

    def test_extra_fields_are_forbidden(self) -> None:
        """The closed carrier rejects undeclared fields."""
        with pytest.raises(ValidationError):
            GraphReadOutcomeDAO.model_validate({"kind": "end", "unexpected": True})

    def test_outcome_is_frozen(self) -> None:
        """Constructed outcomes cannot be mutated after validation."""
        outcome: GraphReadOutcomeDAO = GraphReadOutcomeDAO(kind="end")

        with pytest.raises(ValidationError):
            outcome.kind = "item"
