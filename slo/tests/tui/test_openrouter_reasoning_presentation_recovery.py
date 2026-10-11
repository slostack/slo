"""Presentation must distinguish enabled controls from permission to disable."""

import pytest

from src.agents.model_catalog.seed import SeedModelCatalog
from src.tui.model_catalog import _project_rows
from src.tui.slash_suggestion_engine import SlashSuggestionEngine
from tests.agents.model_catalog.test_openrouter_converter_metadata import _entry


@pytest.mark.parametrize(
    ("reasoning", "summary"),
    [
        ({"supported_efforts": ["none"], "mandatory": False}, "off"),
        ({"supported_efforts": ["low", "high"]}, "low, high"),
    ],
)
def test_picker_reports_only_permitted_reasoning_controls(
    reasoning: dict[str, object], summary: str
) -> None:
    """Project canonical evidence without advertising unestablished disable permission."""
    entry = _entry(reasoning=reasoning)
    snapshot = SeedModelCatalog.load().model_copy(update={"entries": {entry.model_name: entry}})
    row = _project_rows(snapshot=snapshot, active_model_name=entry.model_name, statuses={})[0]

    assert row.reasoning_controls_available is True
    assert row.reasoning_summary == summary
    detail = SlashSuggestionEngine._model_detail(entry=row)
    assert (f"reasoning {summary}" in detail) or "reasoning disable supported" in detail
    assert "controls unavailable" not in detail


@pytest.mark.parametrize(
    ("reasoning", "expected_detail"),
    [
        ({"supported_efforts": ["none"], "mandatory": False}, "reasoning disable supported"),
        ({"supported_efforts": ["low", "high"]}, "reasoning low, high; provider default"),
    ],
)
def test_picker_distinguishes_supported_disable_from_provider_default(
    reasoning: dict[str, object], expected_detail: str
) -> None:
    """Render explicit disable permission separately from absent disable evidence."""
    entry = _entry(reasoning=reasoning)
    snapshot = SeedModelCatalog.load().model_copy(update={"entries": {entry.model_name: entry}})
    row = _project_rows(snapshot=snapshot, active_model_name=entry.model_name, statuses={})[0]

    assert expected_detail in SlashSuggestionEngine._model_detail(entry=row)
