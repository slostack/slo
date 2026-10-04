"""Real metadata protocol coverage for resumed route precedence."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from typer.testing import CliRunner

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.history.dao import (
    HistoryEventKind,
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_store import CredentialStore
from src.cli.app import app

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.preferences.dao import UserPreferencesDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.cli.typer_dispatch import TyperDispatch


@pytest.mark.parametrize("tree", [False, True])
@pytest.mark.parametrize("explicit", [None, "gpt-5.4"])
def test_resume_restores_persisted_route(tmp_path: Path, tree: bool, explicit: str | None) -> None:
    """Both history layouts restore exact routes unless explicitly overridden."""
    root = tmp_path.resolve()
    history = root / "history"
    assert history.resolve().is_relative_to(root)
    store_type = TreeBasedFilesystemSessionHistoryStore if tree else FilesystemSessionHistoryStore
    store = store_type(root=history)
    asyncio.run(
        store.ensure_session(session_id="resumed", workdir=root, model_name="openrouter:author/persisted")
    )
    with (
        patch("src.cli.typer_dispatch.FilesystemSessionHistoryStore", return_value=store),
        patch("src.cli.typer_dispatch.UserPreferencesStore.load", return_value=UserPreferencesDAO()),
        patch("src.cli.typer_dispatch.parse_model_pool_config", return_value=None),
    ):
        config = TyperDispatch._build_session_config(
            workdir=root,
            resume_session_id="resumed",
            resumed_model_name=(
                None
                if explicit is not None
                else TyperDispatch._resolve_resumed_model_name(session_id="resumed")
            ),
            model=explicit,
        )
    assert config.model_name == (explicit or "openrouter:author/persisted")
    assert config.fallback_notice is None


_FALLBACK_NOTICE: str = (
    "Model '{name}' from the resumed session is not available in this version; "
    "using the default model instead."
)


def _config_for_resumed_model(*, root: Path, tree: bool, persisted_model: str) -> SessionConfigDAO:
    """Persist owned metadata, then exercise CLI resume selection before session build.

    Args:
        root (Path): Resolved test-owned temporary root.
        tree (bool): Use the tree decorator rather than the flat store.
        persisted_model (str): Saved route to reopen.

    Returns:
        SessionConfigDAO: Actual CLI config for the saved session.
    """
    history: Path = root / "history"
    assert history.resolve().is_relative_to(root.resolve())
    store_type = TreeBasedFilesystemSessionHistoryStore if tree else FilesystemSessionHistoryStore
    store = store_type(root=history)
    asyncio.run(store.ensure_session(session_id="resumed", workdir=root, model_name=persisted_model))
    with (
        patch(target="src.cli.typer_dispatch.FilesystemSessionHistoryStore", return_value=store),
        patch(
            target="src.cli.typer_dispatch.UserPreferencesStore.load",
            return_value=UserPreferencesDAO(default_model_name="gpt-5.4"),
        ),
        patch(target="src.cli.typer_dispatch.parse_model_pool_config", return_value=None),
    ):
        return TyperDispatch._build_session_config(
            workdir=root,
            resume_session_id="resumed",
            resumed_model_name=TyperDispatch._resolve_resumed_model_name(session_id="resumed"),
        )


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
@pytest.mark.parametrize(argnames="persisted_model", argvalues=["retired-model-x", "claude-retired-x"])
def test_build_session_config_when_resumed_model_is_unknown_falls_back_with_notice(
    tmp_path: Path, tree: bool, persisted_model: str
) -> None:
    """Unknown saved direct models build ready with fixed notice and exactly one warning."""
    with patch(target="src.cli.typer_dispatch.log_warning") as warning:
        config = _config_for_resumed_model(
            root=tmp_path.resolve(), tree=tree, persisted_model=persisted_model
        )
    session = SloAgentSession.build(config=config, allow_pending_preparation=True)

    assert config.model_name == "gpt-5.4"
    assert config.fallback_notice == _FALLBACK_NOTICE.format(name=persisted_model)
    assert session.active_model_name == "gpt-5.4"
    assert session.preparation_status == "ready"
    warning.assert_called_once_with(msg="session_resume_model_unavailable", resumed_model=persisted_model)


def test_build_session_config_when_default_is_invalid_keeps_both_notices(tmp_path: Path) -> None:
    """Resume fallback retains the existing invalid-default explanation on the same line."""
    with (
        patch(
            target="src.cli.typer_dispatch.UserPreferencesStore.load",
            return_value=UserPreferencesDAO(default_model_name="mistral-retired"),
        ),
        patch(target="src.cli.typer_dispatch.parse_model_pool_config", return_value=None),
    ):
        config = TyperDispatch._build_session_config(workdir=tmp_path, resumed_model_name="retired-model-x")
    assert config.model_name == "gpt-5.4"
    assert config.fallback_notice == (
        _FALLBACK_NOTICE.format(name="retired-model-x")
        + " Model 'mistral-retired' is not supported; falling back to gpt-5.4."
    )


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
@pytest.mark.parametrize(argnames="persisted_model", argvalues=["claude-sonnet-4-6", "moonshot-k2"])
def test_build_session_config_when_saved_name_or_alias_is_known_keeps_it(
    tmp_path: Path, tree: bool, persisted_model: str
) -> None:
    """Catalog entries and aliases stay exact and quiet, with a ready real session."""
    with patch(target="src.cli.typer_dispatch.log_warning") as warning:
        config = _config_for_resumed_model(root=tmp_path, tree=tree, persisted_model=persisted_model)
    session = SloAgentSession.build(config=config, allow_pending_preparation=True)
    assert config.model_name == persisted_model
    assert config.fallback_notice is None
    assert session.active_model_name == persisted_model
    assert session.preparation_status == "ready"
    warning.assert_not_called()


def test_build_session_config_when_saved_openrouter_route_is_cold_keeps_pending(tmp_path: Path) -> None:
    """Unknown OpenRouter routes keep preparation ownership rather than direct fallback."""
    with patch(target="src.cli.typer_dispatch.log_warning") as warning:
        config = _config_for_resumed_model(
            root=tmp_path, tree=True, persisted_model="openrouter:author/unpublished"
        )
    session = SloAgentSession.build(config=config, allow_pending_preparation=True)
    assert session.active_model_name == "openrouter:author/unpublished"
    assert session.preparation_status == "pending"
    assert config.fallback_notice is None
    warning.assert_not_called()


@pytest.mark.parametrize(argnames="saved", argvalues=[None, "retired-model-x", "gpt-5.4", "openrouter:a/b"])
@pytest.mark.parametrize(argnames="explicit", argvalues=[None, "gpt-5.4"])
def test_build_session_config_when_pool_configured_preserves_precedence(
    tmp_path: Path, saved: str | None, explicit: str | None
) -> None:
    """Explicit overrides clear pools; otherwise their primary still overrides saved routes."""
    prefs = UserPreferencesDAO(default_model_name="gpt-5.4", default_model_pool="claude-sonnet-4-6,gpt-5.4")
    with (
        patch(target="src.cli.typer_dispatch.UserPreferencesStore.load", return_value=prefs),
        patch(target="src.cli.typer_dispatch.log_warning") as warning,
    ):
        config = TyperDispatch._build_session_config(
            workdir=tmp_path, resumed_model_name=saved, model=explicit
        )
    session = SloAgentSession.build(config=config, allow_pending_preparation=True)
    assert config.model_name == (explicit or "claude-sonnet-4-6")
    assert session.active_model_name == config.model_name
    assert (config.model_pool_dao is None) is (explicit is not None)
    if saved == "retired-model-x" and explicit is None:
        assert config.fallback_notice == _FALLBACK_NOTICE.format(name=saved)
        warning.assert_called_once_with(msg="session_resume_model_unavailable", resumed_model=saved)
    else:
        assert config.fallback_notice is None
        warning.assert_not_called()


@pytest.mark.parametrize(
    argnames="preferred,configured,expected",
    argvalues=[
        ("claude-sonnet-4-6", "gpt-5.4", "claude-sonnet-4-6"),
        (None, "claude-sonnet-4-6", "claude-sonnet-4-6"),
        (None, None, "gpt-5.4"),
    ],
)
@pytest.mark.parametrize(argnames="saved", argvalues=[None, "retired-model-x"])
def test_build_session_config_when_default_sources_vary_preserves_order(
    tmp_path: Path, preferred: str | None, configured: str | None, expected: str, saved: str | None
) -> None:
    """New and fallback resumes both prefer saved defaults, then cfg, then the literal default."""
    with (
        patch(
            target="src.cli.typer_dispatch.UserPreferencesStore.load",
            return_value=UserPreferencesDAO(default_model_name=preferred),
        ),
        patch(target="src.cli.typer_dispatch.cfg", return_value=configured),
        patch(target="src.cli.typer_dispatch.parse_model_pool_config", return_value=None),
    ):
        config = TyperDispatch._build_session_config(workdir=tmp_path, resumed_model_name=saved)
    assert config.model_name == expected
    assert config.fallback_notice == (None if saved is None else _FALLBACK_NOTICE.format(name=saved))


def test_resolve_resumed_model_name_when_metadata_absent_does_not_create_history(tmp_path: Path) -> None:
    """Missing metadata stays the ordinary default path without manufacturing a resume warning."""
    history: Path = tmp_path / "absent-history"
    assert history.resolve().is_relative_to(tmp_path.resolve())
    with patch(
        target="src.cli.typer_dispatch.FilesystemSessionHistoryStore",
        return_value=FilesystemSessionHistoryStore(root=history),
    ):
        assert TyperDispatch._resolve_resumed_model_name(session_id="missing") is None
        assert TyperDispatch._resolve_resumed_model_name(session_id=None) is None
    assert not history.exists()


@pytest.mark.parametrize(argnames="default_notice", argvalues=[None, "Default also unavailable."])
def test_resume_fallback_notice_when_composing_text_does_not_log(default_notice: str | None) -> None:
    """The text-only helper never emits the warning owned by config construction."""
    with patch(target="src.cli.typer_dispatch.log_warning") as warning:
        notice = TyperDispatch._resume_fallback_notice(
            resumed_model_name="retired-model-x", default_notice=default_notice
        )
    expected: str = _FALLBACK_NOTICE.format(name="retired-model-x")
    assert notice == (expected if default_notice is None else f"{expected} {default_notice}")
    warning.assert_not_called()


async def _seed_completed_history(
    *,
    store: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore,
    workdir: Path,
) -> None:
    """Write two complete turns through the real store before CLI continuation tests.

    Args:
        store (FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore): Owned test store.
        workdir (Path): Test-owned session workspace; the caller checks store-root containment.
    """
    await store.ensure_session(session_id="resumed", workdir=workdir, model_name="retired-model-x")
    for turn in range(2):
        entries: list[tuple[HistoryEventKind, str | None]] = [
            ("run_started", None),
            ("user_message", f"old question {turn}"),
            ("assistant_message", f"old answer {turn}"),
            ("run_completed", None),
        ]
        for kind, content in entries:
            await store.append_event(
                event=SessionHistoryEventDAO(
                    session_id="resumed",
                    turn_id=f"old-{turn}",
                    kind=kind,
                    payload=SessionHistoryEventPayloadDAO(content=content),
                )
            )


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
@pytest.mark.parametrize(argnames="explicit", argvalues=[None, "gpt-5.4"])
def test_cli_run_when_saved_model_unknown_continues_all_history(
    tmp_path: Path, isolated_slo_home: Path, tree: bool, explicit: str | None
) -> None:
    """Real Typer, headless runner, session and graph reopen every turn and append a Faux answer."""
    history: Path = isolated_slo_home / "sessions/history"
    assert history.resolve().is_relative_to(isolated_slo_home.resolve())
    store_type = TreeBasedFilesystemSessionHistoryStore if tree else FilesystemSessionHistoryStore
    store = store_type(root=history)
    asyncio.run(_seed_completed_history(store=store, workdir=tmp_path))
    before = asyncio.run(store.load_events(session_id="resumed"))
    credentials = CredentialStore()
    assert credentials.path.resolve().is_relative_to(isolated_slo_home.resolve())
    credentials.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic-resume-test-key"
        )
    )
    argv: list[str] = ["run", "--resume", "resumed", "--cwd", str(tmp_path), "--prompt", "new question"]
    if explicit is not None:
        argv.extend(["--model", explicit])
    with (
        patch(
            target="src.cli.typer_dispatch.UserPreferencesStore.load",
            return_value=UserPreferencesDAO(default_model_name="gpt-5.4"),
        ),
        patch(target="src.cli.typer_dispatch.parse_model_pool_config", return_value=None),
        patch(target="src.cli.typer_dispatch.log_warning") as warning,
        patch(
            target="src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(
                llm=FauxChatModel(responses=[AIMessage(content="new answer")]),
                supports_explicit_caching=False,
            ),
        ) as factory,
    ):
        result = CliRunner().invoke(app=app, args=argv)
    assert result.exit_code == 0, result.output
    emitted: list[dict[str, object]] = [json.loads(line) for line in result.stdout.splitlines()]
    assert emitted[-1]["kind"] == "run_completed"
    factory.assert_called_once()
    assert factory.call_args.kwargs["model_name"] == "gpt-5.4"
    if explicit is None:
        warning.assert_called_once_with(
            msg="session_resume_model_unavailable", resumed_model="retired-model-x"
        )
    else:
        warning.assert_not_called()
    after = asyncio.run(store.load_events(session_id="resumed"))
    assert after[: len(before)] == before
    messages = asyncio.run(SessionHistoryProjector.build_message_history(events=after))
    assert [message.content for message in messages] == [
        "old question 0",
        "old answer 0",
        "old question 1",
        "old answer 1",
        "new question",
        "new answer",
    ]
    metadata = asyncio.run(store.read_metadata(session_id="resumed"))
    assert metadata.model_name == "gpt-5.4"
