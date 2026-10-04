"""Offline contracts for explicit route precedence and headless preparation."""

import asyncio
import json
import signal
from pathlib import Path
from unittest.mock import AsyncMock, call, patch

from contextlib import nullcontext

from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.cli.headless import HeadlessRunner

import pytest

from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO
from src.agents.slo_agent.preferences.dao import UserPreferencesDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.auth.credential_dao import ProviderName
from src.cli.typer_dispatch import TyperDispatch
from src.agents.slo_agent.orchestrator.spawn_env import build_headless_child_env


@pytest.mark.parametrize("model", ["openrouter:author/model", "gpt-5.4"])
def test_explicit_model_bypasses_invalid_pool(tmp_path: Path, model: str) -> None:
    """Explicit selection bypasses both pool parsing and stale-default resolution."""
    with (
        patch("src.cli.typer_dispatch.UserPreferencesStore.load", return_value=UserPreferencesDAO()),
        patch(
            "src.cli.typer_dispatch.parse_model_pool_config", side_effect=ValueError("invalid pool")
        ) as pool,
    ):
        config = TyperDispatch._build_session_config(workdir=tmp_path, model=model)
    assert config.model_name == model
    assert config.model_pool_dao is None
    assert config.fallback_notice is None
    pool.assert_not_called()


def test_override_clears_pool_and_notice(tmp_path: Path) -> None:
    """A supplied route clears all inherited pool and fallback state."""
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_pool_dao=ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=0),
                ModelPoolEntryDAO(model_name="gpt-5.5", provider=ProviderName.OPENAI, priority=1),
            ]
        ),
        fallback_notice="stale default",
    )
    assert TyperDispatch._apply_model_override(config=config, model=None) is config
    updated = TyperDispatch._apply_model_override(config=config, model="openrouter:author/model")
    assert updated.model_name == "openrouter:author/model"
    assert updated.model_pool_dao is None
    assert updated.fallback_notice is None
    assert config.model_pool_dao is not None


@pytest.mark.parametrize("raw_failure", [False, True])
def test_headless_preparation_failure_has_one_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], raw_failure: bool
) -> None:
    """Real dispatch/session/status/notifier owners fail closed before inference."""
    root = tmp_path.resolve()
    monkeypatch.setenv("SLO_WORKFLOW_ID", "wf-preparation")
    monkeypatch.delenv("SLO_SESSION_ID", raising=False)
    with (
        patch("src.cli.typer_dispatch.UserPreferencesStore.load", return_value=UserPreferencesDAO()),
        patch("src.cli.typer_dispatch.headless_logging", return_value=nullcontext()),
        patch("src.cli.headless.default_history_root", return_value=root),
        patch("src.agents.slo_agent.orchestrator.notifier.default_history_root", return_value=root),
        patch(
            "src.agents.model_catalog.service.ModelCatalogService.load",
            return_value=SeedModelCatalog.load(),
            side_effect=RuntimeError("RAW_PRIVATE_SENTINEL") if raw_failure else None,
        ),
        patch.object(SloAgentSession, "prepare", wraps=SloAgentSession.prepare) as prepare,
        patch.object(SloAgentSession, "invoke") as invoke,
        patch("src.agents.base.LLMFactory.create") as factory,
        patch(
            "src.auth.credential_resolver.CredentialResolver.resolve_with_source", return_value=None
        ) as credentials,
        patch.object(
            HeadlessRunner,
            "_write_terminal_status",
            autospec=True,
            side_effect=HeadlessRunner._write_terminal_status,
        ) as terminal_status,
        patch.object(
            HeadlessRunner, "_notify_terminal", autospec=True, side_effect=HeadlessRunner._notify_terminal
        ) as terminal_notify,
    ):
        exit_code = TyperDispatch.run_headless(
            prompt="offline", model="openrouter:author/missing", cwd=str(root), notify_session_id="owner"
        )
    assert exit_code == 1
    prepare.assert_awaited_once()
    config: SessionConfigDAO = prepare.call_args.kwargs["config"]
    assert config.session_id is not None
    invoke.assert_not_called()
    factory.assert_not_called()
    # Catalog admission resolves once unless load itself failed. Terminal inbox
    # serialization independently resolves for redaction even on preparation failure.
    assert credentials.call_args_list == [call(provider=ProviderName.OPENROUTER)] * (1 if raw_failure else 2)
    terminal_status.assert_awaited_once()
    terminal_notify.assert_awaited_once()
    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.out.splitlines()]
    lifecycle = [json.loads(line) for line in captured.err.splitlines() if line.startswith("{")]
    assert [event["kind"] for event in events] == ["run_failed"]
    assert events[0]["metadata"]["session_id"] == config.session_id
    assert [event["kind"] for event in lifecycle] == [
        "headless_session_started",
        "headless_session_resolved",
        "headless_run_failed",
    ]
    assert {event["session_id"] for event in lifecycle} == {config.session_id}
    artifacts: list[str] = []
    for path in root.rglob("*"):
        assert path.resolve().is_relative_to(root)
        if path.is_file():
            artifacts.append(path.read_text())
    joined = "\n".join(artifacts)
    assert '"state": "failed"' in joined
    assert "workflow_failed" in joined
    assert config.session_id in joined
    assert "RAW_PRIVATE_SENTINEL" not in captured.out + captured.err + joined


def test_child_environment_forwards_only_openrouter_key_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trusted children receive only the exact OpenRouter credential exception."""
    monkeypatch.setenv("SLO_OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("SLO_OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("SLO_VISUALIZER_TERMINAL_APP", "unsafe")

    child_env: dict[str, str] = build_headless_child_env()

    assert child_env["SLO_OPENROUTER_API_KEY"] == "test-openrouter-key"
    assert "SLO_OPENAI_API_KEY" not in child_env
    assert child_env["SLO_VISUALIZER_TERMINAL_APP"] == "unsafe"


async def test_preparation_cancellation_emits_one_abort_and_restores_signal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cancellation before session construction uses one materialized abort terminal path."""
    config = SessionConfigDAO(workdir=tmp_path, model_name="openrouter:author/model", session_id="cancelled")
    runner = HeadlessRunner(config=config)

    with (
        patch.object(SloAgentSession, "prepare", side_effect=asyncio.CancelledError()),
        patch("src.cli.headless.signal.signal", return_value=signal.SIG_DFL) as install,
        patch("src.cli.headless.default_history_root", return_value=tmp_path),
        patch("src.agents.slo_agent.orchestrator.notifier.default_history_root", return_value=tmp_path),
    ):
        exit_code: int = await runner.invoke(prompt="offline")

    assert exit_code == 2
    assert install.call_count == 2
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["kind"] for event in events] == ["run_aborted"]


async def test_sigterm_during_preparation_cancels_work_and_emits_one_abort(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The installed preparation SIGTERM controller cancels preparation before inference."""
    config = SessionConfigDAO(workdir=tmp_path, model_name="openrouter:author/model", session_id="sigterm")
    runner = HeadlessRunner(config=config)
    preparation_started = asyncio.Event()
    preparation_cancelled = asyncio.Event()
    installed_handler: list[object] = []

    async def wait_for_preparation(*, config: SessionConfigDAO) -> SloAgentSession:
        """Block preparation until the runner cancellation controller cancels this task."""
        preparation_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            preparation_cancelled.set()
            raise
        raise AssertionError("unreachable")

    def record_handler(signum: int, handler: object) -> signal.Handlers | object:
        """Capture the installed SIGTERM handler without changing the process signal table."""
        if signum == signal.SIGTERM and callable(handler):
            installed_handler.append(handler)
        return signal.SIG_DFL

    with (
        patch.object(SloAgentSession, "prepare", side_effect=wait_for_preparation),
        patch("src.cli.headless.signal.signal", side_effect=record_handler) as install,
        patch("src.cli.headless.default_history_root", return_value=tmp_path),
        patch("src.agents.slo_agent.orchestrator.notifier.default_history_root", return_value=tmp_path),
        patch.object(SloAgentSession, "invoke") as invoke,
    ):
        invoke_task = asyncio.create_task(runner.invoke(prompt="offline"))
        await preparation_started.wait()
        assert len(installed_handler) == 1
        handler = installed_handler[0]
        assert callable(handler)
        handler(signal.SIGTERM, None)
        exit_code: int = await asyncio.wait_for(invoke_task, timeout=1)

    assert preparation_cancelled.is_set()

    assert exit_code == 2
    assert preparation_cancelled.is_set()
    invoke.assert_not_called()
    assert install.call_count == 2
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["kind"] for event in events] == ["run_aborted"]


async def test_prepared_headless_session_reaches_existing_stream(tmp_path: Path) -> None:
    """A successful gateway result enters the ordinary runner path exactly once."""
    config = SessionConfigDAO(workdir=tmp_path, model_name="openrouter:author/model")
    session = AsyncMock(spec=SloAgentSession)
    session.session_id = "prepared-session"
    with (
        patch.object(SloAgentSession, "prepare", return_value=session) as prepare,
        patch.object(HeadlessRunner, "_drain_session_stream_until_abort") as drain,
        patch.object(HeadlessRunner, "_build_status_store", return_value=None),
        patch("src.cli.headless.HeadlessWatchdog"),
    ):
        runner = HeadlessRunner(config=config)
        await runner.invoke(prompt="offline")
    prepare.assert_awaited_once()
    drain.assert_awaited_once_with(session=session, prompt="offline")
    session.subscribe.assert_called_once()
