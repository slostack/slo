"""Exact integer half-up formatting shared with the footer."""

import pytest

from src.agents.slo_agent.sessions.token_format import CompactTokenFormatter
from src.tui.widgets.usage_status_bar import UsageStatusBar


@pytest.mark.parametrize(
    "count,expected",
    [
        (0, "0"),
        (999, "999"),
        (1000, "1.0k"),
        (1249, "1.2k"),
        (1250, "1.3k"),
        (9999, "10.0k"),
        (10000, "10k"),
        (12499, "12k"),
        (12500, "13k"),
        (999999, "1000k"),
        (1000000, "1.0M"),
        (1249999, "1.2M"),
        (1250000, "1.3M"),
        (9999999, "10.0M"),
        (10000000, "10M"),
        (10499999, "10M"),
        (10500000, "11M"),
        (2**63 - 1, "9223372036855M"),
    ],
)
def test_exact_half_up_boundaries(count: int, expected: str) -> None:
    """Every band and rounding boundary retains the existing integer arithmetic."""
    assert CompactTokenFormatter.format(count=count) == expected
    assert UsageStatusBar._format_token_count(count=count) == expected


def test_footer_delegates_to_shared_formatter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The footer owns no second arithmetic implementation."""

    def format_count(*, count: int) -> str:
        """Expose delegation at the shared owner."""
        return f"shared:{count}"

    monkeypatch.setattr(target=CompactTokenFormatter, name="format", value=format_count)
    assert UsageStatusBar._format_token_count(count=1250) == "shared:1250"


def test_footer_decimal_delegate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retain the private decimal compatibility entry without duplicated logic."""

    def format_decimal(*, count: int, unit: int, suffix: str) -> str:
        """Expose all forwarded arguments."""
        return f"{count}:{unit}:{suffix}"

    monkeypatch.setattr(target=CompactTokenFormatter, name="_format_one_decimal", value=format_decimal)
    assert UsageStatusBar._format_one_decimal_token_count(count=1250, unit=1000, suffix="k") == "1250:1000:k"
