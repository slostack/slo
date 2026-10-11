"""Offline full-prompt catalog adoption contracts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO, ModelReasoningProfileDAO
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.service import ModelCatalogService, ModelPreparationRequiredError
from src.agents.providers.faux import FauxChatModel
from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import (
    AuthType,
    CredentialDAO,
    ProviderName,
)
from tests.agents.slo_agent.test_catalog_generation import _prepared_openrouter_snapshot


async def _drain(*, session: SloAgentSession) -> None:
    """Consume a whole submission so its prompt lock always exits."""
    async for _ in session.invoke(text="answer without tools"):
        pass


@pytest.mark.parametrize("changed", [False, True])
async def test_publication_during_prompt_is_pinned_until_next_admission(
    tmp_path: Path, changed: bool
) -> None:
    """Real Faux-backed runs adopt metadata only after the admitted run exits."""
    old = _prepared_openrouter_snapshot(generation=4)
    route = "openrouter:vendor/model"
    entry = old.entries[route]
    if changed:
        entry = entry.model_copy(
            update={
                "runtime_profile": entry.runtime_profile.model_copy(
                    update={"context_window": 8192, "automatic_retry_attempts": 7}
                ),
                "reasoning_profile": ModelReasoningProfileDAO(supported_levels=("off",), default_level="off"),
            }
        )
    future = old.model_copy(update={"generation": 5, "entries": {**old.entries, route: entry}})
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path, model_name=route, reasoning_level="high", enable_history=False
        ),
        catalog_snapshot=old,
    )
    entered, release = asyncio.Event(), asyncio.Event()
    builds: list[ModelCatalogSnapshotDAO | None] = []
    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-prompt-admission-key",
    )

    def build_agent() -> SloAgent:
        """Build the real loop with a synthetic transport and captured generation."""
        builds.append(session.catalog_snapshot)
        return SloAgent(
            llm=FauxChatModel(responses=[AIMessage(content="done")] * 3),
            model_name=route,
            snapshot=session.catalog_snapshot,
            cwd=str(tmp_path),
            system_prompt="Test only.",
        )

    async def barrier() -> None:
        """Suspend before lazy construction, after admission has completed."""
        entered.set()
        await release.wait()

    async def prepare_models(*, model_names: tuple[str, ...]) -> ModelCatalogSnapshotDAO:
        """Return the patched published generation or reject removed route membership."""
        assert model_names == (route,)
        snapshot = ModelCatalogService.load()
        if route not in snapshot.entries:
            raise ModelPreparationRequiredError("route removed")
        return snapshot

    with (
        patch.object(ModelCatalogService, "load", return_value=old) as load,
        patch.object(ModelCatalogService, "prepare_models", side_effect=prepare_models) as prepare,
        patch.object(session, "_build_agent", side_effect=build_agent),
        patch(
            "src.agents.slo_agent.sessions.service.CredentialResolver.resolve",
            return_value=credential,
        ),
        patch.object(session, "_refresh_oauth_credential_if_needed", side_effect=barrier),
    ):
        task = asyncio.create_task(_drain(session=session))
        await entered.wait()
        load.return_value = future
        try:
            assert session.catalog_snapshot == old
            capacity = await session.context_window_snapshot()
            assert capacity.context_window_tokens == old.entries[route].runtime_profile.context_window
        finally:
            release.set()
            await task
        assert session._admitted_run_snapshot is None
        await _drain(session=session)
        assert prepare.await_count == 2
        assert session.catalog_snapshot == future
        assert (
            session._resolve_attempt_policy().automatic_retry_attempts
            == entry.runtime_profile.automatic_retry_attempts
        )
        assert builds == ([old, future] if changed else [old])
        assert session.active_reasoning_level == ("off" if changed else "high")
        load.return_value = SeedModelCatalog.load()
        with pytest.raises(ModelPreparationRequiredError):
            await _drain(session=session)
        assert len(builds) == (2 if changed else 1)
        assert session.active_model_name == route


@pytest.mark.parametrize("pooled", [False, True])
async def test_removed_route_rejects_next_prompt_without_changing_selection(
    tmp_path: Path, pooled: bool
) -> None:
    """Every configured pool member must remain admissible; never subtract one."""
    old = _prepared_openrouter_snapshot(generation=4)
    route = "openrouter:vendor/model"
    pool = None
    if pooled:
        pool = ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=0),
                ModelPoolEntryDAO(model_name=route, provider=ProviderName.OPENROUTER, priority=1),
            ]
        )
    config = SessionConfigDAO(workdir=tmp_path, model_name=route, model_pool_dao=pool, enable_history=False)
    session = SloAgentSession.build(config=config, catalog_snapshot=old)
    with (
        patch.object(ModelCatalogService, "load", return_value=SeedModelCatalog.load()),
        patch.object(
            session, "_ensure_agent_ready", new=AsyncMock(side_effect=AssertionError("admission bypassed"))
        ) as ready,
        patch(
            "src.auth.credential_resolver.CredentialResolver.require",
            side_effect=AssertionError("credential access forbidden"),
        ),
    ):
        with pytest.raises(ModelPreparationRequiredError):
            await _drain(session=session)
        ready.assert_not_awaited()
    assert config.model_pool_dao == pool
    assert not session.is_running
    assert session._admitted_run_snapshot is None
