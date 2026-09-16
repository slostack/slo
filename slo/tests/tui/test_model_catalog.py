"""Tests for the TUI model catalog projection and rendering."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.agents.model_catalog.dao import (
    ModelCatalogEntryDAO,
    ModelCatalogSnapshotDAO,
    ModelReasoningProfileDAO,
    ModelRuntimeProfileDAO,
)
from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_dao import ProviderName
from src.tui.model_catalog import (
    MODEL_CATALOG,
    ModelSuggestionEntryDAO,
    model_suggestion_entries,
    supported_models_by_provider,
)


class TestModelCatalog:
    """Static ``MODEL_CATALOG`` structure and Kimi For Coding entries."""

    def test_catalog_contains_kimi_for_coding_entries(self) -> None:
        """MODEL_CATALOG has at least one entry with provider=='kimi_for_coding'."""
        kfc_entries: list[ModelCatalogEntryDAO] = [
            e for e in MODEL_CATALOG if e.provider == "kimi_for_coding"
        ]
        assert len(kfc_entries) >= 1

    def test_kimi_for_coding_is_in_catalog(self) -> None:
        """``kimi-for-coding`` is a catalog entry."""
        model_names: list[str] = [e.model_name for e in MODEL_CATALOG]
        assert "kimi-for-coding" in model_names

    def test_kimi_for_coding_display_name_is_descriptive(self) -> None:
        """``kimi-for-coding`` entry has a display name mentioning Kimi."""
        entry = next(e for e in MODEL_CATALOG if e.model_name == "kimi-for-coding")
        assert "Kimi" in entry.display_name

    def test_catalog_has_anthropic_entries(self) -> None:
        """MODEL_CATALOG has at least one Anthropic entry."""
        anthropic_entries: list[ModelCatalogEntryDAO] = [
            e for e in MODEL_CATALOG if e.provider == "anthropic"
        ]
        assert len(anthropic_entries) >= 1

    def test_catalog_has_openai_entries(self) -> None:
        """MODEL_CATALOG has at least one OpenAI entry."""
        openai_entries: list[ModelCatalogEntryDAO] = [e for e in MODEL_CATALOG if e.provider == "openai"]
        assert len(openai_entries) >= 1

    @pytest.mark.parametrize(
        "model_name",
        [
            "gpt-5-codex",
            "gpt-5.3-codex",
            "gpt-5.2-codex",
            "gpt-5.3-codex-spark",
        ],
    )
    def test_codex_models_are_in_catalog(self, model_name: str) -> None:
        """Each OpenAI Codex variant is a catalog entry."""
        model_names: list[str] = [e.model_name for e in MODEL_CATALOG]
        assert model_name in model_names

    def test_codex_models_are_openai_entries(self) -> None:
        """Codex catalog entries carry the openai provider label."""
        codex_entries: list[ModelCatalogEntryDAO] = [
            e for e in MODEL_CATALOG if e.model_name.startswith("gpt-5") and "codex" in e.model_name
        ]
        assert len(codex_entries) >= 4
        for entry in codex_entries:
            assert entry.provider == "openai"
            assert entry.display_name.strip()

    def test_all_entries_have_display_name(self) -> None:
        """Every catalog entry has a non-empty display_name."""
        for entry in MODEL_CATALOG:
            assert entry.display_name.strip(), f"Empty display_name for {entry.model_name}"

    def test_all_entries_have_model_name(self) -> None:
        """Every catalog entry has a non-empty model_name."""
        for entry in MODEL_CATALOG:
            assert entry.model_name.strip(), f"Empty model_name for provider {entry.provider}"


class TestSupportedModelsByProvider:
    """``supported_models_by_provider`` grouping and latest-model support."""

    def test_returns_dict_with_kimi_for_coding_key(self) -> None:
        """The returned dict has a ``ProviderName.KIMI_FOR_CODING`` key."""
        result: dict[ProviderName, list[str]] = supported_models_by_provider()
        assert ProviderName.KIMI_FOR_CODING in result

    def test_returns_dict_with_anthropic_key(self) -> None:
        """The returned dict has a ``ProviderName.ANTHROPIC`` key."""
        result: dict[ProviderName, list[str]] = supported_models_by_provider()
        assert ProviderName.ANTHROPIC in result

    def test_returns_dict_with_openai_key(self) -> None:
        """The returned dict has a ``ProviderName.OPENAI`` key."""
        result: dict[ProviderName, list[str]] = supported_models_by_provider()
        assert ProviderName.OPENAI in result

    def test_kimi_for_coding_models_are_sorted(self) -> None:
        """Kimi For Coding models in the grouped result are alphabetically sorted."""
        result: dict[ProviderName, list[str]] = supported_models_by_provider()
        kfc_models: list[str] = result[ProviderName.KIMI_FOR_CODING]
        assert kfc_models == sorted(kfc_models)

    def test_all_values_are_lists(self) -> None:
        """Every value in the result dict is a list."""
        result: dict[ProviderName, list[str]] = supported_models_by_provider()
        for provider, models in result.items():
            assert isinstance(models, list), f"Expected list for {provider}, got {type(models)}"

    def test_latest_first_class_models_appear(self) -> None:
        """Spec-55 models are listed by their correct providers."""
        result: dict[ProviderName, list[str]] = supported_models_by_provider()

        assert "gpt-5.5" in result[ProviderName.OPENAI]
        assert "gpt-5.6-luna" in result[ProviderName.OPENAI]
        assert "claude-fable" in result[ProviderName.ANTHROPIC]
        assert "kimi-k3" in result[ProviderName.KIMI_FOR_CODING]

    def test_claude_mythos_is_hidden_by_default(self) -> None:
        """The conditional entry is not visible."""
        result: dict[ProviderName, list[str]] = supported_models_by_provider()
        for models in result.values():
            assert "claude-mythos" not in models


class TestModelSuggestionEntries:
    """Rich model rows for ``/model`` suggestions."""

    def test_auto_discovered_models_are_marked(self) -> None:
        """Auto-discovered entries carry the support-tier label."""
        auto_entry = ModelCatalogEntryDAO(
            model_name="gpt-5.7-nebula",
            display_name="GPT-5.7 Nebula",
            provider=ProviderName.OPENAI,
            support_tier="auto_discovered",
            visible_in_picker=True,
            runtime_profile=ModelRuntimeProfileDAO(
                max_tokens=8_192,
                context_window=1_050_000,
                streaming=True,
                requests_per_minute=30,
                tokens_per_minute=500_000,
                automatic_retry_attempts=2,
                local_retry_wait_cap_seconds=30,
            ),
            reasoning_profile=ModelReasoningProfileDAO(
                supported_levels=["off", "minimal", "low", "medium", "high", "xhigh"],
                default_level="high",
            ),
        )
        base_snapshot = ModelCatalogService.load()
        patched_snapshot = ModelCatalogSnapshotDAO(
            schema_version=base_snapshot.schema_version,
            generated_at=base_snapshot.generated_at,
            entries={**base_snapshot.entries, "gpt-5.7-nebula": auto_entry},
            aliases=base_snapshot.aliases,
            templates=base_snapshot.templates,
        )
        with patch.object(ModelCatalogService, "load", return_value=patched_snapshot):
            entries: list[ModelSuggestionEntryDAO] = model_suggestion_entries(
                active_model_name="gpt-5.4",
            )
        entry = next((e for e in entries if e.model_name == "gpt-5.7-nebula"), None)
        assert entry is not None
        assert entry.support_tier_label == "auto-discovered"


class TestKimiK3SuggestionEntries:
    """K3 reasoning projections in the model picker."""

    def test_kimi_k3_suggestion_exposes_three_level_reasoning_profile(self) -> None:
        """K3 lists its supported levels while K2 remains off-only."""
        entries: list[ModelSuggestionEntryDAO] = model_suggestion_entries(
            active_model_name="kimi-k3",
        )
        entries_by_name: dict[str, ModelSuggestionEntryDAO] = {entry.model_name: entry for entry in entries}

        assert entries_by_name["kimi-k3"].reasoning_summary == "low, high, xhigh"
        assert entries_by_name["kimi-k3"].is_active is True
        assert entries_by_name["kimi-for-coding"].reasoning_summary == "off"


class TestClaude48SuggestionEntries:
    """Spec-54 Claude models in the TUI picker projections."""

    EXPECTED_DISPLAY_NAMES: dict[str, str] = {
        "claude-opus-4-8": "Claude Opus 4.8",
        "claude-opus-4-8-1m-context": "Claude Opus 4.8 (1M context)",
        "claude-sonnet-4-6-1m-context": "Claude Sonnet 4.6 (1M context)",
        "claude-haiku-4-5": "Claude Haiku 4.5",
    }

    def test_spec54_models_in_model_catalog_with_display_names(self) -> None:
        """MODEL_CATALOG lists the four spec-54 models with their display names."""
        catalog_by_name: dict[str, str] = {e.model_name: e.display_name for e in MODEL_CATALOG}
        for model_name, display_name in self.EXPECTED_DISPLAY_NAMES.items():
            assert catalog_by_name.get(model_name) == display_name, model_name

    def test_spec54_models_in_supported_models_by_provider(self) -> None:
        """All four spec-54 models are picker-visible under Anthropic."""
        result: dict[ProviderName, list[str]] = supported_models_by_provider()
        for model_name in self.EXPECTED_DISPLAY_NAMES:
            assert model_name in result[ProviderName.ANTHROPIC], model_name

    def test_spec54_models_in_model_suggestion_entries(self) -> None:
        """model_suggestion_entries includes the four spec-54 Anthropic rows with display names."""
        entries: list[ModelSuggestionEntryDAO] = model_suggestion_entries(
            active_model_name="claude-opus-4-8",
        )
        entries_by_name: dict[str, ModelSuggestionEntryDAO] = {e.model_name: e for e in entries}
        for model_name, display_name in self.EXPECTED_DISPLAY_NAMES.items():
            entry = entries_by_name.get(model_name)
            assert entry is not None, model_name
            assert entry.provider is ProviderName.ANTHROPIC, model_name
            assert entry.display_name == display_name, model_name
        assert entries_by_name["claude-opus-4-8"].is_active is True
        assert entries_by_name["claude-haiku-4-5"].is_active is False
