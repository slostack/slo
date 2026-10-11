"""Tests for discovery merge, template matching, and auto-discovered entries."""

from __future__ import annotations

from src.agents.model_catalog.dao import (
    ModelCatalogSnapshotDAO,
    ProviderDiscoveryResultDAO,
    ProviderModelMetadataDAO,
    ProviderModelTemplateDAO,
)
from src.agents.model_catalog.discovery import ProviderModelDiscoveryService
from src.agents.model_catalog.seed import SeedModelCatalog
from src.auth.credential_dao import ProviderName


class TestDiscoveryMerge:
    """Provider discovery result merging."""

    def test_discovered_claude_mythos_becomes_visible(self) -> None:
        """When discovery lists claude-mythos it becomes visible."""
        base = SeedModelCatalog.load()
        result = ProviderDiscoveryResultDAO(
            provider=ProviderName.ANTHROPIC,
            available_model_names=["claude-mythos"],
        )

        refreshed = base.model_copy(
            update={
                "entries": ProviderModelDiscoveryService._merge_provider_result(
                    entries=dict(base.entries), templates=base.templates, result=result
                )
            }
        )

        entry = refreshed.entries["claude-mythos"]
        assert entry.visible_in_picker is True

    def test_discovered_new_openai_model_uses_template(self) -> None:
        """A discovered unknown OpenAI latest-family model becomes auto_discovered."""
        base = SeedModelCatalog.load()
        result = ProviderDiscoveryResultDAO(
            provider=ProviderName.OPENAI,
            available_model_names=["gpt-5.7-nebula"],
        )

        refreshed = base.model_copy(
            update={
                "entries": ProviderModelDiscoveryService._merge_provider_result(
                    entries=dict(base.entries), templates=base.templates, result=result
                )
            }
        )

        entry = refreshed.entries["gpt-5.7-nebula"]
        assert entry.support_tier == "auto_discovered"
        assert entry.visible_in_picker is True

    def test_discovered_model_without_template_is_ignored(self) -> None:
        """A discovered name that matches no family template is not added."""
        base = SeedModelCatalog.load()
        result = ProviderDiscoveryResultDAO(
            provider=ProviderName.OPENAI,
            available_model_names=["custom-llama-7b"],
        )

        refreshed = base.model_copy(
            update={
                "entries": ProviderModelDiscoveryService._merge_provider_result(
                    entries=dict(base.entries), templates=base.templates, result=result
                )
            }
        )

        assert "custom-llama-7b" not in refreshed.entries


class TestTemplateMatching:
    """Family template matching logic."""

    def test_regex_pattern_matches(self) -> None:
        """Regex patterns anchored with ^ match discovered names."""
        template = ProviderModelTemplateDAO(
            family_patterns=("^gpt-5\\.7-",),
            provider=ProviderName.OPENAI,
            runtime_profile=SeedModelCatalog.load().templates[0].runtime_profile,
            reasoning_profile=SeedModelCatalog.load().templates[0].reasoning_profile,
            default_visible=True,
        )
        base = ModelCatalogSnapshotDAO(
            schema_version="1",
            generated_at="2026-01-01T00:00:00+00:00",
            entries={},
            aliases={},
            templates=(template,),
        )
        result = ProviderDiscoveryResultDAO(
            provider=ProviderName.OPENAI,
            available_model_names=["gpt-5.7-nebula"],
        )

        refreshed = base.model_copy(
            update={
                "entries": ProviderModelDiscoveryService._merge_provider_result(
                    entries=dict(base.entries), templates=base.templates, result=result
                )
            }
        )

        assert "gpt-5.7-nebula" in refreshed.entries

    def test_prefix_pattern_matches(self) -> None:
        """Plain prefix patterns match discovered names."""
        template = ProviderModelTemplateDAO(
            family_patterns=("kimi-",),
            provider=ProviderName.KIMI_FOR_CODING,
            runtime_profile=SeedModelCatalog.load().templates[2].runtime_profile,
            reasoning_profile=SeedModelCatalog.load().templates[2].reasoning_profile,
            default_visible=True,
        )
        base = ModelCatalogSnapshotDAO(
            schema_version="1",
            generated_at="2026-01-01T00:00:00+00:00",
            entries={},
            aliases={},
            templates=(template,),
        )
        result = ProviderDiscoveryResultDAO(
            provider=ProviderName.KIMI_FOR_CODING,
            available_model_names=["kimi-foo"],
        )

        refreshed = base.model_copy(
            update={
                "entries": ProviderModelDiscoveryService._merge_provider_result(
                    entries=dict(base.entries), templates=base.templates, result=result
                )
            }
        )

        assert "kimi-foo" in refreshed.entries


class TestMetadataPatching:
    """Safe metadata from discovery is applied conservatively."""

    def test_discovered_metadata_patches_runtime_profile(self) -> None:
        """Explicitly reported context window is patched into the entry."""
        base = SeedModelCatalog.load()
        result = ProviderDiscoveryResultDAO(
            provider=ProviderName.OPENAI,
            available_model_names=["gpt-5.7-nebula"],
            metadata={
                "gpt-5.7-nebula": ProviderModelMetadataDAO(
                    max_tokens=16_384,
                    context_window=2_000_000,
                ),
            },
        )

        refreshed = base.model_copy(
            update={
                "entries": ProviderModelDiscoveryService._merge_provider_result(
                    entries=dict(base.entries), templates=base.templates, result=result
                )
            }
        )

        entry = refreshed.entries["gpt-5.7-nebula"]
        assert entry.runtime_profile.max_tokens == 16_384
        assert entry.runtime_profile.context_window == 2_000_000
