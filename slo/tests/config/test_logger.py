"""Tests for interactive TUI logging isolation and app file logging."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.logging import TextualHandler

from config.logger import configure_app_file_logging, interactive_logging, log_info


class TestInteractiveLogging:
    """Cover the temporary TUI-specific logging context."""

    def test_interactive_logging_replaces_root_handlers_and_restores_them(
        self,
        tmp_path: Path,
    ) -> None:
        """The context swaps in interactive handlers, then restores the originals."""
        root_logger: logging.Logger = logging.getLogger()
        previous_handlers: list[logging.Handler] = list(root_logger.handlers)

        with interactive_logging(slo_home=tmp_path) as log_path:
            current_handlers: list[logging.Handler] = list(root_logger.handlers)

            assert current_handlers != previous_handlers
            assert isinstance(current_handlers[0], TextualHandler)
            assert log_path is not None
            assert any(hasattr(handler, "baseFilename") for handler in current_handlers)

        assert root_logger.handlers == previous_handlers

    def test_interactive_logging_creates_private_log_file(
        self,
        tmp_path: Path,
    ) -> None:
        """The context creates ``SLO_HOME/logs/tui.log`` with private perms."""
        with interactive_logging(slo_home=tmp_path) as log_path:
            assert log_path is not None
            assert log_path.exists()
            assert log_path.name == "tui.log"

            logs_dir: Path = log_path.parent
            assert logs_dir.name == "logs"
            assert (logs_dir.stat().st_mode & 0o777) == 0o700
            assert (log_path.stat().st_mode & 0o777) == 0o600

    def test_interactive_logging_does_not_write_to_stdout_or_stderr_without_active_app(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Without a mounted Textual app, records stay off terminal streams."""
        with interactive_logging(slo_home=tmp_path) as log_path:
            log_info(msg="interactive log without terminal fallback")

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        assert log_path is not None
        assert "interactive log without terminal fallback" in log_path.read_text()

    def test_interactive_logging_survives_file_handler_creation_failure(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """If file logging cannot be built, terminal isolation still holds."""
        with patch(
            "config.logger.RotatingFileHandler",
            side_effect=OSError("disk full"),
        ):
            with interactive_logging(slo_home=tmp_path) as log_path:
                log_info(msg="still isolated without file handler")
                assert log_path is None

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


class TestConfigureAppFileLogging:
    """``configure_app_file_logging`` — persistent app.log file sink."""

    def _remove_app_file_handlers(self) -> None:
        """Remove any RotatingFileHandlers added to the root logger by the test."""
        root_logger: logging.Logger = logging.getLogger()
        app_handlers: list[logging.Handler] = [
            handler
            for handler in root_logger.handlers
            if isinstance(handler, RotatingFileHandler)
        ]
        for handler in app_handlers:
            root_logger.removeHandler(handler)
            handler.close()

    def test_configure_app_file_logging_creates_app_log_file(
        self,
        tmp_path: Path,
    ) -> None:
        """``configure_app_file_logging`` creates ``SLO_HOME/logs/app.log`` with private perms."""
        log_path: Path | None = configure_app_file_logging(slo_home=tmp_path)
        self._remove_app_file_handlers()

        assert log_path is not None
        assert log_path.exists()
        assert log_path.name == "app.log"

        logs_dir: Path = log_path.parent
        assert logs_dir.name == "logs"
        assert (logs_dir.stat().st_mode & 0o777) == 0o700
        assert (log_path.stat().st_mode & 0o777) == 0o600

    def test_configure_app_file_logging_replaces_console_handlers_with_file_handler(
        self,
        tmp_path: Path,
    ) -> None:
        """``configure_app_file_logging`` removes console handlers and adds a ``RotatingFileHandler``."""
        root_logger: logging.Logger = logging.getLogger()

        configure_app_file_logging(slo_home=tmp_path)

        console_handlers_after: list[logging.Handler] = [
            handler
            for handler in root_logger.handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
        ]
        file_handlers_after: list[logging.Handler] = [
            handler for handler in root_logger.handlers if isinstance(handler, RotatingFileHandler)
        ]
        self._remove_app_file_handlers()

        assert len(console_handlers_after) == 0
        assert len(file_handlers_after) == 1

    def test_configure_app_file_logging_writes_messages_to_app_log(
        self,
        tmp_path: Path,
    ) -> None:
        """Log records written after setup appear in ``app.log``."""
        log_path: Path | None = configure_app_file_logging(slo_home=tmp_path)

        logging.getLogger("slo").info("app log smoke test")
        logging.getLogger().handlers[-1].flush()
        self._remove_app_file_handlers()

        assert log_path is not None
        assert "app log smoke test" in log_path.read_text()

    def test_configure_app_file_logging_returns_none_on_creation_failure(
        self,
        tmp_path: Path,
    ) -> None:
        """When file creation fails, ``configure_app_file_logging`` returns ``None`` gracefully."""
        with patch(
            "config.logger.RotatingFileHandler",
            side_effect=OSError("disk full"),
        ):
            log_path: Path | None = configure_app_file_logging(slo_home=tmp_path)

        assert log_path is None

    def test_interactive_logging_also_writes_to_app_log(
        self,
        tmp_path: Path,
    ) -> None:
        """``interactive_logging`` installs the app.log handler so TUI sessions capture app records."""
        with interactive_logging(slo_home=tmp_path) as _tui_log_path:
            app_log_path: Path = tmp_path / "logs" / "app.log"
            assert app_log_path.exists()

            root_logger: logging.Logger = logging.getLogger()
            file_handlers: list[logging.Handler] = [
                handler for handler in root_logger.handlers if isinstance(handler, RotatingFileHandler)
            ]
            filenames: list[str] = [
                getattr(handler, "baseFilename", "") for handler in file_handlers
            ]
            assert any("app.log" in name for name in filenames)

    def test_app_log_formatter_is_text_in_dev_environment(self) -> None:
        """``_build_app_log_formatter`` returns a plain ``Formatter`` in dev/test."""
        from config.logger import _build_app_log_formatter

        with patch("config.logger.is_dev", return_value=True), patch(
            "config.logger.is_test", return_value=False
        ):
            formatter: logging.Formatter = _build_app_log_formatter()

        assert type(formatter) is logging.Formatter

    def test_app_log_formatter_is_json_in_non_dev_environment(self) -> None:
        """``_build_app_log_formatter`` returns a JSON formatter in non-dev environments."""
        from pythonjsonlogger import jsonlogger

        from config.logger import _build_app_log_formatter

        with patch("config.logger.is_dev", return_value=False), patch(
            "config.logger.is_test", return_value=False
        ):
            formatter: logging.Formatter = _build_app_log_formatter()

        assert isinstance(formatter, jsonlogger.JsonFormatter)
