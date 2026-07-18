"""Tests for ModelCatalogService load, resolution, and projections."""

from __future__ import annotations

import json

import pytest

from src.agents.model_catalog.dao import (
    ModelCatalogEntryDAO,
    ModelCatalogOverrideDAO,
    ModelCatalogSnapshotDAO,
)
from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_dao import ProviderName


class TestModelCatalogServiceLoad:
    """Load path and memoization."""

    def test_load_returns_seed_when_no_cache(self, tmp_path) -> None:
        """A fresh process loads the committed seed catalog."""
        ModelCatalogService.reset()

        snapshot = ModelCatalogService.load()

        assert "gpt-5.5" in snapshot.entries
        assert "claude-mythos" in snapshot.entries

    def test_load_is_memoized(self, tmp_path) -> None:
        """Repeated calls return the same snapshot object."""
        ModelCatalogService.reset()

        first = ModelCatalogService.load()
        second = ModelCatalogService.load()

        assert first is second


class TestEntryResolution:
    """Canonical-name and alias resolution."""

    def test_entry_for_model_returns_canonical_entry(self) -> None:
        """Canonical model names resolve to their catalog entry."""
        ModelCatalogService.reset()

        entry: ModelCatalogEntryDAO = ModelCatalogService.entry_for_model(model_name="gpt-5.6-sol")

        assert entry.provider is ProviderName.OPENAI
        assert entry.support_tier == "first_class"

    def test_entry_for_model_resolves_legacy_alias(self) -> None:
        """Legacy moonshot aliases resolve to the canonical entry."""
        ModelCatalogService.reset()

        entry: ModelCatalogEntryDAO = ModelCatalogService.entry_for_model(
            model_name="moonshot-for-coding",
        )

        assert entry.model_name == "kimi-for-coding"

    def test_entry_for_model_raises_for_unknown(self) -> None:
        """Unknown names raise a clear ValueError."""
        ModelCatalogService.reset()

        with pytest.raises(ValueError, match="Unsupported model_name"):
            ModelCatalogService.entry_for_model(model_name="not-a-real-model")


class TestSupportedModelsProjection:
    """Picker-visible projections."""

    def test_supported_models_by_provider_groups_visible_entries(self) -> None:
        """Visible entries are grouped and sorted by provider."""
        ModelCatalogService.reset()

        grouped = ModelCatalogService.supported_models_by_provider()

        assert "gpt-5.5" in grouped[ProviderName.OPENAI]
        assert "claude-fable" in grouped[ProviderName.ANTHROPIC]
        assert "kimi-k3" in grouped[ProviderName.KIMI_FOR_CODING]
        for models in grouped.values():
            assert models == sorted(models)

    def test_claude_mythos_is_hidden_by_default(self) -> None:
        """The conditional entry is absent from visible projections."""
        ModelCatalogService.reset()

        grouped = ModelCatalogService.supported_models_by_provider()
        for models in grouped.values():
            assert "claude-mythos" not in models
