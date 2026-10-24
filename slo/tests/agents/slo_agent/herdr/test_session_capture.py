"""Private scalar capture contracts; no reporter or provider activation."""

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from langchain_core.messages import AIMessage
from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import ProviderName


def configured_pool() -> ModelPoolDAO:
    """Build independent valid mutable policy in deliberately unsorted order."""
    return ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(
                model_name="gpt-5.4",
                provider=ProviderName.OPENAI,
                priority=9,
                cooldown_seconds=12,
                rate_limit_cooldown_seconds=3,
            ),
            ModelPoolEntryDAO(
                model_name="gpt-5.4-mini",
                provider=ProviderName.OPENAI,
                priority=1,
                cooldown_seconds=24,
                rate_limit_cooldown_seconds=7,
            ),
        ]
    )


async def test_activation_reads_existing_metadata_without_creating_history(tmp_path: Path) -> None:
    """Input preparation uses real persistence and explicit workspace precedence."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    store = session._history_store
    assert store is not None
    await session._prepare_herdr_capture_inputs(interactive=True)
    assert not (store.root / session.session_id).exists()
    assert session._herdr_capture is None
    await store.ensure_session(
        session_id=session.session_id,
        workdir=tmp_path,
        model_name="gpt-5.4",
        workspace_file=tmp_path / "stored.code-workspace",
    )
    await session._prepare_herdr_capture_inputs(interactive=True)
    assert session._herdr_capture is not None
    assert session._herdr_capture is not None
    assert session._herdr_capture.config.workspace_file == tmp_path / "stored.code-workspace"
    assert session._herdr_configuration_generation == 1
    with patch.object(Path, "resolve", side_effect=AssertionError("capture disk work")):
        assert session._capture_herdr_restore() == session._herdr_capture


@pytest.mark.parametrize("mutation", ["workdir", "workspace", "plugins", "root"])
async def test_activation_path_sources_are_guarded(tmp_path: Path, mutation: str) -> None:
    """Out-of-band path edits refuse capture without resolving on events."""
    config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4")
    session = SloAgentSession.build(config=config)
    await session.rename_session(session_name="persisted")
    await session._prepare_herdr_capture_inputs(interactive=True)
    assert session._herdr_capture is not None
    if mutation == "workdir":
        config.workdir = tmp_path / "other"
    elif mutation == "workspace":
        config.workspace_file = tmp_path / "other.code-workspace"
    elif mutation == "plugins":
        config.plugin_paths.append(tmp_path / "other.py")
    else:
        config.history_root = tmp_path / "other-history"
    with patch.object(Path, "resolve", side_effect=AssertionError("event disk work")):
        assert session._capture_herdr_restore() is None


async def test_real_persistence_and_reasoning_commits_refresh_generation(tmp_path: Path) -> None:
    """Rename's first persistence enables restore; later names do not churn policy."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            reasoning_level="low",
        )
    )
    await session._prepare_herdr_capture_inputs(interactive=True)
    assert session._herdr_configuration_generation == 0
    await session.rename_session(session_name="first")
    assert session._herdr_configuration_generation == 1
    before = session._herdr_capture
    await session.rename_session(session_name="second")
    assert session._herdr_capture == before
    session.switch_reasoning_level(reasoning_level="high")
    assert session._herdr_configuration_generation == 2
    assert session._herdr_capture is not None
    assert session._herdr_capture.config.reasoning_level == "high"
    session.switch_reasoning_level(reasoning_level="high")
    session._rebuild_usage_snapshot()
    assert session._herdr_configuration_generation == 2


@pytest.mark.parametrize("prepared", [False, True])
async def test_model_commit_clears_pool_and_refreshes_capture(tmp_path: Path, prepared: bool) -> None:
    """Both supported selection gateways commit exact configured single policy."""
    from src.agents.model_catalog.service import ModelCatalogService
    from src.auth.credential_dao import CredentialDAO, AuthType

    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_pool_dao=configured_pool(),
            reasoning_level="low",
        )
    )
    await session.rename_session(session_name="pool")
    await session._prepare_herdr_capture_inputs(interactive=True)
    with patch(
        "src.auth.credential_resolver.CredentialResolver.require",
        return_value=CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.API_KEY,
            access_token="synthetic-test",
        ),
    ):
        if prepared:
            await session.prepare_model_selection(model_name="gpt-5.5")
        else:
            session.switch_model(model_name="gpt-5.5")
    assert session._herdr_configuration_generation == 2
    assert session._herdr_capture is not None
    assert session._herdr_capture.config.model_name == "gpt-5.5"
    assert session._herdr_capture is not None
    assert session._herdr_capture.config.model_pool_dao is None
    before = session._herdr_capture
    session._adopt_prepared_snapshot(
        snapshot=ModelCatalogService.load(),
        model_names=("gpt-5.5",),
    )
    assert session._herdr_capture == before
    assert session._herdr_configuration_generation == 2


@pytest.mark.parametrize(
    "case", ["headless", "custom_root", "disabled_history", "resolve_failure", "explicit_workspace"]
)
async def test_activation_eligibility_branches(tmp_path: Path, case: str) -> None:
    """Actual session input preparation fails closed without creating metadata."""
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="gpt-5.4",
        enable_history=case != "disabled_history",
        history_root=tmp_path / "custom" if case == "custom_root" else None,
        workspace_file=tmp_path / "explicit.code-workspace" if case == "explicit_workspace" else None,
    )
    session = SloAgentSession.build(config=config)
    if case != "disabled_history":
        await session.rename_session(session_name="existing")
    if case == "resolve_failure":
        with patch.object(Path, "resolve", side_effect=OSError("private path")):
            await session._prepare_herdr_capture_inputs(interactive=True)
    else:
        await session._prepare_herdr_capture_inputs(interactive=case != "headless")
    if case == "explicit_workspace":
        assert session._herdr_capture is not None
        assert session._herdr_capture.config.workspace_file == config.workspace_file
    else:
        assert session._herdr_capture is None


async def test_prepared_snapshot_effective_reasoning_commit(tmp_path: Path) -> None:
    """A catalog admission reclamp changes capture, not just display usage."""
    from src.agents.model_catalog.service import ModelCatalogService

    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            reasoning_level="low",
        )
    )
    await session.rename_session(session_name="existing")
    await session._prepare_herdr_capture_inputs(interactive=True)
    with patch("src.agents.slo_agent.sessions.service.clamp_reasoning_level", return_value="high"):
        session._adopt_prepared_snapshot(snapshot=ModelCatalogService.load(), model_names=("gpt-5.4",))
    assert session._herdr_capture is not None
    assert session._herdr_capture.config.reasoning_level == "high"
    assert session._herdr_configuration_generation == 2


def test_pool_capture_copies_order_and_all_scalars_without_aliases() -> None:
    """Frozen policy cannot track later mutations of either list or entry."""
    pool = configured_pool()
    capture = SloAgentSession._capture_herdr_pool(pool=pool)
    assert capture is not None
    assert isinstance(capture.entries, tuple)
    assert [entry.model_dump() for entry in capture.entries] == [entry.model_dump() for entry in pool.entries]
    pool.entries[0].cooldown_seconds = 999
    pool.entries.reverse()
    assert capture.entries[0].cooldown_seconds == 12
    assert capture.entries[0].priority == 9
    with pytest.raises(ValidationError):
        capture.entries[0].priority = 8
    assert SloAgentSession._capture_herdr_pool() is None


async def test_capture_uses_established_facts_and_effective_policy(tmp_path: Path) -> None:
    """Memory-only capture is private and inactive sessions remain ineligible."""
    faux = FauxChatModel(responses=[AIMessage(content="done")])
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(llm=faux, supports_explicit_caching=False),
    ):
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    assert session._capture_herdr_restore() is None
    assert session._history_store is not None
    await session._history_store.ensure_session(
        session_id=session.session_id,
        workdir=tmp_path,
        model_name="gpt-5.4",
        workspace_file=tmp_path / "private.code-workspace",
    )
    await session._prepare_herdr_capture_inputs(interactive=True)
    with (
        patch.object(Path, "resolve", side_effect=AssertionError("capture disk work")),
        patch.object(session, "_build_agent", side_effect=AssertionError("capture model build")),
    ):
        capture = session._capture_herdr_restore()
    assert capture is not None
    assert capture.config.model_name == "gpt-5.4"
    assert capture.config.reasoning_level == session.active_reasoning_level
    assert capture.config.workspace_file == tmp_path / "private.code-workspace"
    assert str(tmp_path) not in repr(capture)
    session._adopt_herdr_capture(capture=capture)
    assert session._herdr_configuration_generation == 1
    session._adopt_herdr_capture(capture=session._capture_herdr_restore())
    assert session._herdr_configuration_generation == 1
    session._adopt_herdr_capture(capture=None)
    assert session._herdr_configuration_generation == 2
    session._adopt_herdr_capture(capture=None)
    assert session._herdr_configuration_generation == 2
    session._session_id = "other"
    session._adopt_herdr_capture(capture=None)
    assert session._herdr_configuration_generation == 3
    session._agent_is_injected = True
    assert session._capture_herdr_restore() is None


@pytest.mark.parametrize("mutation", ["provider", "short", "bool"])
def test_mutated_pool_is_refused(mutation: str) -> None:
    """Mutable source DAOs must pass current validators, not trusted-instance shortcuts."""
    pool = configured_pool()
    if mutation == "provider":
        pool.entries[0].provider = ProviderName.ANTHROPIC
    elif mutation == "short":
        pool.entries.pop()
    else:
        pool.entries[0].priority = True
    with pytest.raises(ValueError):
        SloAgentSession._capture_herdr_pool(pool=pool)
