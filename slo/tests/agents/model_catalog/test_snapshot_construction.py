"""Optional catalog injection at real construction seams, without admission policy."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.reasoning_capabilities import ReasoningLevel
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.graph.service import build_slo_agent

from langchain_openai import ChatOpenAI

from src.agents.base import LLMFactory
from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName


def _snapshot() -> ModelCatalogSnapshotDAO:
    """Build a memory-only generation with distinguishable per-member output caps."""
    seed = SeedModelCatalog.load()
    entries = dict(seed.entries)
    for name, cap in (("gpt-6-astra", 1234), ("gpt-5.4", 2345)):
        original = entries[name]
        entries[name] = original.model_copy(
            update={"runtime_profile": original.runtime_profile.model_copy(update={"max_tokens": cap})}
        )
    return seed.model_copy(update={"entries": entries, "generation": 42})


def _pool_config() -> ModelPoolDAO:
    """Return two direct routes so construction cannot hide behind mocked factories."""
    with patch.object(ModelCatalogService, "load", return_value=_snapshot()):
        return ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(model_name="gpt-6-astra", provider=ProviderName.OPENAI, priority=0),
                ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=1),
            ]
        )


def _credential() -> CredentialDAO:
    """Supply a synthetic credential without inspecting any host credential source."""
    return CredentialDAO(provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="fixture")


def test_pool_factory_uses_supplied_snapshot_for_every_member() -> None:
    """Construct real members while all global catalog reads are forbidden."""
    snapshot = _snapshot()
    pool_config = _pool_config()
    with (
        patch.object(ModelCatalogService, "load", side_effect=AssertionError("global load forbidden")),
        patch("src.agents.base.CredentialResolver.require", return_value=_credential()),
    ):
        pool = LLMFactory.create_pool(pool_dao=pool_config, snapshot=snapshot)
        first = pool.active_llm
        assert isinstance(first, ChatOpenAI)
        assert first.max_tokens == 1234
        second = pool._models["gpt-5.4"]
        assert isinstance(second, ChatOpenAI)
        assert second.max_tokens == 2345


@pytest.mark.parametrize("pooled", [False, True])
@pytest.mark.parametrize("reasoning_level", [None, "high"])
def test_session_initialization_and_lazy_build_use_supplied_snapshot(
    tmp_path: Path, pooled: bool, reasoning_level: ReasoningLevel | None
) -> None:
    """Initialize real usage/reasoning and build the lazy agent without global reads."""
    snapshot = _snapshot()
    config = SessionConfigDAO(
        workdir=tmp_path.resolve(),
        model_name="gpt-6-astra",
        model_pool_dao=_pool_config() if pooled else None,
        reasoning_level=reasoning_level,
        enable_history=False,
        system_prompt="Fixture",
    )
    with (
        patch.object(ModelCatalogService, "load", side_effect=AssertionError("global load forbidden")),
        patch("src.agents.base.CredentialResolver.require", return_value=_credential()),
        patch.object(SloAgentSession, "_load_plugins"),
        patch("src.agents.slo_agent.agent.ProjectContextDiscovery.invoke", return_value=[]),
        patch("src.agents.slo_agent.agent.SkillsLoader.load_merged", return_value=[]),
    ):
        session = SloAgentSession.build(config=config, catalog_snapshot=snapshot)
        assert session.usage_snapshot().output_cap_tokens == 1234
        assert session.usage_snapshot().requests_per_minute_limit == 500
        agent = session._build_agent()
        assert agent._catalog_snapshot is snapshot


@pytest.mark.parametrize("pooled", [False, True])
def test_graph_build_retains_supplied_snapshot_without_global_reads(pooled: bool) -> None:
    """Exercise both actual factory branches and retain the view in the build result."""
    snapshot = _snapshot()
    pool_config = _pool_config() if pooled else None
    with (
        patch.object(ModelCatalogService, "load", side_effect=AssertionError("global load forbidden")),
        patch("src.agents.base.CredentialResolver.require", return_value=_credential()),
    ):
        result = build_slo_agent(
            model_name="gpt-6-astra", model_pool_dao=pool_config, tools=[], snapshot=snapshot
        )
    assert result.snapshot is snapshot
    model = result.llm.active_llm if isinstance(result.llm, ModelPool) else result.llm
    assert isinstance(model, ChatOpenAI)
    assert model.max_tokens == 1234


@pytest.mark.parametrize("pooled", [False, True])
def test_agent_construction_uses_supplied_snapshot(tmp_path: Path, pooled: bool) -> None:
    """Exercise real graph/factory construction with only external context readers isolated."""
    snapshot = _snapshot()
    pool_config = _pool_config() if pooled else None
    with (
        patch.object(ModelCatalogService, "load", side_effect=AssertionError("global load forbidden")),
        patch("src.agents.base.CredentialResolver.require", return_value=_credential()),
        patch("src.agents.slo_agent.agent.ProjectContextDiscovery.invoke", return_value=[]),
        patch("src.agents.slo_agent.agent.SkillsLoader.load_merged", return_value=[]),
    ):
        agent = SloAgent(
            model_name="gpt-6-astra",
            model_pool_dao=pool_config,
            tools=[],
            cwd=str(tmp_path.resolve()),
            system_prompt="Fixture",
            snapshot=snapshot,
        )
    assert agent._catalog_snapshot is snapshot
    assert agent.llm is not None
    model = agent.llm.active_llm if isinstance(agent.llm, ModelPool) else agent.llm
    assert isinstance(model, ChatOpenAI)
    assert model.max_tokens == 1234
