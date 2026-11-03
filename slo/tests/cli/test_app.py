"""Tests for the Typer ``app`` surface (sub-spec 02.a.4)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

import pytest

from src.cli.app import app
from src.cli.version import resolve_version
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.tui.app import SloTUI
from tests.tui.recording_prompt import RecordingPromptInput

runner: CliRunner = CliRunner()


def compose_default_tui(*, session: SloAgentSession) -> SloTUI:
    """Capture the real Typer-composed host without opening a native terminal.

    Only session acquisition and terminal launch are replaced. The actual
    TyperDispatch method, SloTUI constructor and later mounted runtime execute.
    """
    from src.cli.typer_dispatch import TyperDispatch

    hosts: list[SloTUI] = []

    def capture_run(self: SloTUI, *, mouse: bool = True) -> None:
        """Retain the actual constructed host for Pilot instead of native terminal I/O."""
        assert mouse is True
        hosts.append(self)

    def acquire_session(*, config: SessionConfigDAO, allow_pending_preparation: bool) -> SloAgentSession:
        """Supply the real test session through the typed acquisition seam."""
        assert allow_pending_preparation is True
        return session

    def build_host(*, session: SloAgentSession, messaging_enabled: bool) -> SloTUI:
        """Mount the actual host with test-owned receipt observation."""
        return SloTUI(
            session=session, messaging_enabled=messaging_enabled, prompt_factory=RecordingPromptInput
        )

    with patch.object(SloTUI, "run", capture_run):
        TyperDispatch.tui(workdir=session.workdir, session_factory=acquire_session, tui_factory=build_host)
    assert len(hosts) == 1
    return hosts[0]


@pytest.mark.parametrize(argnames="mode", argvalues=["fresh", "resume", "restore"])
def test_dispatch_composes_messaging_hosts(tmp_path: Path, mode: str) -> None:
    """Actual interactive roots construct real durable hosts, including private restore."""
    from src.cli.typer_dispatch import TyperDispatch
    from tests.tui.test_prompt_component_protocol import build_session
    from tests.cli.test_herdr_restore import save_revision, SESSION_ID
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore

    session = build_session(tmp_path=tmp_path)
    hosts: list[SloTUI] = []

    def capture_run(self: SloTUI, *, mouse: bool = True) -> None:
        """Capture the production constructor result without terminal I/O."""
        assert mouse is True
        hosts.append(self)

    resume = None
    restore = None
    if mode == "restore":
        _, restore = save_revision()
        resume = SESSION_ID
    elif mode == "resume":
        import asyncio

        # Dispatch resolution uses the canonical default store, not a second test resolver.
        default_store = FilesystemSessionHistoryStore()
        asyncio.run(
            default_store.ensure_session(
                session_id=session.session_id, workdir=tmp_path, model_name="gpt-5.4"
            )
        )
        resume = session.session_id

    def acquire_session(*, config: SessionConfigDAO, allow_pending_preparation: bool) -> SloAgentSession:
        """Supply a real session while checking deferred preparation policy."""
        assert allow_pending_preparation is True
        return session

    with patch.object(SloTUI, "run", capture_run):
        TyperDispatch.tui(
            session_factory=acquire_session,
            workdir=None if mode == "restore" else tmp_path,
            resume_session_reference=resume,
            herdr_restore_reference=restore,
        )
    assert len(hosts) == 1
    assert hosts[0]._session is session
    assert hosts[0]._messaging_enabled is True
    assert hosts[0]._in_flight_task is None and hosts[0]._queued_prompt_text is None


def test_dispatch_headless_runs_actual_finite_messaging(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The actual headless composition persists a messaging input and finishes its scheduler."""
    import json
    import sqlite3
    from langchain_core.messages import AIMessage
    from src.cli.typer_dispatch import TyperDispatch
    from tests.agents.slo_agent.messaging.test_delivery import RecordingModel
    from src.cli import typer_dispatch

    model = RecordingModel(responses=[AIMessage(content="root answer")])
    model.release.set()
    from src.agents.base import LLMBuildResult
    from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName

    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic-no-network"
    )
    with (
        patch("src.auth.credential_resolver.CredentialResolver.resolve", return_value=credential),
        patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(llm=model, supports_explicit_caching=False),
        ),
    ):
        exit_code = TyperDispatch.run_headless(
            prompt="root input", cwd=str(tmp_path), enable_history=True, model="gpt-5.4"
        )
    assert exit_code == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert any(event["kind"] == "run_completed" for event in events)
    databases = list((typer_dispatch._CFG_SLO_HOME / "sessions" / "history").glob("*/messaging.v1.sqlite3"))
    assert len(databases) == 1
    assert databases[0].resolve().is_relative_to(typer_dispatch._CFG_SLO_HOME.resolve())
    with sqlite3.connect(database=databases[0]) as connection:
        identities = connection.execute("SELECT state FROM identity").fetchall()
        submissions = connection.execute("SELECT submission_json FROM messages").fetchall()
    assert identities == [("applied",)]
    assert [json.loads(submission[0])["text"] for submission in submissions] == ["root input"]
    assert len(model.requests) == 1


def test_dispatch_interactive_runs_actual_messaging_journey(tmp_path: Path) -> None:
    """Unmodified dispatch/session construction reaches real mounted admission and history."""
    import asyncio
    from langchain_core.messages import AIMessage
    from src.agents.base import LLMBuildResult
    from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
    from src.cli.typer_dispatch import TyperDispatch
    from src.tui.components.prompt_input.component import PromptInputComponent
    from tests.agents.slo_agent.messaging.test_delivery import RecordingModel
    from tests.tui.test_durable_composer import _wait_until

    model = RecordingModel(responses=[AIMessage(content="root interactive answer")])
    model.release.set()
    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic-no-network"
    )
    hosts: list[SloTUI] = []

    async def mounted_journey(*, host: SloTUI) -> None:
        """Use Pilot on the actual composition and read the committed application back."""
        async with host.run_test() as pilot:
            await _wait_until(predicate=lambda: host._session.is_messaging_ready)
            prompt = host.query_one(PromptInputComponent)
            prompt.load_text("root interactive input")
            await pilot.press("enter")
            await _wait_until(predicate=lambda: len(model.requests) == 1 and not host._session.is_running)
            assert host._session._message_store is not None
            identities = await host._session._message_store.read_identities()
            assert len(identities) == 1 and identities[0].receipt.state == "applied"
            assert host._session.history_store is not None
            events = await host._session.history_store.load_events(session_id=host._session.session_id)
            assert [
                event.payload.content for event in events if "messaging_v1" in event.payload.metadata
            ] == ["root interactive input"]
            assert host._in_flight_task is None and host._queued_prompt_text is None

    def pilot_run(self: SloTUI, *, mouse: bool = True) -> None:
        """Replace only native terminal integration, not host or session composition."""
        hosts.append(self)
        asyncio.run(mounted_journey(host=self))

    with (
        patch.object(SloTUI, "run", pilot_run),
        patch("src.auth.credential_resolver.CredentialResolver.resolve", return_value=credential),
        patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(llm=model, supports_explicit_caching=False),
        ),
    ):
        TyperDispatch.tui(workdir=tmp_path)
    assert len(hosts) == 1 and hosts[0]._messaging_enabled
    assert not hosts[0]._session.is_messaging_ready


class TestAppSurface:
    """Drive the Typer app via ``CliRunner`` to assert its declared surface."""

    def test_version_flag_prints_resolved_version(self) -> None:
        """``slo --version`` prints ``resolve_version()`` and exits 0."""
        result = runner.invoke(app, ["--version"])

        assert result.exit_code == 0
        assert resolve_version() in result.stdout

    def test_help_lists_subcommands(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``slo --help`` lists ``update`` / ``[<dir>]``."""
        # Rich detects console width from the terminal, which is a pipe under
        # parallel test workers; pin the width so the options panel renders fully.
        monkeypatch.setenv("COLUMNS", "120")
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "update" in result.stdout
        assert "WORKDIR" in result.stdout.upper() or "workdir" in result.stdout
        assert "session reference" in result.stdout.lower()

    def test_bare_form_invokes_tui_with_cwd(self) -> None:
        """Bare ``slo`` reaches ``TyperDispatch.tui(workdir=None, resume_session_reference=None)``."""
        with patch("src.cli.app.TyperDispatch.tui") as mock_tui:
            result = runner.invoke(app, [])

        assert result.exit_code == 0
        mock_tui.assert_called_once_with(workdir=None, workspace_file=None, resume_session_reference=None)

    def test_bare_form_with_dir_invokes_tui_with_resolved_path(self, tmp_path: Path) -> None:
        """``slo <dir>`` reaches the dispatcher with the raw ``Path``."""
        with patch("src.cli.app.TyperDispatch.tui") as mock_tui:
            result = runner.invoke(app, [str(tmp_path)])

        assert result.exit_code == 0
        mock_tui.assert_called_once_with(
            workdir=Path(str(tmp_path)),
            workspace_file=None,
            resume_session_reference=None,
        )

    def test_resume_flag_threads_session_id_into_dispatch(self) -> None:
        """``slo --resume <id>`` reaches the dispatcher with the explicit id (05.e)."""
        explicit: str = "8aa00000-0000-0000-0000-000000000000"
        with patch("src.cli.app.TyperDispatch.tui") as mock_tui:
            result = runner.invoke(app, ["--resume", explicit])

        assert result.exit_code == 0
        mock_tui.assert_called_once_with(workdir=None, workspace_file=None, resume_session_reference=explicit)

    def test_resume_flag_threads_session_name_reference_into_dispatch(self) -> None:
        """``slo --resume <name>`` reaches the dispatcher with the raw reference."""
        with patch("src.cli.app.TyperDispatch.tui") as mock_tui:
            result = runner.invoke(app, ["--resume", "release prep"])

        assert result.exit_code == 0
        mock_tui.assert_called_once_with(
            workdir=None, workspace_file=None, resume_session_reference="release prep"
        )

    def test_workspace_flag_threads_path_into_dispatch(self, tmp_path: Path) -> None:
        """``slo --workspace <file>`` reaches the dispatcher with the raw Path."""
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text('{"folders": []}', encoding="utf-8")

        with patch("src.cli.app.TyperDispatch.tui") as mock_tui:
            result = runner.invoke(app, ["--workspace", str(workspace_file)])

        assert result.exit_code == 0
        mock_tui.assert_called_once_with(
            workdir=None,
            workspace_file=Path(str(workspace_file)),
            resume_session_reference=None,
        )

    def test_workspace_flag_coexists_with_workdir_and_resume(self, tmp_path: Path) -> None:
        """`workdir`, `--workspace`, and `--resume` parse together."""
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text('{"folders": []}', encoding="utf-8")

        with patch("src.cli.app.TyperDispatch.tui") as mock_tui:
            result = runner.invoke(
                app,
                ["--workspace", str(workspace_file), "--resume", "abc", str(tmp_path)],
            )

        assert result.exit_code == 0
        mock_tui.assert_called_once_with(
            workdir=Path(str(tmp_path)),
            workspace_file=Path(str(workspace_file)),
            resume_session_reference="abc",
        )

    def test_update_subcommand_passes_development_flag(self) -> None:
        """``slo update --development`` calls ``TyperDispatch.update(development=True, ref=None)``."""
        with patch("src.cli.app.TyperDispatch.update") as mock_update:
            result = runner.invoke(app, ["update", "--development"])

        assert result.exit_code == 0
        mock_update.assert_called_once_with(development=True, ref=None)

    def test_update_subcommand_passes_ref(self) -> None:
        """``slo update --ref v0.3.2`` forwards the explicit ref."""
        with patch("src.cli.app.TyperDispatch.update") as mock_update:
            result = runner.invoke(app, ["update", "--ref", "v0.3.2"])

        assert result.exit_code == 0
        mock_update.assert_called_once_with(development=False, ref="v0.3.2")
