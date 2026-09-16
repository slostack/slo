"""Tests for the model catalog seed data."""

from __future__ import annotations

import pytest

from src.agents.model_catalog.seed import SeedModelCatalog
from src.auth.credential_dao import ProviderName


class TestSeedCatalog:
    """First-class entries and snapshot invariants."""

    def test_seed_loads_first_class_entries(self) -> None:
        """All eight spec-55 models are present as first-class entries."""
        snapshot = SeedModelCatalog.load()

        for model_name in [
            "gpt-5.5",
            "gpt-5.6-luna",
            "gpt-5.6-sol",
            "gpt-5.6-terra",
            "claude-fable",
            "claude-mythos",
            "kimi-k3",
            "kimi-for-coding-highspeed",
        ]:
            assert model_name in snapshot.entries, model_name
            assert snapshot.entries[model_name].support_tier == "first_class"

    def test_claude_mythos_is_hidden_by_default(self) -> None:
        """The conditional first-class entry is not visible until discovery."""
        snapshot = SeedModelCatalog.load()

        entry = snapshot.entries["claude-mythos"]
        assert entry.visible_in_picker is False

    def test_claude_mythos_reasoning_capped_at_high(self) -> None:
        """Seed data does not claim xhigh for claude-mythos."""
        snapshot = SeedModelCatalog.load()

        entry = snapshot.entries["claude-mythos"]
        assert "xhigh" not in entry.reasoning_profile.supported_levels
        assert "high" in entry.reasoning_profile.supported_levels

    def test_openai_flagship_reasoning_supports_xhigh(self) -> None:
        """GPT-5.5/5.6 seeded with xhigh reasoning support."""
        snapshot = SeedModelCatalog.load()

        for model_name in ["gpt-5.5", "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra"]:
            assert "xhigh" in snapshot.entries[model_name].reasoning_profile.supported_levels

    def test_kimi_k3_profile_has_only_verified_effort_levels(self) -> None:
        """K3 declares its verified levels, default, and native effort map."""
        snapshot = SeedModelCatalog.load()

        profile = snapshot.entries["kimi-k3"].reasoning_profile
        assert profile.supported_levels == ["low", "high", "xhigh"]
        assert profile.default_level == "xhigh"
        assert profile.provider_effort_map == {
            "low": "low",
            "high": "high",
            "xhigh": "max",
        }

    @pytest.mark.parametrize("model_name", ["kimi-for-coding", "kimi-for-coding-highspeed"])
    def test_k2_models_remain_off_only(self, model_name: str) -> None:
        """K2 coding models do not expose configurable reasoning in seed."""
        snapshot = SeedModelCatalog.load()

        profile = snapshot.entries[model_name].reasoning_profile
        assert profile.supported_levels == ["off"]
        assert profile.default_level == "off"
        assert profile.provider_effort_map == {}

    def test_existing_models_preserved(self) -> None:
        """Pre-spec-55 curated models remain first-class."""
        snapshot = SeedModelCatalog.load()

        for model_name in [
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "gpt-5.4",
            "gpt-5-codex",
            "kimi-for-coding",
        ]:
            assert model_name in snapshot.entries

    def test_provider_assignment(self) -> None:
        """New models map to the correct providers."""
        snapshot = SeedModelCatalog.load()

        assert snapshot.entries["gpt-5.5"].provider is ProviderName.OPENAI
        assert snapshot.entries["claude-fable"].provider is ProviderName.ANTHROPIC
        assert snapshot.entries["kimi-k3"].provider is ProviderName.KIMI_FOR_CODING


class TestSeedTemplates:
    """Family templates for future discovery."""

    def test_openai_latest_template_is_visible(self) -> None:
        """The GPT-5.5/5.6 family template defaults to visible."""
        snapshot = SeedModelCatalog.load()

        template = next(t for t in snapshot.templates if "gpt-5." in t.family_patterns)
        assert template.default_visible is True
        assert template.provider is ProviderName.OPENAI

    def test_anthropic_latest_template_is_visible(self) -> None:
        """The Claude family template defaults to visible."""
        snapshot = SeedModelCatalog.load()

        template = next(t for t in snapshot.templates if "claude-" in t.family_patterns)
        assert template.default_visible is True
        assert template.provider is ProviderName.ANTHROPIC

    def test_kimi_latest_template_is_visible(self) -> None:
        """The Kimi family template defaults to visible."""
        snapshot = SeedModelCatalog.load()

        template = next(t for t in snapshot.templates if "kimi-" in t.family_patterns)
        assert template.default_visible is True
        assert template.provider is ProviderName.KIMI_FOR_CODING


class TestSeedAliases:
    """Backward-compatible aliases are explicit."""

    def test_legacy_moonshot_aliases_resolve(self) -> None:
        """Legacy moonshot aliases resolve to kimi-for-coding."""
        snapshot = SeedModelCatalog.load()

        for alias in ["moonshot-k2", "moonshot-for-coding"]:
            assert alias in snapshot.aliases
            assert snapshot.aliases[alias].canonical_model_name == "kimi-for-coding"

    def test_kimi_k2_alias_is_compatibility_only(self) -> None:
        """The kimi-k2 alias is marked compatibility_only."""
        snapshot = SeedModelCatalog.load()

        assert snapshot.aliases["kimi-k2"].support_tier == "compatibility_only"


class TestClaude48SeedEntries:
    """Spec-54 first-class Claude 4.8 / Haiku 4.5 / 1M-context entries."""

    NEW_MODEL_NAMES: list[str] = [
        "claude-opus-4-8",
        "claude-opus-4-8-1m-context",
        "claude-sonnet-4-6-1m-context",
        "claude-haiku-4-5",
    ]

    def test_new_models_are_first_class_visible_anthropic_entries(self) -> None:
        """All four spec-54 models are first-class, picker-visible Anthropic entries."""
        snapshot = SeedModelCatalog.load()

        for model_name in self.NEW_MODEL_NAMES:
            entry = snapshot.entries[model_name]
            assert entry.support_tier == "first_class", model_name
            assert entry.visible_in_picker is True, model_name
            assert entry.provider is ProviderName.ANTHROPIC, model_name

    def test_new_models_display_names(self) -> None:
        """Each spec-54 entry carries its spec'd display name."""
        snapshot = SeedModelCatalog.load()

        assert snapshot.entries["claude-opus-4-8"].display_name == "Claude Opus 4.8"
        assert snapshot.entries["claude-opus-4-8-1m-context"].display_name == "Claude Opus 4.8 (1M context)"
        assert (
            snapshot.entries["claude-sonnet-4-6-1m-context"].display_name == "Claude Sonnet 4.6 (1M context)"
        )
        assert snapshot.entries["claude-haiku-4-5"].display_name == "Claude Haiku 4.5"

    def test_context_windows(self) -> None:
        """1M variants expose the 1M context window; base models stay at 200K."""
        snapshot = SeedModelCatalog.load()

        assert snapshot.entries["claude-opus-4-8-1m-context"].runtime_profile.context_window == 1_000_000
        assert snapshot.entries["claude-opus-4-8"].runtime_profile.context_window == 200_000
        assert snapshot.entries["claude-sonnet-4-6-1m-context"].runtime_profile.context_window == 1_000_000

    def test_max_tokens(self) -> None:
        """Opus variants carry the 128K ceiling; sonnet-1M and haiku carry 64K."""
        snapshot = SeedModelCatalog.load()

        assert snapshot.entries["claude-opus-4-8"].runtime_profile.max_tokens == 128_000
        assert snapshot.entries["claude-opus-4-8-1m-context"].runtime_profile.max_tokens == 128_000
        assert snapshot.entries["claude-sonnet-4-6-1m-context"].runtime_profile.max_tokens == 64_000
        assert snapshot.entries["claude-haiku-4-5"].runtime_profile.max_tokens == 64_000

    def test_xhigh_support_only_on_opus_variants(self) -> None:
        """Opus 4.8 variants support xhigh; sonnet-1M and haiku do not."""
        snapshot = SeedModelCatalog.load()

        assert "xhigh" in snapshot.entries["claude-opus-4-8"].reasoning_profile.supported_levels
        assert "xhigh" in snapshot.entries["claude-opus-4-8-1m-context"].reasoning_profile.supported_levels
        assert (
            "xhigh" not in snapshot.entries["claude-sonnet-4-6-1m-context"].reasoning_profile.supported_levels
        )
        assert "xhigh" not in snapshot.entries["claude-haiku-4-5"].reasoning_profile.supported_levels

    def test_rate_limit_knobs_mirror_existing_anthropic_entries(self) -> None:
        """RPM/TPM/retry knobs match the existing Anthropic entries."""
        snapshot = SeedModelCatalog.load()

        for model_name in self.NEW_MODEL_NAMES:
            profile = snapshot.entries[model_name].runtime_profile
            assert profile.requests_per_minute == 60, model_name
            assert profile.tokens_per_minute == 200_000, model_name
            assert profile.automatic_retry_attempts == 2, model_name
            assert profile.local_retry_wait_cap_seconds == 30, model_name
            assert profile.streaming is True, model_name


class TestApiModelNameSeedMappings:
    """Spec-54 api_model_name seed mappings (canonical name vs API model ID)."""

    def test_opus_1m_shares_api_id_with_base_opus(self) -> None:
        """claude-opus-4-8-1m-context routes to the claude-opus-4-8 API ID."""
        snapshot = SeedModelCatalog.load()

        assert snapshot.entries["claude-opus-4-8-1m-context"].api_model_name == "claude-opus-4-8"

    def test_sonnet_1m_shares_api_id_with_base_sonnet(self) -> None:
        """claude-sonnet-4-6-1m-context routes to the claude-sonnet-4-6 API ID."""
        snapshot = SeedModelCatalog.load()

        assert snapshot.entries["claude-sonnet-4-6-1m-context"].api_model_name == "claude-sonnet-4-6"

    def test_haiku_maps_to_dated_api_id(self) -> None:
        """claude-haiku-4-5 routes to the dated claude-haiku-4-5-20251001 API ID."""
        snapshot = SeedModelCatalog.load()

        assert snapshot.entries["claude-haiku-4-5"].api_model_name == "claude-haiku-4-5-20251001"

    def test_opus_4_8_api_model_name_is_identity(self) -> None:
        """claude-opus-4-8 has no api_model_name override (identity)."""
        snapshot = SeedModelCatalog.load()

        assert snapshot.entries["claude-opus-4-8"].api_model_name is None

    def test_fable_api_model_name_is_claude_fable_5(self) -> None:
        """claude-fable routes to the claude-fable-5 API ID; the name is unchanged."""
        snapshot = SeedModelCatalog.load()

        entry = snapshot.entries["claude-fable"]
        assert entry.model_name == "claude-fable"
        assert entry.api_model_name == "claude-fable-5"


class TestAnthropicProviderDefault:
    """Spec-54 Anthropic provider default model."""

    def test_anthropic_default_is_opus_4_8_1m_context(self) -> None:
        """provider_default_models lands Anthropic on claude-opus-4-8-1m-context."""
        defaults = SeedModelCatalog.provider_default_models()

        assert defaults[ProviderName.ANTHROPIC] == "claude-opus-4-8-1m-context"
