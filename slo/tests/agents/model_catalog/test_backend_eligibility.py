"""Record-owned static backend policy, independent of credential material."""

from typing import Optional

import pytest
from pydantic import ValidationError

from src.agents.model_catalog.dao import ModelCatalogEntryDAO
from src.agents.model_catalog.seed import SeedModelCatalog
from src.auth.credential_dao import AuthType, ProviderName


@pytest.mark.parametrize("provider", list(ProviderName))
@pytest.mark.parametrize("auth_type", [None, AuthType.API_KEY, AuthType.OAUTH])
@pytest.mark.parametrize("allowed", [False, True])
def test_record_eligibility_conjunction(
    provider: ProviderName, auth_type: Optional[AuthType], allowed: bool
) -> None:
    """Only OpenAI OAuth with denied static permission is incompatible."""
    from src.agents.model_catalog.dao import ModelBackendEligibilityError

    entry = (
        SeedModelCatalog.load()
        .entries["gpt-5.4"]
        .model_copy(update={"provider": provider, "supports_chatgpt_codex": allowed})
    )
    rejected = provider is ProviderName.OPENAI and auth_type is AuthType.OAUTH and not allowed
    message = entry.backend_eligibility_message(auth_type=auth_type)
    if rejected:
        assert message == (
            "This model requires an OpenAI Platform API key; unavailable for ChatGPT/Codex. Run /auth."
        )
        with pytest.raises(ModelBackendEligibilityError, match="requires an OpenAI Platform API key"):
            entry.require_backend_eligibility(auth_type=auth_type)
        return
    assert message is None
    entry.require_backend_eligibility(auth_type=auth_type)


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol"])
def test_policy_survives_copy_merge_override_and_alias(model_name: str) -> None:
    """Exercise reconstruction paths with cached policy deliberately opposite to seed."""
    from src.agents.model_catalog.dao import ModelAliasDAO, ModelCatalogOverrideDAO, ProviderModelMetadataDAO
    from src.agents.model_catalog.discovery import ModelCatalogOverrideService, ProviderModelDiscoveryService
    from src.agents.model_catalog.service import ModelCatalogService

    seed = SeedModelCatalog.load()
    entry = seed.entries[model_name]
    cached = entry.model_copy(update={"supports_chatgpt_codex": False, "requires_responses_api": False})
    merged = ModelCatalogService._merge_entry(seed_entry=entry, cached_entry=cached)
    metadata = ProviderModelMetadataDAO(max_tokens=1234)
    refreshed = ProviderModelDiscoveryService._refresh_existing_entry(entry=merged, metadata=metadata)
    snapshot = seed.model_copy(
        update={
            "entries": {**seed.entries, model_name: refreshed},
            "aliases": {
                "fixture-alias": ModelAliasDAO(
                    alias="fixture-alias", canonical_model_name=model_name, support_tier="compatibility_only"
                )
            },
        }
    )
    overridden = ModelCatalogOverrideService.apply_overrides(
        snapshot=snapshot, overrides=[ModelCatalogOverrideDAO(model_name=model_name, visible_in_picker=False)]
    )
    removed = ModelCatalogOverrideService.apply_overrides(snapshot=seed, overrides=[])
    alias = ModelCatalogService.entry_for_model(model_name="fixture-alias", snapshot=overridden)
    for candidate in (entry.model_copy(), merged, refreshed, alias, removed.entries[model_name]):
        assert candidate.supports_chatgpt_codex is True
        assert candidate.requires_responses_api is True
        assert candidate.model_dump()["supports_chatgpt_codex"] is True
        assert candidate.model_dump()["requires_responses_api"] is True
    assert refreshed.runtime_profile.max_tokens == 1234
    assert alias.visible_in_picker is False
    assert removed.entries[model_name] == entry


def test_ineligible_seed_rejects_opposite_cached_permission() -> None:
    """A distinct denied seed stays denied when cached metadata claims OAuth support."""
    from src.agents.model_catalog.dao import ModelBackendEligibilityError
    from src.agents.model_catalog.service import ModelCatalogService

    seed = (
        SeedModelCatalog.load()
        .entries["gpt-5.4"]
        .model_copy(update={"model_name": "gpt-fixture-ineligible-89", "supports_chatgpt_codex": False})
    )
    cached = seed.model_copy(update={"supports_chatgpt_codex": True})
    merged = ModelCatalogService._merge_entry(seed_entry=seed, cached_entry=cached)
    assert merged.model_name == "gpt-fixture-ineligible-89"
    assert merged.supports_chatgpt_codex is False
    assert cached.supports_chatgpt_codex is True
    with pytest.raises(ModelBackendEligibilityError, match="requires an OpenAI Platform API key"):
        merged.require_backend_eligibility(auth_type=AuthType.OAUTH)
    merged.require_backend_eligibility(auth_type=AuthType.API_KEY)


@pytest.mark.parametrize("field", ["supports_chatgpt_codex", "requires_responses_api"])
def test_policy_flags_cannot_be_overridden(field: str) -> None:
    """Operator files cannot introduce either seed-owned policy field."""
    from src.agents.model_catalog.dao import ModelCatalogOverrideDAO

    with pytest.raises(ValidationError):
        ModelCatalogOverrideDAO.model_validate({"model_name": "gpt-6-luna", field: False})


@pytest.mark.parametrize("field", ["supports_chatgpt_codex", "requires_responses_api"])
@pytest.mark.parametrize("value", [0, 1, "false"])
def test_policy_flags_reject_non_boolean(field: str, value: object) -> None:
    """Policy flags cannot be enabled through coercion."""
    data = SeedModelCatalog.load().entries["gpt-5.4"].model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        ModelCatalogEntryDAO.model_validate(data)
