"""Offline compatibility projections must follow one catalog owner."""

from unittest.mock import patch

import pytest

from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.service import ModelCatalogService


def test_load_when_discovery_is_requested_rejects_before_returning_memoized_snapshot() -> None:
    """The synchronous API rejects discovery even after a normal offline load populated memory."""
    seed = SeedModelCatalog.load()
    with patch.object(ModelCatalogService, "_snapshot", seed):
        with pytest.raises(ValueError, match="asynchronous"):
            ModelCatalogService.load(enable_discovery=True)


def test_reasoning_capability_when_profile_is_off_only_is_not_supported() -> None:
    """Tuple-backed off-only profiles remain visibly non-reasoning models."""
    from src.agents.reasoning_capabilities import capability_for_model

    snapshot = SeedModelCatalog.load()
    capability = capability_for_model(model_name="kimi-for-coding", snapshot=snapshot)

    assert capability.reasoning_supported is False


def test_catalog_lookups_use_supplied_snapshot_without_loading() -> None:
    """An explicitly pinned generation bypasses global reads, including aliases."""
    snapshot = SeedModelCatalog.load()
    with patch.object(ModelCatalogService, "load", side_effect=AssertionError("global read")):
        entry = ModelCatalogService.entry_for_model(model_name="moonshot-for-coding", snapshot=snapshot)
        assert entry.model_name == "kimi-for-coding"
        assert (
            ModelCatalogService.api_model_name_for(model_name="moonshot-for-coding", snapshot=snapshot)
            == "kimi-for-coding"
        )
        assert (
            entry.model_name
            in ModelCatalogService.supported_models_by_provider(snapshot=snapshot)[entry.provider]
        )
        with pytest.raises(ValueError, match="Unsupported model_name"):
            ModelCatalogService.entry_for_model(model_name="openrouter:unknown/exact:free", snapshot=snapshot)


def test_defaults_view_follows_publication_and_cannot_own_mutations() -> None:
    """Imported defaults are live and returned values cannot mutate the catalog."""
    from config.ai_model_config import MODEL_DEFAULTS
    from src.auth.credential_dao import ProviderName

    seed = SeedModelCatalog.load()
    entry = seed.entries["gpt-5.4"].model_copy(
        update={"model_name": "openrouter:vendor/unseeded", "provider": ProviderName.OPENROUTER}
    )
    published = seed.model_copy(update={"entries": {**seed.entries, entry.model_name: entry}})
    with patch.object(ModelCatalogService, "_snapshot", seed):
        assert entry.model_name not in MODEL_DEFAULTS
        ModelCatalogService._snapshot = published
        assert MODEL_DEFAULTS[entry.model_name]["context_window"] == entry.runtime_profile.context_window
        with pytest.raises(TypeError):
            MODEL_DEFAULTS[entry.model_name] = {}  # type: ignore[index]
        MODEL_DEFAULTS[entry.model_name]["context_window"] = 1
        assert MODEL_DEFAULTS[entry.model_name]["context_window"] != 1


def test_reasoning_view_is_live_detached_and_snapshot_aware() -> None:
    """Capabilities and nested clamps must not return to the global generation."""
    from src.agents.reasoning_capabilities import (
        MODEL_REASONING_CAPABILITIES,
        capability_for_model,
        resolve_reasoning_config,
        default_reasoning_level_for_model,
        highest_supported_reasoning_level,
    )

    seed = SeedModelCatalog.load()
    name = "openrouter:vendor/unseeded"
    entry = seed.entries["gpt-5.4"].model_copy(update={"model_name": name})
    pinned = seed.model_copy(update={"entries": {**seed.entries, name: entry}})
    with patch.object(ModelCatalogService, "_snapshot", seed):
        assert name not in MODEL_REASONING_CAPABILITIES
        ModelCatalogService._snapshot = pinned
        assert name in MODEL_REASONING_CAPABILITIES
        with pytest.raises(TypeError):
            MODEL_REASONING_CAPABILITIES[name] = None  # type: ignore[index]
        MODEL_REASONING_CAPABILITIES[name].supported_levels.clear()
        assert MODEL_REASONING_CAPABILITIES[name].supported_levels
    with patch.object(ModelCatalogService, "load", side_effect=AssertionError("global read")):
        assert capability_for_model(model_name=name, snapshot=pinned).reasoning_supported
        assert resolve_reasoning_config(model_name=name, requested_level="high", snapshot=pinned).enabled
        assert default_reasoning_level_for_model(model_name=name, snapshot=pinned) == "high"
        assert highest_supported_reasoning_level(model_name=name, snapshot=pinned) != "off"


def test_picker_view_follows_publication_and_returns_detached_rows() -> None:
    """Picker sequence reads update without rebuild callbacks or shared rows."""
    from src.tui.model_catalog import MODEL_CATALOG, supported_models_by_provider

    seed = SeedModelCatalog.load()
    name = "openrouter:vendor/unseeded"
    entry = seed.entries["gpt-5.4"].model_copy(update={"model_name": name})
    published = seed.model_copy(update={"entries": {name: entry}})
    with patch.object(ModelCatalogService, "_snapshot", seed):
        assert name not in [row.model_name for row in MODEL_CATALOG]
        ModelCatalogService._snapshot = published
        assert len(MODEL_CATALOG) == 1
        assert MODEL_CATALOG[0].model_name == name
        MODEL_CATALOG[0].model_name = "changed"
        assert MODEL_CATALOG[:][0].model_name == name
        with pytest.raises(TypeError):
            MODEL_CATALOG[0] = None  # type: ignore[index]
    with patch.object(ModelCatalogService, "load", side_effect=AssertionError("global read")):
        assert supported_models_by_provider(snapshot=published)[entry.provider] == [name]


def test_defaults_fallback_and_rate_reads_stay_pinned() -> None:
    """Defaults/rate aliases use the supplied generation; OpenRouter has no landing."""
    from config.ai_model_config import (
        defaults_for_model,
        default_model_for_provider,
        resolve_model_name_with_fallback,
    )
    from src.agents.slo_agent.rate_limit.service import policy_for_model
    from src.auth.credential_dao import ProviderName

    snapshot = SeedModelCatalog.load()
    with patch.object(ModelCatalogService, "load", side_effect=AssertionError("global read")):
        assert defaults_for_model(model_name="moonshot-for-coding", snapshot=snapshot)["temperature"] == 1.0
        assert policy_for_model(model_name="moonshot-for-coding", snapshot=snapshot).requests_per_minute == 20
        assert policy_for_model(model_name="unknown", snapshot=snapshot).requests_per_minute is None
        assert (
            resolve_model_name_with_fallback(model_name="openrouter:vendor/exact:free", snapshot=snapshot)[0]
            == "openrouter:vendor/exact:free"
        )
        assert resolve_model_name_with_fallback(model_name="gpt-5.4", snapshot=snapshot) == ("gpt-5.4", None)
    assert default_model_for_provider(provider=ProviderName.OPENROUTER) is None


async def test_compaction_lookups_use_pinned_snapshot() -> None:
    """Capacity paths, aliases, and unknown fallbacks never consult global state."""
    from src.agents.slo_agent.compaction.compacter import _get_context_window as summary_window
    from src.agents.slo_agent.compaction.compaction_checker import _get_context_window, CompactionChecker
    from src.agents.slo_agent.compaction.context_window import ContextWindowSnapshotService
    from src.agents.slo_agent.compaction.constants import DEFAULT_CONTEXT_WINDOW

    pinned = SeedModelCatalog.load()
    expected = pinned.entries["kimi-for-coding"].runtime_profile.context_window
    with patch.object(ModelCatalogService, "load", side_effect=AssertionError("global read")):
        for name, capacity in [("moonshot-for-coding", expected), ("unknown", DEFAULT_CONTEXT_WINDOW)]:
            assert summary_window(model_name=name, snapshot=pinned) == capacity
            assert _get_context_window(model_name=name, snapshot=pinned) == capacity
            assert (
                ContextWindowSnapshotService.build(
                    events=[], model_name=name, snapshot=pinned
                ).context_window_tokens
                == capacity
            )
            assert (
                ContextWindowSnapshotService.without_history(
                    model_name=name, snapshot=pinned
                ).context_window_tokens
                == capacity
            )
            assert not await CompactionChecker.should_compact(events=[], model_name=name, snapshot=pinned)
        assert (
            ContextWindowSnapshotService.resolve_model_identity(
                model_name="moonshot-for-coding", snapshot=pinned
            )
            == "kimi-for-coding"
        )


async def test_offline_prepare_validates_exact_routes_without_fallback_or_io() -> None:
    """Offline preparation returns one generation or an actionable exact-route failure."""
    from src.agents.model_catalog.service import ModelPreparationRequiredError
    from src.auth.credential_resolver import CredentialResolver

    snapshot = SeedModelCatalog.load()
    with (
        patch.object(ModelCatalogService, "_snapshot", snapshot),
        patch.object(ModelCatalogService, "refresh", side_effect=AssertionError("network")),
        patch.object(
            CredentialResolver, "resolve_with_source", side_effect=AssertionError("credential read")
        ),
    ):
        assert (
            await ModelCatalogService.prepare_models(model_names=("moonshot-for-coding", "gpt-5.4"))
            is snapshot
        )
        assert await ModelCatalogService.prepare_models(model_names=()) is snapshot
        with pytest.raises(ModelPreparationRequiredError, match="openrouter:vendor/unknown:free"):
            await ModelCatalogService.prepare_models(
                model_names=("openrouter:vendor/unknown:free",),
                snapshot=snapshot,
            )
        with pytest.raises(ValueError, match="Unsupported model_name"):
            await ModelCatalogService.prepare_models(model_names=("unknown-direct",))


async def test_converted_openrouter_generation_is_coherent_across_consumers() -> None:
    """A real converter entry appears live while old explicit reads stay pinned."""
    from datetime import datetime, timezone
    from config.ai_model_config import MODEL_DEFAULTS, defaults_for_model
    from src.agents.model_catalog.openrouter import OpenRouterCatalogConverter
    from src.agents.reasoning_capabilities import MODEL_REASONING_CAPABILITIES, capability_for_model
    from src.agents.slo_agent.rate_limit.service import policy_for_model
    from src.agents.slo_agent.compaction.context_window import ContextWindowSnapshotService
    from src.integrations.openrouter.dao import OpenRouterModelsResponseDAO
    from src.tui.model_catalog import MODEL_CATALOG

    entry = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(
            data=[
                {
                    "id": "vendor/unseeded:free",
                    "context_length": 20000,
                    "supported_parameters": ["tools"],
                    "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                }
            ]
        ),
        now=datetime(2026, 9, 30, tzinfo=timezone.utc),
    ).entries[0]
    seed = SeedModelCatalog.load()
    pinned = seed.model_copy(update={"entries": {**seed.entries, entry.model_name: entry}, "generation": 1})
    changed = entry.model_copy(
        update={"runtime_profile": entry.runtime_profile.model_copy(update={"context_window": 1000})}
    )
    newer = pinned.model_copy(update={"entries": {entry.model_name: changed}, "generation": 2})
    with patch.object(ModelCatalogService, "_snapshot", pinned):
        assert (
            await ModelCatalogService.prepare_models(model_names=(entry.model_name,), snapshot=pinned)
            is pinned
        )
        assert entry.model_name in MODEL_DEFAULTS
        assert entry.model_name in MODEL_REASONING_CAPABILITIES
        assert entry.model_name in [row.model_name for row in MODEL_CATALOG]
        ModelCatalogService._snapshot = newer
        assert MODEL_DEFAULTS[entry.model_name]["context_window"] == 1000
        assert defaults_for_model(model_name=entry.model_name, snapshot=pinned)["context_window"] == 20000
        assert policy_for_model(model_name=entry.model_name, snapshot=pinned).tokens_per_minute is None
        assert capability_for_model(model_name=entry.model_name, snapshot=pinned).supported_levels == ["off"]
        assert (
            ContextWindowSnapshotService.without_history(
                model_name=entry.model_name, snapshot=pinned
            ).context_window_tokens
            == 20000
        )


def test_load_and_compatibility_views_never_start_discovery() -> None:
    """Cold offline loading and compatibility shims have no refresh/client side effects."""
    from config.ai_model_config import MODEL_DEFAULTS, rebuild_model_defaults_projection
    from src.agents.model_catalog.store import ModelCatalogStore
    from src.agents.reasoning_capabilities import (
        MODEL_REASONING_CAPABILITIES,
        rebuild_reasoning_capabilities_projection,
    )
    from src.integrations.openrouter.client import OpenRouterAPIClient
    from src.tui.model_catalog import MODEL_CATALOG, _rebuild_model_catalog

    with (
        patch.object(ModelCatalogService, "_snapshot", None),
        patch.object(ModelCatalogStore, "load_provider_cache", return_value=None),
        patch.object(ModelCatalogStore, "load_overrides", return_value=[]),
        patch.object(ModelCatalogService, "refresh", side_effect=AssertionError("refresh")),
        patch.object(OpenRouterAPIClient, "__init__", side_effect=AssertionError("network client")),
    ):
        snapshot = ModelCatalogService.load()
        rebuild_model_defaults_projection()
        rebuild_reasoning_capabilities_projection()
        _rebuild_model_catalog()
        assert len(MODEL_DEFAULTS) == len(snapshot.entries)
        assert len(MODEL_REASONING_CAPABILITIES) == len(snapshot.entries)
        assert len(MODEL_CATALOG) > 0
