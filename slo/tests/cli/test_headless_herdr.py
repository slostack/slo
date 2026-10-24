"""Headless cleanup result ownership regressions (offline orchestration boundary)."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.cli.headless import HeadlessRunner
from tests.cli.test_headless import _make_config, _make_session_mock
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from tests.state_isolation import FakeHerdrFixture


@pytest.mark.parametrize("boundary", ["close_external_reporting", "finish_retired_reporting_cleanup"])
@pytest.mark.parametrize("original_error", [False, True])
@pytest.mark.parametrize("diagnostic_fault", [False, True])
async def test_reporting_cleanup_preserves_original_outcome(
    tmp_path: Path, boundary: str, original_error: bool, diagnostic_fault: bool
) -> None:
    """Optional cleanup defects cannot replace a result or the exact original exception."""
    session = _make_session_mock(events=[AgentStreamEventDAO(kind="run_completed")])
    getattr(session, boundary).side_effect = RuntimeError("private cleanup sentinel")
    runner = HeadlessRunner(config=_make_config(tmp_path))
    original = ValueError("original setup sentinel")
    stderr_write = sys.stderr.write

    def diagnostic_write(text: str) -> int:
        """Fail only the optional diagnostic, not mandatory lifecycle output."""
        if diagnostic_fault and text == "Headless reporting cleanup failed.\n":
            raise OSError("sink")
        return stderr_write(text)

    with (
        patch("src.cli.headless.SloAgentSession.build", return_value=session),
        patch.object(runner, "_install_sigterm_handler", return_value=42),
        patch.object(runner, "_restore_sigterm_handler") as restore,
        patch.object(runner, "_shutdown_model_catalog", new_callable=AsyncMock) as shutdown,
        patch.object(runner, "_notify_started", side_effect=original if original_error else None),
        patch("src.cli.headless.sys.stderr.write", side_effect=diagnostic_write),
    ):
        if original_error:
            with pytest.raises(ValueError) as caught:
                await runner.invoke(prompt="synthetic")
            assert caught.value is original
        else:
            assert await runner.invoke(prompt="synthetic") == 0
        restore.assert_called_once_with(previous=42)
        shutdown.assert_awaited_once_with()
    session.close_external_reporting.assert_awaited_once_with()
    session.finish_retired_reporting_cleanup.assert_awaited_once_with()
    assert runner._operation_credential is None


@pytest.mark.parametrize("boundary", ["signal", "catalog", "both"])
@pytest.mark.parametrize("original_error", [False, True])
async def test_process_cleanup_preserves_original_outcome(
    tmp_path: Path, boundary: str, original_error: bool
) -> None:
    """Independent process cleanup failures must not mask execution or skip reporting."""
    session = _make_session_mock(events=[AgentStreamEventDAO(kind="run_completed")])
    runner = HeadlessRunner(config=_make_config(tmp_path))
    original = ValueError("original setup sentinel")
    fault = RuntimeError("private cleanup sentinel")
    with (
        patch("src.cli.headless.SloAgentSession.build", return_value=session),
        patch.object(runner, "_install_sigterm_handler", return_value=42),
        patch.object(
            runner, "_restore_sigterm_handler", side_effect=fault if boundary in {"signal", "both"} else None
        ) as restore,
        patch.object(
            runner,
            "_shutdown_model_catalog",
            new_callable=AsyncMock,
            side_effect=fault if boundary in {"catalog", "both"} else None,
        ) as shutdown,
        patch.object(runner, "_notify_started", side_effect=original if original_error else None),
    ):
        if original_error:
            with pytest.raises(ValueError) as caught:
                await runner.invoke(prompt="synthetic")
            assert caught.value is original
        else:
            assert await runner.invoke(prompt="synthetic") == 0
        restore.assert_called_once_with(previous=42)
        shutdown.assert_awaited_once_with()
    session.close_external_reporting.assert_awaited_once_with()
    session.finish_retired_reporting_cleanup.assert_awaited_once_with()
    assert runner._operation_credential is None


@pytest.mark.parametrize("terminal", ["run_completed", "run_failed", "run_aborted"])
async def test_watchdog_stop_fault_preserves_terminal_status(tmp_path: Path, terminal: str) -> None:
    """A stop defect must not skip terminal persistence, notification or other cleanup."""
    from typing import cast
    from src.agents.slo_agent.events.stream import StreamEventKind

    session = _make_session_mock(events=[AgentStreamEventDAO(kind=cast(StreamEventKind, terminal))])
    runner = HeadlessRunner(config=_make_config(tmp_path))
    with (
        patch("src.cli.headless.SloAgentSession.build", return_value=session),
        patch("src.cli.headless.HeadlessWatchdog.start"),
        patch("src.cli.headless.HeadlessWatchdog.stop", side_effect=RuntimeError("private sentinel")),
        patch.object(runner, "_install_sigterm_handler", return_value=42),
        patch.object(runner, "_restore_sigterm_handler") as restore,
        patch.object(runner, "_shutdown_model_catalog", new_callable=AsyncMock) as shutdown,
        patch.object(runner, "_write_terminal_status", new_callable=AsyncMock) as status,
        patch.object(runner, "_notify_terminal", new_callable=AsyncMock) as notify,
    ):
        assert (
            await runner.invoke(prompt="synthetic")
            == {"run_completed": 0, "run_failed": 1, "run_aborted": 2}[terminal]
        )
        status.assert_awaited_once_with()
        notify.assert_awaited_once_with()
        restore.assert_called_once_with(previous=42)
        shutdown.assert_awaited_once_with()
    session.close_external_reporting.assert_awaited_once_with()
    session.finish_retired_reporting_cleanup.assert_awaited_once_with()


@pytest.mark.parametrize("boundary", ["_write_terminal_status", "_notify_terminal"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_terminal_error_survives_combined_cleanup_faults(
    tmp_path: Path, boundary: str, cancel: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    """Keep the exact terminal exception while every later cleanup owner is attempted."""
    import asyncio

    session = _make_session_mock(events=[AgentStreamEventDAO(kind="run_completed")])
    original = asyncio.CancelledError() if cancel else RuntimeError("original terminal sentinel")
    cleanup = RuntimeError("private cleanup sentinel")
    session.close_external_reporting.side_effect = cleanup
    session.finish_retired_reporting_cleanup.side_effect = cleanup
    runner = HeadlessRunner(config=_make_config(tmp_path))
    with (
        patch("src.cli.headless.SloAgentSession.build", return_value=session),
        patch("src.cli.headless.HeadlessWatchdog.start"),
        patch("src.cli.headless.HeadlessWatchdog.stop", side_effect=cleanup) as stop,
        patch.object(runner, "_install_sigterm_handler", return_value=42),
        patch.object(runner, "_restore_sigterm_handler", side_effect=cleanup) as restore,
        patch.object(
            runner, "_shutdown_model_catalog", new_callable=AsyncMock, side_effect=cleanup
        ) as shutdown,
        patch.object(runner, boundary, side_effect=original) as terminal,
    ):
        with pytest.raises(type(original)) as caught:
            await runner.invoke(prompt="synthetic")
        assert caught.value is original
        terminal.assert_awaited_once_with()
        stop.assert_called_once_with()
        restore.assert_called_once_with(previous=42)
        shutdown.assert_awaited_once_with()
    session.close_external_reporting.assert_awaited_once_with()
    session.finish_retired_reporting_cleanup.assert_awaited_once_with()
    assert runner._operation_credential is None
    captured = capsys.readouterr()
    assert "private cleanup sentinel" not in captured.out + captured.err
    assert json.loads(captured.out.splitlines()[-1])["kind"] == "run_completed"


@pytest.mark.parametrize("disabled", [False, True])
async def test_config_backed_faux_headless_never_advertises_restore(
    tmp_path: Path,
    fake_herdr: FakeHerdrFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    disabled: bool,
) -> None:
    """Real runner/session/Faux and registered CLI preserve output without native restore."""
    from langchain_core.messages import AIMessage
    from src.agents.base import LLMBuildResult
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
    from src.auth.credential_resolver import CredentialResolver

    credential = CredentialDAO(
        provider=ProviderName.OPENAI,
        auth_type=AuthType.API_KEY,
        access_token="synthetic-headless-secret",
    )
    monkeypatch.setattr(CredentialResolver, "resolve", classmethod(lambda cls, **kwargs: credential))
    if disabled:
        monkeypatch.setenv("SLO_HERDR_DISABLED", "1")
    faux = FauxChatModel(responses=[AIMessage(content="synthetic answer")])
    runner = HeadlessRunner(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(llm=faux, supports_explicit_caching=False),
    ) as factory:
        assert await runner.invoke(prompt="synthetic question") == 0
    factory.assert_called_once()
    assert runner._session is not None
    assert not runner._session._agent_is_injected
    assert runner._session._herdr_capture is None
    assert not runner._session._herdr_interactive
    assert runner._operation_credential is None
    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.out.splitlines() if line.startswith("{")]
    assert events[-1]["kind"] == "run_completed"
    assert any(event.get("content") == "synthetic answer" for event in events)
    wire = fake_herdr.capture.read_text()
    assert "--herdr-restore" not in wire
    assert "synthetic-headless-secret" not in wire + captured.out + captured.err
    assert bool(wire) is not disabled
