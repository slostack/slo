"""Tests for the Typer ``app`` surface (sub-spec 02.a.4)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from src.cli.app import app
from src.cli.version import resolve_version

runner: CliRunner = CliRunner()


class TestAppSurface:
    """Drive the Typer app via ``CliRunner`` to assert its declared surface."""

    def test_version_flag_prints_resolved_version(self) -> None:
        """``slo --version`` prints ``resolve_version()`` and exits 0."""
        result = runner.invoke(app, ["--version"])

        assert result.exit_code == 0
        assert resolve_version() in result.stdout

    def test_help_lists_subcommands(self) -> None:
        """``slo --help`` lists ``update`` / ``[<dir>]``."""
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
        mock_tui.assert_called_once_with(
            workdir=None,
            workspace_file=None,
            resume_session_reference=explicit,
        )

    def test_resume_flag_threads_session_name_reference_into_dispatch(self) -> None:
        """``slo --resume <name>`` reaches the dispatcher with the raw reference."""
        with patch("src.cli.app.TyperDispatch.tui") as mock_tui:
            result = runner.invoke(app, ["--resume", "release prep"])

        assert result.exit_code == 0
        mock_tui.assert_called_once_with(
            workdir=None,
            workspace_file=None,
            resume_session_reference="release prep",
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
