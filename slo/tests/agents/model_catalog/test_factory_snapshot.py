"""Factory snapshot coherence without discovery or inference."""

from unittest.mock import patch
from langchain_openai import ChatOpenAI

from src.agents.base import LLMFactory
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName


def test_factory_supplied_snapshot_resolves_defaults_identity_and_reasoning_without_global_load() -> None:
    """Actual OpenAI construction reads every catalog-dependent value from the supplied view."""
    seed = SeedModelCatalog.load()
    original = seed.entries["gpt-6-astra"]
    profile = original.runtime_profile.model_copy(update={"max_tokens": 1234, "context_window": 123456})
    entry = original.model_copy(update={"runtime_profile": profile, "api_model_name": "fixture-api-id"})
    snapshot = seed.model_copy(update={"entries": {**seed.entries, entry.model_name: entry}})
    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="fixture"
    )
    with (
        patch.object(ModelCatalogService, "load", side_effect=AssertionError("global load forbidden")),
        patch("src.agents.base.CredentialResolver.require", return_value=credential),
    ):
        result = LLMFactory.create(model_name=entry.model_name, reasoning_level="high", snapshot=snapshot)
    assert isinstance(result.llm, ChatOpenAI)
    assert result.llm.model_name == "fixture-api-id"
    assert result.llm.max_tokens == 1234
    assert result.llm.reasoning == {"effort": "high", "summary": "auto"}
