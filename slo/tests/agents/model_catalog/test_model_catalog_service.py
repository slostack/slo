"""Tests for ModelCatalogService load, resolution, and projections."""

from __future__ import annotations

import json

from unittest.mock import patch

import pytest

from src.agents.model_catalog.dao import (
    ModelAliasDAO,
    ModelCatalogEntryDAO,
    ModelCatalogOverrideDAO,
    ModelCatalogSnapshotDAO,
)
from src.agents.model_catalog.seed import SeedModelCatalog
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


class TestApiModelNameFor:
    """api_model_name_for resolution (spec 54)."""

    def test_identity_when_api_model_name_is_none(self) -> None:
        """Entries without an override resolve to their canonical model name."""
        ModelCatalogService.reset()

        assert ModelCatalogService.api_model_name_for(model_name="claude-opus-4-8") == "claude-opus-4-8"

    @pytest.mark.parametrize(
        ("model_name", "expected_api_model_name"),
        [
            ("claude-opus-4-8-1m-context", "claude-opus-4-8"),
            ("claude-sonnet-4-6-1m-context", "claude-sonnet-4-6"),
            ("claude-haiku-4-5", "claude-haiku-4-5-20251001"),
            ("claude-fable", "claude-fable-5"),
        ],
    )
    def test_override_wins_for_mapped_entries(
        self,
        model_name: str,
        expected_api_model_name: str,
    ) -> None:
        """Entries with an api_model_name override resolve to the API model ID."""
        ModelCatalogService.reset()

        assert ModelCatalogService.api_model_name_for(model_name=model_name) == expected_api_model_name

    def test_alias_resolves_to_canonical_api_model_name(self) -> None:
        """Aliases resolve through their canonical entry before the fallback."""
        ModelCatalogService.reset()

        assert ModelCatalogService.api_model_name_for(model_name="moonshot-for-coding") == "kimi-for-coding"

    def test_alias_inherits_canonical_api_model_name_override(self) -> None:
        """An alias of an entry with an api_model_name override inherits the override."""
        ModelCatalogService.reset()
        seed_snapshot: ModelCatalogSnapshotDAO = SeedModelCatalog.load()
        patched_aliases: dict[str, ModelAliasDAO] = dict(seed_snapshot.aliases)
        patched_aliases["opus-4-8-1m-alias"] = ModelAliasDAO(
            alias="opus-4-8-1m-alias",
            canonical_model_name="claude-opus-4-8-1m-context",
            support_tier="compatibility_only",
        )
        patched_snapshot: ModelCatalogSnapshotDAO = ModelCatalogSnapshotDAO(
            schema_version=seed_snapshot.schema_version,
            generated_at=seed_snapshot.generated_at,
            entries=seed_snapshot.entries,
            aliases=patched_aliases,
            templates=seed_snapshot.templates,
        )
        with patch.object(ModelCatalogService, "load", return_value=patched_snapshot):
            assert ModelCatalogService.api_model_name_for(model_name="opus-4-8-1m-alias") == "claude-opus-4-8"

    def test_unknown_model_raises_value_error(self) -> None:
        """Unknown names raise the same ValueError as entry_for_model."""
        ModelCatalogService.reset()

        with pytest.raises(ValueError, match="Unsupported model_name"):
            ModelCatalogService.api_model_name_for(model_name="not-a-real-model")
