"""Immutable published catalog and offline admission contracts."""

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.agents.model_catalog.dao import ModelCapabilitiesDAO, ModelCatalogSnapshotDAO
from src.agents.model_catalog.seed import SeedModelCatalog


def test_gpt6_source_registration_once() -> None:
    """Count explicit registrations before dictionary collapse can hide duplicates."""
    import ast
    import inspect

    source = inspect.getsource(SeedModelCatalog)
    tree = ast.parse(source)
    names = [
        keyword.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "model_name" and isinstance(keyword.value, ast.Constant)
    ]
    for name in ("gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol"):
        assert names.count(name) == 1
    assert "jev-router" not in source
    from src.agents.model_catalog.discovery import ProviderModelDiscoveryService

    for name in ("gpt-6-future", "gpt-6-luna-2099", "openrouter:typesafe/jev-router"):
        assert (
            ProviderModelDiscoveryService._matching_template(
                model_name=name, templates=SeedModelCatalog.load().templates
            )
            is None
        )


def test_published_snapshot_rejects_nested_mutation_and_round_trips() -> None:
    """Every public container and nested model is immutable, including copied snapshots."""
    snapshot = SeedModelCatalog.load()
    entry = snapshot.entries["gpt-5.4"]
    for model, field, value in [
        (snapshot, "generation", 99),
        (entry, "display_name", "changed"),
        (entry.runtime_profile, "context_window", 2),
        (entry.reasoning_profile, "default_level", "off"),
        (next(iter(snapshot.aliases.values())), "alias", "changed"),
        (snapshot.templates[0], "default_visible", True),
    ]:
        with pytest.raises(ValidationError):
            setattr(model, field, value)
    # Execute deliberately invalid consumer code at the runtime boundary: the
    # public Mapping annotation correctly forbids these writes statically too.
    with pytest.raises(TypeError):
        exec('entries["other"] = entry', {"entries": snapshot.entries, "entry": entry})
    with pytest.raises(TypeError):
        exec('efforts["high"] = "changed"', {"efforts": entry.reasoning_profile.provider_effort_map})
    for sequence in [entry.aliases, entry.reasoning_profile.supported_levels, snapshot.templates]:
        with pytest.raises((AttributeError, TypeError)):
            getattr(sequence, "clear")()
    source = dict(snapshot.entries)
    copied = snapshot.model_copy(update={"entries": source}, deep=True)
    source.clear()
    assert copied.entries
    with pytest.raises(TypeError):
        exec('entries["other"] = entry', {"entries": copied.entries, "entry": entry})
    assert ModelCatalogSnapshotDAO.model_validate_json(snapshot.model_dump_json()) == snapshot
    assert isinstance(snapshot.model_dump(mode="json")["templates"], list)


@pytest.mark.parametrize(
    "changes",
    [
        {"availability": "unavailable"},
        {"availability": "ineligible"},
        {"availability": "expired"},
        {"expiration_date": "2026-09-30"},
        {"expiration_date": "2026-09-30T12:00:00+00:00"},
        {"expiration_date": "invalid"},
        {"context_length": True},
        {"context_length": None},
        {"top_provider": {"max_completion_tokens": "100"}},
    ],
)
async def test_offline_admission_rejects_invalid_routes(changes: dict[str, object]) -> None:
    """Preparation rejects bad evidence and expiry without refreshing or resolving keys."""
    from datetime import datetime, timezone
    from src.agents.model_catalog.openrouter import OpenRouterCatalogConverter
    from src.agents.model_catalog.service import ModelCatalogService, ModelPreparationRequiredError
    from src.integrations.openrouter.dao import OpenRouterModelsResponseDAO
    from src.auth.credential_resolver import CredentialResolver

    record = {
        "id": "vendor/unseeded:free",
        "context_length": 20000,
        "supported_parameters": ["tools"],
        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
    }
    record.update({key: value for key, value in changes.items() if key != "availability"})
    entry = OpenRouterCatalogConverter.invoke(
        response=OpenRouterModelsResponseDAO(data=[record]),
        now=datetime(2026, 9, 29, tzinfo=timezone.utc),
    ).entries[0]
    if "availability" in changes:
        entry = entry.model_copy(update=changes)
    snapshot = SeedModelCatalog.load().model_copy(update={"entries": {entry.model_name: entry}})
    with (
        patch.object(ModelCatalogService, "load", side_effect=AssertionError("global")),
        patch.object(ModelCatalogService, "refresh", side_effect=AssertionError("network")),
        patch.object(CredentialResolver, "resolve_with_source", side_effect=AssertionError("keys")),
    ):
        with pytest.raises(ModelPreparationRequiredError, match="openrouter:vendor/unseeded:free"):
            await ModelCatalogService.prepare_models(
                model_names=(entry.model_name,),
                snapshot=snapshot,
                now=datetime(2026, 9, 30, 12, tzinfo=timezone.utc),
            )


def test_schema_two_cache_without_reasoning_capability_flags_defaults_to_no_controls() -> None:
    """Read old schema-two entries without inventing OpenRouter reasoning controls."""
    capabilities = ModelCapabilitiesDAO.model_validate(
        {
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "supported_parameters": ["tools", "reasoning"],
        }
    )

    assert capabilities.reasoning_controls_available is False
    assert capabilities.reasoning_disable_available is False


async def test_future_expiry_and_capabilities_are_immutable() -> None:
    """Exact timestamp expiry admits before its boundary and cannot drift via mutation."""
    from datetime import datetime, timezone
    from src.agents.model_catalog.dao import ModelCapabilitiesDAO
    from src.agents.model_catalog.service import ModelCatalogService
    from src.auth.credential_dao import ProviderName

    parameters = ["tools"]
    # Wire input is mutable JSON; validation must detach it into typed tuples.
    capabilities = ModelCapabilitiesDAO.model_validate(
        {
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "supported_parameters": parameters,
            "expires_at": "2026-09-30T13:00:00+00:00",
        }
    )
    parameters.clear()
    assert capabilities.supported_parameters == ("tools",)
    with pytest.raises(AttributeError):
        getattr(capabilities.supported_parameters, "clear")()
    with pytest.raises(ValidationError):
        capabilities.expires_at = None
    seed = SeedModelCatalog.load()
    entry = seed.entries["gpt-5.4"].model_copy(
        update={
            "model_name": "openrouter:vendor/new",
            "provider": ProviderName.OPENROUTER,
            "capabilities": capabilities,
        }
    )
    snapshot = seed.model_copy(update={"entries": {**seed.entries, entry.model_name: entry}})
    with patch.object(ModelCatalogService, "load", side_effect=AssertionError("global")):
        assert (
            await ModelCatalogService.prepare_models(
                model_names=(entry.model_name, "moonshot-for-coding"),
                snapshot=snapshot,
                now=datetime(2026, 9, 30, 12, tzinfo=timezone.utc),
            )
            is snapshot
        )
