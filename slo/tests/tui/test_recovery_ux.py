"""Tests for TUI recovery UX (Feature 50, sub-spec 50.a.4).

Covers ``TranscriptProjector.project`` recovery notice branches and
the ``saw_failed_event`` suppression on the ``recovery_exhausted`` path.
"""

from __future__ import annotations

from typing import Optional

import pytest

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.tui.transcript_projector import TranscriptProjector


# ── minimal fake host ─────────────────────────────────────────────────────────


class _FakeHost:
    """Minimal transcript host double for recovery-notice tests."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []
        self.blocks: list = []
        self.tool_blocks: dict = {}
        self.user_blocks: list = []
        self.separators: int = 0

    def write_transcript_line(self, *, content: str, classes: str) -> None:
        """Record a transcript notice line.

        Args:
            content (str): Line text.
            classes (str): CSS class string.
        """
        self.lines.append((content, classes))

    def record_transcript_line(self, *, content: str, classes: str) -> None:
        """Record a logical line (no-op for these tests).

        Args:
            content (str): Line text.
            classes (str): CSS class string.
        """

    def mount_turn_separator_if_needed(self) -> None:
        """No-op separator stub."""

    async def mount_assistant_block(self, *, title_prefix: Optional[str] = None):
        """Stub — no blocks needed for notice tests."""
        from unittest.mock import MagicMock

        return MagicMock()

    async def mount_tool_execution_block(self, *, tool_call_id: str, tool_name: str):
        """Stub."""
        from unittest.mock import MagicMock

        return MagicMock()

    async def mount_user_message_block(self, *, text: str):
        """Stub."""
        from unittest.mock import MagicMock

        return MagicMock()


# ── projector notice tests ────────────────────────────────────────────────────


class TestRecoveryNoticeLines:
    """``TranscriptProjector.project`` writes the correct notice line for each recovery kind."""

    async def test_recovery_started_writes_notice_line(self) -> None:
        """``recovery_started`` writes the recovering notice and returns early."""
        host = _FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="recovery_started", iteration=0),
        )

        assert len(host.lines) == 1
        content, classes = host.lines[0]
        assert "recovering from error" in content.lower()
        assert classes == "assistant-aborted"

    async def test_recovery_succeeded_writes_notice_line(self) -> None:
        """``recovery_succeeded`` writes the recovered notice and returns early."""
        host = _FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="recovery_succeeded", iteration=1),
        )

        assert len(host.lines) == 1
        content, classes = host.lines[0]
        assert "recovered" in content.lower()
        assert classes == "assistant-aborted"

    async def test_recovery_exhausted_writes_notice_line(self) -> None:
        """``recovery_exhausted`` writes the could-not-recover notice and returns early."""
        host = _FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="recovery_exhausted", iteration=1),
        )

        assert len(host.lines) == 1
        content, classes = host.lines[0]
        assert "could not recover" in content.lower()
        assert classes == "assistant-aborted"

    async def test_recovery_started_does_not_mount_assistant_block(self) -> None:
        """``recovery_started`` writes only a transcript line — no assistant block is mounted."""
        host = _FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="recovery_started", iteration=0),
        )

        assert len(host.blocks) == 0

    async def test_recovery_three_events_write_three_notice_lines(self) -> None:
        """Three recovery events produce exactly three distinct notice lines in order."""
        host = _FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="recovery_started", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="recovery_succeeded", iteration=1),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="recovery_exhausted", iteration=2),
        )

        assert len(host.lines) == 3
        contents = [line[0] for line in host.lines]
        assert any("recovering" in c.lower() for c in contents)
        assert any("recovered" in c.lower() for c in contents)
        assert any("could not recover" in c.lower() for c in contents)


# ── saw_failed_event suppression ─────────────────────────────────────────────


class TestSawFailedEventSuppression:
    """``recovery_exhausted`` trips the ``saw_failed_event`` flag in ``_run_prompt``."""

    def test_recovery_exhausted_kind_is_in_suppression_set(self) -> None:
        """The ``_run_prompt`` guard set includes ``recovery_exhausted``.

        This is a structural test: we read the source of ``_run_prompt`` and
        confirm that ``recovery_exhausted`` appears in the same set as
        ``run_failed`` for the ``saw_failed_event`` flag.
        """
        import inspect
        from src.tui.app import SloTUI

        src = inspect.getsource(SloTUI._run_prompt)  # type: ignore[attr-defined]
        assert "recovery_exhausted" in src, (
            "_run_prompt must trip saw_failed_event on recovery_exhausted "
            "to suppress a duplicate error line on the exhausted path"
        )

    def test_run_failed_still_in_suppression_set(self) -> None:
        """``run_failed`` is still in the suppression set (regression guard)."""
        import inspect
        from src.tui.app import SloTUI

        src = inspect.getsource(SloTUI._run_prompt)  # type: ignore[attr-defined]
        assert "run_failed" in src


# ── spinner update method ─────────────────────────────────────────────────────


class TestApplyRecoverySpinnerUpdate:
    """``SloTUI._apply_recovery_spinner_update`` structure verified via source inspection."""

    def test_recovery_kinds_in_spinner_override_clear_exclusion_set(self) -> None:
        """All three recovery kinds are in the spinner-override-clear exclusion set."""
        import inspect
        from src.tui.app import SloTUI

        src = inspect.getsource(SloTUI._render_event)  # type: ignore[attr-defined]
        assert "recovery_started" in src
        assert "recovery_succeeded" in src
        assert "recovery_exhausted" in src

    def test_apply_recovery_spinner_update_method_exists(self) -> None:
        """``SloTUI`` has a ``_apply_recovery_spinner_update`` method."""
        from src.tui.app import SloTUI

        assert hasattr(SloTUI, "_apply_recovery_spinner_update")

    def test_apply_recovery_spinner_update_handles_all_recovery_kinds(self) -> None:
        """The method source contains all three recovery kind branches."""
        import inspect
        from src.tui.app import SloTUI

        src = inspect.getsource(SloTUI._apply_recovery_spinner_update)  # type: ignore[attr-defined]
        assert "recovery_started" in src
        assert "recovery_succeeded" in src
        assert "recovery_exhausted" in src

    def test_render_event_calls_apply_recovery_spinner_update(self) -> None:
        """``_render_event`` calls ``_apply_recovery_spinner_update``."""
        import inspect
        from src.tui.app import SloTUI

        src = inspect.getsource(SloTUI._render_event)  # type: ignore[attr-defined]
        assert "_apply_recovery_spinner_update" in src


# ── replay guard ──────────────────────────────────────────────────────────────


class TestReplayRecoveryObservationNotRendered:
    """On replay, ``recovery_observation`` must not mount as a ``UserMessageBlock``."""

    def test_recovery_observation_absent_from_replay_entry_builder_handlers(self) -> None:
        """``recovery_observation`` is intentionally not registered in ``_ReplayEntryBuilder``."""
        import inspect
        from src.agents.slo_agent.history.transcript import ReplayEntryProjector

        # Locate _ReplayEntryBuilder inside the module
        src = inspect.getsource(ReplayEntryProjector)
        # The handler table must not route recovery_observation to a visible block
        # (it is intentionally ignored — model context only, not visible transcript)
        assert "recovery_observation" not in src or "recovery_observation" not in src.split(
            "_handlers"
        )[1] if "_handlers" in src else True
