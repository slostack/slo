"""Tests for src/cli/headless_events.py.

Decision points covered:
- HeadlessLifecycleEventDAO: valid construction with each kind / minimal fields / payload defaults
- emit_lifecycle_event: writes JSONL to stderr / includes all fields / flushes after write
- timestamp is present and ISO-8601
"""

from __future__ import annotations

import json
import sys
from io import StringIO
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from src.cli.headless_events import (
    HeadlessLifecycleEventDAO,
    emit_lifecycle_event,
)


# ---------------------------------------------------------------------------
# HeadlessLifecycleEventDAO
# ---------------------------------------------------------------------------


class TestHeadlessLifecycleEventDAO:
    def test_constructs_with_required_kind_only(self) -> None:
        event: HeadlessLifecycleEventDAO = HeadlessLifecycleEventDAO(
            kind="headless_session_started"
        )
        assert event.kind == "headless_session_started"
        assert event.session_id is None
        assert event.message is None
        assert event.payload == {}
        assert event.timestamp_utc  # non-empty string

    def test_payload_defaults_to_empty_dict(self) -> None:
        event: HeadlessLifecycleEventDAO = HeadlessLifecycleEventDAO(
            kind="headless_status"
        )
        assert event.payload == {}

    def test_accepts_all_known_kinds(self) -> None:
        kinds = [
            "headless_session_started",
            "headless_session_resolved",
            "headless_orchestrator_attached",
            "headless_status",
            "headless_warning",
            "headless_run_completed",
            "headless_run_failed",
            "headless_run_aborted",
            "headless_child_stderr",
        ]
        for kind in kinds:
            event: HeadlessLifecycleEventDAO = HeadlessLifecycleEventDAO(kind=kind)  # type: ignore[arg-type]
            assert event.kind == kind

    def test_timestamp_is_iso_format(self) -> None:
        event: HeadlessLifecycleEventDAO = HeadlessLifecycleEventDAO(
            kind="headless_status"
        )
        # ISO 8601 timestamps contain a 'T' and a timezone offset or 'Z'
        assert "T" in event.timestamp_utc
        assert "+" in event.timestamp_utc or "Z" in event.timestamp_utc

    def test_serialises_to_json(self) -> None:
        event: HeadlessLifecycleEventDAO = HeadlessLifecycleEventDAO(
            kind="headless_run_completed",
            session_id="abc-123",
            message="finished",
            payload={"exit_code": 0},
        )
        raw: str = event.model_dump_json()
        parsed: dict[str, Any] = json.loads(raw)
        assert parsed["kind"] == "headless_run_completed"
        assert parsed["session_id"] == "abc-123"
        assert parsed["message"] == "finished"
        assert parsed["payload"]["exit_code"] == 0

    def test_is_frozen(self) -> None:
        event: HeadlessLifecycleEventDAO = HeadlessLifecycleEventDAO(
            kind="headless_warning"
        )
        with pytest.raises(Exception):
            event.kind = "headless_status"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# emit_lifecycle_event
# ---------------------------------------------------------------------------


class TestEmitLifecycleEvent:
    def test_writes_jsonl_line_to_stderr(self, capsys: pytest.CaptureFixture) -> None:
        emit_lifecycle_event(
            kind="headless_session_started",
            session_id="test-session",
            message="session booting",
        )
        captured = capsys.readouterr()
        assert captured.out == ""  # nothing on stdout
        lines: list[str] = [ln for ln in captured.err.splitlines() if ln.strip()]
        assert len(lines) == 1
        parsed: dict[str, Any] = json.loads(lines[0])
        assert parsed["kind"] == "headless_session_started"
        assert parsed["session_id"] == "test-session"
        assert parsed["message"] == "session booting"

    def test_payload_included_in_output(self, capsys: pytest.CaptureFixture) -> None:
        emit_lifecycle_event(
            kind="headless_run_failed",
            session_id="sess-1",
            payload={"error": "timeout"},
        )
        captured = capsys.readouterr()
        parsed: dict[str, Any] = json.loads(captured.err.strip())
        assert parsed["payload"]["error"] == "timeout"

    def test_payload_defaults_to_empty_dict_in_output(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        emit_lifecycle_event(kind="headless_status")
        captured = capsys.readouterr()
        parsed: dict[str, Any] = json.loads(captured.err.strip())
        assert parsed["payload"] == {}

    def test_stderr_is_flushed_after_write(self) -> None:
        mock_stderr: MagicMock = MagicMock()
        with patch("src.cli.headless_events.sys") as mock_sys:
            mock_sys.stderr = mock_stderr
            emit_lifecycle_event(kind="headless_status")
        mock_stderr.flush.assert_called_once()

    def test_write_precedes_flush(self) -> None:
        mock_stderr: MagicMock = MagicMock()
        call_order: list[str] = []

        def record_write(_: str) -> None:
            call_order.append("write")

        def record_flush() -> None:
            call_order.append("flush")

        mock_stderr.write = record_write
        mock_stderr.flush = record_flush

        with patch("src.cli.headless_events.sys") as mock_sys:
            mock_sys.stderr = mock_stderr
            emit_lifecycle_event(kind="headless_run_completed")

        assert call_order == ["write", "flush"]

    def test_line_ends_with_newline(self) -> None:
        written: list[str] = []
        mock_stderr: MagicMock = MagicMock()
        mock_stderr.write = lambda s: written.append(s)
        with patch("src.cli.headless_events.sys") as mock_sys:
            mock_sys.stderr = mock_stderr
            emit_lifecycle_event(kind="headless_warning", message="test")
        assert len(written) == 1
        assert written[0].endswith("\n")
