"""Contained Feature89 child forwarding and CLI configuration acceptance."""

import asyncio
from typing import Optional
from src.agents.model_catalog.dao import ReasoningLevel
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.slo_agent.orchestrator.dao import SubAgentTaskDAO
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry
from src.cli.typer_dispatch import TyperDispatch
from src.auth.credential_store import CredentialStore
from tests.integration.test_openrouter_full_flow import isolated_catalog

ROUTES = ("gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol", "openrouter:typesafe/jev-router")


@pytest.mark.parametrize("model_name", ROUTES)
async def test_feature89_child_model_selection(
    isolated_catalog: CredentialStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, model_name: str
) -> None:
    """Capture shipped spawn argv/env without launching a child, then parse its config."""
    root = tmp_path.resolve()
    home = root / "child-home"
    assert home.resolve().is_relative_to(root)
    monkeypatch.setenv(name="SLO_OPENAI_API_KEY", value="fixture-filtered-openai")
    monkeypatch.setenv(name="SLO_OPENROUTER_API_KEY", value="fixture-forwarded-router")
    task = SubAgentTaskDAO(
        task_summary="Check model request compatibility",
        task_id="child89",
        prompt="offline",
        model=model_name,
        reasoning_level="off",
        cwd=str(root),
    )
    fake = MagicMock(pid=424242, returncode=0)
    fake.stdout = asyncio.StreamReader()
    fake.stdout.feed_eof()
    fake.stderr = asyncio.StreamReader()
    fake.stderr.feed_eof()
    fake.wait = AsyncMock(return_value=0)
    registry = ProcessRegistry()
    registry.begin_dispatch(dispatch_id="44444444-4444-4444-8444-444444444444")
    execution_id = registry.register(
        dispatch_id="44444444-4444-4444-8444-444444444444",
        task_id=task.task_id,
        session_id="child89",
        task=task,
    )
    process = SubAgentProcess(
        task=task,
        session_id="child89",
        model=task.model,
        relay=AsyncMock(),
        registry=registry,
        execution_id=execution_id,
        parent_session_id="parent89",
        slo_home=home,
    )
    capture_dir = process._capture_dir()
    assert capture_dir is not None and capture_dir.resolve().is_relative_to(root)
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)) as spawn:
        result = await process.run()
    assert result.status == "completed"
    argv = list(spawn.call_args.args)
    env = spawn.call_args.kwargs["env"]
    assert argv[argv.index("--model") + 1] == model_name
    assert argv[argv.index("--reasoning") + 1] == "off"
    assert env["SLO_OPENROUTER_API_KEY"] == "fixture-forwarded-router"
    assert "SLO_OPENAI_API_KEY" not in env
    from typer.testing import CliRunner
    from src.cli.app import app

    with patch.object(TyperDispatch, "run_headless", return_value=0) as dispatch:
        parsed = CliRunner().invoke(app=app, args=argv[3:])
    assert parsed.exit_code == 0, parsed.output
    inputs = dispatch.call_args.kwargs
    config = TyperDispatch._build_session_config(workdir=root, model=inputs["model"])
    config = TyperDispatch._apply_reasoning_override(config=config, reasoning=inputs["reasoning"])
    assert config.model_name == model_name and config.reasoning_level == "off"
    assert config.model_pool_dao is None


@pytest.mark.parametrize("model_name", ROUTES[:3])
@pytest.mark.parametrize("selected", [None, "off", "max", "low"])
def test_feature89_cli_fresh_saved_explicit_precedence(
    isolated_catalog: CredentialStore, tmp_path: Path, model_name: str, selected: Optional[ReasoningLevel]
) -> None:
    """Use real preference bytes and CLI config parsing, not a parallel precedence table."""
    from src.agents.slo_agent.preferences.service import UserPreferencesStore
    from src.agents.slo_agent.sessions.service import SloAgentSession

    root = tmp_path.resolve()
    assert isolated_catalog.path.parent.resolve().is_relative_to(root)
    UserPreferencesStore.upsert(model_name=model_name, reasoning_level=selected)
    config = TyperDispatch._build_session_config(workdir=root)
    session = SloAgentSession.build(config=config)
    assert session.active_model_name == model_name
    assert session.active_reasoning_level == (selected or "medium")
    explicit = TyperDispatch._build_session_config(workdir=root, model="gpt-6-sol")
    explicit = TyperDispatch._apply_reasoning_override(config=explicit, reasoning="off")
    explicit_session = SloAgentSession.build(config=explicit)
    assert explicit_session.active_model_name == "gpt-6-sol"
    assert explicit_session.active_reasoning_level == "off"
    assert explicit.model_pool_dao is None


@pytest.mark.parametrize("model_name", ROUTES)
def test_feature89_cli_pool_resume_and_explicit_model_precedence(
    isolated_catalog: CredentialStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, model_name: str
) -> None:
    """A configured pool precedes resumed/saved routes; explicit task model clears it."""
    from src.agents.slo_agent.preferences.service import UserPreferencesStore

    root = tmp_path.resolve()
    assert isolated_catalog.path.parent.resolve().is_relative_to(root)
    UserPreferencesStore.upsert(model_name="gpt-5.4", reasoning_level="low")
    resumed = TyperDispatch._build_session_config(workdir=root, resumed_model_name=model_name)
    assert resumed.model_name == model_name and resumed.model_pool_dao is None
    monkeypatch.setenv(name="SLO_MODEL_POOL", value='["gpt-6-luna", "gpt-6-sol"]')
    pooled = TyperDispatch._build_session_config(workdir=root, resumed_model_name=model_name)
    assert pooled.model_name == "gpt-6-luna" and pooled.model_pool_dao is not None
    explicit = TyperDispatch._build_session_config(
        workdir=root, resumed_model_name="gpt-5.4", model=model_name
    )
    assert explicit.model_name == model_name and explicit.model_pool_dao is None
