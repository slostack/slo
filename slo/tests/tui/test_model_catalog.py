"""Tests for ``src.tui.model_catalog`` (spec 28.a.5)."""
from __future__ import annotations

import pytest

from src.auth.credential_dao import ProviderName
from src.tui.model_catalog import (
    MODEL_CATALOG,
    ModelCatalogEntryDAO,
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
        openai_entries: list[ModelCatalogEntryDAO] = [
            e for e in MODEL_CATALOG if e.provider == "openai"
        ]
        assert len(openai_entries) >= 1

    @pytest.mark.parametrize("model_name", [
        "gpt-5-codex",
        "gpt-5.3-codex",
        "gpt-5.2-codex",
        "gpt-5.3-codex-spark",
    ])
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
    """``supported_models_by_provider`` grouping and Kimi For Coding key."""

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

    def test_kimi_models_appear_under_kimi_for_coding_group(self) -> None:
        """``kimi-*`` model names appear in the KIMI_FOR_CODING group."""
        result: dict[ProviderName, list[str]] = supported_models_by_provider()
        kfc_models: list[str] = result[ProviderName.KIMI_FOR_CODING]
        kimi_models: list[str] = [m for m in kfc_models if m.startswith("kimi-")]
        assert len(kimi_models) >= 1

    def test_all_values_are_lists(self) -> None:
        """Every value in the result dict is a list."""
        result: dict[ProviderName, list[str]] = supported_models_by_provider()
        for provider, models in result.items():
            assert isinstance(models, list), f"Expected list for {provider}, got {type(models)}"
