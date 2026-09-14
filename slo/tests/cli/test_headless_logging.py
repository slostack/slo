"""Tests for src/cli/headless_logging.py.

Decision points covered:
- headless_logging: installs file handler when file creation succeeds
- headless_logging: installs NullHandler when file creation fails
- headless_logging: restores original handlers after normal exit
- headless_logging: restores original handlers after exception in body
- headless_logging: yields log_path when file handler present / None otherwise
- logger lines do not reach sys.stdout during the headless context
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from src.cli.headless_logging import headless_logging


def _make_stream_handler(stream=None) -> logging.StreamHandler:
    handler: logging.StreamHandler = logging.StreamHandler(stream or sys.stdout)
    return handler


class TestHeadlessLogging:
    def test_installs_file_handler_when_creation_succeeds(self, tmp_path: Path) -> None:
        slo_home: Path = tmp_path / "slo"
        root_logger: logging.Logger = logging.getLogger()
        original_handlers: list[logging.Handler] = list(root_logger.handlers)
        try:
            with headless_logging(slo_home=slo_home) as log_path:
                current_handlers: list[logging.Handler] = list(root_logger.handlers)
                file_handlers: list[logging.Handler] = [
                    h for h in current_handlers if isinstance(h, RotatingFileHandler)
                ]
                assert len(file_handlers) == 1
                assert log_path is not None
                assert log_path.name == "app.log"
        finally:
            root_logger.handlers = original_handlers

    def test_installs_null_handler_when_file_creation_fails(self, tmp_path: Path) -> None:
        root_logger: logging.Logger = logging.getLogger()
        original_handlers: list[logging.Handler] = list(root_logger.handlers)
        try:
            with patch("src.cli.headless_logging._build_app_file_handler", return_value=None):
                with headless_logging(slo_home=tmp_path / "slo") as log_path:
                    current_handlers: list[logging.Handler] = list(root_logger.handlers)
                    null_handlers: list[logging.Handler] = [
                        h for h in current_handlers if isinstance(h, logging.NullHandler)
                    ]
                    assert len(null_handlers) >= 1
                    assert log_path is None
        finally:
            root_logger.handlers = original_handlers

    def test_restores_original_handlers_after_normal_exit(self, tmp_path: Path) -> None:
        root_logger: logging.Logger = logging.getLogger()
        sentinel: logging.StreamHandler = _make_stream_handler()
        original_handlers: list[logging.Handler] = list(root_logger.handlers)
        root_logger.handlers = [sentinel]
        try:
            with headless_logging(slo_home=tmp_path / "slo"):
                pass
            assert root_logger.handlers == [sentinel]
        finally:
            root_logger.handlers = original_handlers
            sentinel.close()

    def test_restores_original_handlers_after_exception_in_body(self, tmp_path: Path) -> None:
        root_logger: logging.Logger = logging.getLogger()
        sentinel: logging.StreamHandler = _make_stream_handler()
        original_handlers: list[logging.Handler] = list(root_logger.handlers)
        root_logger.handlers = [sentinel]
        try:
            with pytest.raises(RuntimeError):
                with headless_logging(slo_home=tmp_path / "slo"):
                    raise RuntimeError("deliberate error")
            assert root_logger.handlers == [sentinel]
        finally:
            root_logger.handlers = original_handlers
            sentinel.close()

    def test_stdout_stream_handlers_removed_during_context(self, tmp_path: Path) -> None:
        stdout_handler: logging.StreamHandler = logging.StreamHandler(sys.stdout)
        root_logger: logging.Logger = logging.getLogger()
        original_handlers: list[logging.Handler] = list(root_logger.handlers)
        root_logger.handlers = [stdout_handler]
        try:
            with headless_logging(slo_home=tmp_path / "slo"):
                handlers_inside: list[logging.Handler] = list(root_logger.handlers)
                stdout_in_context: list[logging.Handler] = [
                    h
                    for h in handlers_inside
                    if isinstance(h, logging.StreamHandler)
                    and not isinstance(h, logging.FileHandler)
                    and getattr(h, "stream", None) is sys.stdout
                ]
                assert stdout_in_context == []
        finally:
            root_logger.handlers = original_handlers
            stdout_handler.close()

    def test_yields_none_when_file_handler_unavailable(self, tmp_path: Path) -> None:
        root_logger: logging.Logger = logging.getLogger()
        original_handlers: list[logging.Handler] = list(root_logger.handlers)
        try:
            with patch("src.cli.headless_logging._build_app_file_handler", return_value=None):
                with headless_logging(slo_home=tmp_path / "slo") as log_path:
                    assert log_path is None
        finally:
            root_logger.handlers = original_handlers

    def test_yields_app_log_path_when_file_handler_available(self, tmp_path: Path) -> None:
        slo_home: Path = tmp_path / "slo"
        root_logger: logging.Logger = logging.getLogger()
        original_handlers: list[logging.Handler] = list(root_logger.handlers)
        try:
            with headless_logging(slo_home=slo_home) as log_path:
                assert log_path is not None
                assert "app.log" in log_path.name
        finally:
            root_logger.handlers = original_handlers
