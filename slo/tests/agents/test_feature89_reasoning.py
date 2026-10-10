"""Explicit selected/effective reasoning contract for the three new direct routes."""

from typing import Optional

import pytest

from src.agents.model_catalog.dao import ReasoningLevel
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.providers.openai_codex import openai_reasoning_payload
from src.agents.reasoning_capabilities import ResolvedReasoningConfigDAO, resolve_reasoning_config


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol"])
@pytest.mark.parametrize(
    "level,effort",
    [
        ("off", "none"),
        ("minimal", "low"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("xhigh", "xhigh"),
        ("max", "max"),
    ],
)
def test_all_selected_levels_resolve(model_name: str, level: ReasoningLevel, effort: str) -> None:
    """All 21 cells preserve selection while explicitly resolving provider effort."""
    resolved = resolve_reasoning_config(
        model_name=model_name, requested_level=level, snapshot=SeedModelCatalog.load()
    )
    enabled = level != "off" or model_name == "gpt-6.1-sol"
    expected_effort = "low" if level == "off" and enabled else effort
    assert resolved.requested_level == resolved.active_level == level
    assert resolved.enabled is enabled
    assert resolved.provider_effort == expected_effort
    assert resolved.provider_summary_mode == ("auto" if enabled else None)
    expected = {"effort": expected_effort}
    if enabled:
        expected["summary"] = "auto"
    assert openai_reasoning_payload(reasoning=resolved) == expected


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol"])
def test_default_and_highest_are_pinned(model_name: str) -> None:
    """New rows default to medium and expose max without loading another view."""
    from unittest.mock import patch
    from src.agents.model_catalog.service import ModelCatalogService
    from src.agents.reasoning_capabilities import (
        default_reasoning_level_for_model,
        highest_supported_reasoning_level,
    )

    snapshot = SeedModelCatalog.load()
    with patch.object(ModelCatalogService, "load", side_effect=AssertionError("unpinned")):
        assert default_reasoning_level_for_model(model_name=model_name, snapshot=snapshot) == "medium"
        assert highest_supported_reasoning_level(model_name=model_name, snapshot=snapshot) == "max"


def test_invalid_reasoning_and_unknown_model_reject() -> None:
    """Invalid tokens and absent identities cannot silently select medium."""
    from src.agents.reasoning_capabilities import parse_reasoning_level

    with pytest.raises(ValueError):
        parse_reasoning_level(token="bogus")
    with pytest.raises(ValueError):
        resolve_reasoning_config(
            model_name="unknown-89", requested_level="off", snapshot=SeedModelCatalog.load()
        )


@pytest.mark.parametrize("effort", [None, "none"])
def test_disabled_payload_omits_summary(effort: Optional[str]) -> None:
    """Disabled explicit effort survives while even an erroneous summary is omitted."""
    resolved = ResolvedReasoningConfigDAO(
        enabled=False,
        requested_level="off",
        active_level="off",
        provider_effort=effort,
        provider_summary_mode="auto",
    )
    assert openai_reasoning_payload(reasoning=resolved) == ({"effort": "none"} if effort else None)


def test_absent_and_inconsistent_payload() -> None:
    """No configuration omits payload; enabled configuration requires effort."""
    assert openai_reasoning_payload(reasoning=None) is None
    with pytest.raises(ValueError, match="missing provider_effort"):
        openai_reasoning_payload(
            reasoning=ResolvedReasoningConfigDAO(
                enabled=True,
                requested_level="high",
                active_level="high",
            )
        )
