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

    def test_kimi_models_are_off_only(self) -> None:
        """Kimi family models do not expose configurable reasoning in seed."""
        snapshot = SeedModelCatalog.load()

        for model_name in ["kimi-k3", "kimi-for-coding-highspeed", "kimi-for-coding"]:
            profile = snapshot.entries[model_name].reasoning_profile
            assert profile.supported_levels == ["off"]

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
