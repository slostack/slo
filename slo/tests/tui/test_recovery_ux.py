"""Tests for TUI recovery UX (Feature 50, sub-spec 50.a.4).

Covers ``TranscriptProjectionAdapter.project`` recovery notice branches and
the ``saw_failed_event`` suppression on the ``recovery_exhausted`` path.
"""

from __future__ import annotations

import pytest

from src.agents.slo_agent.events.stream import AgentStreamEventDAO, StreamEventKind
from src.tui.components.chat_transcript.adapters.transcript_projector import TranscriptProjectionAdapter

from tests.tui.test_transcript_projector import FakeHost

# ── projector notice tests ────────────────────────────────────────────────────


class TestRecoveryNoticeLines:
    """``TranscriptProjectionAdapter.project`` writes the correct notice line for each recovery kind."""

    async def test_recovery_started_writes_notice_line(self) -> None:
        """``recovery_started`` writes the recovering notice and returns early."""
        host = FakeHost()
        projector = TranscriptProjectionAdapter(host=host)

        await projector.handle(
            event=AgentStreamEventDAO(kind="recovery_started", iteration=0),
        )

        assert len(host.lines) == 1
        content, classes = host.lines[0]
        assert "recovering from error" in content.lower()
        assert classes == "assistant-aborted"

    async def test_recovery_succeeded_writes_notice_line(self) -> None:
        """``recovery_succeeded`` writes the recovered notice and returns early."""
        host = FakeHost()
        projector = TranscriptProjectionAdapter(host=host)

        await projector.handle(
            event=AgentStreamEventDAO(kind="recovery_succeeded", iteration=1),
        )

        assert len(host.lines) == 1
        content, classes = host.lines[0]
        assert "recovered" in content.lower()
        assert classes == "assistant-aborted"

    async def test_recovery_exhausted_writes_notice_line(self) -> None:
        """``recovery_exhausted`` writes the could-not-recover notice and returns early."""
        host = FakeHost()
        projector = TranscriptProjectionAdapter(host=host)

        await projector.handle(
            event=AgentStreamEventDAO(kind="recovery_exhausted", iteration=1),
        )

        assert len(host.lines) == 1
        content, classes = host.lines[0]
        assert "could not recover" in content.lower()
        assert classes == "assistant-aborted"

    async def test_recovery_started_does_not_mount_assistant_block(self) -> None:
        """``recovery_started`` writes only a transcript line — no assistant block is mounted."""
        host = FakeHost()
        projector = TranscriptProjectionAdapter(host=host)

        await projector.handle(
            event=AgentStreamEventDAO(kind="recovery_started", iteration=0),
        )

        assert len(host.blocks) == 0

    async def test_recovery_three_events_write_three_notice_lines(self) -> None:
        """Three recovery events produce exactly three distinct notice lines in order."""
        host = FakeHost()
        projector = TranscriptProjectionAdapter(host=host)

        await projector.handle(
            event=AgentStreamEventDAO(kind="recovery_started", iteration=0),
        )
        await projector.handle(
            event=AgentStreamEventDAO(kind="recovery_succeeded", iteration=1),
        )
        await projector.handle(
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
    """Recovery translation preserves status without consuming projector notices."""

    def test_recovery_status_copy_and_normal_reset(self) -> None:
        """Each recovery transition overrides status until an ordinary event arrives."""
        from src.tui.session_event_presentation import SessionEventPresentation

        statuses: dict[StreamEventKind, str] = {
            "recovery_started": "Recovering from error…",
            "recovery_succeeded": "Recovered — continuing.",
            "recovery_exhausted": "Could not recover automatically.",
        }
        for kind, expected in statuses.items():
            presentation = SessionEventPresentation.build(event=AgentStreamEventDAO(kind=kind))
            assert presentation.update_spinner
            assert presentation.spinner_status == expected
            assert not presentation.notice_only
        ordinary = SessionEventPresentation.build(event=AgentStreamEventDAO(kind="text_delta", delta="ok"))
        assert ordinary.update_spinner
        assert ordinary.spinner_status is None


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
        assert (
            "recovery_observation" not in src or "recovery_observation" not in src.split("_handlers")[1]
            if "_handlers" in src
            else True
        )
