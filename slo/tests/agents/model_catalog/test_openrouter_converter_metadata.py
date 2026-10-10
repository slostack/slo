"""Decision-specific OpenRouter converter metadata contracts."""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

from src.agents.model_catalog.openrouter import OpenRouterCatalogConverter
from src.integrations.openrouter.dao import OpenRouterModelsResponseDAO


def test_jev_unknown_output_and_reasoning_projection() -> None:
    """The literal authenticated-shaped fixture supplies evidence, not authorization."""
    record = json.loads(Path(__file__).with_name("feature89_jev.json").read_text(encoding="utf-8"))
    entry = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(data=[record]),
        now=datetime(2026, 10, 9, tzinfo=timezone.utc),
    ).entries[0]
    assert entry.model_name == "openrouter:typesafe/jev-router"
    assert entry.api_model_name == "typesafe/jev-router"
    assert entry.display_name == "TypeSafe: Jev Router"
    assert entry.provider.value == "openrouter"
    assert entry.support_tier == "auto_discovered"
    assert entry.aliases == ()
    assert entry.availability == "available"
    assert entry.visible_in_picker is True
    assert entry.runtime_profile.model_dump() == {
        "max_tokens": 4096,
        "context_window": 1000000,
        "streaming": True,
        "requests_per_minute": 20,
        "tokens_per_minute": None,
        "automatic_retry_attempts": 2,
        "local_retry_wait_cap_seconds": 60,
    }
    assert entry.reasoning_profile.model_dump() == {
        "supported_levels": ("off",),
        "default_level": "off",
        "provider_effort_map": {},
        "provider_budget_map": {},
        "provider_reasoning_required": False,
        "forbid_sampling_parameters_when_enabled": False,
    }
    assert entry.capabilities is not None
    assert entry.capabilities.reported_output_ceiling is None
    assert entry.capabilities.reasoning_controls_available is False
    assert entry.capabilities.reasoning_disable_available is False
    assert entry.capabilities.supports_max_tokens is None
    assert entry.capabilities.supported_parameters == tuple(record["supported_parameters"])
    assert "pricing" not in entry.model_dump()


def _record(**changes: object) -> dict[str, object]:
    """Build one otherwise eligible OpenRouter record for metadata decisions."""
    record: dict[str, object] = {
        "id": "vendor/model",
        "name": "Vendor Model",
        "context_length": 1000,
        "top_provider": {"context_length": 800},
        "supported_parameters": ["tools", "temperature", "reasoning"],
        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
    }
    record.update(changes)
    return record


def _entry(**changes: object):
    """Convert exactly one model under a fixed UTC clock."""
    result = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(data=[_record(**changes)]),
        now=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )
    return result.entries[0]


@pytest.mark.parametrize(
    ("architecture", "parameters"),
    [
        ({"input_modalities": ["image"], "output_modalities": ["text"]}, ["tools"]),
        ({"input_modalities": ["text"], "output_modalities": ["image"]}, ["tools"]),
        ({"input_modalities": ["text"], "output_modalities": ["text"]}, []),
    ],
)
def test_convert_when_required_text_or_tools_evidence_is_missing_preserves_ineligible_record(
    architecture: dict[str, list[str]], parameters: list[str]
) -> None:
    """Interactive eligibility requires explicit text input/output and tool evidence."""
    entry = _entry(architecture=architecture, supported_parameters=parameters)

    assert entry.availability == "ineligible"
    assert entry.visible_in_picker is False


@pytest.mark.parametrize(
    "top_provider",
    [
        {"context_length": True},
        {"context_length": 10.5},
        {"context_length": "800"},
        {"max_completion_tokens": True},
        {"max_completion_tokens": 10.5},
        {"max_completion_tokens": "400"},
    ],
)
def test_convert_when_supplied_top_provider_limit_is_malformed_preserves_ineligible_record(
    top_provider: dict[str, object],
) -> None:
    """Supplied endpoint context/output evidence fails closed rather than becoming absent."""
    entry = _entry(top_provider=top_provider)

    assert entry.availability == "ineligible"
    assert entry.visible_in_picker is False


@pytest.mark.parametrize(
    ("top_provider", "expected_ceiling", "expected_cap"),
    [
        ({}, None, 500),
        ({"max_completion_tokens": None}, None, 500),
        ({"max_completion_tokens": 300}, 300, 300),
        ({"max_completion_tokens": 800}, 800, 500),
    ],
)
def test_convert_when_output_ceiling_is_absent_or_supplied_retains_remote_evidence_and_safe_cap(
    top_provider: dict[str, object], expected_ceiling: int | None, expected_cap: int
) -> None:
    """Absent and explicit output ceilings remain distinguishable in canonical metadata."""
    entry = _entry(top_provider=top_provider)

    assert entry.availability == "available"
    assert entry.capabilities is not None
    assert entry.capabilities.reported_output_ceiling == expected_ceiling
    assert entry.runtime_profile.max_tokens == expected_cap


@pytest.mark.parametrize(
    "changes",
    [
        {"supported_parameters": []},
        {"architecture": {"input_modalities": ["image"], "output_modalities": ["text"]}},
        {"architecture": {"input_modalities": ["text"], "output_modalities": ["image"]}},
        {"context_length": True},
        {"context_length": "1000"},
        {"top_provider": []},
        {"expiration_date": "2026-09-30"},
    ],
)
def test_unknown_output_still_requires_other_evidence(changes: dict[str, object]) -> None:
    """Null output evidence cannot bypass independent eligibility and expiry gates."""
    record = {"top_provider": {"max_completion_tokens": None}, **changes}
    entry = _entry(**record)
    assert entry.availability in {"ineligible", "expired"}
    assert entry.visible_in_picker is False


@pytest.mark.parametrize(
    "context,ceiling,expected",
    [
        (1000000, None, 4096),
        (1000000, 1, 1),
        (1000000, 2048, 2048),
        (1000000, 8192, 4096),
        (2, None, 1),
        (1000, None, 500),
    ],
)
def test_unknown_output_uses_existing_conservative_minimum(
    context: int,
    ceiling: int | None,
    expected: int,
) -> None:
    """Generic metadata, not a Jev name exception, determines the safe local cap."""
    entry = _entry(context_length=context, top_provider={"max_completion_tokens": ceiling})
    assert entry.availability == "available"
    assert entry.runtime_profile.max_tokens == expected
    assert entry.capabilities is not None
    assert entry.capabilities.reported_output_ceiling == ceiling


@pytest.mark.parametrize(
    ("expiration_date", "now", "availability"),
    [
        ("2026-09-30", datetime(2026, 9, 29, 23, 59, tzinfo=timezone.utc), "available"),
        ("2026-09-30", datetime(2026, 9, 30, tzinfo=timezone.utc), "expired"),
        ("2026-09-30T12:00:00+00:00", datetime(2026, 9, 30, 11, 59, tzinfo=timezone.utc), "available"),
        ("2026-09-30T12:00:00+00:00", datetime(2026, 9, 30, 12, tzinfo=timezone.utc), "expired"),
        ("2026-09-30T12:00:00", datetime(2026, 9, 30, tzinfo=timezone.utc), "expired"),
        ("not-a-date", datetime(2026, 9, 30, tzinfo=timezone.utc), "expired"),
    ],
    ids=["date-before", "date-boundary", "timestamp-before", "timestamp-boundary", "naive", "malformed"],
)
def test_convert_when_expiry_evidence_has_boundaries_or_is_invalid_fails_closed(
    expiration_date: str, now: datetime, availability: str
) -> None:
    """UTC date/timestamp evidence changes eligibility exactly at its boundary."""
    result = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(data=[_record(expiration_date=expiration_date)]), now=now
    )

    assert result.entries[0].availability == availability


@pytest.mark.parametrize(
    "top_provider",
    [{"max_completion_tokens": 0}, {"max_completion_tokens": -1}],
    ids=["zero", "negative"],
)
def test_convert_when_output_ceiling_is_invalid_preserves_ineligible_record(
    top_provider: dict[str, object],
) -> None:
    """Supplied non-positive output ceilings are not treated as absent evidence."""
    entry = _entry(top_provider=top_provider)

    assert entry.availability == "ineligible"


@pytest.mark.parametrize(
    "record_change",
    [
        {"supported_parameters": None},
        {"supported_parameters": "tools"},
        {"architecture": None},
        {"architecture": {"input_modalities": ["text"]}},
        {"architecture": {"output_modalities": ["text"]}},
    ],
    ids=["parameters-null", "parameters-string", "architecture-null", "missing-output", "missing-input"],
)
def test_convert_when_capability_record_is_absent_or_invalid_preserves_ineligible_record(
    record_change: dict[str, object],
) -> None:
    """Selectable routes require structurally valid text and tools capability records."""
    entry = _entry(**record_change)

    assert entry.availability == "ineligible"


@pytest.mark.parametrize("model_id", ["vendor/model:batch", "openrouter/auto", "vendor/model~latest"])
def test_convert_when_batch_router_or_latest_identity_is_listed_preserves_ineligible_record(
    model_id: str,
) -> None:
    """Concrete interactive catalog entries exclude batch, router, and latest aliases."""
    entry = _entry(id=model_id)

    assert entry.availability == "ineligible"
    assert entry.visible_in_picker is False


def test_convert_when_label_contains_control_and_bidi_characters_sanitizes_literal_display_name() -> None:
    """External labels cannot inject terminal controls or bidirectional formatting."""
    entry = _entry(name="  Safe\x1b Label\u202e  Name  ")

    assert entry.display_name == "Safe Label Name"


def test_convert_when_reasoning_efforts_are_omitted_disables_controls_without_claiming_no_reasoning() -> None:
    """Omitted reasoning metadata keeps only the safe off control."""
    entry = _entry()

    assert entry.capabilities is not None
    assert entry.capabilities.reasoning_controls_available is False
    assert entry.reasoning_profile.supported_levels == ("off",)


@pytest.mark.parametrize(
    ("reasoning", "expected_controls", "expected_disable", "expected_levels"),
    [
        ({}, False, False, ("off",)),
        ({"supported_efforts": ["low"]}, True, False, ("off", "low")),
        (
            {"supported_efforts": None},
            True,
            False,
            ("off", "minimal", "low", "medium", "high", "xhigh", "max"),
        ),
        ({"supported_efforts": ["low"], "mandatory": False}, True, True, ("off", "low")),
        ({"supported_efforts": ["low"], "mandatory": True}, True, False, ("low",)),
    ],
    ids=["empty", "omitted-efforts", "explicit-null-efforts", "explicit-disable", "mandatory"],
)
def test_convert_when_reasoning_metadata_has_each_permission_shape_preserves_capability_truth(
    reasoning: dict[str, object],
    expected_controls: bool,
    expected_disable: bool,
    expected_levels: tuple[str, ...],
) -> None:
    """Keep effort availability and explicit disable permission independently truthful."""
    entry = _entry(reasoning=reasoning)

    assert entry.capabilities is not None
    assert entry.capabilities.reasoning_controls_available is expected_controls
    assert entry.capabilities.reasoning_disable_available is expected_disable
    assert entry.reasoning_profile.supported_levels == expected_levels


@pytest.mark.parametrize(
    ("reasoning", "expected_levels", "expected_default", "required"),
    [
        ({"supported_efforts": ["invalid"], "default_effort": "invalid"}, ("off",), "off", False),
        ({"supported_efforts": ["low"], "default_effort": "invalid"}, ("off", "low"), "low", False),
        (
            {"supported_efforts": ["low"], "default_effort": None, "mandatory": True},
            ("low",),
            "low",
            False,
        ),
        (
            {"supported_efforts": None, "default_effort": "invalid", "mandatory": True},
            ("minimal", "low", "medium", "high", "xhigh", "max"),
            "minimal",
            False,
        ),
    ],
    ids=["all-invalid", "invalid-default", "mandatory-missing-default", "mandatory-null-efforts"],
)
def test_convert_when_reasoning_metadata_is_invalid_or_mandatory_preserves_conservative_profile(
    reasoning: dict[str, object],
    expected_levels: tuple[str, ...],
    expected_default: str,
    required: bool,
) -> None:
    """Invalid optional evidence never invents controls or a default effort."""
    entry = _entry(reasoning=reasoning)

    assert entry.reasoning_profile.supported_levels == expected_levels
    assert entry.reasoning_profile.default_level == expected_default
    assert entry.reasoning_profile.provider_reasoning_required is required


def test_convert_when_reasoning_is_mandatory_clamps_off_to_lowest_enabled_effort() -> None:
    """Mandatory reasoning maps canonical off to the lowest advertised enabled effort."""
    entry = _entry(
        reasoning={
            "supported_efforts": ["low", "high", "unknown"],
            "default_effort": "high",
            "default_enabled": True,
            "mandatory": True,
        }
    )

    assert entry.reasoning_profile.supported_levels == ("low", "high")
    assert entry.reasoning_profile.default_level == "high"
    assert "off" not in entry.reasoning_profile.provider_effort_map
    assert entry.reasoning_profile.provider_effort_map["low"] == "low"
    assert entry.runtime_profile.tokens_per_minute is None


@pytest.mark.parametrize(
    ("reasoning", "expected_levels", "expected_default", "controls_available"),
    [
        (
            {"supported_efforts": ["low"], "mandatory": False, "default_enabled": False},
            ("off", "low"),
            "off",
            True,
        ),
        (
            {"supported_efforts": ["low"], "mandatory": False, "default_enabled": True},
            ("off", "low"),
            "low",
            True,
        ),
        ({"supported_efforts": ["low"]}, ("off", "low"), "low", True),
        ({"supported_efforts": []}, ("off",), "off", False),
        ({"supported_efforts": ["unknown"]}, ("off",), "off", False),
    ],
    ids=[
        "optional-disabled-default",
        "optional-enabled-default",
        "missing-mandatory-enabled",
        "empty",
        "unknown",
    ],
)
def test_convert_when_reasoning_control_evidence_is_incomplete_remains_conservative(
    reasoning: dict[str, object],
    expected_levels: tuple[str, ...],
    expected_default: str,
    controls_available: bool,
) -> None:
    """Preserve known enabled efforts while requiring explicit false to advertise disable."""
    entry = _entry(reasoning=reasoning)

    assert entry.reasoning_profile.supported_levels == expected_levels
    assert entry.reasoning_profile.default_level == expected_default
    assert entry.capabilities is not None
    assert entry.capabilities.reasoning_controls_available is controls_available
