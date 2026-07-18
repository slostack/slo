"""Tests for manual override application to the catalog snapshot."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.agents.model_catalog.dao import (
    ModelCatalogOverrideDAO,
    ModelReasoningProfileDAO,
    ModelRuntimeProfileDAO,
)
from src.agents.model_catalog.discovery import ModelCatalogOverrideService
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.service import ModelCatalogService


class TestOverrideApplication:
    """Operator overrides patch the merged snapshot."""

    def test_override_forces_visibility_on(self) -> None:
        """An override can make claude-mythos visible."""
        snapshot = SeedModelCatalog.load()
        override = ModelCatalogOverrideDAO(
            model_name="claude-mythos",
            visible_in_picker=True,
        )

        result = ModelCatalogOverrideService.apply_overrides(
            snapshot=snapshot,
            overrides=[override],
        )

        assert result.entries["claude-mythos"].visible_in_picker is True

    def test_override_forces_visibility_off(self) -> None:
        """An override can hide a visible first-class entry."""
        snapshot = SeedModelCatalog.load()
        override = ModelCatalogOverrideDAO(
            model_name="gpt-5.5",
            visible_in_picker=False,
        )

        result = ModelCatalogOverrideService.apply_overrides(
            snapshot=snapshot,
            overrides=[override],
        )

        assert result.entries["gpt-5.5"].visible_in_picker is False

    def test_unknown_override_target_is_ignored(self) -> None:
        """An override for an unknown model does not crash the merge."""
        snapshot = SeedModelCatalog.load()
        override = ModelCatalogOverrideDAO(
            model_name="unknown-model",
            visible_in_picker=True,
        )

        result = ModelCatalogOverrideService.apply_overrides(
            snapshot=snapshot,
            overrides=[override],
        )

        assert result.entries == snapshot.entries

    def test_override_patches_support_tier(self) -> None:
        """An override can change the support tier."""
        snapshot = SeedModelCatalog.load()
        override = ModelCatalogOverrideDAO(
            model_name="gpt-5.5",
            support_tier="compatibility_only",
        )

        result = ModelCatalogOverrideService.apply_overrides(
            snapshot=snapshot,
            overrides=[override],
        )

        assert result.entries["gpt-5.5"].support_tier == "compatibility_only"

    def test_override_patches_runtime_profile(self) -> None:
        """An override can patch runtime defaults."""
        snapshot = SeedModelCatalog.load()
        override = ModelCatalogOverrideDAO(
            model_name="gpt-5.5",
            runtime_profile=ModelRuntimeProfileDAO(
                max_tokens=16_384,
                context_window=2_000_000,
                streaming=True,
                requests_per_minute=100,
                tokens_per_minute=1_000_000,
                automatic_retry_attempts=2,
                local_retry_wait_cap_seconds=30,
            ),
        )

        result = ModelCatalogOverrideService.apply_overrides(
            snapshot=snapshot,
            overrides=[override],
        )

        assert result.entries["gpt-5.5"].runtime_profile.max_tokens == 16_384

    def test_override_patches_reasoning_profile(self) -> None:
        """An override can patch reasoning support."""
        snapshot = SeedModelCatalog.load()
        override = ModelCatalogOverrideDAO(
            model_name="claude-mythos",
            reasoning_profile=ModelReasoningProfileDAO(
                supported_levels=["off", "minimal", "low", "medium", "high", "xhigh"],
                default_level="high",
            ),
        )

        result = ModelCatalogOverrideService.apply_overrides(
            snapshot=snapshot,
            overrides=[override],
        )

        assert "xhigh" in result.entries["claude-mythos"].reasoning_profile.supported_levels

    def test_override_without_target_is_ignored(self) -> None:
        """An override with neither model_name nor alias is ignored."""
        snapshot = SeedModelCatalog.load()
        override = ModelCatalogOverrideDAO()

        result = ModelCatalogOverrideService.apply_overrides(
            snapshot=snapshot,
            overrides=[override],
        )

        assert result.entries == snapshot.entries


class TestServiceOverrideIntegration:
    """Service loads and applies overrides from disk."""

    def test_service_applies_override_file(self, tmp_path) -> None:
        """The service loads overrides and makes claude-mythos visible."""
        overrides_path = tmp_path / "overrides.json"
        overrides_path.write_text(
            '[{"model_name":"claude-mythos","visible_in_picker":true}]',
            encoding="utf-8",
        )
        ModelCatalogService.reset()

        with patch.object(
            ModelCatalogService,
            "_apply_manual_overrides",
            return_value=ModelCatalogOverrideService.apply_overrides(
                snapshot=SeedModelCatalog.load(),
                overrides=[
                    ModelCatalogOverrideDAO(
                        model_name="claude-mythos",
                        visible_in_picker=True,
                    ),
                ],
            ),
        ):
            snapshot = ModelCatalogService.load()

        assert snapshot.entries["claude-mythos"].visible_in_picker is True
