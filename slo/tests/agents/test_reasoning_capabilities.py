"""Unit tests for ``src.agents.reasoning_capabilities``."""

from __future__ import annotations

import pytest

from config.ai_model_config import MODEL_DEFAULTS
from src.agents.reasoning_capabilities import (
    MODEL_REASONING_CAPABILITIES,
    REASONING_LEVELS,
    ModelReasoningCapabilityDAO,
    ReasoningLevel,
    ResolvedReasoningConfigDAO,
    capability_for_model,
    clamp_reasoning_level,
    default_reasoning_level_for_model,
    highest_supported_reasoning_level,
    parse_reasoning_level,
    resolve_reasoning_config,
    supported_reasoning_levels_for_model,
)


class TestCapabilityLookup:
    """Capability-catalog lookup and supported-level rendering."""

    def test_capability_for_model_returns_record_for_supported_model(self) -> None:
        """Supported interactive models return a validated capability record."""
        capability: ModelReasoningCapabilityDAO = capability_for_model(
            model_name="gpt-5.4",
        )

        assert capability.reasoning_supported is True
        assert capability.supported_levels == [
            "off",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
        ]

    def test_capability_for_model_raises_for_unknown_model(self) -> None:
        """Unknown model names raise a clear ``ValueError``."""
        with pytest.raises(ValueError, match="Unsupported reasoning model"):
            capability_for_model(model_name="mistral-large")

    def test_supported_reasoning_levels_for_model_returns_off_only_when_reasoning_unsupported(
        self,
    ) -> None:
        """Non-reasoning models expose only the ``off`` level."""
        supported_levels: list[ReasoningLevel] = supported_reasoning_levels_for_model(
            model_name="gpt-4.1",
        )

        assert supported_levels == ["off"]


class TestDefaultSeeding:
    """Default seeded reasoning levels."""

    def test_default_reasoning_level_returns_high_when_model_supports_it(self) -> None:
        """Reasoning-capable models seed to ``high`` by default."""
        default_level: str = default_reasoning_level_for_model(
            model_name="claude-sonnet-4-6",
        )

        assert default_level == "high"

    def test_default_reasoning_level_returns_k3_profile_default(self) -> None:
        """K3 seeds its catalog default rather than the generic high heuristic."""
        default_level: str = default_reasoning_level_for_model(
            model_name="kimi-k3",
        )

        assert default_level == "xhigh"

    def test_default_reasoning_level_preserves_existing_high_profile_default(self) -> None:
        """Existing high-default models retain their declared default."""
        default_level: str = default_reasoning_level_for_model(
            model_name="claude-sonnet-4-6",
        )

        assert default_level == "high"

    def test_default_reasoning_level_returns_off_for_non_reasoning_model(self) -> None:
        """Non-reasoning models seed to ``off``."""
        default_level: str = default_reasoning_level_for_model(
            model_name="gpt-4o",
        )

        assert default_level == "off"

    @pytest.mark.parametrize(
        "model_name",
        [
            "gpt-5.5",
            "gpt-5.6-luna",
            "gpt-5.6-sol",
            "gpt-5.6-terra",
            "claude-fable",
            "kimi-k3",
            "kimi-for-coding-highspeed",
        ],
    )
    def test_capability_for_model_returns_record_for_new_models(self, model_name: str) -> None:
        """Spec-55 first-class models have catalog-backed capability records."""
        capability: ModelReasoningCapabilityDAO = capability_for_model(
            model_name=model_name,
        )

        assert capability is not None

    def test_claude_mythos_clamps_xhigh_to_high(self) -> None:
        """The conditional entry clamps xhigh to high from seed."""
        active_level: str = clamp_reasoning_level(
            model_name="claude-mythos",
            requested_level="xhigh",
        )

        assert active_level == "high"


class TestClamping:
    """Provider-neutral clamping behavior."""

    def test_clamp_reasoning_level_returns_exact_match_when_supported(self) -> None:
        """Supported levels survive clamping unchanged."""
        active_level: str = clamp_reasoning_level(
            model_name="gpt-5.4",
            requested_level="medium",
        )

        assert active_level == "medium"

    def test_clamp_reasoning_level_clamps_upward_when_requested_level_is_unsupported(self) -> None:
        """Unsupported levels clamp to the nearest stronger supported level first."""
        active_level: str = clamp_reasoning_level(
            model_name="claude-sonnet-4-6",
            requested_level="xhigh",
        )

        assert active_level == "high"

    def test_clamp_reasoning_level_clamps_downward_when_no_stronger_level_exists(self) -> None:
        """`minimal` on an off-only model falls back downward to ``off``."""
        active_level: str = clamp_reasoning_level(
            model_name="gpt-4.1",
            requested_level="minimal",
        )

        assert active_level == "off"


class TestResolvedConfig:
    """Provider-ready resolved reasoning config."""

    def test_resolve_reasoning_config_returns_disabled_config_when_reasoning_is_off(self) -> None:
        """Off resolves to a disabled config with no provider payload fields."""
        resolved: ResolvedReasoningConfigDAO = resolve_reasoning_config(
            model_name="gpt-5.4",
            requested_level="off",
        )

        assert resolved.enabled is False
        assert resolved.active_level == "off"
        assert resolved.provider_effort is None
        assert resolved.provider_budget_tokens is None

    def test_resolve_reasoning_config_translates_openai_minimal_to_provider_low(self) -> None:
        """GPT-5.4 keeps canonical ``minimal`` while mapping provider effort to ``low``."""
        resolved: ResolvedReasoningConfigDAO = resolve_reasoning_config(
            model_name="gpt-5.4",
            requested_level="minimal",
        )

        assert resolved.enabled is True
        assert resolved.active_level == "minimal"
        assert resolved.provider_effort == "low"
        assert resolved.provider_summary_mode == "auto"

    def test_resolve_reasoning_config_translates_openai_xhigh_to_provider_xhigh(self) -> None:
        """GPT-5.4 maps canonical ``xhigh`` to OpenAI's accepted ``xhigh`` effort."""
        resolved: ResolvedReasoningConfigDAO = resolve_reasoning_config(
            model_name="gpt-5.4",
            requested_level="xhigh",
        )

        assert resolved.enabled is True
        assert resolved.active_level == "xhigh"
        assert resolved.provider_effort == "xhigh"
        assert resolved.provider_summary_mode == "auto"

    def test_resolve_reasoning_config_translates_anthropic_high_to_provider_effort(self) -> None:
        """Anthropic thinking models resolve canonical levels to adaptive effort strings."""
        resolved: ResolvedReasoningConfigDAO = resolve_reasoning_config(
            model_name="claude-sonnet-4-6",
            requested_level="high",
        )

        assert resolved.enabled is True
        assert resolved.active_level == "high"
        assert resolved.provider_effort == "high"
        assert resolved.provider_budget_tokens is None

    @pytest.mark.parametrize(
        ("requested_level", "active_level", "provider_effort"),
        [
            ("off", "low", "low"),
            ("minimal", "low", "low"),
            ("low", "low", "low"),
            ("medium", "high", "high"),
            ("high", "high", "high"),
            ("xhigh", "xhigh", "max"),
        ],
    )
    def test_resolve_reasoning_config_maps_k3_requested_level_to_provider_effort(
        self,
        requested_level: str,
        active_level: str,
        provider_effort: str,
    ) -> None:
        """K3 clamps each canonical level to its verified provider effort."""
        resolved: ResolvedReasoningConfigDAO = resolve_reasoning_config(
            model_name="kimi-k3",
            requested_level=requested_level,  # type: ignore[arg-type]
        )

        assert resolved.enabled is True
        assert resolved.active_level == active_level
        assert resolved.provider_effort == provider_effort

    @pytest.mark.parametrize("model_name", ["kimi-for-coding", "kimi-for-coding-highspeed"])
    def test_resolve_reasoning_config_keeps_k2_models_off_only(self, model_name: str) -> None:
        """K2 profiles remain disabled and have no provider effort."""
        resolved: ResolvedReasoningConfigDAO = resolve_reasoning_config(
            model_name=model_name,
            requested_level="high",
        )

        assert resolved.enabled is False
        assert resolved.active_level == "off"
        assert resolved.provider_effort is None


class TestCodexCapabilityRecords:
    """Reasoning capability records for the OpenAI Codex model family."""

    @pytest.mark.parametrize(
        "model_name",
        [
            "gpt-5-codex",
            "gpt-5.3-codex",
            "gpt-5.3-codex-spark",
        ],
    )
    def test_codex_flagship_models_support_reasoning_and_xhigh(
        self,
        model_name: str,
    ) -> None:
        """Flagship and 5.3 Codex variants expose reasoning up to xhigh."""
        capability: ModelReasoningCapabilityDAO = capability_for_model(
            model_name=model_name,
        )

        assert capability.reasoning_supported is True
        assert "xhigh" in capability.supported_levels
        assert capability.provider_summary_mode == "auto"

    def test_gpt_5_2_codex_supports_reasoning_but_not_xhigh(self) -> None:
        """The compact 5.2 Codex variant supports reasoning but clamps xhigh."""
        capability: ModelReasoningCapabilityDAO = capability_for_model(
            model_name="gpt-5.2-codex",
        )

        assert capability.reasoning_supported is True
        assert "xhigh" not in capability.supported_levels
        assert "high" in capability.supported_levels
        assert capability.provider_summary_mode == "auto"

    def test_gpt_5_2_codex_clamps_xhigh_to_high(self) -> None:
        """A request for xhigh on the 5.2 Codex variant clamps to high."""
        active_level: str = clamp_reasoning_level(
            model_name="gpt-5.2-codex",
            requested_level="xhigh",
        )

        assert active_level == "high"


class TestCatalogInvariants:
    """Capability-catalog coverage and ordering invariants."""

    def test_reasoning_catalog_covers_exactly_the_supported_model_defaults(self) -> None:
        """Every supported interactive model has exactly one reasoning record."""
        assert set(MODEL_REASONING_CAPABILITIES) == set(MODEL_DEFAULTS)

    def test_reasoning_levels_stay_in_canonical_order_per_model(self) -> None:
        """Each model's supported levels stay ordered by the canonical vocabulary."""
        ordered_index: dict[str, int] = {level: index for index, level in enumerate(REASONING_LEVELS)}

        for model_name, capability in MODEL_REASONING_CAPABILITIES.items():
            indexes: list[int] = [ordered_index[level] for level in capability.supported_levels]
            assert indexes == sorted(indexes), model_name
            if "off" in capability.supported_levels:
                assert capability.supported_levels[0] == "off", model_name


class TestCanonicalVocabulary:
    """The global reasoning vocabulary is exactly off..max in canonical order."""

    def test_reasoning_levels_is_the_dao_owned_canonical_order(self) -> None:
        """REASONING_LEVELS derives from the catalog-owned tuple (no duplication)."""
        from src.agents.model_catalog.dao import CANONICAL_REASONING_LEVEL_ORDER

        assert REASONING_LEVELS == CANONICAL_REASONING_LEVEL_ORDER
        assert REASONING_LEVELS == (
            "off",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        )

    def test_parse_reasoning_level_accepts_max(self) -> None:
        """Canonical ``max`` parses into a valid reasoning level."""
        assert parse_reasoning_level(token="max") == "max"

    def test_parse_reasoning_level_rejects_unknown_token(self) -> None:
        """Unknown tokens still raise a clear ``ValueError`` listing all seven levels."""
        with pytest.raises(ValueError, match="unknown reasoning level"):
            parse_reasoning_level(token="ultra")


class TestReasoningProfileValidation:
    """``ModelReasoningProfileDAO`` enforces generic profile consistency."""

    def test_rejects_out_of_order_supported_levels(self) -> None:
        """Supported levels must follow the canonical vocabulary order."""
        from src.agents.model_catalog.dao import ModelReasoningProfileDAO

        with pytest.raises(ValueError, match="canonical order"):
            ModelReasoningProfileDAO(
                supported_levels=["high", "low"],
                default_level="low",
                provider_effort_map={"low": "low", "high": "high"},
            )

    def test_rejects_duplicate_supported_levels(self) -> None:
        """Duplicate supported levels are rejected."""
        from src.agents.model_catalog.dao import ModelReasoningProfileDAO

        with pytest.raises(ValueError, match="duplicate"):
            ModelReasoningProfileDAO(
                supported_levels=["low", "low", "high"],
                default_level="low",
                provider_effort_map={"low": "low", "high": "high"},
            )

    def test_rejects_default_outside_supported_levels(self) -> None:
        """The default level must be one of the supported levels."""
        from src.agents.model_catalog.dao import ModelReasoningProfileDAO

        with pytest.raises(ValueError, match="default_level"):
            ModelReasoningProfileDAO(
                supported_levels=["off", "low"],
                default_level="high",
                provider_effort_map={"low": "low"},
            )

    def test_rejects_provider_map_key_outside_supported_levels(self) -> None:
        """Provider translation keys must be supported levels."""
        from src.agents.model_catalog.dao import ModelReasoningProfileDAO

        with pytest.raises(ValueError, match="provider_effort_map"):
            ModelReasoningProfileDAO(
                supported_levels=["off", "low"],
                default_level="low",
                provider_effort_map={"low": "low", "high": "high"},
            )

    def test_rejects_reasoning_enabled_level_without_translation(self) -> None:
        """Every reasoning-enabled supported level needs effort or budget."""
        from src.agents.model_catalog.dao import ModelReasoningProfileDAO

        with pytest.raises(ValueError, match="translation"):
            ModelReasoningProfileDAO(
                supported_levels=["off", "low", "high"],
                default_level="high",
                provider_effort_map={"low": "low"},
            )

    def test_rejects_effort_and_budget_for_one_level(self) -> None:
        """A level carries exactly one translation — effort XOR budget."""
        from src.agents.model_catalog.dao import ModelReasoningProfileDAO

        with pytest.raises(ValueError, match="exactly one"):
            ModelReasoningProfileDAO(
                supported_levels=["off", "low"],
                default_level="low",
                provider_effort_map={"low": "low"},
                provider_budget_map={"low": 2048},
            )

    def test_rejects_provider_reasoning_required_without_off_support(self) -> None:
        """``provider_reasoning_required`` needs ``off`` among supported levels."""
        from src.agents.model_catalog.dao import ModelReasoningProfileDAO

        with pytest.raises(ValueError, match="provider_reasoning_required"):
            ModelReasoningProfileDAO(
                supported_levels=["low", "high"],
                default_level="high",
                provider_effort_map={"low": "low", "high": "high"},
                provider_reasoning_required=True,
            )

    def test_rejects_provider_reasoning_required_without_off_effort_mapping(self) -> None:
        """``provider_reasoning_required`` needs an ``off`` provider-effort mapping."""
        from src.agents.model_catalog.dao import ModelReasoningProfileDAO

        with pytest.raises(ValueError, match="off"):
            ModelReasoningProfileDAO(
                supported_levels=["off", "low"],
                default_level="low",
                provider_effort_map={"low": "low"},
                provider_reasoning_required=True,
            )

    def test_accepts_plain_off_profile_without_off_translation(self) -> None:
        """Off-only profiles with disabled provider reasoning stay valid."""
        from src.agents.model_catalog.dao import ModelReasoningProfileDAO

        profile = ModelReasoningProfileDAO(
            supported_levels=["off"],
            default_level="off",
        )

        assert profile.provider_reasoning_required is False
        assert profile.forbid_sampling_parameters_when_enabled is False

    def test_accepts_budget_only_translation(self) -> None:
        """A budget-only translation satisfies the enabled-level requirement."""
        from src.agents.model_catalog.dao import ModelReasoningProfileDAO

        profile = ModelReasoningProfileDAO(
            supported_levels=["off", "low"],
            default_level="low",
            provider_budget_map={"low": 2048},
        )

        assert profile.provider_budget_map == {"low": 2048}

    def test_all_seed_profiles_preserve_canonical_order(self) -> None:
        """Every seeded profile's supported levels are unique and canonically ordered."""
        from src.agents.model_catalog.dao import CANONICAL_REASONING_LEVEL_ORDER
        from src.agents.model_catalog.seed import SeedModelCatalog

        ordered_index: dict[str, int] = {
            level: index for index, level in enumerate(CANONICAL_REASONING_LEVEL_ORDER)
        }

        for model_name, entry in SeedModelCatalog.load().entries.items():
            levels: list[str] = list(entry.reasoning_profile.supported_levels)
            assert len(levels) == len(set(levels)), model_name
            assert [ordered_index[level] for level in levels] == sorted(
                ordered_index[level] for level in levels
            ), model_name


class TestAstraReasoningCapability:
    """Feature 83.a.1: generic reasoning resolution for ``gpt-6-astra``."""

    def test_astra_capability_supports_all_seven_levels(self) -> None:
        """Astra's capability record exposes every canonical level plus both flags."""
        capability: ModelReasoningCapabilityDAO = capability_for_model(model_name="gpt-6-astra")

        assert capability.reasoning_supported is True
        assert capability.supported_levels == list(REASONING_LEVELS)
        assert capability.provider_reasoning_required is True
        assert capability.forbid_sampling_parameters_when_enabled is True

    def test_astra_default_reasoning_level_is_high(self) -> None:
        """Astra seeds to ``high`` by default."""
        assert default_reasoning_level_for_model(model_name="gpt-6-astra") == "high"

    def test_astra_highest_supported_level_is_max(self) -> None:
        """Astra's strongest supported level is canonical ``max``."""
        assert highest_supported_reasoning_level(model_name="gpt-6-astra") == "max"

    @pytest.mark.parametrize(
        ("requested_level", "provider_effort"),
        [
            ("off", "low"),
            ("minimal", "low"),
            ("low", "low"),
            ("medium", "medium"),
            ("high", "high"),
            ("xhigh", "xhigh"),
            ("max", "max"),
        ],
    )
    def test_astra_resolve_reasoning_config_maps_all_canonical_levels(
        self,
        requested_level: str,
        provider_effort: str,
    ) -> None:
        """Every Astra input resolves enabled with the exact documented effort."""
        resolved: ResolvedReasoningConfigDAO = resolve_reasoning_config(
            model_name="gpt-6-astra",
            requested_level=requested_level,  # type: ignore[arg-type]
        )

        assert resolved.enabled is True
        assert resolved.requested_level == requested_level
        assert resolved.active_level == requested_level
        assert resolved.provider_effort == provider_effort
        assert resolved.provider_effort not in {"none", "off"}
        assert resolved.provider_summary_mode == "auto"

    def test_astra_off_preserves_active_off_while_enabling_low_effort(self) -> None:
        """Selected Slo ``off`` stays canonical off but resolves enabled low effort."""
        resolved: ResolvedReasoningConfigDAO = resolve_reasoning_config(
            model_name="gpt-6-astra",
            requested_level="off",
        )

        assert resolved.enabled is True
        assert resolved.active_level == "off"
        assert resolved.provider_effort == "low"

    def test_gpt_5_4_off_stays_disabled(self) -> None:
        """Legacy ``provider_reasoning_required=False`` profiles keep off disabled."""
        resolved: ResolvedReasoningConfigDAO = resolve_reasoning_config(
            model_name="gpt-5.4",
            requested_level="off",
        )

        assert resolved.enabled is False
        assert resolved.active_level == "off"
        assert resolved.provider_effort is None

    def test_k3_xhigh_maps_to_provider_max_unchanged(self) -> None:
        """K3 retains its existing ``xhigh -> max`` provider mapping."""
        resolved: ResolvedReasoningConfigDAO = resolve_reasoning_config(
            model_name="kimi-k3",
            requested_level="xhigh",
        )

        assert resolved.enabled is True
        assert resolved.active_level == "xhigh"
        assert resolved.provider_effort == "max"

    def test_max_token_clamps_to_legacy_highest_for_models_without_max(self) -> None:
        """Canonical ``max`` clamps downward for legacy profiles that omit it."""
        active_level: str = clamp_reasoning_level(
            model_name="gpt-5.4",
            requested_level="max",
        )

        assert active_level == "xhigh"
        assert highest_supported_reasoning_level(model_name="gpt-5.4") == "xhigh"
